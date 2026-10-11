"""``testbench web ...`` commands: serve the app and manage users.

Workspaces and connections are managed in the app itself.
"""

from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

from testbench.web.security import SecretBox
from testbench.web.store import Store, StoreError


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
    store = _store()
    if args.if_missing:
        try:
            store.user_by_email(args.email)
        except StoreError:
            pass
        else:
            print(f"User {args.email} already exists.")
            return 0
    user = store.create_user(args.email, args.name, _password("Password: "))
    print(f"Created user {user.email}")
    return 0


def cmd_add_member(args: argparse.Namespace) -> int:
    _store().add_member(args.slug, args.email, args.role)
    print(f"{args.email} is now {args.role} of {args.slug}")
    return 0


def add_parser(sub: argparse._SubParsersAction) -> None:
    web = sub.add_parser("web", help="run the web app and manage users")
    web_sub = web.add_subparsers(dest="web_command", required=True)

    p = web_sub.add_parser("serve", help="start the web app")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, help="default: $PORT or 8000")
    p.add_argument(
        "--insecure-cookies", action="store_true", help="allow plain HTTP (local use only)"
    )
    p.set_defaults(func=cmd_serve)

    p = web_sub.add_parser(
        "create-user", help="create a user (password from TESTBENCH_NEW_PASSWORD or a prompt)"
    )
    p.add_argument("email")
    p.add_argument("--name", required=True)
    p.add_argument("--if-missing", action="store_true", help="do nothing if the user exists")
    p.set_defaults(func=cmd_create_user)

    p = web_sub.add_parser("add-member", help="give a user access to a workspace")
    p.add_argument("slug")
    p.add_argument("email")
    p.add_argument("--role", choices=["owner", "member"], default="member")
    p.set_defaults(func=cmd_add_member)
