"""Numeric checks with an explicit tolerance, including trig.

Trig values are usually irrational, so answer keys round them. Numeric mode
compares two values within a stated tolerance instead of testing exact equality.

The expression language: decimal constants, pi, parentheses, + - * /, integer
powers from -8 to 8, and the calls sqrt, sin, cos, tan, asin, acos, atan
(arcsin, arccos, arctan also accepted). No variables. Expressions are built
directly as SymPy objects from Python's syntax tree. Nothing is passed to eval,
sympify, or parse_expr.

Any expression with a trig call needs angle_convention set to 'degrees' or
'radians'. In degrees, sin(30) means sin(30 degrees), and asin(0.5) returns 30.
There is no default, because a wrong default is the most common trig error.
"""
from __future__ import annotations

import ast
from typing import Any

import sympy as sp

from .rational import MAX_AST_NODES, MAX_EXPRESSION_LENGTH, Undefined, Unsupported, _DECIMAL, _number

MAX_POWER = 8
MAX_RATIONAL_BITS = 1024
MAX_CALL_DEPTH = 4
PRECISION = 50
FORWARD = {"sin": sp.sin, "cos": sp.cos, "tan": sp.tan}
INVERSE = {"asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
           "arcsin": sp.asin, "arccos": sp.acos, "arctan": sp.atan}
DEGREE_LOOKING = {15, 30, 45, 60, 75, 90, 120, 135, 150, 180, 210, 225, 240, 270, 300, 315, 330, 360}
ANGLE_UNITS = {"deg": "degrees", "degree": "degrees", "degrees": "degrees",
               "rad": "radians", "radian": "radians", "radians": "radians"}


class ParsedValue:
    def __init__(self, expr: sp.Expr, uses_trig: bool, warnings: list[str]):
        self.expr, self.uses_trig, self.warnings = expr, uses_trig, warnings


def _bits(value: sp.Rational) -> int:
    return max(abs(int(value.p)).bit_length(), int(value.q).bit_length())


def parse_numeric(source: Any, convention: str | None) -> ParsedValue:
    """Build a SymPy expression from a whitelisted syntax tree."""
    if isinstance(source, (int, float)) and not isinstance(source, bool):
        value = _number(source)
        return ParsedValue(sp.Rational(value.numerator, value.denominator), False, [])
    if not isinstance(source, str) or not source.strip():
        raise Unsupported("Values must be numbers or nonempty expression strings.")
    source = source.strip()
    if len(source) > MAX_EXPRESSION_LENGTH:
        raise Unsupported(f"Expression is longer than {MAX_EXPRESSION_LENGTH} characters.")
    try:
        tree = ast.parse(source, mode="eval")
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise Unsupported("Could not read the expression. Use explicit operators, for example 2*sin(30).") from exc
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise Unsupported(f"Expression has more than {MAX_AST_NODES} syntax nodes.")
    state = {"trig": False, "warnings": []}

    def visit(node: ast.AST, depth: int) -> sp.Expr:
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            token = ast.get_source_segment(source, node) or ""
            if not _DECIMAL.fullmatch(token):
                raise Unsupported("Only base-10 integer and decimal constants are supported.")
            value = _number(token)
            return sp.Rational(value.numerator, value.denominator)
        if isinstance(node, ast.Name) and node.id == "pi":
            return sp.pi
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand, depth)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Pow):
                exponent = visit(node.right, depth)
                if not exponent.is_Integer or abs(int(exponent)) > MAX_POWER:
                    raise Unsupported(f"Powers must be integer constants from -{MAX_POWER} to {MAX_POWER}. Use sqrt for roots.")
                base = visit(node.left, depth)
                if base.is_Rational and _bits(base) * abs(int(exponent)) > MAX_RATIONAL_BITS:
                    raise Unsupported("The power is too large for the resource limit.")
                if base == 0 and int(exponent) <= 0:
                    raise Undefined("Zero to a zero or negative power is undefined.")
                return base ** int(exponent)
            left, right = visit(node.left, depth), visit(node.right, depth)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                if right == 0:
                    raise Undefined("Division by zero.")
                return left / right
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name not in FORWARD and name not in INVERSE and name != "sqrt":
                raise Unsupported(f"Unknown function '{name}'. Allowed: sqrt, sin, cos, tan, asin, acos, atan.")
            if node.keywords or len(node.args) != 1:
                raise Unsupported(f"{name} takes exactly one argument.")
            if depth >= MAX_CALL_DEPTH:
                raise Unsupported(f"Function calls are nested deeper than {MAX_CALL_DEPTH}.")
            argument = visit(node.args[0], depth + 1)
            if name == "sqrt":
                return sp.sqrt(argument)
            state["trig"] = True
            if convention not in ("degrees", "radians"):
                raise Unsupported("This expression uses trig. Set angle_convention to 'degrees' or 'radians'.")
            if name in FORWARD:
                _warn_argument(node.args[0], argument, convention, name, state["warnings"])
                if convention == "degrees":
                    argument = argument * sp.pi / 180
                return FORWARD[name](argument)
            result = INVERSE[name](argument)
            return result * 180 / sp.pi if convention == "degrees" else result
        raise Unsupported("Unsupported notation. Variables, attributes, indexing, and implicit multiplication are not accepted.")

    expr = visit(tree.body, 0)
    return ParsedValue(expr, state["trig"], state["warnings"])


