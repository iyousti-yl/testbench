"""Connection forms in the web app, built from what each connector declares about itself.

Nothing here knows about a specific system: a connector is offered when it declares
``title`` and ``settings_fields`` (see ``SettingField``).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from testbench.connectors import ConnectorError, create_connector, form_connectors
from testbench.connectors.base import SettingField
from testbench.web.store import Connection

FIELD_PREFIX = "s_"  # form inputs are named s_<setting> so they never clash with ours


def offered_types() -> dict[str, type]:
    return form_connectors()


@dataclass
class ConnectionView:
    connection: Connection
    title: str
    summary: list[tuple[SettingField, str]]


def view(connection: Connection) -> ConnectionView:
    cls = offered_types().get(connection.type)
    fields = getattr(cls, "settings_fields", ()) if cls else ()
    summary = [
        (f, str(connection.settings[f.key]))
        for f in fields
        if f.summary and connection.settings.get(f.key)
    ]
    return ConnectionView(connection, getattr(cls, "title", connection.type), summary)


def groups(cls: type) -> list[tuple[str, list[SettingField]]]:
    """Fields in display order: ungrouped first, then each group once."""
    result: list[tuple[str, list[SettingField]]] = []
    for f in cls.settings_fields:
        if result and result[-1][0] == f.group:
            result[-1][1].append(f)
        else:
            result.append((f.group, [f]))
    return result


def read_form(
    cls: type, form: dict[str, str], stored_secrets: dict[str, str]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validated (settings, secrets) from a submitted form.

    A secret left empty keeps the stored value, so passwords are never sent back to the
    browser. Raises ``ConnectorError`` with a message for the person filling in the form.
    """
    raw: dict[str, str] = {}
    for f in cls.settings_fields:
        value = form.get(FIELD_PREFIX + f.key, "")
        if f.secret and not value:
            value = stored_secrets.get(f.key, "")
        if f.kind == "choice" and value not in {v for v, _ in f.choices}:
            value = f.default
        if f.required and not value.strip():
            raise ConnectorError(f"{f.label} is required")
        raw[f.key] = value
    check = getattr(cls, "check_settings", None)
    if check is not None:
        raw = check(raw)
    known = {f.key: f for f in cls.settings_fields}
    settings = {k: v for k, v in raw.items() if k in known and not known[k].secret}
    secrets = {k: v for k, v in raw.items() if k in known and known[k].secret and v}
    return settings, secrets


def _plural(kind: str, count: int) -> str:
    if count == 1:
        return kind
    return kind[:-1] + "ies" if kind.endswith("y") else kind + "s"


def _overview(connector: Any) -> str:
    if "metadata" not in connector.capabilities:
        return "Connected."
    try:
        kinds = Counter(obj.kind for obj in connector.list_objects())
    except Exception as exc:  # connected; only the overview failed
        return f"Connected, but listing objects failed: {exc}"
    if not kinds:
        return "Connected, but this user cannot see any objects yet."
    found = ", ".join(f"{n} {_plural(kind, n)}" for kind, n in sorted(kinds.items()))
    return f"Connected. Readable: {found}."


def check_connection(connection: Connection, secrets: dict[str, str]) -> tuple[bool, str]:
    """Connect, and list what the user can read. Never raises: the result is shown."""
    connector = None
    try:
        connector = create_connector(connection.type, {**connection.settings, **secrets})
        connector.test_connection()
        return True, _overview(connector)
    except ConnectorError as exc:
        return False, str(exc)
    except Exception as exc:  # a driver problem must not break the page
        return False, f"Unexpected error from the connector: {exc.__class__.__name__}: {exc}"
    finally:
        if connector is not None:
            try:
                connector.close()
            except Exception:  # noqa: BLE001 - closing is best effort
                pass
