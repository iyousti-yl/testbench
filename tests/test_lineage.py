"""Lineage: capture, compare with the previous capture, impact and scenarios to re-run."""

from pathlib import Path

import pytest
from conftest import FIXTURES, break_target

from testbench.cli import main
from testbench.connectors import create_connector
from testbench.lineage import (
    LineageEdge,
    LineageGraph,
    LineageObject,
    LineageSnapshot,
    LineageStore,
    capture,
    compare,
)
from testbench.scenario import load_suite


def snapshot(objects: list[LineageObject], edges: list[tuple[str, str]], n: int = 1):
    graph = LineageGraph(edges=[LineageEdge(s, t) for s, t in edges])
    for obj in objects:
        graph.add(obj)
    return LineageSnapshot(f"20261011T1200000000{n:02d}Z", "target", f"t{n}", ["S"], graph)


def view(name: str, sql: str = "SELECT 1", columns: tuple[str, ...] = ("A INTEGER",)):
    return LineageObject("S", name, "view", list(columns), sql)


def table(name: str, columns: tuple[str, ...] = ("A INTEGER",)):
    return LineageObject("S", name, "table", list(columns))


def test_first_lineage_has_no_changes() -> None:
    diff = compare(None, snapshot([table("T")], []))
    assert diff.first and diff.changes == []


def test_changes_impact_and_dependencies() -> None:
    before = snapshot(
        [table("T"), view("V1", "SELECT a FROM T"), view("V2", "SELECT a FROM V1"), view("OLD")],
        [("S.T", "S.V1"), ("S.V1", "S.V2")],
        1,
    )
    after = snapshot(
        [
            table("T", ("A INTEGER", "B NVARCHAR(10)")),
            view("V1", "SELECT a\nFROM T WHERE a > 0"),
            view("V2", "SELECT  a   FROM V1"),  # only whitespace: not a change
            view("NEW", "SELECT a FROM T"),
        ],
        [("S.T", "S.V1"), ("S.V1", "S.V2"), ("S.T", "S.NEW")],
        2,
    )
    diff = compare(before, after)
    changes = {c.key: c for c in diff.changes}
    assert {k: c.status for k, c in changes.items()} == {
        "S.NEW": "added",
        "S.OLD": "removed",
        "S.T": "changed",
        "S.V1": "changed",
    }
    assert diff.counts() == [("added", 1), ("changed", 2), ("removed", 1)]
    assert changes["S.T"].details == ["columns added: B"]
    assert changes["S.T"].impacted == ["S.NEW", "S.V1", "S.V2"]  # transitive
    assert changes["S.V1"].details == ["definition changed"]
    assert "+FROM T WHERE a > 0" in changes["S.V1"].definition_diff
    assert diff.edges_added == [LineageEdge("S.T", "S.NEW")]


def test_column_type_changes_are_named() -> None:
    before = snapshot([table("T", ("A INTEGER", "B NVARCHAR(10)"))], [], 1)
    after = snapshot([table("T", ("A DECIMAL(15,2)", "B NVARCHAR(10)"))], [], 2)
    (change,) = compare(before, after).changes
    assert change.details == ["column types changed: A INTEGER -> DECIMAL(15,2)"]


def test_scenarios_that_read_changed_or_impacted_objects() -> None:
    suite = load_suite(FIXTURES / "suites" / "contracts")
    before = snapshot(
        [table("HR_CONTRACTS"), view("HR_COST_LINES_V"), view("PAYROLL_EXPORT_V")],
        [("S.HR_CONTRACTS", "S.HR_COST_LINES_V"), ("S.HR_COST_LINES_V", "S.PAYROLL_EXPORT_V")],
        1,
    )
    after = snapshot(
        [table("HR_CONTRACTS"), view("HR_COST_LINES_V", "changed"), view("PAYROLL_EXPORT_V")],
        [("S.HR_CONTRACTS", "S.HR_COST_LINES_V"), ("S.HR_COST_LINES_V", "S.PAYROLL_EXPORT_V")],
        2,
    )
    (change,) = compare(before, after, [suite]).changes
    assert change.impacted == ["S.PAYROLL_EXPORT_V"]
    assert change.scenarios == [
        "contracts/cost-lines-unchanged",
        "contracts/payroll-matches-source",
        "contracts/two-contracts-same-month",
    ]


def test_store_keeps_history_and_finds_the_previous(tmp_path: Path) -> None:
    store = LineageStore(tmp_path)
    first, second = snapshot([table("T")], [], 1), snapshot([table("T")], [], 2)
    store.save(first)
    store.save(second)
    assert store.latest("target").id == second.id
    assert store.previous("target", second.id).id == first.id
    assert store.previous("target", first.id) is None
    assert store.load("target", "../../app") is None
    with pytest.raises(ValueError):
        store.ids("../x")


