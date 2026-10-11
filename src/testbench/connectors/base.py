"""The connector contract. Every system Testbench talks to implements this protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from testbench.table import Table


class ConnectorError(Exception):
    """Raised when a connector cannot connect or a query fails."""


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


@dataclass
class ObjectSchema:
    ref: ObjectRef
    columns: list[ColumnInfo] = field(default_factory=list)


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
