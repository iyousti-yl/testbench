"""The Testbench web app: login, workspaces, connections, suites, runs and reports.

Every workspace route resolves the workspace through the signed-in user's memberships.
A workspace the user is not a member of answers 404, exactly like one that does not exist.
Members can look and run tests; only owners change the workspace and its connections.
"""

# No "from __future__ import annotations" here: FastAPI must see the real Annotated
# dependency types, which are defined inside create_app.
import os
import threading
import time
from collections import defaultdict
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from testbench.checks import ERROR, FAILED, PASSED, SKIPPED
from testbench.config import ConfigError
from testbench.connectors import ConnectorError
from testbench.scenario import ScenarioError
from testbench.web import connections as conn_forms
from testbench.web.security import SecretBox, csrf_matches, new_csrf_token
from testbench.web.store import Connection, Store, StoreError, User, Workspace
from testbench.web.workspaces import NotFound, WorkspaceFiles, workspace_lock

SESSION_HOURS = 8
MAX_LOGIN_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60
STATUS_LABELS = {PASSED: "Passed", FAILED: "Failed", ERROR: "Error", SKIPPED: "Not tested"}

_APP_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'none'; "
    "frame-ancestors 'none'; form-action 'self'; base-uri 'none'; object-src 'none'"
)
# Reports are self-contained HTML with inline styles and no scripts; they are framed by
# the run page and may never load anything else.
_REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'self'"


