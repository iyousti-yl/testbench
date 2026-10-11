import json
from pathlib import Path

from testbench import demo
from testbench.cli import main
from testbench.config import load_config
from testbench.runner import Runner

SUITE = "hr-payroll"


def statuses(project: Path) -> dict[str, str]:
    result = Runner(load_config(project)).run_suite(SUITE)
    return {s.id: s.status for s in result.scenarios}


def test_clean_demo_passes_after_baseline(demo_project: Path) -> None:
    assert main(["baseline", SUITE]) == 0
    assert main(["run", SUITE]) == 0
    assert set(statuses(demo_project).values()) == {"passed"}


def test_every_scenario_catches_the_injected_defects(demo_project: Path) -> None:
    assert main(["baseline", SUITE]) == 0
    demo.set_broken(demo_project, broken=True)
    assert set(statuses(demo_project).values()) == {"failed"}
    assert main(["run", SUITE]) == 1

    demo.set_broken(demo_project, broken=False)
    assert set(statuses(demo_project).values()) == {"passed"}


def test_regression_without_baseline_is_an_error(demo_project: Path) -> None:
    assert statuses(demo_project)["cost-lines-unchanged"] == "error"


def test_sensitive_baselines_contain_no_employee_ids(demo_project: Path) -> None:
    assert main(["baseline", SUITE]) == 0
    files = list((demo_project / ".testbench" / "baselines").rglob("*.json"))
    assert files
    for path in files:
        assert "E0001" not in path.read_text(encoding="utf-8")


def test_run_writes_report_and_results(demo_project: Path) -> None:
    main(["run", SUITE, "--tag", "data-quality"])
    run_dir = next((demo_project / ".testbench" / "runs").iterdir())
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in results["scenarios"]] == ["contract-data-quality"]
    assert "Contract data is complete" in (run_dir / "report.html").read_text(encoding="utf-8")


def test_scenario_without_matching_records_is_not_tested(demo_project: Path) -> None:
    scenario = demo_project / "suites" / SUITE / "two-contracts-same-month.yaml"
    scenario.write_text(
        scenario.read_text(encoding="utf-8").replace("COUNT(*) = 2", "COUNT(*) = 5"),
        encoding="utf-8",
    )
    assert statuses(demo_project)["two-contracts-same-month"] == "skipped"


def test_single_scenario_can_be_run(demo_project: Path) -> None:
    assert main(["run", SUITE, "--scenario", "contract-data-quality"]) == 0
    assert main(["run", SUITE, "--scenario", "does-not-exist"]) == 2
