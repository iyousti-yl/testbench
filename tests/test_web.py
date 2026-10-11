import json
import shutil
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from conftest import FIXTURES, build_project  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from webhelpers import PASSWORD, SECRET, client_for, csrf_of, login, post  # noqa: E402

from testbench.connectors import successfactors  # noqa: E402
from testbench.runner import Runner  # noqa: E402
from testbench.web.app import create_app  # noqa: E402
from testbench.web.security import SecretBox  # noqa: E402
from testbench.web.store import Store, StoreError  # noqa: E402
from testbench.web.workspaces import WorkspaceFiles  # noqa: E402

DATASPHERE = {
    "name": "datasphere-dev",
    "s_tenant_url": "https://acme.eu10.hcs.cloud.sap",
    "s_space": "HR_SPACE",
    "s_host": "abc-123.hana.prod-eu10.hanacloud.ondemand.com",
    "s_user": "HR_SPACE#TESTBENCH",
    "s_password": "s3cret-value",
    "sensitive": "on",
}


def add_datasphere(client: TestClient, slug: str = "client-a-hr", **changes):
    return post(client, f"/w/{slug}/connections/new/datasphere", {**DATASPHERE, **changes})


# Sign-in -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["/", "/workspaces/new", "/w/client-a-hr", "/w/client-a-hr/connections/new/datasphere"]
)
def test_anonymous_requests_are_sent_to_login(app, path: str) -> None:
    response = TestClient(app).get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_wrong_password_is_rejected(app) -> None:
    client = TestClient(app)
    response = login(client, "alice@client-a.test", "wrong password!!")
    assert response.headers["location"] == "/login"
    assert client.get("/", follow_redirects=False).status_code == 303


def test_repeated_failures_lock_the_account(app) -> None:
    client = TestClient(app)
    for _ in range(5):
        login(client, "alice@client-a.test", "wrong password!!")
    login(client, "alice@client-a.test")
    assert client.get("/", follow_redirects=False).status_code == 303


# Workspaces ----------------------------------------------------------------------------


def test_user_only_sees_own_workspaces(alice: TestClient) -> None:
    home = alice.get("/").text
    assert "Client A · HR" in home
    assert "Client B" not in home
    assert alice.get("/w/client-a-hr").status_code == 200


def test_create_rename_and_delete_a_workspace(alice: TestClient, app) -> None:
    response = post(alice, "/workspaces", {"name": "NMBS · Payroll", "description": "Pilot"})
    assert response.headers["location"] == "/w/nmbs-payroll"
    folder = app.state.store.data_dir / "workspaces" / "nmbs-payroll"
    assert (folder / "suites").is_dir()
    assert "NMBS · Payroll" in alice.get("/").text

    post(alice, "/w/nmbs-payroll/edit", {"name": "NMBS · Payroll 2027", "description": ""})
    page = alice.get("/w/nmbs-payroll").text
    assert "NMBS · Payroll 2027" in page and "Pilot" not in page

    (folder / ".testbench").mkdir()
    response = post(alice, "/w/nmbs-payroll/delete", {"confirm": "wrong"})
    assert response.headers["location"] == "/w/nmbs-payroll/delete"
    assert folder.exists()
    response = post(alice, "/w/nmbs-payroll/delete", {"confirm": "nmbs-payroll"})
    assert response.headers["location"] == "/"
    assert not folder.exists()
    assert alice.get("/w/nmbs-payroll").status_code == 404


def test_same_name_gets_its_own_id(alice: TestClient) -> None:
    first = post(alice, "/workspaces", {"name": "Payroll"}).headers["location"]
    second = post(alice, "/workspaces", {"name": "Payroll"}).headers["location"]
    assert first == "/w/payroll" and second == "/w/payroll-2"


def test_workspace_needs_a_name(alice: TestClient) -> None:
    response = post(alice, "/workspaces", {"name": "  "})
    assert response.status_code == 400
    assert "give the workspace a name" in response.text


