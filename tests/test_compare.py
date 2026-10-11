from decimal import Decimal

import pytest

from testbench.compare import CompareError, Snapshot, compare_tables, diff, snapshot
from testbench.table import Table

COLUMNS = ["id", "month", "cost"]


def table(*rows: tuple) -> Table:
    return Table(COLUMNS, list(rows))


def test_keyed_diff_reports_added_removed_and_changed() -> None:
    before = table((1, "01", 100.0), (2, "01", 200.0), (3, "01", 300.0))
    after = table((1, "01", 100.0), (2, "01", 250.0), (4, "01", 400.0))
    result = compare_tables(before, after, keys=["id", "month"])
    assert (result.added_count, result.removed_count, result.changed_count) == (1, 1, 1)
    assert result.changed[0]["differences"] == [{"column": "cost", "expected": 200, "actual": 250}]
    assert not result.ok


def test_tolerance_and_driver_types_are_normalized() -> None:
    before = table((1, "01", 100.0))
    after = Table(["ID", "MONTH", "COST"], [(1, "01  ", Decimal("100.004"))])
    assert compare_tables(before, after, keys=["id", "month"], tolerance=0.01).ok
    assert not compare_tables(before, after, keys=["id", "month"]).ok


def test_unkeyed_diff_is_a_multiset_comparison() -> None:
    before = table((1, "01", 1.0), (1, "01", 1.0))
    after = table((1, "01", 1.0))
    result = compare_tables(before, after)
    assert result.removed_count == 1 and result.added_count == 0


def test_column_changes_are_reported() -> None:
    result = compare_tables(table((1, "01", 1.0)), Table(["id", "month"], [(1, "01")]))
    assert result.missing_columns == ["cost"]


def test_duplicate_keys_are_rejected() -> None:
    with pytest.raises(CompareError, match="not unique"):
        snapshot(table((1, "01", 1.0), (1, "01", 2.0)), keys=["id", "month"])


def test_hash_mode_stores_no_values_but_detects_changes() -> None:
    before = table((1, "01", 100.0), (2, "01", 200.0))
    stored = Snapshot.from_json(snapshot(before, ["id", "month"], mode="hash").to_json())
    serialized = str(stored.to_json())
    assert "200" not in serialized.replace("row_count", "")  # only hashes and totals
    assert stored.totals == {"id": 3, "cost": 300}

    assert diff(stored, before).ok
    result = diff(stored, table((1, "01", 100.0), (2, "01", 210.0)))
    assert result.changed_count == 1
    assert result.changed[0]["key"]["cost"] == 210  # current values only
    assert result.totals
