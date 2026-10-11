import pytest

from testbench.expressions import ExpressionError, compile_expression, evaluate


def check(expr: str, row: dict) -> object:
    return evaluate(compile_expression(expr), row)


def test_comparisons_and_logic() -> None:
    row = {"FTE": 0.8, "lines": 2, "cost_center": "CC-1"}
    assert check("fte > 0 and fte <= 1", row) is True
    assert check("lines == 2", row) is True
    assert check("0 < fte < 0.5", row) is False
    assert check("cost_center in ['CC-1', 'CC-2']", row) is True
    assert check("abs(lines - 3) == 1", row) is True


def test_none_comparison_fails_instead_of_crashing() -> None:
    assert check("fte > 0", {"fte": None}) is False
    assert check("fte is None", {"fte": None}) is True


def test_unknown_column_is_reported() -> None:
    with pytest.raises(ExpressionError, match="unknown column 'salary'"):
        check("salary > 0", {"fte": 1})


@pytest.mark.parametrize(
    "expr", ["__import__('os').system('x')", "fte.__class__", "[x for x in fte]", "lambda: 1"]
)
def test_unsafe_syntax_is_rejected(expr: str) -> None:
    with pytest.raises(ExpressionError):
        check(expr, {"fte": 1})
