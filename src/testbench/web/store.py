"""The app database: users, workspaces, memberships and encrypted connection secrets.

Workspace content (configuration, suites, baselines, runs) lives in a folder per workspace;
this database only decides who may open which workspace.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from testbench.web.security import (
    DUMMY_HASH,
    SecretBox,
    check_password_strength,
    hash_password,
    verify_password,
)

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")
ROLES = ("owner", "member")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspaces (
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  is_demo INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('owner', 'member')),
  PRIMARY KEY (user_id, workspace_id)
);
CREATE TABLE IF NOT EXISTS secrets (
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  connection TEXT NOT NULL,
  key TEXT NOT NULL,
  ciphertext TEXT NOT NULL,
  PRIMARY KEY (workspace_id, connection, key)
);
"""


class StoreError(ValueError):
    pass


@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str


@dataclass(frozen=True)
class Workspace:
    id: int
    slug: str
    name: str
    is_demo: bool
    role: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, data_dir: Path, secret_box: SecretBox) -> None:
        self.data_dir = data_dir
        self.box = secret_box
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "app.db"
        with self._db() as db:
            db.executescript(_SCHEMA)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
            db.commit()
        finally:
            db.close()

    # Users -----------------------------------------------------------------

    def create_user(self, email: str, name: str, password: str) -> User:
        check_password_strength(password)
        email = email.strip().lower()
        if "@" not in email:
            raise StoreError("email address is not valid")
        try:
            with self._db() as db:
                cur = db.execute(
                    "INSERT INTO users (email, name, password_hash, created_at) VALUES (?,?,?,?)",
                    (email, name.strip(), hash_password(password), _now()),
                )
        except sqlite3.IntegrityError as exc:
            raise StoreError(f"a user with email {email} already exists") from exc
        return User(id=cur.lastrowid, email=email, name=name.strip())

    def authenticate(self, email: str, password: str) -> User | None:
        with self._db() as db:
            row = db.execute(
                "SELECT id, email, name, password_hash FROM users WHERE email = ?",
                (email.strip().lower(),),
            ).fetchone()
        if row is None:
            verify_password(password, DUMMY_HASH)  # same cost as a real check
            return None
        if not verify_password(password, row["password_hash"]):
            return None
        return User(id=row["id"], email=row["email"], name=row["name"])

    def get_user(self, user_id: int) -> User | None:
        with self._db() as db:
            row = db.execute(
                "SELECT id, email, name FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return User(**dict(row)) if row else None

    def user_by_email(self, email: str) -> User:
        with self._db() as db:
            row = db.execute(
                "SELECT id, email, name FROM users WHERE email = ?", (email.strip().lower(),)
            ).fetchone()
        if row is None:
            raise StoreError(f"no user with email {email}")
        return User(**dict(row))

    # Workspaces ------------------------------------------------------------

    def create_workspace(self, slug: str, name: str, is_demo: bool = False) -> Workspace:
        if not SLUG.match(slug):
            raise StoreError("workspace id must be 3-50 lowercase letters, digits or dashes")
        try:
            with self._db() as db:
                cur = db.execute(
                    "INSERT INTO workspaces (slug, name, is_demo, created_at) VALUES (?,?,?,?)",
                    (slug, name.strip(), int(is_demo), _now()),
                )
        except sqlite3.IntegrityError as exc:
            raise StoreError(f"workspace {slug} already exists") from exc
        return Workspace(id=cur.lastrowid, slug=slug, name=name.strip(), is_demo=is_demo)

    def add_member(self, workspace_slug: str, email: str, role: str = "member") -> None:
        if role not in ROLES:
            raise StoreError(f"role must be one of {', '.join(ROLES)}")
        user = self.user_by_email(email)
        workspace = self._workspace_by_slug(workspace_slug)
        with self._db() as db:
            db.execute(
                "INSERT INTO memberships (user_id, workspace_id, role) VALUES (?,?,?) "
                "ON CONFLICT (user_id, workspace_id) DO UPDATE SET role = excluded.role",
                (user.id, workspace.id, role),
            )

    def workspaces_for(self, user: User) -> list[Workspace]:
        with self._db() as db:
            rows = db.execute(
                "SELECT w.id, w.slug, w.name, w.is_demo, m.role FROM workspaces w "
                "JOIN memberships m ON m.workspace_id = w.id WHERE m.user_id = ? "
                "ORDER BY w.name",
                (user.id,),
            ).fetchall()
        return [
            Workspace(r["id"], r["slug"], r["name"], bool(r["is_demo"]), r["role"]) for r in rows
        ]

    def workspace_for(self, user: User, slug: str) -> Workspace | None:
        """The only way the web app resolves a workspace: membership is part of the query."""
        with self._db() as db:
            row = db.execute(
                "SELECT w.id, w.slug, w.name, w.is_demo, m.role FROM workspaces w "
                "JOIN memberships m ON m.workspace_id = w.id "
                "WHERE m.user_id = ? AND w.slug = ?",
                (user.id, slug),
            ).fetchone()
        if row is None:
            return None
        return Workspace(row["id"], row["slug"], row["name"], bool(row["is_demo"]), row["role"])

    def _workspace_by_slug(self, slug: str) -> Workspace:
        with self._db() as db:
            row = db.execute(
                "SELECT id, slug, name, is_demo FROM workspaces WHERE slug = ?", (slug,)
            ).fetchone()
        if row is None:
            raise StoreError(f"no workspace {slug}")
        return Workspace(row["id"], row["slug"], row["name"], bool(row["is_demo"]))

    def workspace_dir(self, workspace: Workspace) -> Path:
        return self.data_dir / "workspaces" / workspace.slug

    # Secrets ---------------------------------------------------------------

    def set_secret(self, workspace_slug: str, connection: str, key: str, value: str) -> None:
        workspace = self._workspace_by_slug(workspace_slug)
        with self._db() as db:
            db.execute(
                "INSERT INTO secrets (workspace_id, connection, key, ciphertext) VALUES (?,?,?,?) "
                "ON CONFLICT (workspace_id, connection, key) "
                "DO UPDATE SET ciphertext = excluded.ciphertext",
                (workspace.id, connection, key, self.box.encrypt(value)),
            )

    def secrets_for(self, workspace: Workspace) -> dict[str, dict[str, str]]:
        with self._db() as db:
            rows = db.execute(
                "SELECT connection, key, ciphertext FROM secrets WHERE workspace_id = ?",
                (workspace.id,),
            ).fetchall()
        result: dict[str, dict[str, str]] = {}
        for row in rows:
            result.setdefault(row["connection"], {})[row["key"]] = self.box.decrypt(
                row["ciphertext"]
            )
        return result

    def secret_names(self, workspace: Workspace) -> dict[str, list[str]]:
        """Which secrets are set, without their values (for display)."""
        with self._db() as db:
            rows = db.execute(
                "SELECT connection, key FROM secrets WHERE workspace_id = ? ORDER BY 1, 2",
                (workspace.id,),
            ).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row["connection"], []).append(row["key"])
        return result
