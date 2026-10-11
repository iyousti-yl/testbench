"""Comparing tables: used by ``equals``, ``regression`` and ``reconcile`` checks.

Two representations are compared:

* **full**: every row's values are kept, so differences can be shown value by value;
* **hash**: only a hash per row (and totals per numeric column) is kept, so a baseline can be
  stored without keeping personal data. Differences are reported per row, without old values.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from testbench.table import Table

HASH_DIGITS = 6
MAX_EXAMPLES = 20


class CompareError(Exception):
    pass


def normalize(value: Any) -> Any:
    """Bring values from any driver (or from a JSON baseline) into one comparable form."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, bytes | bytearray | memoryview):
        return base64.b16encode(bytes(value)).decode()
    if isinstance(value, str):
        return value.rstrip()  # fixed-length CHAR columns pad with spaces
    return value


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _values_match(expected: Any, actual: Any, tolerance: float) -> bool:
    if _is_number(expected) and _is_number(actual):
        return abs(expected - actual) <= tolerance + 1e-12
    return expected == actual


def _digest(values: tuple[Any, ...]) -> str:
    def hashable(v: Any) -> Any:
        return round(v, HASH_DIGITS) if isinstance(v, float) else v

    payload = json.dumps([hashable(v) for v in values], default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


@dataclass
class Snapshot:
    """A comparable form of a table: full rows or hashes, keyed or as a multiset."""

    mode: str  # "full" or "hash"
    columns: list[str]
    keys: list[str] = field(default_factory=list)
    rows: dict[str, list[Any]] = field(default_factory=dict)  # full + keys: key-json -> values
    counts: dict[str, int] = field(default_factory=dict)  # no keys: row-id -> occurrences
    examples: dict[str, list[Any]] = field(default_factory=dict)  # full, no keys: row-id -> row
    hashes: dict[str, str] = field(default_factory=dict)  # hash + keys: key-hash -> value-hash
    totals: dict[str, float] = field(default_factory=dict)  # hash: numeric column totals
    row_count: int = 0

    def to_json(self) -> dict[str, Any]:
        data = {"mode": self.mode, "columns": self.columns, "keys": self.keys}
        data["row_count"] = self.row_count
        for name in ("rows", "counts", "examples", "hashes", "totals"):
            if getattr(self, name):
                data[name] = getattr(self, name)
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Snapshot:
        return cls(
            mode=data["mode"],
            columns=data["columns"],
            keys=data.get("keys", []),
            rows=data.get("rows", {}),
            counts=data.get("counts", {}),
            examples=data.get("examples", {}),
            hashes=data.get("hashes", {}),
            totals=data.get("totals", {}),
            row_count=data.get("row_count", 0),
        )


def snapshot(table: Table, keys: list[str] | None = None, mode: str = "full") -> Snapshot:
    keys = keys or []
    key_idx = [table.index_of(k) for k in keys]
    value_idx = [i for i in range(len(table.columns)) if i not in key_idx]
    columns = [table.columns[i].lower() for i in range(len(table.columns))]
    snap = Snapshot(mode=mode, columns=columns, keys=[k.lower() for k in keys])
    snap.row_count = len(table)

    for raw in table.rows:
        row = [normalize(v) for v in raw]
        if keys:
            key_values = tuple(row[i] for i in key_idx)
            values = [row[i] for i in value_idx]
            key_id = _digest(key_values) if mode == "hash" else json.dumps(key_values, default=str)
            store = snap.hashes if mode == "hash" else snap.rows
            if key_id in store:
                duplicate = dict(zip(keys, key_values, strict=True))
                raise CompareError(
                    f"key {', '.join(keys)} is not unique: {duplicate} appears more than once"
                )
            store[key_id] = _digest(tuple(values)) if mode == "hash" else values
        else:
            row_id = _digest(tuple(row))
            snap.counts[row_id] = snap.counts.get(row_id, 0) + 1
            if mode == "full":
                snap.examples.setdefault(row_id, row)

    if mode == "hash":
        for i, name in enumerate(columns):
            numbers = [normalize(r[i]) for r in table.rows]
            numbers = [n for n in numbers if _is_number(n)]
            if numbers and len(numbers) == sum(1 for r in table.rows if r[i] is not None):
                snap.totals[name] = round(sum(numbers), HASH_DIGITS)
    return snap


@dataclass
class Diff:
    expected_rows: int
    actual_rows: int
    missing_columns: list[str] = field(default_factory=list)
    extra_columns: list[str] = field(default_factory=list)
    added: list[dict[str, Any]] = field(default_factory=list)  # in actual, not expected
    removed: list[dict[str, Any]] = field(default_factory=list)  # in expected, not actual
    changed: list[dict[str, Any]] = field(default_factory=list)
    added_count: int = 0
    removed_count: int = 0
    changed_count: int = 0
    totals: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (
            self.missing_columns
            or self.extra_columns
            or self.added_count
            or self.removed_count
            or self.changed_count
            or self.totals
        )

    def summary(self) -> str:
        if self.ok:
            return f"{self.actual_rows} rows match"
        parts = []
        if self.missing_columns:
            parts.append(f"missing columns: {', '.join(self.missing_columns)}")
        if self.extra_columns:
            parts.append(f"new columns: {', '.join(self.extra_columns)}")
        if self.added_count:
            parts.append(f"{self.added_count} unexpected rows")
        if self.removed_count:
            parts.append(f"{self.removed_count} missing rows")
        if self.changed_count:
            parts.append(f"{self.changed_count} changed rows")
        if self.totals:
            parts.append(f"{len(self.totals)} column totals differ")
        return "; ".join(parts) + f" (expected {self.expected_rows} rows, got {self.actual_rows})"

    def to_json(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in ([], 0) or k.endswith("_rows")}


def diff(
    expected: Snapshot, actual: Table, tolerance: float = 0.0, actual_mode: str | None = None
) -> Diff:
    """Compare a stored or computed snapshot with a freshly queried table."""
    keys = expected.keys
    result = Diff(expected_rows=expected.row_count, actual_rows=len(actual))
    actual_columns = [c.lower() for c in actual.columns]
    result.missing_columns = [c for c in expected.columns if c not in actual_columns]
    result.extra_columns = [c for c in actual_columns if c not in expected.columns]
    if result.missing_columns or result.extra_columns:
        return result
    if any(k not in actual_columns for k in keys):
        raise CompareError(f"key columns {keys} not found in result")

    # Align the actual table's column order with the expected snapshot.
    order = [actual_columns.index(c) for c in expected.columns]
    aligned = Table(
        columns=expected.columns, rows=[tuple(r[i] for i in order) for r in actual.rows]
    )
    current = snapshot(aligned, keys, mode=actual_mode or expected.mode)
    value_columns = [c for c in expected.columns if c not in keys]

    def record(key_id: str, values: list[Any] | None) -> dict[str, Any]:
        key_values = json.loads(key_id) if expected.mode == "full" else []
        rec = dict(zip(keys, key_values, strict=True))
        if values is not None:
            rec.update(zip(value_columns, values, strict=True))
        return rec

    if keys and expected.mode == "full":
        for key_id, values in current.rows.items():
            if key_id not in expected.rows:
                result.added_count += 1
                if len(result.added) < MAX_EXAMPLES:
                    result.added.append(record(key_id, values))
                continue
            old = expected.rows[key_id]
            deltas = [
                {"column": col, "expected": o, "actual": n}
                for col, o, n in zip(value_columns, old, values, strict=True)
                if not _values_match(o, n, tolerance)
            ]
            if deltas:
                result.changed_count += 1
                if len(result.changed) < MAX_EXAMPLES:
                    result.changed.append({"key": record(key_id, None), "differences": deltas})
        for key_id, values in expected.rows.items():
            if key_id not in current.rows:
                result.removed_count += 1
                if len(result.removed) < MAX_EXAMPLES:
                    result.removed.append(record(key_id, values))
    elif keys:  # hash mode: identify rows by key hash, show current values only
        current_rows = {}
        for raw in aligned.rows:
            row = [normalize(v) for v in raw]
            key_hash = _digest(tuple(row[expected.columns.index(k)] for k in keys))
            current_rows[key_hash] = dict(zip(expected.columns, row, strict=True))
        for key_hash, value_hash in current.hashes.items():
            if key_hash not in expected.hashes:
                result.added_count += 1
                if len(result.added) < MAX_EXAMPLES:
                    result.added.append(current_rows[key_hash])
            elif expected.hashes[key_hash] != value_hash:
                result.changed_count += 1
                if len(result.changed) < MAX_EXAMPLES:
                    result.changed.append({"key": current_rows[key_hash], "differences": []})
        result.removed_count = sum(1 for k in expected.hashes if k not in current.hashes)
    else:
        before, after = Counter(expected.counts), Counter(current.counts)
        for row_id, n in (after - before).items():
            result.added_count += n
            if len(result.added) < MAX_EXAMPLES and row_id in current.examples:
                result.added.append(
                    dict(zip(expected.columns, current.examples[row_id], strict=True))
                )
        for row_id, n in (before - after).items():
            result.removed_count += n
            if len(result.removed) < MAX_EXAMPLES and row_id in expected.examples:
                result.removed.append(
                    dict(zip(expected.columns, expected.examples[row_id], strict=True))
                )

    if expected.mode == "hash":
        for column, total in expected.totals.items():
            new_total = current.totals.get(column)
            if new_total is None or abs(new_total - total) > tolerance * max(1, len(actual)):
                result.totals.append({"column": column, "expected": total, "actual": new_total})
    return result


def compare_tables(
    expected: Table, actual: Table, keys: list[str] | None = None, tolerance: float = 0.0
) -> Diff:
    return diff(snapshot(expected, keys, mode="full"), actual, tolerance)
