import pytest

from curriculum_auditor.mathcheck import check_answer_key


def checked(mode, **kwargs):
    response = check_answer_key([{"id": "example", "mode": mode, **kwargs}])
    assert response["deterministic"] is True
    return response["results"][0]


def test_exact_rational_arithmetic_and_decimal_arithmetic():
    assert checked("arithmetic", expected="1/3 + 1/6", actual="0.5")["status"] == "correct"
    assert checked("arithmetic", expected="0.1 + 0.2", actual="0.3")["status"] == "correct"
    assert checked("arithmetic", expected="2**3", actual="6")["status"] == "incorrect"


def test_polynomial_equivalence_and_incorrect_expansion():
    assert checked("equivalence", expected="(x+1)**2", actual="x*x+2*x+1")["status"] == "correct"
    assert checked("equivalence", expected="(x+1)**2", actual="x*x+1")["status"] == "incorrect"


def test_canceling_a_denominator_keeps_the_original_domain():
    result = checked("equivalence", expected="x/x", actual="1")
    assert result["status"] == "incorrect"
    assert result["equivalent_values"] is True
    assert result["same_real_domain"] is False
    assert result["expected_excluded_values"] == ["0"]


def test_equal_domain_guards_are_compared_by_real_roots():
    result = checked("equivalence", expected="x/x", actual="x**2/x**2")
    assert result["status"] == "correct"
    result = checked("equivalence", expected="(x*x+1)/(x*x+1)", actual="1")
    assert result["status"] == "correct"
    result = checked("equivalence", expected="(x*x-2)/(x*x-2)", actual="(x**4-4)/(x**4-4)")
    assert result["status"] == "correct"


def test_nested_division_preserves_all_exclusions():
    result = checked("equivalence", expected="1/(1/x)", actual="x")
    assert result["status"] == "incorrect"
    assert result["expected_excluded_values"] == ["0"]
    assert checked("equivalence", expected="x**-1", actual="1/x")["status"] == "correct"


@pytest.mark.parametrize("expression", ["1/0", "0**0", "(1/0)**0"])
def test_undefined_arithmetic_never_passes(expression):
    assert checked("arithmetic", expected=expression, actual="1")["status"] == "indeterminate"


@pytest.mark.parametrize("expression", [
    "__import__('os').system('false')", "open('secret')", "x.__class__", "[1][0]",
    "2x", "True", "1j", "0xff", "1_000", "x^2", "sin(x)", "x**(x/x)",
    "y+1", "lambda: 1", "1 if True else 0", "1//2", "1%2",
])
def test_untrusted_or_unsupported_notation_is_rejected(expression):
    assert checked("equivalence", expected=expression, actual="1")["status"] == "unsupported"


@pytest.mark.parametrize("expression", ["x**9", "(x**8)**8", "2**10000000", "1e9999999", "9" * 100,
                                         "+".join(["1"] * 50), " " .join(["x"] * 200)])
def test_resource_limits_are_enforced(expression):
    assert checked("equivalence", expected=expression, actual="1")["status"] == "unsupported"


def test_finite_equation_roots_require_the_complete_set():
    assert checked("equation", equation="x*x=4", actual=["-2", "2"])["status"] == "correct"
    result = checked("equation", equation="x*x=4", actual=["2"])
    assert result["status"] == "incorrect"
    assert result["expected_roots"] == ["-2", "2"]


def test_equations_filter_roots_excluded_by_original_denominators():
    result = checked("equation", equation="(x*x-1)/(x-1)=0", actual=["-1"])
    assert result["status"] == "correct"
    assert result["excluded_values"] == ["1"]


def test_no_real_solutions_infinite_solutions_and_irrational_solutions():
    assert checked("equation", equation="x*x+1=0", actual=[])["status"] == "correct"
    assert checked("equation", equation="x=x", actual=[])["status"] == "unsupported"
    assert checked("equation", equation="x*x=2", actual=["1.414"])["status"] == "unsupported"
    assert checked("equation", equation="x=2", actual=["2", "2"])["status"] == "unsupported"
    assert checked("equation", equation="x*x-4", actual=["2"])["status"] == "unsupported"


def test_numeric_tolerances_use_exact_decimal_boundary():
    inputs = {"expected": "10", "unit": "cm", "actual_unit": "cm", "absolute_tolerance": "0.1"}
    assert checked("numeric", actual="10.1", **inputs)["status"] == "correct"
    assert checked("numeric", actual="10.1001", **inputs)["status"] == "incorrect"
    assert checked("numeric", expected=100, actual=101, unit="cm", actual_unit="cm", relative_tolerance="0.01")["status"] == "correct"


def test_numeric_units_and_angles_are_explicit():
    assert checked("numeric", expected=1, actual=1, absolute_tolerance=0)["status"] == "unsupported"
    assert checked("numeric", expected=1, actual=100, unit="m", actual_unit="cm", absolute_tolerance=0)["status"] == "unsupported"
    inputs = {"expected": 90, "actual": 90, "unit": "degrees", "actual_unit": "degrees", "absolute_tolerance": 0}
    assert checked("numeric", **inputs)["status"] == "unsupported"
    assert checked("numeric", **inputs, angle_convention="radians")["status"] == "unsupported"
    assert checked("numeric", **inputs, angle_convention="degrees")["status"] == "correct"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "1e9999999"])
def test_numeric_nonfinite_or_excessive_input_is_rejected(value):
    assert checked("numeric", expected=1, actual=value, unit="dimensionless", actual_unit="dimensionless",
                   absolute_tolerance=0)["status"] == "unsupported"


def test_numeric_missing_and_negative_tolerances_are_rejected():
    inputs = {"expected": 1, "actual": 1, "unit": "dimensionless", "actual_unit": "dimensionless"}
    assert checked("numeric", **inputs)["status"] == "unsupported"
    assert checked("numeric", **inputs, absolute_tolerance=-1)["status"] == "unsupported"


def test_batch_preserves_item_ids_and_continues_after_bad_input():
    result = check_answer_key([None, {"id": "good", "mode": "arithmetic", "expected": "2", "actual": "1+1"}])
    assert [item["status"] for item in result["results"]] == ["unsupported", "correct"]
    assert result["results"][1]["id"] == "good"
    with pytest.raises(ValueError):
        check_answer_key([{}] * 101)
