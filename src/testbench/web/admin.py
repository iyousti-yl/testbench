"""``testbench web ...`` commands: serve the app and manage users, workspaces and secrets."""

from __future__ import annotations

import argparse
import getpass
import os
import secrets
from pathlib import Path

import yaml

from testbench import demo
from testbench.web.security import SecretBox
from testbench.web.store import Store, Workspace

_EMPTY_CONFIG = {"project": "", "connections": {}, "suites_dir": "suites"}


def _settings() -> tuple[Path, str]:
    data_dir = Path(os.environ.get("TESTBENCH_DATA_DIR", "testbench-data"))
    key = os.environ.get("TESTBENCH_SECRET_KEY", "")
    if len(key) < 32:
        raise SystemExit(
            "error: set TESTBENCH_SECRET_KEY to a random value of at least 32 characters, e.g.\n"
            "  export TESTBENCH_SECRET_KEY=$(python -c 'import secrets; "
            "print(secrets.token_urlsafe(48))')"
        )
    return data_dir, key


def _store() -> Store:
    data_dir, key = _settings()
    return Store(data_dir, SecretBox(key))


def _password(prompt: str) -> str:
    from_env = os.environ.get("TESTBENCH_NEW_PASSWORD")
    if from_env:
        return from_env
    first = getpass.getpass(prompt)
    if first != getpass.getpass("Repeat: "):
        raise SystemExit("error: the passwords do not match")
    return first


def create_workspace(store: Store, slug: str, name: str, with_demo: bool) -> Workspace:
    workspace = store.create_workspace(slug, name, is_demo=with_demo)
    folder = store.workspace_dir(workspace)
    if with_demo:
        demo.create_example_project(folder)
        config_path = folder / "testbench.yaml"
        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace(
                "project: HR payroll demo", f"project: {name}"
            ),
            encoding="utf-8",
        )
    else:
        (folder / "suites").mkdir(parents=True, exist_ok=True)
        config = {**_EMPTY_CONFIG, "project": name}
        (folder / "testbench.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    return workspace


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from testbench.web.app import create_app

    data_dir, key = _settings()
    if args.insecure_cookies:
        print("warning: cookies are sent over plain HTTP; use this only on your own machine")
    app = create_app(data_dir, key, secure_cookies=not args.insecure_cookies)
    port = args.port or int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host=args.host, port=port, proxy_headers=True)
    return 0


def cmd_create_user(args: argparse.Namespace) -> int:
    user = _store().create_user(args.email, args.name, _password("Password: "))
    print(f"Created user {user.email}")
    return 0


def cmd_create_workspace(args: argparse.Namespace) -> int:
    workspace = create_workspace(_store(), args.slug, args.name, args.demo)
    print(f"Created workspace {workspace.slug}")
    return 0


def cmd_add_member(args: argparse.Namespace) -> int:
    _store().add_member(args.slug, args.email, args.role)
    print(f"{args.email} is now {args.role} of {args.slug}")
    return 0


def cmd_set_secret(args: argparse.Namespace) -> int:
    value = getpass.getpass(f"Value for {args.connection}.{args.key}: ")
    _store().set_secret(args.slug, args.connection, args.key, value)
    print(f"Stored {args.connection}.{args.key} (encrypted)")
    return 0


DEMO_ACCOUNTS = [
    # email, name, workspace, environment variable that may hold the password
    ("consultant@nmbs-demo.test", "NMBS consultant", "nmbs-demo", "TESTBENCH_DEMO_PASSWORD_NMBS"),
    (
        "consultant@other-demo.test",
        "Other client consultant",
        "other-client-demo",
        "TESTBENCH_DEMO_PASSWORD_OTHER",
    ),
]


def cmd_seed_demo(args: argparse.Namespace) -> int:
    """Two demo workspaces and two users, to show that each user only sees their own.

    Passwords come from TESTBENCH_DEMO_PASSWORD_NMBS / _OTHER when set (hosted demo), and are
    otherwise generated and printed once.
    """
    store = _store()
    if args.if_empty and store.has_workspaces():
        print("Demo already seeded.")
        return 0
    create_workspace(store, "nmbs-demo", "NMBS · HR integration (demo data)", with_demo=True)
    create_workspace(store, "other-client-demo", "Other client (demo data)", with_demo=True)
    print("Demo accounts:")
    for email, name, slug, env_var in DEMO_ACCOUNTS:
        password = os.environ.get(env_var) or secrets.token_urlsafe(12)
        store.create_user(email, name, password)
        store.add_member(slug, email, "owner")
        shown = f"password from {env_var}" if os.environ.get(env_var) else password
        print(f"  {email}  {shown}  -> {slug}")
    return 0


def add_parser(sub: argparse._SubParsersAction) -> None:
    web = sub.add_parser("web", help="run the web app and manage users and workspaces")
    web_sub = web.add_subparsers(dest="web_command", required=True)

    p = web_sub.add_parser("serve", help="start the web app")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, help="default: $PORT or 8000")
    p.add_argument(
        "--insecure-cookies", action="store_true", help="allow plain HTTP (local use only)"
    )
    p.set_defaults(func=cmd_serve)

    p = web_sub.add_parser("create-user", help="create a user (asks for the password)")
    p.add_argument("email")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_create_user)

    p = web_sub.add_parser("create-workspace", help="create a workspace")
    p.add_argument("slug", help="short id used in URLs, for example nmbs-hr")
    p.add_argument("--name", required=True)
    p.add_argument("--demo", action="store_true", help="fill it with the synthetic HR demo")
    p.set_defaults(func=cmd_create_workspace)

    p = web_sub.add_parser("add-member", help="give a user access to a workspace")
    p.add_argument("slug")
    p.add_argument("email")
    p.add_argument("--role", choices=["owner", "member"], default="member")
    p.set_defaults(func=cmd_add_member)

    p = web_sub.add_parser("set-secret", help="store an encrypted connection secret")
    p.add_argument("slug")
    p.add_argument("connection")
    p.add_argument("key", help="setting name, for example password")
    p.set_defaults(func=cmd_set_secret)

    p = web_sub.add_parser("seed-demo", help="create the NMBS demo and a second workspace")
    p.add_argument("--if-empty", action="store_true", help="do nothing if workspaces exist")
    p.set_defaults(func=cmd_seed_demo)
