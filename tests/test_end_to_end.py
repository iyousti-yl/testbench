import json
from pathlib import Path

from conftest import break_target

from testbench.cli import main
from testbench.config import load_config
from testbench.runner import Runner

SUITE = "contracts"


def statuses(project: Path) -> dict[str, str]:
    result = Runner(load_config(project)).run_suite(SUITE)
    return {s.id: s.status for s in result.scenarios}


def test_clean_project_passes_after_baseline(project: Path) -> None:
    assert main(["baseline", SUITE]) == 0
    assert main(["run", SUITE]) == 0
    assert set(statuses(project).values()) == {"passed"}


def test_every_scenario_catches_the_injected_defects(project: Path) -> None:
    assert main(["baseline", SUITE]) == 0
    break_target(project)
    assert set(statuses(project).values()) == {"failed"}
    assert main(["run", SUITE]) == 1

    break_target(project, broken=False)
    assert set(statuses(project).values()) == {"passed"}


def test_regression_without_baseline_is_an_error(project: Path) -> None:
    assert statuses(project)["cost-lines-unchanged"] == "error"


def test_sensitive_baselines_contain_no_employee_ids(project: Path) -> None:
    assert main(["baseline", SUITE]) == 0
    files = list((project / ".testbench" / "baselines").rglob("*.json"))
    assert files
    for path in files:
        assert "E0001" not in path.read_text(encoding="utf-8")


def test_run_writes_report_and_results(project: Path) -> None:
    main(["run", SUITE, "--tag", "data-quality"])
    run_dir = next((project / ".testbench" / "runs").iterdir())
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in results["scenarios"]] == ["contract-data-quality"]
    assert "Contract data is complete" in (run_dir / "report.html").read_text(encoding="utf-8")


def test_scenario_without_matching_records_is_not_tested(project: Path) -> None:
    scenario = project / "suites" / SUITE / "two-contracts-same-month.yaml"
    scenario.write_text(
        scenario.read_text(encoding="utf-8").replace("COUNT(*) = 2", "COUNT(*) = 5"),
        encoding="utf-8",
    )
    assert statuses(project)["two-contracts-same-month"] == "skipped"


def test_single_scenario_can_be_run(project: Path) -> None:
    assert main(["run", SUITE, "--scenario", "contract-data-quality"]) == 0
    assert main(["run", SUITE, "--scenario", "does-not-exist"]) == 2


def test_init_creates_an_empty_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init", "new"]) == 0
    config = load_config(tmp_path / "new")
    assert config.connections == {}
    assert (tmp_path / "new" / "suites").is_dir()
    assert main(["init", "new"]) == 2  # never overwrites
