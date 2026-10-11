"""Creating, editing, deleting and running scenarios in the web app."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

pytest.importorskip("fastapi")

from conftest import FIXTURES, break_target, build_project  # noqa: E402
from webhelpers import client_for, csrf_of, post  # noqa: E402

SCENARIO = {
    "suite": "__new__",
    "new_suite": "HR payroll",
    "title": "Contract data is complete",
    "requirement": "Every contract must have a cost center.",
    "connection": "target",
    "tags": "data-quality, hr",
    "checks": (
        "- name: no contract without cost center\n"
        "  query: |\n"
        "    SELECT contract_id, month\n"
        "    FROM HR_CONTRACTS\n"
        "    WHERE cost_center IS NULL\n"
        "  expect:\n"
        "    row_count: 0\n"
    ),
}


@pytest.fixture
def data(app, tmp_path: Path) -> Path:
    """Client A's workspace with two SQLite connections on generated test data."""
    store = app.state.store
    workspace = store.workspace_for(store.user_by_email("alice@client-a.test"), "client-a-hr")
    project = build_project(tmp_path / "test-data")
    for name in ("target", "source"):  # only tests can add SQLite connections
        store.save_connection(
            workspace, name, "sqlite", {"path": str(project / f"{name}.db")}, {}, sensitive=True
        )
    return project


def folder(app) -> Path:
    return app.state.store.data_dir / "workspaces" / "client-a-hr"


def create(client, **changes):
    return post(client, "/w/client-a-hr/scenarios/new", {**SCENARIO, **changes})


def test_create_writes_a_readable_scenario_file(alice, app, data) -> None:
    response = create(alice)
    assert response.status_code == 303
    url = "/w/client-a-hr/suites/hr-payroll/scenarios/contract-data-is-complete"
    assert response.headers["location"] == url

    path = folder(app) / "suites" / "hr-payroll" / "contract-data-is-complete.yaml"
    text = path.read_text(encoding="utf-8")
    assert "query: |\n" in text  # SQL stays a readable block
    document = yaml.safe_load(text)
    assert document["requirement"] == "Every contract must have a cost center."
    assert document["tags"] == ["data-quality", "hr"]
    assert document["checks"][0]["expect"] == {"row_count": 0}

    page = alice.get(url).text
    assert "Every contract must have a cost center." in page and "Run this scenario" in page
    assert "Contract data is complete" in alice.get("/w/client-a-hr").text


def test_same_title_gets_its_own_file(alice, app, data) -> None:
    create(alice)
    response = create(alice, suite="hr-payroll")
    assert response.headers["location"].endswith("/contract-data-is-complete-2")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"checks": "- name: x\n  query: [unclosed"}, "checks (line"),
        ({"checks": "- name: x\n  query: SELECT 1\n  expect: {rows: 1}"}, "checks/0/expect"),
        ({"requirement": " "}, "write the business requirement"),
        ({"connection": "nope"}, "choose one of this workspace"),
        ({"new_suite": ""}, "choose a test suite or name a new one"),
        (
            {
                "checks": "- name: x\n  query: SELECT 1\n  expect:\n"
                "    reconcile: {connection: elsewhere, query: SELECT 1}"
            },
            "connection 'elsewhere' does not exist",
        ),
        (
            {"checks": "- name: a\n  query: SELECT 1\n  expect: {row_count: 1}\n" * 2},
            "check names must be unique",
        ),
    ],
)
def test_invalid_scenarios_are_explained_and_not_saved(alice, app, data, changes, message):
    response = create(alice, **changes)
    assert response.status_code == 400
    assert message in response.text.replace("&#39;", "'")
    assert SCENARIO["requirement"] in response.text or "requirement" in changes  # input kept
    assert not (folder(app) / "suites" / "hr-payroll").exists()


def test_selection_needs_a_sql_connection(alice, app, data) -> None:
    store = app.state.store
    workspace = store.workspace_for(store.user_by_email("alice@client-a.test"), "client-a-hr")
    store.save_connection(
        workspace,
        "sf",
        "successfactors",
        {"api_url": "https://api55.sapsf.eu", "company_id": "C", "auth": "basic", "username": "u"},
        {"password": "p"},
        sensitive=True,
    )
    response = create(
        alice,
        connection="sf",
        select="SELECT 1",
        checks="- name: jobs\n  query: EmpJob?$select=userId\n  expect: {row_count: {min: 1}}",
    )
    assert response.status_code == 400
    assert "only works on SQL connections" in response.text


