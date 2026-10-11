"""A small in-memory table, so the core does not depend on any database library."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Table:
    columns: list[str]
    rows: list[tuple[Any, ...]] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Column names are compared case-insensitively: HANA returns upper case,
        # SQLite returns whatever the query used.
        self.columns = [str(c) for c in self.columns]
        self.rows = [tuple(r) for r in self.rows]

    def __len__(self) -> int:
        return len(self.rows)

    def index_of(self, column: str) -> int:
        wanted = column.lower()
        for i, name in enumerate(self.columns):
            if name.lower() == wanted:
                return i
        raise KeyError(f"column '{column}' not found; available: {', '.join(self.columns)}")

    def records(self) -> Iterator[dict[str, Any]]:
        for row in self.rows:
            yield dict(zip(self.columns, row, strict=True))

    def column(self, name: str) -> list[Any]:
        i = self.index_of(name)
        return [row[i] for row in self.rows]

    @classmethod
    def from_records(cls, records: Sequence[dict[str, Any]]) -> Table:
        if not records:
            return cls(columns=[], rows=[])
        columns = list(records[0].keys())
        return cls(columns=columns, rows=[tuple(r.get(c) for c in columns) for r in records])
