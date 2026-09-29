"""Trig and numeric mode: correctness, the degree/radian trap, domains, and limits."""
import time

import pytest

from curriculum_auditor.mathcheck import check_answer


def item(expected, actual, convention="degrees", unit="dimensionless", **extra):
    base = {"id": "t", "mode": "numeric", "expected": expected, "actual": actual, "unit": unit,
            "actual_unit": unit, "angle_convention": convention, "absolute_tolerance": "0.001"}
    base.update(extra)
    return base


@pytest.mark.parametrize("expected,actual", [
    ("sin(30)", "0.5"), ("cos(60)", "1/2"), ("tan(45)", "1"), ("sqrt(3)/2", "0.866"),
    ("12*sin(40)", "7.713"), ("2*cos(30)**2 - 1", "0.5")])
def test_degree_values(expected, actual):
    assert check_answer(item(expected, actual))["status"] == "correct"


def test_inverse_trig_returns_degrees():
    result = check_answer(item("asin(0.5)", "30", unit="degrees"))
    assert result["status"] == "correct"


def test_inverse_trig_returns_radians():
    result = check_answer(item("acos(0)", "1.5708", convention="radians", unit="radians"))
    assert result["status"] == "correct"


def test_degree_radian_trap_is_caught_and_explained():
    result = check_answer(item("sin(30)", "0.5", convention="radians"))
    assert result["status"] == "incorrect"
    assert "radians" in result["warnings"][0]


def test_pi_in_degree_mode_warns():
    result = check_answer(item("sin(pi/6)", "0.5", convention="degrees"))
    assert result["status"] == "incorrect"
    assert "pi" in result["warnings"][0]


def test_trig_without_convention_is_unsupported():
    result = check_answer(item("sin(30)", "0.5", convention=None))
    assert result["status"] == "unsupported" and "angle_convention" in result["reason"]


def test_angle_unit_must_match_convention():
    assert check_answer(item("asin(0.5)", "30", convention="radians", unit="degrees"))["status"] == "unsupported"


def test_units_must_match():
    bad = item("5", "5")
    bad["actual_unit"] = "cm"
    assert check_answer(bad)["status"] == "unsupported"


@pytest.mark.parametrize("expected", ["tan(90)", "asin(2)", "sqrt(-1)", "1/(cos(90))", "1/0", "0**-1"])
def test_domain_edges_are_indeterminate(expected):
    assert check_answer(item(expected, "0"))["status"] == "indeterminate"


def test_tolerance_is_required():
    no_tolerance = item("sin(30)", "0.5")
    del no_tolerance["absolute_tolerance"]
    assert check_answer(no_tolerance)["status"] == "unsupported"


def test_relative_tolerance():
    loose = item("1000*sin(30)", "501", absolute_tolerance=None, relative_tolerance="0.01")
    assert check_answer(loose)["status"] == "correct"
    tight = item("1000*sin(30)", "501", absolute_tolerance=None, relative_tolerance="0.001")
    assert check_answer(tight)["status"] == "incorrect"


def test_negative_tolerance_is_unsupported():
    assert check_answer(item("1", "1", absolute_tolerance="-1"))["status"] == "unsupported"


@pytest.mark.parametrize("expected", [
    "__import__('os').system('false')", "open('secret')", "sin.__class__", "[1][0]",
    "(lambda: 1)()", "sin(x=30)", "sin(30, 2)", "exp(1)", "x + 1", "2 sin(30)", "sin 30",
    "2**0.5", "2**(1/2)", "E", "print(1)", "sin(30) if 1 else 2", "0x10", "1_000"])
def test_rejects_unsafe_or_unknown_notation(expected):
    assert check_answer(item(expected, "1"))["status"] == "unsupported"


def test_length_node_power_and_nesting_limits():
    assert check_answer(item("1+" * 200 + "1", "1"))["status"] == "unsupported"
    assert check_answer(item("+".join(["1"] * 60), "60"))["status"] == "unsupported"
    assert check_answer(item("2**9", "512"))["status"] == "unsupported"
    assert check_answer(item("sin(sin(sin(sin(sin(1)))))", "0"))["status"] == "unsupported"


def test_nested_powers_stop_fast():
    start = time.perf_counter()
    result = check_answer(item("((((((10**8)**8)**8)**8)**8)**8)", "1"))
    assert result["status"] == "unsupported"
    assert time.perf_counter() - start < 1


def test_plain_numbers_still_work():
    assert check_answer(item(0.5, 0.5004, convention=None))["status"] == "correct"
