"""Evaluating the expectations of a check against a query result."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from testbench.compare import Diff, Snapshot, compare_tables, diff, normalize
from testbench.expressions import ExpressionError, compile_expression, evaluate
from testbench.table import Table

PASSED, FAILED, ERROR, SKIPPED = "passed", "failed", "error", "skipped"
MAX_FAILING_ROWS = 20


@dataclass
class Outcome:
    expectation: str
    status: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def check_row_count(spec: Any, table: Table) -> Outcome:
    n = len(table)
    if isinstance(spec, int):
        ok, wanted = n == spec, f"exactly {spec}"
    else:
        low, high = spec.get("min"), spec.get("max")
        ok = (low is None or n >= low) and (high is None or n <= high)
        wanted = " and ".join(
            p
            for p in (
                f"at least {low}" if low is not None else "",
                f"at most {high}" if high is not None else "",
            )
            if p
        )
    details = {} if ok else {"rows": list(table.records())[:MAX_FAILING_ROWS]}
    message = f"{n} {'row' if n == 1 else 'rows'} (expected {wanted})"
    return Outcome("row_count", PASSED if ok else FAILED, message, details)


def check_all_rows(spec: Any, table: Table) -> Outcome:
    expressions = [spec] if isinstance(spec, str) else list(spec)
    compiled = [(e, compile_expression(e)) for e in expressions]
    failing: list[dict[str, Any]] = []
    failing_count = 0
    for record in table.records():
        normalized = {k: normalize(v) for k, v in record.items()}
        broken = [source for source, tree in compiled if not evaluate(tree, normalized)]
        if broken:
            failing_count += 1
            if len(failing) < MAX_FAILING_ROWS:
                failing.append({"row": record, "broken": broken})
    rule = " and ".join(expressions)
    if failing_count:
        return Outcome(
            "all_rows",
            FAILED,
            f"{failing_count} of {len(table)} rows break: {rule}",
            {"failing_rows": failing},
        )
    return Outcome("all_rows", PASSED, f"all {len(table)} rows satisfy: {rule}")


def _expected_rows(spec: Any, scenario_dir: Path) -> tuple[Table, bool, float]:
    if isinstance(spec, list):
        return Table.from_records(spec), False, 0.0
    ordered, tolerance = bool(spec.get("ordered", False)), float(spec.get("tolerance", 0))
    if "csv" in spec:
        with (scenario_dir / spec["csv"]).open(newline="", encoding="utf-8") as fh:
            records = [
                {k: _parse_csv_value(v) for k, v in row.items()} for row in csv.DictReader(fh)
            ]
        return Table.from_records(records), ordered, tolerance
    return Table.from_records(spec.get("rows", [])), ordered, tolerance


def _parse_csv_value(value: str) -> Any:
    if value == "":
        return None
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value


def check_equals(spec: Any, table: Table, scenario_dir: Path) -> Outcome:
    expected, ordered, tolerance = _expected_rows(spec, scenario_dir)
    if ordered:
        # Position becomes the key, so row order matters.
        expected = Table(
            ["__position", *expected.columns], [(i, *r) for i, r in enumerate(expected.rows)]
        )
        table = Table(["__position", *table.columns], [(i, *r) for i, r in enumerate(table.rows)])
        result = compare_tables(expected, table, keys=["__position"], tolerance=tolerance)
    else:
        result = compare_tables(expected, table, tolerance=tolerance)
    return _diff_outcome("equals", result)


def check_regression(baseline: Snapshot | None, table: Table, spec: Any) -> Outcome:
    if baseline is None:
        return Outcome(
            "regression", ERROR, "no baseline yet: run 'testbench baseline' on a known-good state"
        )
    tolerance = float(spec.get("tolerance", 0)) if isinstance(spec, dict) else 0.0
    return _diff_outcome("regression", diff(baseline, table, tolerance))


def check_reconcile(spec: dict[str, Any], table: Table, other: Table) -> Outcome:
    """``table`` is the check's own result (target); ``other`` comes from the reconcile query."""
    result = compare_tables(
        other, table, keys=spec.get("keys"), tolerance=float(spec.get("tolerance", 0))
    )
    return _diff_outcome("reconcile", result)


def _diff_outcome(expectation: str, result: Diff) -> Outcome:
    status = PASSED if result.ok else FAILED
    return Outcome(expectation, status, result.summary(), {} if result.ok else result.to_json())


__all__ = [
    "ERROR",
    "FAILED",
    "PASSED",
    "SKIPPED",
    "ExpressionError",
    "Outcome",
    "check_all_rows",
    "check_equals",
    "check_reconcile",
    "check_regression",
    "check_row_count",
]
