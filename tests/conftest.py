"""A small test project: a source and a target SQLite database with generated contracts.

All names and numbers are made up. The target has a cost-line view and a payroll export view,
and ``break_target`` introduces a logic defect and a data anomaly the scenarios must catch.
"""

import shutil
import sqlite3
import sys
import types
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
MONTHS = ["2026-01", "2026-02", "2026-03"]

_CONTRACTS = """
CREATE TABLE {name} (
  contract_id TEXT NOT NULL, employee_id TEXT NOT NULL, month TEXT NOT NULL,
  share REAL NOT NULL, fte REAL NOT NULL, cost_center TEXT, monthly_salary REAL NOT NULL,
  PRIMARY KEY (contract_id, month)
)
"""
_COST_LINES = """
CREATE VIEW HR_COST_LINES_V AS
SELECT contract_id, employee_id, month, cost_center, share,
       ROUND(monthly_salary * fte * share, 2) AS cost
FROM HR_CONTRACTS {where}
"""
# The defect: "deduplicating" per employee and month drops the first contract when an
# employee changes contract mid-month.
_DEDUPLICATED = """
c WHERE contract_id = (SELECT MAX(contract_id) FROM HR_CONTRACTS c2
                       WHERE c2.employee_id = c.employee_id AND c2.month = c.month)
"""
_PAYROLL = """
CREATE VIEW PAYROLL_EXPORT_V AS
SELECT employee_id, month, ROUND(SUM(cost), 2) AS total_cost
FROM HR_COST_LINES_V GROUP BY employee_id, month
"""


def contracts() -> list[tuple]:
    rows = []
    for e in range(1, 9):
        employee, contract = f"E{e:04d}", f"C{100 + e}"
        fte, salary, cost_center = (1.0, 0.8)[e % 2], 3000.0 + 250 * e, f"CC-{e % 3}"
        for month in MONTHS:
            if e in (3, 6) and month == "2026-02":  # contract change in the middle of a month
                rows.append((contract, employee, month, 0.5, fte, cost_center, salary))
                contract, salary = f"C{200 + e}", salary + 300
                rows.append((contract, employee, month, 0.5, fte, cost_center, salary))
            else:
                rows.append((contract, employee, month, 1.0, fte, cost_center, salary))
    return rows


def _write(path: Path, table: str, views: list[str]) -> None:
    db = sqlite3.connect(path)
    try:
        db.execute(_CONTRACTS.format(name=table))
        db.executemany(f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?)", contracts())
        for view in views:
            db.execute(view)
        db.commit()
    finally:
        db.close()


def build_project(folder: Path) -> Path:
    shutil.copytree(FIXTURES, folder)
    _write(folder / "source.db", "SF_CONTRACTS", [])
    _write(folder / "target.db", "HR_CONTRACTS", [_COST_LINES.format(where=""), _PAYROLL])
    return folder


def break_target(folder: Path, broken: bool = True) -> None:
    db = sqlite3.connect(folder / "target.db")
    try:
        db.execute("DROP VIEW PAYROLL_EXPORT_V")
        db.execute("DROP VIEW HR_COST_LINES_V")
        db.execute(_COST_LINES.format(where=_DEDUPLICATED if broken else ""))
        db.execute(_PAYROLL)
        cost_center = None if broken else "CC-1"
        db.execute(
            "UPDATE HR_CONTRACTS SET cost_center = ? WHERE contract_id = 'C101' AND month = ?",
            (cost_center, MONTHS[0]),
        )
        db.commit()
    finally:
        db.close()


@pytest.fixture
def app(tmp_path: Path):
    """The web app with two clients' workspaces: Alice owns A (Carol is a member), Bob owns B."""
    pytest.importorskip("fastapi")
    from webhelpers import PASSWORD, SECRET

    from testbench.web.app import create_app

    app = create_app(tmp_path / "data", SECRET, secure_cookies=False)
    store = app.state.store
    alice = store.create_user("alice@client-a.test", "Alice", PASSWORD)
    bob = store.create_user("bob@client-b.test", "Bob", PASSWORD)
    store.create_user("carol@client-a.test", "Carol", PASSWORD)
    store.create_workspace(alice, "Client A · HR")
    store.create_workspace(bob, "Client B")
    store.add_member("client-a-hr", "carol@client-a.test", "member")
    return app


@pytest.fixture
def alice(app):
    from webhelpers import client_for

    return client_for(app, "alice@client-a.test")


@pytest.fixture
def carol(app):
    from webhelpers import client_for

    return client_for(app, "carol@client-a.test")


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = build_project(tmp_path / "project")
    monkeypatch.chdir(folder)
    return folder


# A fake SAP HANA driver (hdbcli), so the Datasphere connector runs without a tenant.


class FakeCursor:
    def __init__(self, conn: "FakeConnection") -> None:
        self.conn = conn
        self.description = None
        self._rows: list[tuple] = []

    def execute(self, sql: str, params=None) -> None:
        self.conn.executed.append((" ".join(sql.split()), params))
        if "FAIL" in sql:
            raise self.conn.module.Error("SQL syntax error")
        for marker, (columns, rows) in self.conn.responses.items():
            if marker in sql:
                self.description = [(c,) for c in columns]
                self._rows = rows
                return
        self.description, self._rows = [("X",)], [(1,)]

    def fetchall(self) -> list[tuple]:
        return self._rows

    def close(self) -> None:
        pass


class FakeConnection:
    def __init__(self, module, responses) -> None:
        self.module = module
        self.responses = responses
        self.executed: list[tuple] = []
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def driver(monkeypatch: pytest.MonkeyPatch):
    dbapi = types.ModuleType("hdbcli.dbapi")
    dbapi.Error = type("Error", (Exception,), {})
    dbapi.calls = []
    dbapi.responses = {}

    def connect(**kwargs):
        dbapi.calls.append(kwargs)
        if kwargs["password"] == "wrong":
            raise dbapi.Error("authentication failed")
        dbapi.connection = FakeConnection(dbapi, dbapi.responses)
        return dbapi.connection

    dbapi.connect = connect
    package = types.ModuleType("hdbcli")
    package.dbapi = dbapi
    monkeypatch.setitem(sys.modules, "hdbcli", package)
    monkeypatch.setitem(sys.modules, "hdbcli.dbapi", dbapi)
    return dbapi
