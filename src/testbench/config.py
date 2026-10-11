"""Project configuration: ``testbench.yaml`` with connections and where suites live."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_FILE = "testbench.yaml"
_ENV_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ConfigError(Exception):
    pass


@dataclass
class ConnectionConfig:
    name: str
    type: str
    sensitive: bool = False
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProjectConfig:
    root: Path
    project: str
    connections: dict[str, ConnectionConfig]
    suites_dir: Path
    output_dir: Path

    def connection(self, name: str) -> ConnectionConfig:
        if name not in self.connections:
            known = ", ".join(sorted(self.connections)) or "none"
            raise ConfigError(f"unknown connection '{name}' (configured: {known})")
        return self.connections[name]


def expand_env(value: Any) -> Any:
    """Replace ``${VAR}`` and ``${VAR:-default}`` in strings, recursively."""
    if isinstance(value, str):

        def substitute(match: re.Match[str]) -> str:
            var, default = match.group(1), match.group(2)
            if var in os.environ:
                return os.environ[var]
            if default is not None:
                return default
            raise ConfigError(f"environment variable {var} is not set")

        return _ENV_VAR.sub(substitute, value)
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    return value


def find_project_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / CONFIG_FILE).is_file():
            return candidate
    raise ConfigError(f"no {CONFIG_FILE} found in {start} or its parents (run 'testbench init')")


def load_config(start: Path | None = None) -> ProjectConfig:
    root = find_project_root((start or Path.cwd()).resolve())
    raw = yaml.safe_load((root / CONFIG_FILE).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{CONFIG_FILE} must be a mapping")

    connections: dict[str, ConnectionConfig] = {}
    for name, body in (raw.get("connections") or {}).items():
        if not isinstance(body, dict) or "type" not in body:
            raise ConfigError(f"connection '{name}' needs a 'type'")
        # Environment variables are expanded lazily, when the connection is opened,
        # so a missing secret for one connection does not break the others.
        settings = {k: v for k, v in body.items() if k not in ("type", "sensitive")}
        connections[name] = ConnectionConfig(
            name=name,
            type=str(body["type"]),
            sensitive=bool(body.get("sensitive", False)),
            settings=settings,
        )

    return ProjectConfig(
        root=root,
        project=str(raw.get("project", root.name)),
        connections=connections,
        suites_dir=root / raw.get("suites_dir", "suites"),
        output_dir=root / raw.get("output_dir", ".testbench"),
    )
