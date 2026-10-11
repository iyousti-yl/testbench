"""Creating, editing and deleting scenario files from the web app.

Scenarios stay files in the workspace folder (``suites/<suite>/<id>.yaml``), so the engine,
the command line and the write-scenario skill keep working on the same files. Every save is
validated against the scenario schema before anything is written.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from testbench.connectors import ConnectorError, connector_class
from testbench.scenario import (
    SCENARIO_SUFFIXES,
    SUITE_FILE,
    Check,
    ScenarioError,
    list_suites,
    read_document,
    validate_scenario,
)
from testbench.web.store import Connection

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")  # suite folders and scenario file names
MAX_TEXT = 20_000


@dataclass
class ScenarioForm:
    """What the editor shows and posts. ``checks`` and ``select`` are text as typed."""

    title: str = ""
    requirement: str = ""
    description: str = ""
    tags: str = ""
    connection: str = ""
    select: str = ""
    checks: str = ""
    suite: str = ""
    new_suite: str = ""
    errors: list[str] = field(default_factory=list)

    @classmethod
    def from_post(cls, form: dict[str, str]) -> ScenarioForm:
        keys = ("title", "requirement", "description", "tags", "connection", "select", "checks")
        values = {k: form.get(k, "")[:MAX_TEXT] for k in keys}
        return cls(**values, suite=form.get("suite", ""), new_suite=form.get("new_suite", ""))

    @classmethod
    def from_document(
        cls, raw: dict[str, Any], suite: str, default_connection: str
    ) -> ScenarioForm:
        checks = raw.get("checks") or []
        return cls(
            title=raw.get("scenario", ""),
            requirement=str(raw.get("requirement", "")).strip(),
            description=str(raw.get("description", "")).strip(),
            tags=", ".join(raw.get("tags") or []),
            connection=raw.get("connection") or default_connection,
            select=str(raw.get("select") or "").strip(),
            checks=dump_yaml(checks) if checks else "",
            suite=suite,
        )


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].strip("-")
    return slug or "scenario"


class _BlockDumper(yaml.SafeDumper):
    """Multi-line strings (SQL) as ``|`` blocks, so files stay readable and diffable."""


def _str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    if "\n" in value:
        value = "\n".join(line.rstrip() for line in value.strip("\n").splitlines()) + "\n"
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", value)


_BlockDumper.add_representer(str, _str)


def dump_yaml(data: Any) -> str:
    return yaml.dump(data, Dumper=_BlockDumper, sort_keys=False, allow_unicode=True, width=100)


def _parse_checks(text: str) -> Any:
    try:
        checks = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark else ""
        problem = getattr(exc, "problem", None) or "not valid YAML"
        raise ScenarioError(f"checks{where}: {problem}") from exc
    if isinstance(checks, dict):
        checks = [checks]  # one check written without the leading "- "
    if not isinstance(checks, list) or not checks:
        raise ScenarioError("checks: write at least one check (a list item starting with '- ')")
    return checks


def build_document(form: ScenarioForm, connections: dict[str, Connection]) -> dict[str, Any]:
    """The scenario as it will be stored, or ScenarioError with every problem found."""
    problems: list[str] = []
    if not form.title.strip():
        problems.append("give the scenario a title")
    if not form.requirement.strip():
        problems.append("write the business requirement: it is shown next to every result")
    if form.connection not in connections:
        problems.append("choose one of this workspace's connections")
    checks: Any = []
    try:
        checks = _parse_checks(form.checks)
    except ScenarioError as exc:
        problems.append(str(exc))

    document: dict[str, Any] = {"version": 1, "scenario": form.title.strip()}
    document["requirement"] = form.requirement.strip()
    if form.description.strip():
        document["description"] = form.description.strip()
    tags = [t.strip() for t in form.tags.split(",") if t.strip()]
    if tags:
        document["tags"] = tags
    document["connection"] = form.connection
    if form.select.strip():
        document["select"] = form.select.strip()
    document["checks"] = checks
    if problems:
        raise ScenarioError("\n".join(problems))

    try:
        validate_scenario(document, "this scenario")
    except ScenarioError as exc:  # one line per problem, without the heading
        lines = str(exc).splitlines()[1:]
        raise ScenarioError("\n".join(line.strip().removeprefix("- ") for line in lines)) from exc
    slugs = [Check(c["name"], c["query"], c["expect"]).slug for c in checks]
    duplicates = sorted({s for s in slugs if slugs.count(s) > 1})
    if duplicates:
        problems.append(f"check names must be unique ({', '.join(duplicates)})")
    used = {form.connection, *(c["connection"] for c in checks if c.get("connection"))}
    used |= {
        c["expect"]["reconcile"]["connection"]
        for c in checks
        if isinstance(c["expect"].get("reconcile"), dict)
        and c["expect"]["reconcile"].get("connection")
    }
    for name in sorted(used - set(connections)):
        problems.append(f"connection '{name}' does not exist in this workspace")
    if document.get("select") and form.connection in connections:
        if "sql" not in _capabilities(connections[form.connection]):
            problems.append(
                "records to test (select) only works on SQL connections such as SAP Datasphere"
            )
    if problems:
        raise ScenarioError("\n".join(problems))
    return document


def _capabilities(connection: Connection) -> frozenset[str]:
    try:
        return frozenset(connector_class(connection.type).capabilities)
    except ConnectorError:
        return frozenset()


def _write(path: Path, document: dict[str, Any]) -> None:
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    if path.suffix != ".json":
        text = dump_yaml(document)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class ScenarioFiles:
    """Scenario files of one workspace. Callers hold the workspace lock while writing."""

    def __init__(self, root: Path) -> None:
        self.suites_dir = root / "suites"
        self.baselines_dir = root / ".testbench" / "baselines"

    def _suite_dir(self, suite: str) -> Path:
        if suite not in list_suites(self.suites_dir):
            raise ScenarioError(f"suite {suite} does not exist")
        return self.suites_dir / suite

    def _file(self, suite: str, scenario_id: str) -> Path:
        folder = self._suite_dir(suite)
        for path in folder.iterdir():
            if path.stem == scenario_id and path.suffix in SCENARIO_SUFFIXES:
                if path.name != SUITE_FILE:
                    return path
        raise ScenarioError(f"scenario {scenario_id} does not exist")

    def document(self, suite: str, scenario_id: str) -> tuple[dict[str, Any], str]:
        """The stored document and the suite's default connection."""
        raw = read_document(self._file(suite, scenario_id))
        defaults = {}
        suite_file = self._suite_dir(suite) / SUITE_FILE
        if suite_file.is_file():
            defaults = yaml.safe_load(suite_file.read_text(encoding="utf-8")) or {}
        return raw, str(defaults.get("connection", ""))

    def suite_for_new(self, form: ScenarioForm) -> str:
        """A typed new suite name wins over the suite chosen in the list."""
        name = form.new_suite.strip()
        if name:
            suite = slugify(name)
            if not NAME.match(suite):
                raise ScenarioError("suite name: use letters, digits and dashes")
            return suite
        if form.suite and form.suite != "__new__":
            self._suite_dir(form.suite)
            return form.suite
        raise ScenarioError("choose a test suite or name a new one")

    def create(self, form: ScenarioForm, document: dict[str, Any]) -> tuple[str, str]:
        suite = self.suite_for_new(form)
        folder = self.suites_dir / suite
        folder.mkdir(parents=True, exist_ok=True)
        base = slugify(document["scenario"])
        taken = {p.stem for p in folder.iterdir()} | {Path(SUITE_FILE).stem}
        scenario_id = next(
            candidate
            for candidate in [base, *(f"{base}-{n}" for n in range(2, 1000))]
            if candidate not in taken
        )
        # A scenario id that was deleted earlier must not inherit its old baselines.
        shutil.rmtree(self.baselines_dir / suite / scenario_id, ignore_errors=True)
        _write(folder / f"{scenario_id}.yaml", document)
        return suite, scenario_id

    def update(self, suite: str, scenario_id: str, document: dict[str, Any]) -> None:
        _write(self._file(suite, scenario_id), document)

    def delete(self, suite: str, scenario_id: str) -> bool:
        """Remove the scenario and its baselines; an emptied suite is removed too.
        Returns True when the suite was removed."""
        path = self._file(suite, scenario_id)
        path.unlink()
        shutil.rmtree(self.baselines_dir / suite / scenario_id, ignore_errors=True)
        folder = path.parent
        left = [
            p for p in folder.iterdir() if p.suffix in SCENARIO_SUFFIXES and p.name != SUITE_FILE
        ]
        if not left:
            shutil.rmtree(folder)
            shutil.rmtree(self.baselines_dir / suite, ignore_errors=True)
            return True
        return False