def test_cli_lineage_reports_what_changed(project: Path, capsys) -> None:
    assert main(["lineage", "target"]) == 0
    assert "First lineage" in capsys.readouterr().out
    assert main(["lineage", "target"]) == 0
    assert "Nothing changed" in capsys.readouterr().out

    break_target(project)
    assert main(["lineage", "target"]) == 0
    out = capsys.readouterr().out
    assert "changed  view     main.HR_COST_LINES_V (definition changed)" in out
    assert "impacts: main.PAYROLL_EXPORT_V" in out
    assert "contracts/cost-lines-unchanged" in out
    assert len(list((project / ".testbench" / "lineage" / "target").glob("*.json"))) == 3


def test_sqlite_lineage_finds_views_and_what_they_read(project: Path) -> None:
    connector = create_connector("sqlite", {"path": str(project / "target.db")})
    graph = capture(connector, "target").graph
    assert graph.upstream("main.PAYROLL_EXPORT_V") == ["main.HR_COST_LINES_V"]
    assert graph.downstream("main.HR_CONTRACTS") == ["main.HR_COST_LINES_V"]
    assert graph.objects["main.HR_COST_LINES_V"].columns[0] == "contract_id TEXT"


class _Lob:
    def __init__(self, text: str) -> None:
        self.text = text

    def read(self) -> str:
        return self.text


def test_datasphere_lineage_reads_the_catalog(driver) -> None:
    driver.responses["LINEAGE_VIEWS"] = (
        ["SCHEMA_NAME", "VIEW_NAME", "DEFINITION", "CREATE_TIME"],
        [("HR", "COST_V", _Lob('SELECT * FROM "HR"."CONTRACTS"'), "2026-10-01")],
    )
    driver.responses["LINEAGE_TABLES"] = (
        ["SCHEMA_NAME", "TABLE_NAME", "TABLE_TYPE", "CREATE_TIME"],
        [("HR", "CONTRACTS", "VIRTUAL", "2026-09-01")],
    )
    driver.responses["LINEAGE_COLUMNS"] = (
        ["SCHEMA_NAME", "OBJECT_NAME", "COLUMN_NAME", "DATA_TYPE_NAME", "LENGTH", "SCALE", "P"],
        [
            ("HR", "CONTRACTS", "ID", "NVARCHAR", 10, None, 1),
            ("HR", "COST_V", "COST", "DECIMAL", 15, 2, 1),
        ],
    )
    driver.responses["LINEAGE_DEPENDENCIES"] = (
        ["BS", "BN", "BT", "DS", "DN"],
        [("HR", "CONTRACTS", "TABLE", "HR", "COST_V"), ("SHARED", "RATES", "VIEW", "HR", "COST_V")],
    )
    settings = {"host": "h", "user": "HR#TB", "password": "pw", "space": "HR"}
    graph, scope = create_connector("datasphere", settings).lineage()
    assert scope == ["HR"]
    assert graph.objects["HR.COST_V"].definition == 'SELECT * FROM "HR"."CONTRACTS"'
    assert graph.objects["HR.COST_V"].columns == ["COST DECIMAL(15,2)"]
    assert graph.objects["HR.CONTRACTS"].kind == "virtual table"
    assert graph.objects["SHARED.RATES"].kind == "external"
    assert graph.upstream("HR.COST_V") == ["HR.CONTRACTS", "SHARED.RATES"]
    lineage_queries = [p for sql, p in driver.connection.executed if "LINEAGE_" in sql]
    assert lineage_queries[0] == ("HR",) and lineage_queries[2] == ("HR", "HR")


def test_datasphere_lineage_scope_setting(driver) -> None:
    from testbench.connectors import ConnectorError, connector_class

    cls = connector_class("datasphere")
    typed = {
        "tenant_url": "https://acme.eu10.hcs.cloud.sap",
        "space": "hr",
        "host": "abc.hana.prod-eu10.hanacloud.ondemand.com",
        "user": "HR#TB",
        "lineage_scope": "hr, finance  hr#open",
    }
    assert cls.check_settings(typed)["lineage_scope"] == "HR, FINANCE, HR#OPEN"
    with pytest.raises(ConnectorError, match="not a space ID"):
        cls.check_settings({**typed, "lineage_scope": "HR; DROP"})

    for key in ("LINEAGE_VIEWS", "LINEAGE_TABLES", "LINEAGE_COLUMNS", "LINEAGE_DEPENDENCIES"):
        driver.responses[key] = (["X"], [])
    settings = {"host": "h", "user": "HR#TB", "password": "pw", "space": "HR"}
    connector = create_connector("datasphere", {**settings, "lineage_scope": "HR, FINANCE"})
    assert connector.lineage()[1] == ["FINANCE", "HR"]
    assert connector.lineage(["OTHER"])[1] == ["OTHER"]  # --scope on the command line wins
