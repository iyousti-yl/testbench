import json
from pathlib import Path

import pytest

from testbench.scenario import ScenarioError, load_scenario, load_suite

VALID = {
    "version": 1,
    "scenario": "Two contracts",
    "requirement": "One cost line per contract.",
    "connection": "target",
    "checks": [{"name": "lines", "query": "SELECT 1 AS x", "expect": {"row_count": 1}}],
}


def write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_json_scenario_loads(tmp_path: Path) -> None:
    scenario = load_scenario(write(tmp_path / "two.json", VALID))
    assert scenario.name == "Two contracts"
    assert scenario.requirement == "One cost line per contract."
    assert scenario.checks[0].expect == {"row_count": 1}


def test_schema_errors_point_to_the_field(tmp_path: Path) -> None:
    bad = {**VALID, "checks": [{"name": "x", "query": "SELECT 1", "expect": {"rows": 1}}]}
    with pytest.raises(ScenarioError, match="checks/0/expect"):
        load_scenario(write(tmp_path / "bad.json", bad))


def test_unknown_top_level_field_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ScenarioError, match="Additional properties"):
        load_scenario(write(tmp_path / "bad.json", {**VALID, "owner": "someone"}))


def test_connection_can_come_from_suite_defaults(tmp_path: Path) -> None:
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "suite.yaml").write_text("connection: target\ntags: [hr]\n", encoding="utf-8")
    data = {k: v for k, v in VALID.items() if k != "connection"}
    write(suite_dir / "a.json", {**data, "tags": ["edge"]})
    suite = load_suite(suite_dir)
    assert suite.scenarios[0].connection == "target"
    assert suite.scenarios[0].tags == ["hr", "edge"]


def test_missing_connection_is_an_error(tmp_path: Path) -> None:
    data = {k: v for k, v in VALID.items() if k != "connection"}
    with pytest.raises(ScenarioError, match="connection"):
        load_scenario(write(tmp_path / "a.json", data))


def test_fixture_suite_is_valid() -> None:
    suite = Path(__file__).parent / "fixtures" / "suites" / "contracts"
    assert len(load_suite(suite).scenarios) == 4