def test_leftover_folders_are_never_reused(alice: TestClient, app) -> None:
    leftover = app.state.store.data_dir / "workspaces" / "payroll"
    (leftover / ".testbench").mkdir(parents=True)
    assert post(alice, "/workspaces", {"name": "Payroll"}).headers["location"] == "/w/payroll-2"


@pytest.mark.parametrize(
    "path",
    [
        "/w/client-b",
        "/w/client-b/edit",
        "/w/client-b/delete",
        "/w/client-b/connections/new/datasphere",
        "/w/client-b/suites/contracts/scenarios/cost-lines-unchanged",
        "/w/client-b/runs/20260101T000000000000Z-contracts-run",
        "/w/client-b/runs/20260101T000000000000Z-contracts-run/report",
        "/w/does-not-exist",
    ],
)
def test_other_workspaces_look_like_they_do_not_exist(alice: TestClient, path: str) -> None:
    assert alice.get(path).status_code == 404


def test_cannot_change_another_workspace(alice: TestClient, app) -> None:
    for path, data in [
        ("/w/client-b/edit", {"name": "taken over"}),
        ("/w/client-b/delete", {"confirm": "client-b"}),
        ("/w/client-b/connections/new/datasphere", DATASPHERE),
        ("/w/client-b/suites/contracts/run", {}),
    ]:
        assert post(alice, path, data).status_code == 404
    folder = app.state.store.data_dir / "workspaces" / "client-b"
    assert folder.exists() and not (folder / ".testbench").exists()


def test_members_can_look_but_only_owners_change(carol: TestClient) -> None:
    page = carol.get("/w/client-a-hr").text
    assert "Client A · HR" in page and "Add SAP Datasphere" not in page
    assert carol.get("/w/client-a-hr/edit").status_code == 403
    assert post(carol, "/w/client-a-hr/delete", {"confirm": "client-a-hr"}).status_code == 403
    assert add_datasphere(carol).status_code == 403


def test_posts_without_csrf_token_are_rejected(alice: TestClient) -> None:
    for path in (
        "/workspaces",
        "/w/client-a-hr/delete",
        "/w/client-a-hr/connections/new/datasphere",
    ):
        response = alice.post(path, data={"csrf": "forged", "name": "x", "confirm": "client-a-hr"})
        assert response.status_code == 400
    assert alice.get("/w/client-a-hr").status_code == 200


# Connections ---------------------------------------------------------------------------


def test_offered_connectors_are_datasphere_and_successfactors(alice: TestClient) -> None:
    page = alice.get("/w/client-a-hr").text
    assert "Add SAP Datasphere" in page and "Add SAP SuccessFactors" in page
    assert "sqlite" not in page.lower()
    # Never offered: the server would read local files.
    assert alice.get("/w/client-a-hr/connections/new/sqlite").status_code == 404
    assert post(alice, "/w/client-a-hr/connections/new/sqlite", {"name": "x"}).status_code == 404


def test_add_datasphere_shows_tenant_and_space(alice: TestClient, app, driver) -> None:
    driver.responses["SYS.VIEWS"] = (
        ["SCHEMA_NAME", "NAME", "KIND"],
        [("HR_SPACE", "HR_COST_LINES_V", "view"), ("HR_SPACE", "HR_PAYROLL_V", "view")],
    )
    response = add_datasphere(alice)
    assert response.headers["location"] == "/w/client-a-hr"
    page = alice.get("/w/client-a-hr").text
    assert "https://acme.eu10.hcs.cloud.sap" in page
    assert "HR_SPACE" in page and "HR_SPACE#TESTBENCH" in page
    assert "Connected. Readable: 2 views." in page
    assert "s3cret-value" not in page
    assert driver.calls[0]["user"] == "HR_SPACE#TESTBENCH"
    assert driver.calls[0]["password"] == "s3cret-value"
    assert driver.calls[0]["currentSchema"] == "HR_SPACE"

    home = alice.get("/").text
    assert "acme.eu10.hcs.cloud.sap" in home and "HR_SPACE" in home

    with sqlite3.connect(app.state.store.path) as db:
        stored = [row[0] for row in db.execute("SELECT ciphertext FROM connection_secrets")]
        settings = db.execute("SELECT settings FROM connections").fetchone()[0]
    assert stored and all("s3cret-value" not in value for value in stored)
    assert "s3cret-value" not in settings


