"""Helpers for the web app tests: sign in, read the CSRF token, post a form."""

import re

SECRET = "test-secret-key-that-is-long-enough-1234567890"
PASSWORD = "correct horse battery"


def csrf_of(client, path: str = "/login") -> str:
    html = client.get(path).text
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match, f"no csrf token on {path}"
    return match.group(1)


def login(client, email: str, password: str = PASSWORD):
    token = csrf_of(client)
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf": token},
        follow_redirects=False,
    )


def client_for(app, email: str):
    from fastapi.testclient import TestClient

    client = TestClient(app)
    assert login(client, email).headers["location"] == "/"
    return client


def post(client, path: str, data: dict | None = None, page: str = "/"):
    token = csrf_of(client, page)
    return client.post(path, data={"csrf": token, **(data or {})}, follow_redirects=False)
