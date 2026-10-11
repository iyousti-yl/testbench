"""The app database: users, workspaces, memberships and connections.

Connection passwords and keys are encrypted. Workspace content (suites, baselines, runs)
lives in a folder per workspace; this database decides who may open which workspace.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from testbench.web.security import (
    DUMMY_HASH,
    SecretBox,
    check_password_strength,
    hash_password,
    verify_password,
)

SCHEMA_VERSION = 1
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")
CONNECTION_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
ROLES = ("owner", "member")
MAX_NAME = 80
MAX_DESCRIPTION = 500

_SCHEMA = """
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE workspaces (
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE memberships (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('owner', 'member')),
  PRIMARY KEY (user_id, workspace_id)
);
CREATE TABLE connections (
  id INTEGER PRIMARY KEY,
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  settings TEXT NOT NULL,          -- JSON, never secrets
  sensitive INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  checked_at TEXT,
  check_ok INTEGER,
  check_message TEXT NOT NULL DEFAULT '',
  UNIQUE (workspace_id, name)
);
CREATE TABLE connection_secrets (
  connection_id INTEGER NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  ciphertext TEXT NOT NULL,
  PRIMARY KEY (connection_id, key)
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
    description: str = ""
    role: str = ""

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"


@dataclass(frozen=True)
class Connection:
    id: int
    workspace_id: int
    name: str
    type: str
    settings: dict[str, Any]
    sensitive: bool
    secret_keys: tuple[str, ...]
    updated_at: str
    checked_at: str | None
    check_ok: bool | None
    check_message: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:40].strip("-")
    return slug if len(slug) >= 3 else (slug + "-workspace").strip("-")


def _clean_name(name: str, description: str) -> tuple[str, str]:
    name, description = name.strip(), description.strip()
    if not name:
        raise StoreError("give the workspace a name")
    if len(name) > MAX_NAME:
        raise StoreError(f"the name can be at most {MAX_NAME} characters")
    if len(description) > MAX_DESCRIPTION:
        raise StoreError(f"the description can be at most {MAX_DESCRIPTION} characters")
    return name, description


