"""The connector contract. Every system Testbench talks to implements this protocol."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from testbench.table import Table


class ConnectorError(Exception):
    """Raised when a connector cannot connect or a query fails."""


_COMMENTS = re.compile(r"(--[^\n]*)|(/\*.*?\*/)", re.DOTALL)
_READ_START = ("select", "with", "(")


def ensure_read_only(sql: str) -> None:
    """Refuse anything but a single SELECT. Connectors must never change client data.

    This is a guard against mistakes, not a security boundary: the database user itself
    must only have read privileges.
    """
    statement = _COMMENTS.sub(" ", sql).strip().rstrip(";").strip()
    if not statement.lower().startswith(_READ_START):
        raise ConnectorError("only SELECT queries are allowed")
    if ";" in statement:
        raise ConnectorError("only one statement per query is allowed")


@dataclass(frozen=True)
class ObjectRef:
    name: str
    kind: str = "view"  # "table", "view", ...
    schema: str | None = None

    @property
    def qualified_name(self) -> str:
        return f'"{self.schema}"."{self.name}"' if self.schema else f'"{self.name}"'


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type: str
    nullable: bool = True
    key: bool = False
    label: str = ""  # business name, when the system has one


@dataclass
class ObjectSchema:
    ref: ObjectRef
    columns: list[ColumnInfo] = field(default_factory=list)


@dataclass(frozen=True)
class SettingField:
    """One setting a person fills in to add a connection in the web app.

    A connector is offered in the web app only when it declares ``title`` and
    ``settings_fields``. It may also declare ``check_settings(settings) -> settings`` to
    validate and normalise what was typed, raising ``ConnectorError`` with a readable message.
    """

    key: str
    label: str
    help: str = ""
    placeholder: str = ""
    kind: str = "text"  # text, url, password, textarea, choice
    choices: tuple[tuple[str, str], ...] = ()  # (value, label) for kind "choice"
    default: str = ""
    required: bool = True
    secret: bool = False  # stored encrypted, never shown again
    summary: bool = False  # shown on the connection card, for example tenant and space
    group: str = ""  # fields with the same group are shown together


@runtime_checkable
class Connector(Protocol):
    """A plug-in that talks to one kind of system.

    Implementations are constructed with the connection's settings from ``testbench.yaml``
    (everything except ``type`` and ``sensitive``) as keyword arguments, plus ``base_dir``,
    the project folder. They should accept and ignore settings they do not use.
    """

    name: str
    capabilities: frozenset[str]

    def test_connection(self) -> None: ...

    def list_objects(self, scope: str | None = None) -> list[ObjectRef]: ...

    def describe(self, obj: ObjectRef) -> ObjectSchema: ...

    def query(self, sql: str, params: dict[str, Any] | None = None) -> Table: ...

    def close(self) -> None: ...
