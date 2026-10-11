"""Workspace content: connections from the app database, suites and runs from the workspace
folder. Always reached through a membership."""

from __future__ import annotations

import json
import re
import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from testbench.config import ConnectionConfig, ProjectConfig
from testbench.report import write_report
from testbench.runner import Runner, RunResult, save_run
from testbench.scenario import Scenario, Suite, list_suites, load_suite
from testbench.web.store import Store, Workspace

RUN_ID = re.compile(r"^[0-9TZ]+-[a-z0-9-]+-(run|baseline)$")
_locks: defaultdict[int, threading.Lock] = defaultdict(threading.Lock)


def workspace_lock(workspace: Workspace) -> threading.Lock:
    """One run, or a delete, at a time per workspace."""
    return _locks[workspace.id]


class NotFound(Exception):
    pass


@dataclass
class RunSummary:
    id: str
    suite: str
    mode: str
    status: str
    started_at: str
    counts: dict[str, int]


class WorkspaceFiles:
    def __init__(self, store: Store, workspace: Workspace) -> None:
        self.store = store
        self.workspace = workspace
        self.root = store.workspace_dir(workspace)

    def config(self) -> ProjectConfig:
        connections = {
            c.name: ConnectionConfig(
                name=c.name,
                type=c.type,
                sensitive=c.sensitive,
                settings=c.settings,
                env_vars=False,  # typed in the app: never read the server's environment
            )
            for c in self.store.connections(self.workspace)
        }
        return ProjectConfig(
            root=self.root,
            project=self.workspace.name,
            connections=connections,
            suites_dir=self.root / "suites",
            output_dir=self.root / ".testbench",
        )

    def suites(self) -> list[Suite]:
        config = self.config()
        return [load_suite(config.suites_dir / name) for name in list_suites(config.suites_dir)]

    def suite(self, name: str) -> Suite:
        config = self.config()
        if name not in list_suites(config.suites_dir):
            raise NotFound(f"suite {name}")
        return load_suite(config.suites_dir / name)

    def scenario(self, suite_name: str, scenario_id: str) -> tuple[Scenario, str]:
        for scenario in self.suite(suite_name).scenarios:
            if scenario.id == scenario_id:
                return scenario, scenario.path.read_text(encoding="utf-8")
        raise NotFound(f"scenario {scenario_id}")

    def run(self, suite_name: str, mode: str) -> RunResult:
        self.suite(suite_name)  # 404 for unknown suites before anything runs
        config = self.config()
        with workspace_lock(self.workspace):
            runner = Runner(config, secrets=self.store.secrets_for(self.workspace))
            result = runner.run_suite(suite_name, mode=mode)
            run_dir = save_run(result, config.output_dir)
            write_report(result, run_dir)
        return result

    def run_dir(self, run_id: str) -> Path:
        if not RUN_ID.match(run_id):
            raise NotFound(run_id)
        runs = (self.config().output_dir / "runs").resolve()
        path = (runs / run_id).resolve()
        if path.parent != runs or not (path / "results.json").is_file():
            raise NotFound(run_id)
        return path

    def run_result(self, run_id: str) -> dict[str, Any]:
        return json.loads((self.run_dir(run_id) / "results.json").read_text(encoding="utf-8"))

    def report_html(self, run_id: str) -> str:
        return (self.run_dir(run_id) / "report.html").read_text(encoding="utf-8")

    def runs(self, limit: int = 20) -> list[RunSummary]:
        runs_dir = self.config().output_dir / "runs"
        if not runs_dir.is_dir():
            return []
        summaries = []
        for path in sorted(runs_dir.iterdir(), reverse=True)[:limit]:
            results = path / "results.json"
            if not RUN_ID.match(path.name) or not results.is_file():
                continue
            data = json.loads(results.read_text(encoding="utf-8"))
            summaries.append(
                RunSummary(
                    id=path.name,
                    suite=data["suite"],
                    mode=data["mode"],
                    status=data["status"],
                    started_at=data["started_at"],
                    counts=data["counts"],
                )
            )
        return summaries
