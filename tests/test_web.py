import re
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from testbench.web.admin import create_workspace  # noqa: E402
from testbench.web.app import create_app  # noqa: E402

SECRET = "test-secret-key-that-is-long-enough-1234567890"
PASSWORD = "correct horse battery"


@pytest.fixture
def app(tmp_path: Path):
    app = create_app(tmp_path / "data", SECRET, secure_cookies=False)
    store = app.state.store
    create_workspace(store, "nmbs-demo", "NMBS demo", with_demo=True)
    create_workspace(store, "other-demo", "Other client", with_demo=True)
    store.create_user("alice@nmbs.test", "Alice", PASSWORD)
    store.create_user("bob@other.test", "Bob", PASSWORD)
    store.add_member("nmbs-demo", "alice@nmbs.test", "owner")
    store.add_member("other-demo", "bob@other.test", "owner")
    return app


def csrf_of(client: TestClient, path: str = "/login") -> str:
    html = client.get(path).text
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match, f"no csrf token on {path}"
    return match.group(1)


def login(client: TestClient, email: str, password: str = PASSWORD):
    token = csrf_of(client)
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf": token},
        follow_redirects=False,
    )


@pytest.fixture
def alice(app) -> TestClient:
    client = TestClient(app)
    assert login(client, "alice@nmbs.test").headers["location"] == "/"
    return client


@pytest.mark.parametrize(
    "path", ["/", "/w/nmbs-demo", "/w/nmbs-demo/suites/hr-payroll/scenarios/cost-lines-unchanged"]
)
def test_anonymous_requests_are_sent_to_login(app, path: str) -> None:
    response = TestClient(app).get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_wrong_password_is_rejected(app) -> None:
    client = TestClient(app)
    response = login(client, "alice@nmbs.test", "wrong password!!")
    assert response.headers["location"] == "/login"
    assert client.get("/", follow_redirects=False).status_code == 303


def test_repeated_failures_lock_the_account(app) -> None:
    client = TestClient(app)
    for _ in range(5):
        login(client, "alice@nmbs.test", "wrong password!!")
    login(client, "alice@nmbs.test")
    assert client.get("/", follow_redirects=False).status_code == 303


def test_user_only_sees_own_workspaces(alice: TestClient) -> None:
    home = alice.get("/").text
    assert "NMBS demo" in home
    assert "Other client" not in home
    assert alice.get("/w/nmbs-demo").status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/w/other-demo",
        "/w/other-demo/suites/hr-payroll/scenarios/cost-lines-unchanged",
        "/w/other-demo/runs/20260101T000000000000Z-hr-payroll-run",
        "/w/other-demo/runs/20260101T000000000000Z-hr-payroll-run/report",
        "/w/does-not-exist",
    ],
)
def test_other_workspaces_look_like_they_do_not_exist(alice: TestClient, path: str) -> None:
    assert alice.get(path).status_code == 404


def test_cannot_run_or_break_another_workspace(alice: TestClient, app) -> None:
    token = csrf_of(alice, "/")
    for path in ("/w/other-demo/suites/hr-payroll/run", "/w/other-demo/demo/break"):
        assert alice.post(path, data={"csrf": token}).status_code == 404
    runs = app.state.store.data_dir / "workspaces" / "other-demo" / ".testbench"
    assert not runs.exists()


def test_posts_without_csrf_token_are_rejected(alice: TestClient) -> None:
    response = alice.post("/w/nmbs-demo/suites/hr-payroll/run", data={"csrf": "forged"})
    assert response.status_code == 400


def test_run_flow_with_report(alice: TestClient) -> None:
    token = csrf_of(alice, "/w/nmbs-demo")
    base = "/w/nmbs-demo/suites/hr-payroll/run"
    alice.post(base, data={"csrf": token, "mode": "baseline"})
    response = alice.post(base, data={"csrf": token, "mode": "run"}, follow_redirects=False)
    run_url = response.headers["location"]
    assert run_url.startswith("/w/nmbs-demo/runs/")

    page = alice.get(run_url)
    assert "Passed" in page.text
    report = alice.get(run_url + "/report")
    assert report.status_code == 200
    assert "default-src 'none'" in report.headers["content-security-policy"]

    alice.post("/w/nmbs-demo/demo/break", data={"csrf": token})
    response = alice.post(base, data={"csrf": token}, follow_redirects=False)
    assert "Failed" in alice.get(response.headers["location"]).text


@pytest.mark.parametrize("run_id", ["..", "..%2F..%2Fapp.db", "x", "20260101T00Z-hr-payroll-run"])
def test_run_ids_cannot_escape_the_workspace(alice: TestClient, run_id: str) -> None:
    assert alice.get(f"/w/nmbs-demo/runs/{run_id}/report").status_code == 404


def test_secrets_are_encrypted_and_never_shown(alice: TestClient, app) -> None:
    store = app.state.store
    store.set_secret("nmbs-demo", "target", "password", "s3cret-value")
    with sqlite3.connect(store.path) as db:
        stored = db.execute("SELECT ciphertext FROM secrets").fetchone()[0]
    assert "s3cret-value" not in stored
    workspace = store.workspace_for(store.user_by_email("alice@nmbs.test"), "nmbs-demo")
    assert store.secrets_for(workspace) == {"target": {"password": "s3cret-value"}}

    page = alice.get("/w/nmbs-demo").text
    assert "password" in page
    assert "s3cret-value" not in page


def test_security_headers_and_session_cookie(app) -> None:
    client = TestClient(app)
    response = client.get("/login")
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    login_response = login(client, "alice@nmbs.test")
    cookie = login_response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_logout_ends_the_session(alice: TestClient) -> None:
    token = csrf_of(alice, "/")
    alice.post("/logout", data={"csrf": token})
    assert alice.get("/", follow_redirects=False).status_code == 303


def test_app_refuses_to_start_without_a_strong_secret(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="TESTBENCH_SECRET_KEY"):
        create_app(tmp_path, "short")