def test_edit_keeps_the_file_and_its_format(alice, app, data) -> None:
    suites = folder(app) / "suites"
    shutil.copytree(FIXTURES / "suites" / "contracts", suites / "contracts")
    base = "/w/client-a-hr/suites/contracts/scenarios/contract-data-quality"
    form = alice.get(base + "/edit").text
    assert "Contract data is complete and plausible" in form
    assert "connection" in form and 'value="target" selected' in form  # suite default

    edited = {
        "title": "Contract data is complete and plausible",
        "requirement": "Every contract must have a cost center (edited).",
        "connection": "target",
        "checks": "- name: FTE within range\n  query: SELECT fte FROM HR_CONTRACTS\n"
        "  expect: {all_rows: fte > 0 and fte <= 1}\n",
    }
    response = post(alice, base + "/edit", edited, page=base + "/edit")
    assert response.headers["location"] == base
    document = json.loads((suites / "contracts" / "contract-data-quality.json").read_text())
    assert document["requirement"].endswith("(edited).")
    assert [c["name"] for c in document["checks"]] == ["FTE within range"]


def test_run_one_scenario_then_delete_it_with_its_baselines(alice, app, data) -> None:
    create(alice)
    create(
        alice,
        suite="hr-payroll",
        title="Cost lines unchanged",
        checks=(
            "- name: cost lines match the baseline\n"
            "  query: SELECT contract_id, month, cost FROM HR_COST_LINES_V\n"
            "  expect:\n    regression: {keys: [contract_id, month], tolerance: 0.01}\n"
        ),
    )
    base = "/w/client-a-hr/suites/hr-payroll/scenarios/cost-lines-unchanged"
    token = csrf_of(alice, base)
    run = "/w/client-a-hr/suites/hr-payroll/run"
    alice.post(run, data={"csrf": token, "mode": "baseline", "scenario": "cost-lines-unchanged"})
    response = alice.post(
        run, data={"csrf": token, "scenario": "cost-lines-unchanged"}, follow_redirects=False
    )
    run_id = response.headers["location"].rsplit("/", 1)[1]
    results = json.loads(
        (folder(app) / ".testbench" / "runs" / run_id / "results.json").read_text()
    )
    assert [s["id"] for s in results["scenarios"]] == ["cost-lines-unchanged"]
    assert results["status"] == "passed"

    break_target(data)
    response = alice.post(
        run, data={"csrf": token, "scenario": "cost-lines-unchanged"}, follow_redirects=False
    )
    assert "Failed" in alice.get(response.headers["location"]).text

    baselines = folder(app) / ".testbench" / "baselines" / "hr-payroll"
    assert (baselines / "cost-lines-unchanged").is_dir()
    post(alice, base + "/delete", page=base)
    assert not (baselines / "cost-lines-unchanged").exists()
    assert alice.get(base).status_code == 404
    assert (folder(app) / "suites" / "hr-payroll").is_dir()  # another scenario is left

    other = "/w/client-a-hr/suites/hr-payroll/scenarios/contract-data-is-complete"
    response = post(alice, other + "/delete", page=other)
    assert not (folder(app) / "suites" / "hr-payroll").exists()  # the empty suite goes too
    assert "was empty and is removed" in alice.get(response.headers["location"]).text


def test_members_can_write_scenarios(carol, data) -> None:
    assert create(carol).status_code == 303


def test_scenarios_of_other_workspaces_are_out_of_reach(app, data) -> None:
    owner = client_for(app, "alice@client-a.test")
    create(owner)
    bob = client_for(app, "bob@client-b.test")
    base = "/w/client-a-hr/suites/hr-payroll/scenarios/contract-data-is-complete"
    for path in (base, base + "/edit", base + "/delete", "/w/client-a-hr/scenarios/new"):
        assert bob.get(path).status_code == 404
    assert post(bob, base + "/delete").status_code == 404
    assert post(bob, base + "/edit", SCENARIO).status_code == 404
    assert post(bob, "/w/client-a-hr/scenarios/new", SCENARIO).status_code == 404
    assert (folder(app) / "suites" / "hr-payroll" / "contract-data-is-complete.yaml").exists()


def test_unknown_suites_and_scenarios_are_not_found(alice, data) -> None:
    create(alice)
    for path in (
        "/w/client-a-hr/suites/nope/scenarios/x/edit",
        "/w/client-a-hr/suites/hr-payroll/scenarios/suite/edit",
        "/w/client-a-hr/suites/hr-payroll/scenarios/..%2F..%2Fapp/edit",
    ):
        assert alice.get(path).status_code == 404
    response = post(alice, "/w/client-a-hr/suites/hr-payroll/run", {"scenario": "nope"})
    assert response.status_code == 404


def test_scenario_forms_need_the_csrf_token(alice, app, data) -> None:
    response = alice.post("/w/client-a-hr/scenarios/new", data={**SCENARIO, "csrf": "forged"})
    assert response.status_code == 400
    assert not (folder(app) / "suites" / "hr-payroll").exists()


def test_a_reused_name_does_not_inherit_old_baselines(alice, app, data) -> None:
    stale = folder(app) / ".testbench" / "baselines" / "hr-payroll" / "contract-data-is-complete"
    stale.mkdir(parents=True)
    (stale / "check.json").write_text("{}")
    create(alice)
    assert not stale.exists()
