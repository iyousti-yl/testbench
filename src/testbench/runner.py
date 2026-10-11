"""Running a suite: selection, checks, baselines and results."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from testbench.baseline import BaselineStore
from testbench.checks import (
    ERROR,
    FAILED,
    PASSED,
    SKIPPED,
    Outcome,
    check_all_rows,
    check_equals,
    check_reconcile,
    check_regression,
    check_row_count,
)
from testbench.compare import CompareError, snapshot
from testbench.config import ConfigError, ProjectConfig, expand_env
from testbench.connectors import Connector, ConnectorError, create_connector
from testbench.connectors.base import ensure_read_only
from testbench.expressions import ExpressionError
from testbench.scenario import Check, Scenario, Suite, load_suite
from testbench.table import Table

_SELECTION = re.compile(r"\{\{\s*selection\s*\}\}")
_RECOVERABLE = (ConnectorError, CompareError, ExpressionError, ConfigError, OSError, ValueError)


@dataclass
class CheckResult:
    name: str
    status: str
    outcomes: list[Outcome] = field(default_factory=list)
    rows: int | None = None
    error: str | None = None


@dataclass
class ScenarioResult:
    id: str
    name: str
    status: str
    requirement: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    message: str = ""
    selected_rows: int | None = None
    checks: list[CheckResult] = field(default_factory=list)


@dataclass
class RunResult:
    project: str
    suite: str
    mode: str  # "run" or "baseline"
    started_at: str
    finished_at: str = ""
    scenarios: list[ScenarioResult] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        counts = {PASSED: 0, FAILED: 0, ERROR: 0, SKIPPED: 0}
        for s in self.scenarios:
            counts[s.status] += 1
        return counts

    @property
    def status(self) -> str:
        return worst(s.status for s in self.scenarios) if self.scenarios else SKIPPED

    def to_json(self) -> dict[str, Any]:
        return {**asdict(self), "status": self.status, "counts": self.counts()}


def worst(statuses: Any) -> str:
    statuses = list(statuses)
    for status in (ERROR, FAILED, PASSED):
        if status in statuses:
            return status
    return SKIPPED


def render_query(sql: str, selection: str | None) -> str:
    if _SELECTION.search(sql):
        if selection is None:
            raise ConfigError("query uses {{ selection }} but the scenario has no 'select'")
        return _SELECTION.sub(lambda _: selection.strip().rstrip(";"), sql)
    return sql


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Runner:
    def __init__(
        self, config: ProjectConfig, secrets: dict[str, dict[str, str]] | None = None
    ) -> None:
        """``secrets`` maps connection name to settings (such as a password) kept outside
        ``testbench.yaml``; the web app passes the decrypted values here."""
        self.config = config
        self.secrets = secrets or {}
        self.baselines = BaselineStore(config.output_dir)
        self._connections: dict[str, Connector] = {}

    def connection(self, name: str) -> Connector:
        if name not in self._connections:
            cfg = self.config.connection(name)
            settings = {**expand_env(cfg.settings), **self.secrets.get(name, {})}
            self._connections[name] = create_connector(
                cfg.type, {**settings, "base_dir": self.config.root}
            )
        return self._connections[name]

    def query(self, connection: str, sql: str) -> Table:
        ensure_read_only(sql)
        return self.connection(connection).query(sql)

    def close(self) -> None:
        for conn in self._connections.values():
            conn.close()
        self._connections.clear()

    def run_suite(
        self,
        suite_name: str,
        mode: str = "run",
        tags: list[str] | None = None,
        scenarios: list[str] | None = None,
    ) -> RunResult:
        suite = load_suite(self.config.suites_dir / suite_name)
        result = RunResult(
            project=self.config.project, suite=suite.name, mode=mode, started_at=_now()
        )
        try:
            for scenario in suite.scenarios:
                if tags and not set(tags) & set(scenario.tags):
                    continue
                if scenarios and scenario.id not in scenarios:
                    continue
                result.scenarios.append(self.run_scenario(suite, scenario, mode))
        finally:
            self.close()
        result.finished_at = _now()
        return result

    def run_scenario(self, suite: Suite, scenario: Scenario, mode: str) -> ScenarioResult:
        result = ScenarioResult(
            id=scenario.id,
            name=scenario.name,
            status=PASSED,
            requirement=scenario.requirement,
            description=scenario.description,
            tags=scenario.tags,
        )
        checks = scenario.checks
        if mode == "baseline":
            checks = [c for c in checks if "regression" in c.expect]
            if not checks:
                result.status, result.message = SKIPPED, "no regression checks"
                return result

        if scenario.select:
            try:
                selected = self.query(scenario.connection, scenario.select)
            except _RECOVERABLE as exc:
                result.status, result.message = ERROR, f"selection failed: {exc}"
                return result
            result.selected_rows = len(selected)
            if not selected.rows:
                result.status = SKIPPED
                result.message = "no records match this scenario, so it was not tested"
                return result

        for check in checks:
            result.checks.append(self.run_check(suite, scenario, check, mode))
        result.status = worst(c.status for c in result.checks)
        return result

    def run_check(self, suite: Suite, scenario: Scenario, check: Check, mode: str) -> CheckResult:
        result = CheckResult(name=check.name, status=PASSED)
        connection_name = check.connection or scenario.connection
        try:
            sql = render_query(check.query, scenario.select)
            table = self.query(connection_name, sql)
            result.rows = len(table)

            if mode == "baseline":
                spec = check.expect["regression"]
                keys = spec.get("keys") if isinstance(spec, dict) else None
                sensitive = self.config.connection(connection_name).sensitive
                snap = snapshot(table, keys, mode="hash" if sensitive else "full")
                self.baselines.save(suite.name, scenario.id, check.slug, snap)
                kind = "hashed" if sensitive else "full"
                result.outcomes.append(
                    Outcome("regression", PASSED, f"baseline saved: {len(table)} rows ({kind})")
                )
                return result

            for expectation, spec in check.expect.items():
                result.outcomes.append(
                    self._evaluate(expectation, spec, table, suite, scenario, check)
                )
        except _RECOVERABLE as exc:
            result.status, result.error = ERROR, str(exc)
            return result

        result.status = worst(o.status for o in result.outcomes)
        return result

    def _evaluate(
        self,
        expectation: str,
        spec: Any,
        table: Any,
        suite: Suite,
        scenario: Scenario,
        check: Check,
    ) -> Outcome:
        try:
            if expectation == "row_count":
                return check_row_count(spec, table)
            if expectation == "all_rows":
                return check_all_rows(spec, table)
            if expectation == "equals":
                return check_equals(spec, table, scenario.path.parent)
            if expectation == "regression":
                baseline = self.baselines.load(suite.name, scenario.id, check.slug)
                return check_regression(baseline, table, spec)
            if expectation == "reconcile":
                other_conn = spec.get("connection") or check.connection or scenario.connection
                other_sql = render_query(spec["query"], scenario.select)
                other = self.query(other_conn, other_sql)
                return check_reconcile(spec, table, other)
        except _RECOVERABLE as exc:
            return Outcome(expectation, ERROR, str(exc))
        return Outcome(expectation, ERROR, f"unknown expectation '{expectation}'")


def save_run(result: RunResult, output_dir: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = output_dir / "runs" / f"{stamp}-{result.suite}-{result.mode}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "results.json").write_text(
        json.dumps(result.to_json(), indent=1, default=str), encoding="utf-8"
    )
    return run_dir