def test_failed_connection_is_saved_and_reported(alice: TestClient, driver) -> None:
    add_datasphere(alice, s_password="wrong")
    page = alice.get("/w/client-a-hr").text
    assert "Cannot connect" in page and "authentication failed" in page


def test_invalid_settings_are_explained_and_not_saved(alice: TestClient, driver) -> None:
    response = add_datasphere(alice, s_host="db.internal.example")
    assert response.status_code == 400
    assert "SAP HANA Cloud host" in response.text
    assert "s3cret-value" not in response.text  # typed secrets are not sent back
    assert "db.internal.example" in response.text  # other values are kept
    assert not driver.calls
    assert "datasphere-dev" not in alice.get("/w/client-a-hr").text


def test_edit_keeps_the_stored_password(alice: TestClient, app, driver) -> None:
    add_datasphere(alice)
    connection = app.state.store.connections(
        app.state.store.workspace_for(
            app.state.store.user_by_email("alice@client-a.test"), "client-a-hr"
        )
    )[0]
    form = alice.get(f"/w/client-a-hr/connections/{connection.id}").text
    assert "s3cret-value" not in form and "Leave empty to keep it" in form

    post(
        alice,
        f"/w/client-a-hr/connections/{connection.id}",
        {**DATASPHERE, "s_password": "", "s_space": "FINANCE"},
    )
    assert driver.calls[-1]["password"] == "s3cret-value"
    assert driver.calls[-1]["currentSchema"] == "FINANCE"


def test_duplicate_connection_names_are_refused(alice: TestClient, driver) -> None:
    add_datasphere(alice)
    response = add_datasphere(alice)
    assert response.status_code == 400
    assert "already has a connection named datasphere-dev" in response.text


def test_test_and_delete_a_connection(alice: TestClient, carol: TestClient, app, driver) -> None:
    add_datasphere(alice)
    store = app.state.store
    workspace = store.workspace_for(store.user_by_email("alice@client-a.test"), "client-a-hr")
    connection = store.connections(workspace)[0]
    calls = len(driver.calls)
    post(carol, f"/w/client-a-hr/connections/{connection.id}/test", page="/w/client-a-hr")
    assert len(driver.calls) == calls + 1  # members may test
    assert post(carol, f"/w/client-a-hr/connections/{connection.id}/delete").status_code == 403

    post(alice, f"/w/client-a-hr/connections/{connection.id}/delete")
    assert store.connections(workspace) == []
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM connection_secrets").fetchone()[0] == 0


def test_connections_of_other_workspaces_are_not_found(alice: TestClient, app, driver) -> None:
    bob = client_for(app, "bob@client-b.test")
    add_datasphere(bob, slug="client-b")
    store = app.state.store
    theirs = store.connections(
        store.workspace_for(store.user_by_email("bob@client-b.test"), "client-b")
    )[0]
    for path in (f"/connections/{theirs.id}", f"/connections/{theirs.id}/delete"):
        assert alice.get("/w/client-a-hr" + path).status_code == 404
    assert post(alice, f"/w/client-a-hr/connections/{theirs.id}/test").status_code == 404
    assert alice.get("/w/client-a-hr/connections/not-a-number").status_code == 404


