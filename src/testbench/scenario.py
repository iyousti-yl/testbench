"""Loading suites and scenarios (JSON or YAML) and validating them against the scenario schema."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

SUITE_FILE = "suite.yaml"
SCENARIO_SUFFIXES = (".json", ".yaml", ".yml")


class ScenarioError(Exception):
    pass


@dataclass
class Check:
    name: str
    query: str
    expect: dict[str, Any]
    connection: str | None = None

    @property
    def slug(self) -> str:
        return slugify(self.name)


@dataclass
class Scenario:
    id: str
    name: str
    path: Path
    connection: str
    checks: list[Check]
    requirement: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    select: str | None = None


@dataclass
class Suite:
    name: str
    path: Path
    scenarios: list[Scenario]
    description: str = ""


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "check"


@cache
def scenario_schema() -> dict[str, Any]:
    text = files("testbench").joinpath("schema/scenario.schema.json").read_text(encoding="utf-8")
    return json.loads(text)


def validate_scenario(raw: Any, where: str) -> None:
    """Raise ScenarioError listing every place the document breaks the scenario schema."""
    validator = Draft202012Validator(scenario_schema())
    errors = sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path))
    if errors:
        lines = []
        for error in errors:
            location = "/".join(str(p) for p in error.absolute_path) or "(top level)"
            lines.append(f"  - {location}: {error.message}")
        raise ScenarioError(f"{where} does not match the scenario format:\n" + "\n".join(lines))


def read_document(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    try:
        # JSON is a subset of YAML, but json gives clearer errors for .json files.
        return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ScenarioError(f"{path.name}: cannot parse file: {exc}") from exc


def load_scenario(path: Path, defaults: dict[str, Any] | None = None) -> Scenario:
    defaults = defaults or {}
    raw = read_document(path)
    validate_scenario(raw, path.name)

    connection = raw.get("connection") or defaults.get("connection")
    if not connection:
        raise ScenarioError(f"{path.name}: 'connection' is required (here or in {SUITE_FILE})")

    checks = [
        Check(name=c["name"], query=c["query"], expect=c["expect"], connection=c.get("connection"))
        for c in raw["checks"]
    ]
    slugs = [c.slug for c in checks]
    duplicates = sorted({s for s in slugs if slugs.count(s) > 1})
    if duplicates:
        raise ScenarioError(f"{path.name}: check names must be unique ({', '.join(duplicates)})")

    return Scenario(
        id=path.stem,
        name=raw["scenario"],
        path=path,
        connection=str(connection),
        checks=checks,
        requirement=raw.get("requirement", "").strip(),
        description=raw.get("description", "").strip(),
        tags=[*defaults.get("tags", []), *raw.get("tags", [])],
        select=raw.get("select"),
    )


def load_suite(path: Path) -> Suite:
    if not path.is_dir():
        raise ScenarioError(f"suite folder not found: {path}")
    defaults: dict[str, Any] = {}
    suite_file = path / SUITE_FILE
    if suite_file.is_file():
        defaults = yaml.safe_load(suite_file.read_text(encoding="utf-8")) or {}
    scenario_files = sorted(
        p for p in path.iterdir() if p.suffix in SCENARIO_SUFFIXES and p.name != SUITE_FILE
    )
    scenarios = [load_scenario(p, defaults) for p in scenario_files]
    ids = [s.id for s in scenarios]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ScenarioError(f"{path.name}: two files share a name ({', '.join(duplicates)})")
    return Suite(
        name=path.name,
        path=path,
        scenarios=scenarios,
        description=str(defaults.get("description", "")).strip(),
    )


def list_suites(suites_dir: Path) -> list[str]:
    if not suites_dir.is_dir():
        return []
    return sorted(p.name for p in suites_dir.iterdir() if p.is_dir())