def _warn_argument(node: ast.AST, value: sp.Expr, convention: str, name: str, warnings: list[str]) -> None:
    """Flag the two classic unit slips. A warning never changes the result."""
    if convention == "degrees" and value.has(sp.pi):
        warnings.append(f"{name} has pi in its argument, but angle_convention is degrees. "
                        "Check whether the key meant radians.")
    if convention == "radians" and value.is_Integer and abs(int(value)) in DEGREE_LOOKING:
        warnings.append(f"{name}({int(value)}) is read as {int(value)} radians. "
                        "Check whether the key meant degrees.")


def evaluate(expr: sp.Expr) -> sp.Float:
    if expr.has(sp.zoo, sp.nan, sp.oo, -sp.oo):
        raise Undefined("The expression is undefined, for example tan(90) in degrees.")
    value = sp.N(expr, PRECISION)
    real, imaginary = value.as_real_imag()
    if abs(imaginary) > sp.Float(10) ** (-PRECISION + 5):
        raise Undefined("The value is not a real number, for example asin(2) or sqrt(-1).")
    if not real.is_finite:
        raise Undefined("The value is not finite.")
    return sp.Float(real, PRECISION)


def check_numeric(item: dict[str, Any]) -> dict[str, Any]:
    unit, actual_unit = item.get("unit"), item.get("actual_unit")
    if not isinstance(unit, str) or not unit.strip() or not isinstance(actual_unit, str) or not actual_unit.strip():
        raise Unsupported("Numeric checks need unit and actual_unit. Use 'dimensionless' for trig ratios.")
    if unit != actual_unit:
        raise Unsupported("Units differ. Convert them before checking.")
    convention = item.get("angle_convention")
    if convention is not None and convention not in ("degrees", "radians"):
        raise Unsupported("angle_convention must be 'degrees' or 'radians'.")
    if unit in ANGLE_UNITS and convention != ANGLE_UNITS[unit]:
        raise Unsupported("An angle unit needs a matching angle_convention.")
    if item.get("absolute_tolerance") is None and item.get("relative_tolerance") is None:
        raise Unsupported("Set absolute_tolerance or relative_tolerance. There is no default.")
    absolute = _number(item["absolute_tolerance"]) if item.get("absolute_tolerance") is not None else 0
    relative = _number(item["relative_tolerance"]) if item.get("relative_tolerance") is not None else 0
    if absolute < 0 or relative < 0:
        raise Unsupported("Tolerances must be zero or positive.")
    expected = parse_numeric(item.get("expected"), convention)
    actual = parse_numeric(item.get("actual"), convention)
    expected_value, actual_value = evaluate(expected.expr), evaluate(actual.expr)
    error = abs(expected_value - actual_value)
    allowed = max(sp.Rational(absolute), sp.Rational(relative) * abs(expected_value))
    return {"status": "correct" if error <= allowed else "incorrect",
            "reason": "Compared values within max(absolute_tolerance, relative_tolerance * |expected|).",
            "expected_value": sp.N(expected_value, 12).__str__(),
            "actual_value": sp.N(actual_value, 12).__str__(),
            "absolute_error": sp.N(error, 6).__str__(),
            "allowed_error": sp.N(allowed, 6).__str__(),
            "unit": unit, "angle_convention": convention,
            "warnings": expected.warnings + actual.warnings}