class LoginThrottle:
    """Locks an email address after repeated failures (in memory, per process)."""

    def __init__(self) -> None:
        self._failures: defaultdict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        cutoff = time.monotonic() - LOCKOUT_SECONDS
        self._failures[key] = [t for t in self._failures[key] if t > cutoff]
        return self._failures[key]

    def locked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key)) >= MAX_LOGIN_FAILURES

    def fail(self, key: str) -> None:
        with self._lock:
            self._recent(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


def create_app(
    data_dir: Path | None = None,
    secret_key: str | None = None,
    secure_cookies: bool | None = None,
) -> FastAPI:
    data_dir = Path(data_dir or os.environ.get("TESTBENCH_DATA_DIR", "testbench-data"))
    secret_key = secret_key or os.environ.get("TESTBENCH_SECRET_KEY")
    if not secret_key or len(secret_key) < 32:
        raise RuntimeError(
            "TESTBENCH_SECRET_KEY must be set to a random value of at least 32 characters "
            "(for example: python -c 'import secrets; print(secrets.token_urlsafe(48))')"
        )
    if secure_cookies is None:
        secure_cookies = os.environ.get("TESTBENCH_INSECURE_COOKIES") != "1"

    store = Store(data_dir, SecretBox(secret_key))
    throttle = LoginThrottle()
    package = files("testbench.web")
    templates = Jinja2Templates(directory=str(package / "templates"))
    templates.env.globals["status_label"] = STATUS_LABELS
    templates.env.filters["when"] = format_time

    app = FastAPI(title="Testbench", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret_key,
        session_cookie="testbench_session",
        max_age=SESSION_HOURS * 3600,
        same_site="lax",
        https_only=secure_cookies,
    )
    app.mount("/static", StaticFiles(directory=str(package / "static")), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        is_report = request.url.path.endswith("/report")
        response.headers["Content-Security-Policy"] = _REPORT_CSP if is_report else _APP_CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if not request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = "no-store"
        if secure_cookies:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    # Helpers -------------------------------------------------------------------

    def csrf_token(request: Request) -> str:
        token = request.session.get("csrf")
        if not token:
            token = request.session["csrf"] = new_csrf_token()
        return token

    def require_csrf(request: Request, token: str) -> None:
        if not csrf_matches(request.session.get("csrf"), token):
            raise HTTPException(status_code=400, detail="Your session expired. Please try again.")

    def flash(request: Request, message: str, kind: str = "info") -> None:
        request.session.setdefault("flash", []).append({"kind": kind, "message": message})

    def render(
        request: Request, template: str, status_code: int = 200, **context: Any
    ) -> HTMLResponse:
        messages = request.session.pop("flash", [])
        return templates.TemplateResponse(
            request,
            template,
            {"csrf": csrf_token(request), "messages": messages, **context},
            status_code=status_code,
        )

    def current_user(request: Request) -> User:
        user_id = request.session.get("user_id")
        user = store.get_user(user_id) if isinstance(user_id, int) else None
        if user is None:
            request.session.pop("user_id", None)
            raise HTTPException(status_code=303, headers={"Location": "/login"})
        return user

    CurrentUser = Annotated[User, Depends(current_user)]

    def member_workspace(slug: str, user: CurrentUser) -> Workspace:
        workspace = store.workspace_for(user, slug)
        if workspace is None:
            raise HTTPException(status_code=404)
        return workspace

    MemberWorkspace = Annotated[Workspace, Depends(member_workspace)]

    def owned_workspace(workspace: MemberWorkspace) -> Workspace:
        if not workspace.is_owner:
            message = "Only owners of this workspace can do this."
            raise HTTPException(status_code=403, detail=message)
        return workspace

    OwnedWorkspace = Annotated[Workspace, Depends(owned_workspace)]

    async def form_fields(request: Request) -> dict[str, str]:
        form = await request.form()
        return {k: v for k, v in form.items() if isinstance(v, str)}

    FormFields = Annotated[dict[str, str], Depends(form_fields)]

    def connector_type(type_name: str) -> type:
        cls = conn_forms.offered_types().get(type_name)
        if cls is None:
            raise HTTPException(status_code=404)
        return cls

    def workspace_connection(workspace: Workspace, connection_id: int) -> Connection:
        connection = store.connection(workspace, connection_id)
        if connection is None:
            raise HTTPException(status_code=404)
        return connection

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> Response:
        if exc.status_code == 303:
            return RedirectResponse(exc.headers["Location"], status_code=303)
        message = exc.detail if exc.status_code in (400, 403) else "This page does not exist."
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": message, "user": None, "csrf": "", "messages": []},
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError) -> Response:
        # Malformed ids in a URL look like any other page that does not exist.
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": "This page does not exist.", "user": None, "csrf": "", "messages": []},
            status_code=404,
        )

    # Routes --------------------------------------------------------------------

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request) -> HTMLResponse:
        return render(request, "login.html", user=None, email="")

    @app.post("/login")
    def login(
        request: Request,
        email: Annotated[str, Form()],
        password: Annotated[str, Form()],
        csrf: Annotated[str, Form()],
    ) -> Response:
        require_csrf(request, csrf)
        key = email.strip().lower()
        if throttle.locked(key):
            flash(request, "Too many failed attempts. Try again in 15 minutes.", "error")
            return RedirectResponse("/login", status_code=303)
        user = store.authenticate(email, password)
        if user is None:
            throttle.fail(key)
            flash(request, "Email or password is not correct.", "error")
            return RedirectResponse("/login", status_code=303)
        throttle.reset(key)
        request.session.clear()  # new session on login
        request.session["user_id"] = user.id
        request.session["csrf"] = new_csrf_token()
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    def logout(request: Request, csrf: Annotated[str, Form()]) -> Response:
        require_csrf(request, csrf)
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, user: CurrentUser) -> HTMLResponse:
        workspaces = [
            (w, [conn_forms.view(c) for c in store.connections(w)])
            for w in store.workspaces_for(user)
        ]
        return render(request, "home.html", user=user, workspaces=workspaces)

    # Workspaces ----------------------------------------------------------------

    @app.get("/workspaces/new", response_class=HTMLResponse)
    def new_workspace(request: Request, user: CurrentUser) -> HTMLResponse:
        return render(request, "workspace_form.html", user=user, workspace=None, values={})

    @app.post("/workspaces", response_model=None)
    def create_workspace(
        request: Request,
        user: CurrentUser,
        csrf: Annotated[str, Form()],
        name: Annotated[str, Form()] = "",
        description: Annotated[str, Form()] = "",
    ) -> Response:
        require_csrf(request, csrf)
        try:
            workspace = store.create_workspace(user, name, description)
        except StoreError as exc:
            values = {"name": name, "description": description}
            return render(
                request,
                "workspace_form.html",
                user=user,
                workspace=None,
                values=values,
                error=str(exc),
                status_code=400,
            )
        flash(request, f"Created workspace {workspace.name}. Add a connection to get started.")
        return RedirectResponse(f"/w/{workspace.slug}", status_code=303)

    @app.get("/w/{slug}", response_class=HTMLResponse)
    def workspace_page(request: Request, user: CurrentUser, workspace: MemberWorkspace) -> Any:
        ws = WorkspaceFiles(store, workspace)
        error = None
        try:
            suites = ws.suites()
        except (ConfigError, ScenarioError) as exc:
            suites, error = [], str(exc)
        return render(
            request,
            "workspace.html",
            user=user,
            workspace=workspace,
            connections=[conn_forms.view(c) for c in store.connections(workspace)],
            connector_types=conn_forms.offered_types(),
            suites=suites,
            runs=ws.runs(),
            error=error,
        )

    @app.get("/w/{slug}/edit", response_class=HTMLResponse)
    def edit_workspace(request: Request, user: CurrentUser, workspace: OwnedWorkspace) -> Any:
        values = {"name": workspace.name, "description": workspace.description}
        return render(request, "workspace_form.html", user=user, workspace=workspace, values=values)

    @app.post("/w/{slug}/edit", response_model=None)
    def update_workspace(
        request: Request,
        user: CurrentUser,
        workspace: OwnedWorkspace,
        csrf: Annotated[str, Form()],
        name: Annotated[str, Form()] = "",
        description: Annotated[str, Form()] = "",
    ) -> Response:
        require_csrf(request, csrf)
        try:
            store.update_workspace(workspace, name, description)
        except StoreError as exc:
            values = {"name": name, "description": description}
            return render(
                request,
                "workspace_form.html",
                user=user,
                workspace=workspace,
                values=values,
                error=str(exc),
                status_code=400,
            )
        flash(request, "Saved the workspace.")
        return RedirectResponse(f"/w/{workspace.slug}", status_code=303)

    @app.get("/w/{slug}/delete", response_class=HTMLResponse)
    def confirm_delete_workspace(
        request: Request, user: CurrentUser, workspace: OwnedWorkspace
    ) -> HTMLResponse:
        return render(request, "delete_workspace.html", user=user, workspace=workspace)

    @app.post("/w/{slug}/delete", response_model=None)
    def delete_workspace(
        request: Request,
        user: CurrentUser,
        workspace: OwnedWorkspace,
        csrf: Annotated[str, Form()],
        confirm: Annotated[str, Form()] = "",
    ) -> Response:
        require_csrf(request, csrf)
        if confirm.strip() != workspace.slug:
            flash(request, f"Type {workspace.slug} to confirm.", "error")
            return RedirectResponse(f"/w/{workspace.slug}/delete", status_code=303)
        with workspace_lock(workspace):
            store.delete_workspace(workspace)
        flash(request, f"Deleted workspace {workspace.name} and all its data.")
        return RedirectResponse("/", status_code=303)

    # Connections ---------------------------------------------------------------

    def connection_form(
        request: Request,
        user: User,
        workspace: Workspace,
        cls: type,
        type_name: str,
        connection: Connection | None,
        values: dict[str, str],
        error: str | None = None,
    ) -> HTMLResponse:
        return render(
            request,
            "connection_form.html",
            user=user,
            workspace=workspace,
            cls=cls,
            type_name=type_name,
            groups=conn_forms.groups(cls),
            connection=connection,
            values=values,
            prefix=conn_forms.FIELD_PREFIX,
            error=error,
            status_code=400 if error else 200,
        )

    def save_connection(
        request: Request,
        user: User,
        workspace: Workspace,
        type_name: str,
        form: dict[str, str],
        connection: Connection | None,
    ) -> Response:
        require_csrf(request, form.get("csrf", ""))
        cls = connector_type(type_name)
        stored = store.connection_secrets(connection) if connection else {}
        try:
            settings, secrets = conn_forms.read_form(cls, form, stored)
            saved = store.save_connection(
                workspace,
                name=form.get("name", ""),
                type_name=type_name,
                settings=settings,
                secrets=secrets,
                sensitive=form.get("sensitive") == "on",
                connection_id=connection.id if connection else None,
            )
        except (ConnectorError, StoreError) as exc:
            values = {k: v for k, v in form.items() if k != "csrf"}
            for field in cls.settings_fields:  # typed secrets are never echoed back
                if field.secret:
                    values.pop(conn_forms.FIELD_PREFIX + field.key, None)
            return connection_form(
                request, user, workspace, cls, type_name, connection, values, str(exc)
            )
        ok, message = conn_forms.check_connection(saved, secrets)
        store.record_check(workspace, saved.id, ok, message)
        if ok:
            flash(request, f"Saved {saved.name}. {message}")
        else:
            flash(request, f"Saved {saved.name}, but it cannot connect yet. See below.", "error")
        return RedirectResponse(f"/w/{workspace.slug}", status_code=303)

    @app.get("/w/{slug}/connections/new/{type_name}", response_class=HTMLResponse)
    def new_connection(
        request: Request, user: CurrentUser, workspace: OwnedWorkspace, type_name: str
    ) -> HTMLResponse:
        cls = connector_type(type_name)
        taken = {c.name for c in store.connections(workspace)}
        name = next(
            n for n in [type_name, *(f"{type_name}-{i}" for i in range(2, 100))] if n not in taken
        )
        values = {"name": name, "sensitive": "on"}
        values.update({conn_forms.FIELD_PREFIX + f.key: f.default for f in cls.settings_fields})
        return connection_form(request, user, workspace, cls, type_name, None, values)

    @app.post("/w/{slug}/connections/new/{type_name}", response_model=None)
    def create_connection(
        request: Request,
        user: CurrentUser,
        workspace: OwnedWorkspace,
        type_name: str,
        form: FormFields,
    ) -> Response:
        return save_connection(request, user, workspace, type_name, form, None)

    @app.get("/w/{slug}/connections/{connection_id}", response_class=HTMLResponse)
    def edit_connection(
        request: Request, user: CurrentUser, workspace: OwnedWorkspace, connection_id: int
    ) -> HTMLResponse:
        connection = workspace_connection(workspace, connection_id)
        cls = connector_type(connection.type)
        values = {"name": connection.name, "sensitive": "on" if connection.sensitive else ""}
        values.update({conn_forms.FIELD_PREFIX + k: str(v) for k, v in connection.settings.items()})
        return connection_form(request, user, workspace, cls, connection.type, connection, values)

    @app.post("/w/{slug}/connections/{connection_id}", response_model=None)
    def update_connection(
        request: Request,
        user: CurrentUser,
        workspace: OwnedWorkspace,
        connection_id: int,
        form: FormFields,
    ) -> Response:
        connection = workspace_connection(workspace, connection_id)
        return save_connection(request, user, workspace, connection.type, form, connection)

    @app.post("/w/{slug}/connections/{connection_id}/test", response_model=None)
    def test_connection(
        request: Request,
        user: CurrentUser,
        workspace: MemberWorkspace,
        connection_id: int,
        csrf: Annotated[str, Form()],
    ) -> Response:
        require_csrf(request, csrf)
        connection = workspace_connection(workspace, connection_id)
        ok, message = conn_forms.check_connection(connection, store.connection_secrets(connection))
        store.record_check(workspace, connection.id, ok, message)
        flash(request, f"{connection.name}: {message}", "info" if ok else "error")
        return RedirectResponse(f"/w/{workspace.slug}", status_code=303)

    @app.get("/w/{slug}/connections/{connection_id}/delete", response_class=HTMLResponse)
    def confirm_delete_connection(
        request: Request, user: CurrentUser, workspace: OwnedWorkspace, connection_id: int
    ) -> HTMLResponse:
        connection = workspace_connection(workspace, connection_id)
        return render(
            request,
            "delete_connection.html",
            user=user,
            workspace=workspace,
            view=conn_forms.view(connection),
        )

    @app.post("/w/{slug}/connections/{connection_id}/delete", response_model=None)
    def delete_connection(
        request: Request,
        user: CurrentUser,
        workspace: OwnedWorkspace,
        connection_id: int,
        csrf: Annotated[str, Form()],
    ) -> Response:
        require_csrf(request, csrf)
        connection = workspace_connection(workspace, connection_id)
        store.delete_connection(workspace, connection.id)
        flash(request, f"Deleted connection {connection.name} and its stored credentials.")
        return RedirectResponse(f"/w/{workspace.slug}", status_code=303)

    # Suites and runs -----------------------------------------------------------

    @app.post("/w/{slug}/suites/{suite}/run")
    def run_suite(
        request: Request,
        user: CurrentUser,
        workspace: MemberWorkspace,
        suite: str,
        csrf: Annotated[str, Form()],
        mode: Annotated[str, Form()] = "run",
    ) -> Response:
        require_csrf(request, csrf)
        if mode not in ("run", "baseline"):
            raise HTTPException(status_code=400, detail="Unknown run mode.")
        ws = WorkspaceFiles(store, workspace)
        try:
            ws.run(suite, mode)
        except NotFound as exc:
            raise HTTPException(status_code=404) from exc
        except (ConfigError, ScenarioError, ConnectorError) as exc:
            flash(request, f"The suite could not run: {exc}", "error")
            return RedirectResponse(f"/w/{workspace.slug}", status_code=303)
        latest = ws.runs(limit=1)[0]
        return RedirectResponse(f"/w/{workspace.slug}/runs/{latest.id}", status_code=303)

    @app.get("/w/{slug}/runs/{run_id}", response_class=HTMLResponse)
    def run_page(
        request: Request, user: CurrentUser, workspace: MemberWorkspace, run_id: str
    ) -> HTMLResponse:
        try:
            result = WorkspaceFiles(store, workspace).run_result(run_id)
        except NotFound as exc:
            raise HTTPException(status_code=404) from exc
        return render(
            request, "run.html", user=user, workspace=workspace, run_id=run_id, result=result
        )

    @app.get("/w/{slug}/runs/{run_id}/report", response_class=HTMLResponse)
    def run_report(user: CurrentUser, workspace: MemberWorkspace, run_id: str) -> HTMLResponse:
        try:
            return HTMLResponse(WorkspaceFiles(store, workspace).report_html(run_id))
        except NotFound as exc:
            raise HTTPException(status_code=404) from exc

    @app.get("/w/{slug}/suites/{suite}/scenarios/{scenario_id}", response_class=HTMLResponse)
    def scenario_page(
        request: Request,
        user: CurrentUser,
        workspace: MemberWorkspace,
        suite: str,
        scenario_id: str,
    ) -> HTMLResponse:
        try:
            scenario, source = WorkspaceFiles(store, workspace).scenario(suite, scenario_id)
        except NotFound as exc:
            raise HTTPException(status_code=404) from exc
        return render(
            request,
            "scenario.html",
            user=user,
            workspace=workspace,
            suite=suite,
            scenario=scenario,
            source=source,
        )

    return app


def format_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y, %H:%M UTC")
    except (TypeError, ValueError):
        return value
