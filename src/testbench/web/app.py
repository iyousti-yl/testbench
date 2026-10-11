"""The Testbench web app: login, workspaces, suites, runs and reports.

Every workspace route resolves the workspace through the signed-in user's memberships.
A workspace the user is not a member of answers 404, exactly like one that does not exist.
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
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from testbench import demo
from testbench.checks import ERROR, FAILED, PASSED, SKIPPED
from testbench.config import ConfigError
from testbench.connectors import ConnectorError
from testbench.scenario import ScenarioError
from testbench.web.security import SecretBox, csrf_matches, new_csrf_token
from testbench.web.store import Store, User, Workspace
from testbench.web.workspaces import NotFound, WorkspaceFiles

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

    def render(request: Request, template: str, **context: Any) -> HTMLResponse:
        messages = request.session.pop("flash", [])
        return templates.TemplateResponse(
            request,
            template,
            {"csrf": csrf_token(request), "messages": messages, **context},
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

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> Response:
        if exc.status_code == 303:
            return RedirectResponse(exc.headers["Location"], status_code=303)
        message = exc.detail if exc.status_code == 400 else "This page does not exist."
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": message, "user": None, "csrf": "", "messages": []},
            status_code=exc.status_code,
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
        return render(request, "home.html", user=user, workspaces=store.workspaces_for(user))

    @app.get("/w/{slug}", response_class=HTMLResponse)
    def workspace_page(request: Request, user: CurrentUser, workspace: MemberWorkspace) -> Any:
        ws = WorkspaceFiles(store, workspace)
        error = None
        try:
            config = ws.config()
            suites = ws.suites()
            connections = list(config.connections.values())
        except (ConfigError, ScenarioError) as exc:
            suites, connections, error = [], [], str(exc)
        return render(
            request,
            "workspace.html",
            user=user,
            workspace=workspace,
            suites=suites,
            connections=connections,
            secret_names=store.secret_names(workspace),
            runs=ws.runs(),
            error=error,
        )

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

    @app.post("/w/{slug}/demo/{action}")
    def demo_action(
        request: Request,
        user: CurrentUser,
        workspace: MemberWorkspace,
        action: str,
        csrf: Annotated[str, Form()],
    ) -> Response:
        require_csrf(request, csrf)
        if not workspace.is_demo or action not in ("break", "fix"):
            raise HTTPException(status_code=404)
        demo.set_broken(store.workspace_dir(workspace), broken=action == "break")
        if action == "break":
            flash(request, "Injected a logic defect and a missing cost center into the demo data.")
        else:
            flash(request, "Restored the demo data.")
        return RedirectResponse(f"/w/{workspace.slug}", status_code=303)

    return app


def format_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y, %H:%M UTC")
    except (TypeError, ValueError):
        return value
