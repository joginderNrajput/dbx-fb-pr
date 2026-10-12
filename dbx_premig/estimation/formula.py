"""A small, safe expression language for the assessment rules file.

Expressions are Python-like arithmetic over the per-asset variables, for example::

    lines / 25 + cells / 2 + notebook_calls * 2
    readiness == "Unsupported" or unsupported_constructs > 0
    min(100, penalty_total + size_points)

Allowed: numbers, strings, ``true``/``false``, variable names, ``+ - * / // % **``,
comparisons, ``and``/``or``/``not``, ``x if cond else y`` and the functions
``min max round abs ceil floor sqrt log``. Nothing else: no attributes, subscripts,
lambdas, comprehensions or imports. The rules file is configuration, but it is still parsed
as untrusted text, so ``eval`` is never used.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

__all__ = ["FUNCTIONS", "Formula", "FormulaError"]

Value = float | int | str | bool


def _round(value: float, places: int = 0) -> float:
    """Half-up rounding (2.5 -> 3), unlike Python's banker's round()."""
    from dbx_premig.estimation.rounding import round_hours

    result = round_hours(float(value), int(places))
    return int(result) if places == 0 else result


FUNCTIONS: dict[str, Callable[..., Any]] = {
    "min": min,
    "max": max,
    "round": _round,
    "abs": abs,
    "ceil": math.ceil,
    "floor": math.floor,
    "sqrt": math.sqrt,
    "log": math.log,
}
_CONSTANTS: dict[str, Value] = {"true": True, "false": False, "True": True, "False": False}

_BINOPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_CMPOPS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
_MAX_LENGTH = 2000
_MAX_POWER = 100


class FormulaError(ValueError):
    """An expression that does not parse, uses something not allowed, or fails to evaluate."""


@dataclass(frozen=True)
class Formula:
    """A parsed, validated expression."""

    source: str
    tree: ast.Expression
    names: frozenset[str]

    @classmethod
    def parse(cls, source: object, known: frozenset[str] | None = None) -> Formula:
        text = str(source).strip()
        if not text:
            raise FormulaError("empty expression")
        if len(text) > _MAX_LENGTH:
            raise FormulaError("expression too long")
        try:
            tree = ast.parse(text, mode="eval")
        except SyntaxError as exc:
            raise FormulaError(f"cannot parse {text!r}") from exc
        names: set[str] = set()
        for node in ast.walk(tree):
            _check_node(node, names)
        names -= set(_CONSTANTS)
        if known is not None:
            unknown = sorted(names - known)
            if unknown:
                raise FormulaError(f"unknown name(s) {', '.join(unknown)} in {text!r}")
        return cls(source=text, tree=tree, names=frozenset(names))

    def evaluate(self, variables: Mapping[str, Value]) -> Value:
        try:
            result: Value = _eval(self.tree.body, variables)
        except FormulaError:
            raise
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise FormulaError(f"{self.source!r} failed: {type(exc).__name__}") from exc
        return result

    def number(self, variables: Mapping[str, Value]) -> float:
        value = self.evaluate(variables)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise FormulaError(f"{self.source!r} must give a number")
        if math.isnan(value) or math.isinf(value):
            raise FormulaError(f"{self.source!r} gave {value}")
        return float(value)

    def truth(self, variables: Mapping[str, Value]) -> bool:
        return bool(self.evaluate(variables))


_ALLOWED = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.Name,
    ast.Constant,
    ast.Load,
    ast.And,
    ast.Or,
    ast.Not,
    ast.USub,
    ast.UAdd,
    *_BINOPS,
    *_CMPOPS,
)


def _check_node(node: ast.AST, names: set[str]) -> None:
    if not isinstance(node, _ALLOWED):
        raise FormulaError(f"{type(node).__name__} is not allowed in a rule expression")
    if isinstance(node, ast.Constant) and not isinstance(node.value, int | float | str | bool):
        raise FormulaError("only numbers, strings and true/false are allowed")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            raise FormulaError(f"only the functions {', '.join(FUNCTIONS)} may be called")
        if node.keywords:
            raise FormulaError("keyword arguments are not allowed")
    elif isinstance(node, ast.Name) and node.id not in FUNCTIONS:
        names.add(node.id)


def _eval(node: ast.AST, env: Mapping[str, Value]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        if node.id not in env:
            raise FormulaError(f"unknown name {node.id}")
        return env[node.id]
    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left, env), _eval(node.right, env)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POWER:
            raise FormulaError("exponent too large")
        if isinstance(node.op, ast.Div | ast.FloorDiv | ast.Mod) and right == 0:
            return 0  # a missing metric must not abort the assessment
        return _BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp):
        value = _eval(node.operand, env)
        if isinstance(node.op, ast.Not):
            return not value
        return -value if isinstance(node.op, ast.USub) else +value
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result: Any = True
            for v in node.values:
                result = _eval(v, env)
                if not result:
                    return result
            return result
        result = False
        for v in node.values:
            result = _eval(v, env)
            if result:
                return result
        return result
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        for op, comp in zip(node.ops, node.comparators, strict=True):
            right = _eval(comp, env)
            if not _CMPOPS[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _eval(node.body, env) if _eval(node.test, env) else _eval(node.orelse, env)
    if isinstance(node, ast.Call):
        assert isinstance(node.func, ast.Name)
        return FUNCTIONS[node.func.id](*(_eval(a, env) for a in node.args))
    raise FormulaError(f"{type(node).__name__} is not allowed")  # pragma: no cover
