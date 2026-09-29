"""Exact checks on rational expressions: arithmetic, equivalence, and equations.

Every item has ``id`` and ``mode``. Arithmetic/equivalence use ``expected`` and
``actual`` expression strings. Equivalence permits one ``variable`` (default x).
Equation mode uses ``equation`` (one equals sign), ``actual`` (a list of exact
rational root strings), and an optional variable. Only real solutions count.
Numeric mode, including trig, lives in numeric.py.

The expression language contains decimal/integer constants, parentheses, one
variable, +, -, *, /, and integer powers from -8 to 8. It has no calls, implicit
multiplication, attributes, indexing, or Python execution. Rational expressions
retain exclusions from the original expression, even after cancellation.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import sympy as sp

MAX_EXPRESSION_LENGTH = 256
MAX_AST_NODES = 80
MAX_DEGREE = 8
MAX_COEFFICIENT_BITS = 256
MAX_ITEMS = 100
_DECIMAL = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
_VARIABLE = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{0,15}\Z")


class Unsupported(ValueError):
    """Input is outside the supported mathematical language or resource bounds."""


class Undefined(ValueError):
    """An expression is undefined everywhere in its stated domain."""


def _bounded(poly: sp.Poly) -> sp.Poly:
    if not poly.is_zero and poly.degree() > MAX_DEGREE:
        raise Unsupported(f"Polynomial degree exceeds {MAX_DEGREE}.")
    for coefficient in poly.all_coeffs():
        if max(abs(int(coefficient.p)).bit_length(), int(coefficient.q).bit_length()) > MAX_COEFFICIENT_BITS:
            raise Unsupported("Coefficient size exceeds the deterministic resource limit.")
    return poly


def _multiply(left: sp.Poly, right: sp.Poly) -> sp.Poly:
    if not left.is_zero and not right.is_zero and left.degree() + right.degree() > MAX_DEGREE:
        raise Unsupported(f"Intermediate polynomial degree exceeds {MAX_DEGREE}.")
    return _bounded(left * right)


@dataclass(frozen=True)
class RationalExpression:
    numerator: sp.Poly
    denominator: sp.Poly
    exclusions: tuple[sp.Poly, ...] = ()

    @classmethod
    def make(cls, numerator: sp.Poly, denominator: sp.Poly,
             exclusions: tuple[sp.Poly, ...] = ()) -> RationalExpression:
        _bounded(numerator)
        _bounded(denominator)
        if denominator.is_zero or any(p.is_zero for p in exclusions):
            raise Undefined("Division by zero makes the expression undefined.")
        divisor = sp.gcd(numerator, denominator)
        numerator, denominator = numerator.exquo(divisor), denominator.exquo(divisor)
        lead = denominator.LC()
        numerator, denominator = numerator.mul_ground(1 / lead), denominator.mul_ground(1 / lead)
        return cls(_bounded(numerator), _bounded(denominator), exclusions)

    def subtract(self, other: RationalExpression) -> RationalExpression:
        return self.add(other.negate())

    def negate(self) -> RationalExpression:
        return RationalExpression(-self.numerator, self.denominator, self.exclusions)

    def add(self, other: RationalExpression) -> RationalExpression:
        return self.make(
            _multiply(self.numerator, other.denominator) + _multiply(other.numerator, self.denominator),
            _multiply(self.denominator, other.denominator), self.exclusions + other.exclusions,
        )

    def multiply(self, other: RationalExpression) -> RationalExpression:
        return self.make(_multiply(self.numerator, other.numerator),
                         _multiply(self.denominator, other.denominator),
                         self.exclusions + other.exclusions)

    def divide(self, other: RationalExpression) -> RationalExpression:
        return self.make(_multiply(self.numerator, other.denominator),
                         _multiply(self.denominator, other.numerator),
                         self.exclusions + other.exclusions + (other.numerator,))

    def power(self, exponent: int) -> RationalExpression:
        exclusions = self.exclusions + ((self.numerator,) if exponent < 0 else ())
        numerator, denominator = self.numerator, self.denominator
        if exponent < 0:
            numerator, denominator = denominator, numerator
        exponent = abs(exponent)
        for poly in (numerator, denominator):
            if not poly.is_zero and poly.degree() * exponent > MAX_DEGREE:
                raise Unsupported(f"Intermediate polynomial degree exceeds {MAX_DEGREE}.")
            for coefficient in poly.all_coeffs():
                if max(abs(int(coefficient.p)).bit_length(), int(coefficient.q).bit_length()) * exponent > MAX_COEFFICIENT_BITS:
                    raise Unsupported("Power exceeds the coefficient resource limit.")
        if exponent == 0 and numerator.is_zero:
            raise Undefined("Zero to the zero power is not supported as a defined value.")
        return self.make(numerator ** exponent, denominator ** exponent, exclusions)

    def excluded_real_values(self) -> tuple[sp.Expr, ...]:
        roots = {root for poly in self.exclusions if poly.degree() > 0
                 for root in poly.real_roots(radicals=False)}
        return tuple(sorted(roots, key=sp.default_sort_key))

    def constant(self) -> sp.Rational:
        if self.numerator.degree() > 0 or self.denominator.degree() > 0:
            raise Unsupported("A numeric constant is required here.")
        return self.numerator.nth(0) / self.denominator.nth(0)


class SafeExpressionParser:
    def __init__(self, variable: str | None = None):
        if variable is not None and (not isinstance(variable, str) or not _VARIABLE.fullmatch(variable)):
            raise Unsupported("variable must be a short ASCII identifier.")
        self.variable = variable
        self.symbol = sp.Symbol(variable or "_constant", real=True)
        self.one = sp.Poly(1, self.symbol, domain=sp.QQ)

    def parse(self, source: Any) -> RationalExpression:
        if not isinstance(source, str) or not source.strip():
            raise Unsupported("Expressions must be nonempty strings.")
        source = source.strip()
        if len(source) > MAX_EXPRESSION_LENGTH:
            raise Unsupported(f"Expression length exceeds {MAX_EXPRESSION_LENGTH} characters.")
        try:
            tree = ast.parse(source, mode="eval")
        except (SyntaxError, ValueError, RecursionError) as exc:
            raise Unsupported("Use explicit Python-style arithmetic operators and parentheses.") from exc
        if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
            raise Unsupported(f"Expression exceeds {MAX_AST_NODES} syntax nodes.")

        def visit(node: ast.AST) -> RationalExpression:
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                token = ast.get_source_segment(source, node) or ""
                if not _DECIMAL.fullmatch(token):
                    raise Unsupported("Only base-10 integer and decimal constants are supported.")
                value = _number(token)
                poly = sp.Poly(sp.Rational(value.numerator, value.denominator), self.symbol, domain=sp.QQ)
                return RationalExpression.make(poly, self.one)
            if isinstance(node, ast.Name) and self.variable is not None and node.id == self.variable:
                return RationalExpression(sp.Poly(self.symbol, self.symbol, domain=sp.QQ), self.one)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = visit(node.operand)
                return value.negate() if isinstance(node.op, ast.USub) else value
            if isinstance(node, ast.BinOp):
                if isinstance(node.op, ast.Pow):
                    if any(isinstance(part, ast.Name) for part in ast.walk(node.right)):
                        raise Unsupported("A power exponent cannot contain a variable.")
                    exponent = visit(node.right).constant()
                    if exponent.q != 1 or abs(exponent) > MAX_DEGREE:
                        raise Unsupported(f"Powers must be integer constants from -{MAX_DEGREE} to {MAX_DEGREE}.")
                    return visit(node.left).power(int(exponent))
                left, right = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Add):
                    return left.add(right)
                if isinstance(node.op, ast.Sub):
                    return left.subtract(right)
                if isinstance(node.op, ast.Mult):
                    return left.multiply(right)
                if isinstance(node.op, ast.Div):
                    return left.divide(right)
            raise Unsupported("Unsupported notation. Calls, attributes, indexing, and implicit multiplication are not accepted.")

        return visit(tree.body)


def _number(value: Any) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise Unsupported("Numbers must be finite decimal strings or JSON numbers.")
    if isinstance(value, int) and value.bit_length() > MAX_COEFFICIENT_BITS:
        raise Unsupported("Number exceeds the deterministic resource limit.")
    text = str(value).strip()
    if len(text) > 100 or not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text):
        raise Unsupported("A finite decimal number with at most 100 characters is required.")
    exponent = re.search(r"[eE]([+-]?\d+)$", text)
    if exponent and abs(int(exponent.group(1))) > 70:
        raise Unsupported("Decimal exponent exceeds the numeric resource limit.")
    number = Fraction(text)
    if max(abs(number.numerator).bit_length(), number.denominator.bit_length()) > MAX_COEFFICIENT_BITS:
        raise Unsupported("Number exceeds the deterministic resource limit.")
    return number


def _result(status: str, reason: str, **details: Any) -> dict[str, Any]:
    return {"status": status, "reason": reason, **details}


def check_exact(item: dict[str, Any]) -> dict[str, Any]:
    """Exact rational modes: arithmetic, equivalence, equation."""
    mode = item.get("mode")
    if mode == "arithmetic":
        parser = SafeExpressionParser()
        expected, actual = parser.parse(item.get("expected")), parser.parse(item.get("actual"))
        expected_value, actual_value = expected.constant(), actual.constant()
        return _result("correct" if expected_value == actual_value else "incorrect",
                       "Compared exact rational values.", expected_value=str(expected_value), actual_value=str(actual_value))
    if mode == "equivalence":
        parser = SafeExpressionParser(item.get("variable", "x"))
        expected, actual = parser.parse(item.get("expected")), parser.parse(item.get("actual"))
        same_values = expected.subtract(actual).numerator.is_zero
        expected_exclusions, actual_exclusions = expected.excluded_real_values(), actual.excluded_real_values()
        same_domains = set(expected_exclusions) == set(actual_exclusions)
        return _result("correct" if same_values and same_domains else "incorrect",
                       "Expressions have equal values and equal original real domains." if same_values and same_domains
                       else "Expressions differ in values or in their original real domains.",
                       equivalent_values=bool(same_values), same_real_domain=same_domains,
                       expected_excluded_values=[str(x) for x in expected_exclusions],
                       actual_excluded_values=[str(x) for x in actual_exclusions])
    if mode == "equation":
        equation = item.get("equation")
        if not isinstance(equation, str) or equation.count("=") != 1:
            raise Unsupported("equation must contain exactly one '='.")
        parser = SafeExpressionParser(item.get("variable", "x"))
        lhs, rhs = equation.split("=")
        expression = parser.parse(lhs).subtract(parser.parse(rhs))
        if expression.numerator.is_zero:
            raise Unsupported("The equation has infinitely many real solutions, not a finite solution set.")
        excluded = set(expression.excluded_real_values())
        roots = set(expression.numerator.real_roots(radicals=False)) - excluded
        if any(root.is_Rational is not True for root in roots):
            raise Unsupported("This exact-root input format supports rational real solutions only. Irrational roots need a separately specified numeric check.")
        supplied = item.get("actual")
        if not isinstance(supplied, list) or len(supplied) > MAX_DEGREE:
            raise Unsupported(f"actual must be a list of at most {MAX_DEGREE} exact rational root strings.")
        actual = [SafeExpressionParser().parse(value).constant() for value in supplied]
        if len(set(actual)) != len(actual):
            raise Unsupported("Provide each root once. This checker compares solution sets, not multiplicities.")
        return _result("correct" if roots == set(actual) else "incorrect", "Compared complete sets of real rational solutions.",
                       expected_roots=[str(x) for x in sorted(roots)], actual_roots=[str(x) for x in sorted(actual)],
                       excluded_values=[str(x) for x in sorted(excluded, key=sp.default_sort_key)])
    raise Unsupported("mode must be arithmetic, equivalence, equation, or numeric.")
