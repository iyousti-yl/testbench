"""Datasphere connector tests against a fake HANA driver (no tenant needed)."""

import sys
from decimal import Decimal

import pytest

from testbench.connectors import create_connector
from testbench.connectors.base import ConnectorError, ObjectRef, ensure_read_only
from testbench.connectors.datasphere import DatasphereConnector

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


def test_space_setting_selects_the_schema(driver) -> None:
    settings = {k: v for k, v in SETTINGS.items() if k != "schema"}
    create_connector("datasphere", {**settings, "space": "HR_SPACE"}).test_connection()
    assert driver.calls[0]["currentSchema"] == "HR_SPACE"
    assert driver.calls[0]["connectTimeout"] == 20000


FORM = {
    "tenant_url": "https://acme.eu10.hcs.cloud.sap/dwaas-core/index.html#/home",
    "space": " hr_space ",
    "host": "https://abc-123.hana.prod-eu10.hanacloud.ondemand.com:443",
    "user": "HR_SPACE#TB",
    "password": "pw",
}


def test_form_settings_are_normalised() -> None:
    settings = DatasphereConnector.check_settings(FORM)
    assert settings["tenant_url"] == "https://acme.eu10.hcs.cloud.sap"
    assert settings["space"] == "HR_SPACE"
    assert settings["host"] == "abc-123.hana.prod-eu10.hanacloud.ondemand.com"


@pytest.mark.parametrize(
    "change",
    [
        {"host": "db.internal.example"},  # only SAP HANA Cloud hosts
        {"host": "127.0.0.1"},
        {"tenant_url": "http://acme.eu10.hcs.cloud.sap"},
        {"space": "HR SPACE"},
        {"user": " "},
    ],
)
def test_form_settings_are_rejected(change: dict) -> None:
    with pytest.raises(ConnectorError):
        DatasphereConnector.check_settings({**FORM, **change})
