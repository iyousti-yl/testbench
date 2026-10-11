"""SQLite connector, used for the demo and for automated tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from testbench.connectors.base import ColumnInfo, ConnectorError, ObjectRef, ObjectSchema
from testbench.table import Table


class SQLiteConnector:
    name = "sqlite"
    capabilities = frozenset({"sql", "metadata"})

    def __init__(self, path: str, base_dir: Path | None = None, **_: Any) -> None:
        db_path = Path(path)
        if not db_path.is_absolute() and base_dir is not None:
            db_path = base_dir / db_path
        self.path = db_path
        self._conn: sqlite3.Connection | None = None

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            if not self.path.exists():
                raise ConnectorError(f"SQLite database not found: {self.path}")
            # Read-only: a test tool must never change the data it checks.
            self._conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        return self._conn

    def test_connection(self) -> None:
        self.query("SELECT 1")

    def list_objects(self, scope: str | None = None) -> list[ObjectRef]:
        table = self.query(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name"
        )
        return [ObjectRef(name=name, kind=kind) for name, kind in table.rows]

    def describe(self, obj: ObjectRef) -> ObjectSchema:
        info = self.query(f"PRAGMA table_info({obj.qualified_name})")
        columns = [
            ColumnInfo(name=row[1], type=row[2] or "", nullable=not row[3], key=bool(row[5]))
            for row in info.rows
        ]
        if not columns:
            raise ConnectorError(f"object not found: {obj.name}")
        return ObjectSchema(ref=obj, columns=columns)

    def query(self, sql: str, params: dict[str, Any] | None = None) -> Table:
        try:
            cursor = self._connection().execute(sql, params or {})
        except sqlite3.Error as exc:
            raise ConnectorError(str(exc)) from exc
        columns = [d[0] for d in cursor.description or []]
        return Table(columns=columns, rows=cursor.fetchall())

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
