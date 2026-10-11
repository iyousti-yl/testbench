"""Connector registry: connectors are found through the ``testbench.connectors`` entry point."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from testbench.connectors.base import Connector, ConnectorError

# Built-ins stay available even when the package is not installed (for example in a checkout).
_BUILTIN = {
    "sqlite": "testbench.connectors.sqlite:SQLiteConnector",
}


def _load(target: str) -> type:
    module_name, _, attr = target.partition(":")
    module = __import__(module_name, fromlist=[attr])
    return getattr(module, attr)


def available_connectors() -> dict[str, str]:
    found = dict(_BUILTIN)
    for ep in entry_points(group="testbench.connectors"):
        found[ep.name] = ep.value
    return found


def create_connector(type_name: str, settings: dict[str, Any]) -> Connector:
    targets = available_connectors()
    if type_name not in targets:
        known = ", ".join(sorted(targets))
        raise ConnectorError(f"unknown connector type '{type_name}' (available: {known})")
    try:
        cls = _load(targets[type_name])
    except ImportError as exc:
        raise ConnectorError(
            f"connector '{type_name}' needs an extra package: {exc}. "
            f"Try: pip install 'testbench[{type_name}]'"
        ) from exc
    return cls(**settings)


__all__ = ["Connector", "ConnectorError", "available_connectors", "create_connector"]
