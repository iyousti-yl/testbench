"""A tiny, safe expression language for ``all_rows`` checks.

Supports column names, numbers, strings, None/True/False, arithmetic, comparisons,
``and``/``or``/``not``, ``in`` with lists, and a few functions. Nothing else is evaluated.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from typing import Any


class ExpressionError(Exception):
    pass


_BIN_OPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}
_CMP_OPS: dict[type, Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}
_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "abs": abs,
    "round": round,
    "len": len,
    "lower": lambda s: s.lower() if isinstance(s, str) else s,
    "upper": lambda s: s.upper() if isinstance(s, str) else s,
}
_CONSTANTS = {"None": None, "True": True, "False": False, "null": None}


def compile_expression(source: str) -> ast.Expression:
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"invalid expression '{source}': {exc.msg}") from exc
    return tree


def evaluate(tree: ast.Expression, row: dict[str, Any]) -> Any:
    # Column names are matched case-insensitively.
    lowered = {k.lower(): v for k, v in row.items()}
    return _eval(tree.body, lowered)


def _eval(node: ast.AST, row: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        key = node.id.lower()
        if key not in row:
            raise ExpressionError(f"unknown column '{node.id}' (columns: {', '.join(row)})")
        return row[key]
    if isinstance(node, ast.BoolOp):
        values = (_eval(v, row) for v in node.values)
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand, row)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_eval(node.left, row), _eval(node.right, row))
    if isinstance(node, ast.Compare):
        left = _eval(node.left, row)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = _eval(comparator, row)
            if type(op) not in _CMP_OPS:
                break
            try:
                if not _CMP_OPS[type(op)](left, right):
                    return False
            except TypeError:
                # Comparing None with a number counts as a failed check, not a crash.
                return False
            left = right
        else:
            return True
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return [_eval(e, row) for e in node.elts]
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCTIONS
        and not node.keywords
    ):
        return _FUNCTIONS[node.func.id](*(_eval(a, row) for a in node.args))
    raise ExpressionError(f"unsupported syntax: {ast.unparse(node)}")