class Store:
    def __init__(self, data_dir: Path, secret_box: SecretBox) -> None:
        self.data_dir = data_dir
        self.box = secret_box
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "app.db"
        self._migrate()

    def _migrate(self) -> None:
        with self._db() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            has_tables = db.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
            if version == SCHEMA_VERSION:
                return
            if version == 0 and not has_tables:
                db.executescript(_SCHEMA)
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                return
        raise StoreError(
            f"the data folder {self.data_dir} was created by an earlier preview of Testbench. "
            "Stop the app, delete that folder (or set TESTBENCH_DATA_DIR to a new one) and "
            "start again."
        )

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

    def _workspaces_root(self) -> Path:
        return self.data_dir / "workspaces"

    def workspace_dir(self, workspace: Workspace) -> Path:
        if not SLUG.match(workspace.slug):  # never build a path from anything else
            raise StoreError(f"invalid workspace id {workspace.slug!r}")
        return self._workspaces_root() / workspace.slug

    def _free_slug(self, db: sqlite3.Connection, base: str) -> str:
        for n in range(1, 1000):
            slug = base if n == 1 else f"{base}-{n}"
            taken = db.execute("SELECT 1 FROM workspaces WHERE slug = ?", (slug,)).fetchone()
            # A leftover folder is never reused: it could hold another workspace's runs.
            if not taken and not (self._workspaces_root() / slug).exists():
                return slug
        raise StoreError("could not find a free workspace id; choose another name")

    def create_workspace(self, owner: User, name: str, description: str = "") -> Workspace:
        """A new workspace with ``owner`` as its first owner, and its empty folder."""
        name, description = _clean_name(name, description)
        with self._db() as db:
            slug = self._free_slug(db, slugify(name))
            now = _now()
            cur = db.execute(
                "INSERT INTO workspaces (slug, name, description, created_at, updated_at) "
                "VALUES (?,?,?,?,?)",
                (slug, name, description, now, now),
            )
            db.execute(
                "INSERT INTO memberships (user_id, workspace_id, role) VALUES (?,?,'owner')",
                (owner.id, cur.lastrowid),
            )
            workspace = Workspace(cur.lastrowid, slug, name, description, "owner")
            (self.workspace_dir(workspace) / "suites").mkdir(parents=True)
        return workspace

    def update_workspace(self, workspace: Workspace, name: str, description: str) -> Workspace:
        name, description = _clean_name(name, description)
        with self._db() as db:
            db.execute(
                "UPDATE workspaces SET name = ?, description = ?, updated_at = ? WHERE id = ?",
                (name, description, _now(), workspace.id),
            )
        return Workspace(workspace.id, workspace.slug, name, description, workspace.role)

    def delete_workspace(self, workspace: Workspace) -> None:
        """Remove the folder first: if that fails, the workspace still exists and can be
        deleted again, instead of leaving data behind that nobody can reach."""
        folder = self.workspace_dir(workspace)
        if folder.exists():
            shutil.rmtree(folder)
        with self._db() as db:
            db.execute("DELETE FROM workspaces WHERE id = ?", (workspace.id,))

    def add_member(self, workspace_slug: str, email: str, role: str = "member") -> None:
        if role not in ROLES:
            raise StoreError(f"role must be one of {', '.join(ROLES)}")
        user = self.user_by_email(email)
        with self._db() as db:
            row = db.execute(
                "SELECT id FROM workspaces WHERE slug = ?", (workspace_slug,)
            ).fetchone()
            if row is None:
                raise StoreError(f"no workspace {workspace_slug}")
            db.execute(
                "INSERT INTO memberships (user_id, workspace_id, role) VALUES (?,?,?) "
                "ON CONFLICT (user_id, workspace_id) DO UPDATE SET role = excluded.role",
                (user.id, row["id"], role),
            )

    def workspaces_for(self, user: User) -> list[Workspace]:
        with self._db() as db:
            rows = db.execute(
                "SELECT w.id, w.slug, w.name, w.description, m.role FROM workspaces w "
                "JOIN memberships m ON m.workspace_id = w.id WHERE m.user_id = ? "
                "ORDER BY w.name COLLATE NOCASE",
                (user.id,),
            ).fetchall()
        return [Workspace(**dict(r)) for r in rows]

    def workspace_for(self, user: User, slug: str) -> Workspace | None:
        """The only way the web app resolves a workspace: membership is part of the query."""
        with self._db() as db:
            row = db.execute(
                "SELECT w.id, w.slug, w.name, w.description, m.role FROM workspaces w "
                "JOIN memberships m ON m.workspace_id = w.id "
                "WHERE m.user_id = ? AND w.slug = ?",
                (user.id, slug),
            ).fetchone()
        return Workspace(**dict(row)) if row else None

    # Connections -----------------------------------------------------------

    def _connection(self, db: sqlite3.Connection, row: sqlite3.Row) -> Connection:
        keys = db.execute(
            "SELECT key FROM connection_secrets WHERE connection_id = ? ORDER BY key",
            (row["id"],),
        ).fetchall()
        return Connection(
            id=row["id"],
            workspace_id=row["workspace_id"],
            name=row["name"],
            type=row["type"],
            settings=json.loads(row["settings"]),
            sensitive=bool(row["sensitive"]),
            secret_keys=tuple(k["key"] for k in keys),
            updated_at=row["updated_at"],
            checked_at=row["checked_at"],
            check_ok=None if row["check_ok"] is None else bool(row["check_ok"]),
            check_message=row["check_message"],
        )

    def connections(self, workspace: Workspace) -> list[Connection]:
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM connections WHERE workspace_id = ? ORDER BY name",
                (workspace.id,),
            ).fetchall()
            return [self._connection(db, row) for row in rows]

    def connection(self, workspace: Workspace, connection_id: int) -> Connection | None:
        """Scoped to the workspace: an id from another workspace is simply not found."""
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM connections WHERE id = ? AND workspace_id = ?",
                (connection_id, workspace.id),
            ).fetchone()
            return self._connection(db, row) if row else None

    def save_connection(
        self,
        workspace: Workspace,
        name: str,
        type_name: str,
        settings: dict[str, Any],
        secrets: dict[str, str],
        sensitive: bool,
        connection_id: int | None = None,
    ) -> Connection:
        """Create or update a connection. ``secrets`` is the complete set to keep, encrypted;
        any other stored secret of the connection is removed."""
        name = name.strip().lower()
        if not CONNECTION_NAME.match(name):
            raise StoreError(
                "connection name: start with a letter, then letters, digits, '-' or '_' "
                "(at most 40), for example datasphere-dev"
            )
        now = _now()
        try:
            with self._db() as db:
                if connection_id is None:
                    cur = db.execute(
                        "INSERT INTO connections (workspace_id, name, type, settings, sensitive, "
                        "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                        (workspace.id, name, type_name, json.dumps(settings), int(sensitive))
                        + (now, now),
                    )
                    connection_id = cur.lastrowid
                else:
                    cur = db.execute(
                        "UPDATE connections SET name = ?, settings = ?, sensitive = ?, "
                        "updated_at = ?, checked_at = NULL, check_ok = NULL, check_message = '' "
                        "WHERE id = ? AND workspace_id = ? AND type = ?",
                        (
                            name,
                            json.dumps(settings),
                            int(sensitive),
                            now,
                            connection_id,
                            workspace.id,
                            type_name,
                        ),
                    )
                    if cur.rowcount != 1:
                        raise StoreError("connection not found")
                db.execute(
                    "DELETE FROM connection_secrets WHERE connection_id = ?", (connection_id,)
                )
                db.executemany(
                    "INSERT INTO connection_secrets (connection_id, key, ciphertext) "
                    "VALUES (?,?,?)",
                    [(connection_id, k, self.box.encrypt(v)) for k, v in secrets.items()],
                )
        except sqlite3.IntegrityError as exc:
            raise StoreError(f"this workspace already has a connection named {name}") from exc
        connection = self.connection(workspace, connection_id)
        assert connection is not None
        return connection

    def delete_connection(self, workspace: Workspace, connection_id: int) -> None:
        with self._db() as db:
            db.execute(
                "DELETE FROM connections WHERE id = ? AND workspace_id = ?",
                (connection_id, workspace.id),
            )

    def record_check(
        self, workspace: Workspace, connection_id: int, ok: bool, message: str
    ) -> None:
        with self._db() as db:
            db.execute(
                "UPDATE connections SET checked_at = ?, check_ok = ?, check_message = ? "
                "WHERE id = ? AND workspace_id = ?",
                (_now(), int(ok), message[:500], connection_id, workspace.id),
            )

    def connection_secrets(self, connection: Connection) -> dict[str, str]:
        with self._db() as db:
            rows = db.execute(
                "SELECT key, ciphertext FROM connection_secrets WHERE connection_id = ?",
                (connection.id,),
            ).fetchall()
        return {row["key"]: self.box.decrypt(row["ciphertext"]) for row in rows}

    def secrets_for(self, workspace: Workspace) -> dict[str, dict[str, str]]:
        """Decrypted secrets per connection name, for the runner."""
        return {c.name: self.connection_secrets(c) for c in self.connections(workspace)}
