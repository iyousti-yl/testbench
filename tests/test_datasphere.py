"""Datasphere connector tests against a fake HANA driver (no tenant needed)."""

import sys
import types
from decimal import Decimal

import pytest

from testbench.connectors import create_connector
from testbench.connectors.base import ConnectorError, ObjectRef, ensure_read_only


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


SETTINGS = {"host": "tenant.example.test", "user": "HR#TB", "password": "pw", "schema": "HR"}


def test_connects_with_tls_and_space_schema(driver) -> None:
    connector = create_connector("datasphere", SETTINGS)
    connector.test_connection()
    call = driver.calls[0]
    assert call["address"] == "tenant.example.test" and call["port"] == 443
    assert call["encrypt"] is True and call["sslValidateCertificate"] is True
    assert call["currentSchema"] == "HR"
    assert "pw" not in repr(connector)


def test_connection_errors_are_reported_without_crashing(driver) -> None:
    connector = create_connector("datasphere", {**SETTINGS, "password": "wrong"})
    with pytest.raises(ConnectorError, match="cannot connect to Datasphere"):
        connector.test_connection()


def test_query_returns_a_table_and_wraps_errors(driver) -> None:
    driver.responses["HR_COST_LINES_V"] = (["CONTRACT_ID", "COST"], [("C1", Decimal("10.50"))])
    connector = create_connector("datasphere", SETTINGS)
    table = connector.query('SELECT * FROM "HR_COST_LINES_V"')
    assert table.columns == ["CONTRACT_ID", "COST"] and len(table) == 1
    with pytest.raises(ConnectorError, match="syntax"):
        connector.query("SELECT FAIL")


def test_lists_and_describes_space_objects(driver) -> None:
    driver.responses["SYS.VIEWS"] = (
        ["SCHEMA_NAME", "NAME", "KIND"],
        [("HR", "HR_COST_LINES_V", "view")],
    )
    driver.responses["SYS.VIEW_COLUMNS"] = (
        ["COLUMN_NAME", "DATA_TYPE_NAME", "IS_NULLABLE", "POSITION"],
        [("CONTRACT_ID", "NVARCHAR", "FALSE", 1), ("COST", "DECIMAL", "TRUE", 2)],
    )
    connector = create_connector("datasphere", SETTINGS)
    objects = connector.list_objects()
    assert objects == [ObjectRef(name="HR_COST_LINES_V", kind="view", schema="HR")]
    schema = connector.describe(objects[0])
    assert [(c.name, c.type, c.nullable) for c in schema.columns] == [
        ("CONTRACT_ID", "NVARCHAR", False),
        ("COST", "DECIMAL", True),
    ]
    assert driver.connection.executed[0][1] == ("HR", "HR")


def test_close_releases_the_connection(driver) -> None:
    connector = create_connector("datasphere", SETTINGS)
    connector.test_connection()
    connector.close()
    assert driver.connection.closed


def test_missing_driver_gives_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "hdbcli", None)
    with pytest.raises(ConnectorError, match="testbench\\[datasphere\\]"):
        create_connector("datasphere", SETTINGS)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM HR_CONTRACTS",
        "UPDATE x SET a = 1",
        "SELECT 1; DROP TABLE x",
        "-- comment\nINSERT INTO x VALUES (1)",
        "CALL some_procedure()",
    ],
)
def test_only_select_statements_are_allowed(sql: str) -> None:
    with pytest.raises(ConnectorError):
        ensure_read_only(sql)


@pytest.mark.parametrize(
    "sql", ["SELECT 1", "  with t as (select 1) select * from t;", "/* note */ SELECT 1"]
)
def test_select_statements_pass_the_guard(sql: str) -> None:
    ensure_read_only(sql)
