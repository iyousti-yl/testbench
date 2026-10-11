"""Connector registry: connectors are found through the ``testbench.connectors`` entry point."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from testbench.connectors.base import Connector, ConnectorError, SettingField

# Built-ins stay available even when the package is not installed (for example in a checkout).
_BUILTIN = {
    "sqlite": "testbench.connectors.sqlite:SQLiteConnector",
    "datasphere": "testbench.connectors.datasphere:DatasphereConnector",
    "successfactors": "testbench.connectors.successfactors:SuccessFactorsConnector",
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


def connector_class(type_name: str) -> type:
    targets = available_connectors()
    if type_name not in targets:
        known = ", ".join(sorted(targets))
        raise ConnectorError(f"unknown connector type '{type_name}' (available: {known})")
    try:
        return _load(targets[type_name])
    except ImportError as exc:
        raise ConnectorError(
            f"connector '{type_name}' needs an extra package: {exc}. "
            f"Try: pip install 'testbench[{type_name}]'"
        ) from exc


def create_connector(type_name: str, settings: dict[str, Any]) -> Connector:
    return connector_class(type_name)(**settings)


def form_connectors() -> dict[str, type]:
    """Connector types a person can add in the web app: those that describe their settings.

    Connectors without ``settings_fields`` (such as the SQLite connector used in tests) are
    never offered, so nobody can point the server at a local file.
    """
    offered = {}
    for type_name in available_connectors():
        try:
            cls = connector_class(type_name)
        except ConnectorError:
            continue
        if getattr(cls, "settings_fields", None) and getattr(cls, "title", None):
            offered[type_name] = cls
    return offered


__all__ = [
    "Connector",
    "ConnectorError",
    "SettingField",
    "available_connectors",
    "connector_class",
    "create_connector",
    "form_connectors",
]