def test_add_successfactors_shows_api_server_and_company(
    alice: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = []

    def fake_send(request, timeout):
        requests.append(request)
        return json.dumps({"d": {"EntitySets": ["EmpJob", "PerPerson", "User"]}}).encode()

    monkeypatch.setattr(successfactors, "_send", fake_send)
    form = {
        "name": "sf-test",
        "s_api_url": "https://api55.sapsf.eu",
        "s_company_id": "ACMET1",
        "s_auth": "basic",
        "s_username": "api_reader",
        "s_password": "sf-pass-123",
        "sensitive": "on",
    }
    post(alice, "/w/client-a-hr/connections/new/successfactors", form)
    page = alice.get("/w/client-a-hr").text
    assert "SAP SuccessFactors" in page
    assert "https://api55.sapsf.eu" in page and "ACMET1" in page and "api_reader" in page
    assert "3 entities" in page
    assert "sf-pass-123" not in page
    assert requests[0].full_url.startswith("https://api55.sapsf.eu/odata/v2/")


def test_typed_settings_never_read_the_server_environment(app, driver, monkeypatch) -> None:
    monkeypatch.setenv("SERVER_ONLY", "do-not-leak")
    store = app.state.store
    workspace = store.workspace_for(store.user_by_email("alice@client-a.test"), "client-a-hr")
    store.save_connection(
        workspace,
        name="dsp",
        type_name="datasphere",
        settings={"host": "h.hanacloud.ondemand.com", "user": "${SERVER_ONLY}", "space": "S"},
        secrets={"password": "pw"},
        sensitive=True,
    )
    ws = WorkspaceFiles(store, workspace)
    Runner(ws.config(), secrets=store.secrets_for(workspace)).connection("dsp").test_connection()
    assert driver.calls[-1]["user"] == "${SERVER_ONLY}"


# Runs ----------------------------------------------------------------------------------


def test_run_flow_with_report(alice: TestClient, app, tmp_path: Path) -> None:
    store = app.state.store
    workspace = store.workspace_for(store.user_by_email("alice@client-a.test"), "client-a-hr")
    data = build_project(tmp_path / "test-data")
    folder = store.workspace_dir(workspace)
    shutil.rmtree(folder / "suites")
    shutil.copytree(FIXTURES / "suites", folder / "suites")
    for name in ("target", "source"):  # only tests can add SQLite connections
        store.save_connection(
            workspace, name, "sqlite", {"path": str(data / f"{name}.db")}, {}, sensitive=True
        )

    token = csrf_of(alice, "/w/client-a-hr")
    base = "/w/client-a-hr/suites/contracts/run"
    alice.post(base, data={"csrf": token, "mode": "baseline"})
    response = alice.post(base, data={"csrf": token, "mode": "run"}, follow_redirects=False)
    run_url = response.headers["location"]
    assert run_url.startswith("/w/client-a-hr/runs/")
    assert "Passed" in alice.get(run_url).text
    report = alice.get(run_url + "/report")
    assert report.status_code == 200
    assert "default-src 'none'" in report.headers["content-security-policy"]


@pytest.mark.parametrize("run_id", ["..", "..%2F..%2Fapp.db", "x", "20260101T00Z-contracts-run"])
def test_run_ids_cannot_escape_the_workspace(alice: TestClient, run_id: str) -> None:
    assert alice.get(f"/w/client-a-hr/runs/{run_id}/report").status_code == 404


# App -----------------------------------------------------------------------------------


def test_security_headers_and_session_cookie(app) -> None:
    client = TestClient(app)
    response = client.get("/login")
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    login_response = login(client, "alice@client-a.test")
    cookie = login_response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_logout_ends_the_session(alice: TestClient) -> None:
    post(alice, "/logout")
    assert alice.get("/", follow_redirects=False).status_code == 303


def test_app_refuses_to_start_without_a_strong_secret(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="TESTBENCH_SECRET_KEY"):
        create_app(tmp_path, "short")


def test_data_folders_from_the_demo_preview_are_refused(tmp_path: Path) -> None:
    with sqlite3.connect(tmp_path / "app.db") as db:
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    with pytest.raises(StoreError, match="earlier preview"):
        Store(tmp_path, SecretBox(SECRET))


def test_first_account_can_be_created_on_every_start(tmp_path: Path, monkeypatch, capsys) -> None:
    from testbench.cli import main

    monkeypatch.setenv("TESTBENCH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TESTBENCH_SECRET_KEY", SECRET)
    monkeypatch.setenv("TESTBENCH_NEW_PASSWORD", PASSWORD)
    command = ["web", "create-user", "admin@example.test", "--name", "Admin", "--if-missing"]
    assert main(command) == 0
    assert main(command) == 0
    assert "already exists" in capsys.readouterr().out
    assert main(command[:-1]) == 2  # without --if-missing a duplicate is an error
