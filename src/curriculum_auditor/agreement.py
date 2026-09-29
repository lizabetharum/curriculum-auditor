"""Agreement with explicit reference ratings and separate evidence abstentions.

Rows are keyed by work_id and subcompetency_id. A rated row has level 1 through
4 and optional status='scored'. An abstention has level=None and
status='insufficient_evidence'. Missing pairs are not abstentions. No acceptance
threshold is invented. Rates are proportions in [0, 1], with denominators.
"""

from __future__ import annotations

from typing import Any


def _index(rows: list[dict[str, Any]], label: str) -> dict[tuple[str, str], int | None]:
    if not isinstance(rows, list):
        raise ValueError(f"{label} must be a list")
    indexed = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"Every {label} row must be an object")
        key = (row.get("work_id"), row.get("subcompetency_id"))
        if not all(isinstance(part, str) and part.strip() for part in key):
            raise ValueError(f"Every {label} row needs work_id and subcompetency_id")
        if key in indexed:
            raise ValueError(f"Duplicate {label} pair: {key}")
        level, status = row.get("level"), row.get("status")
        if status == "insufficient_evidence":
            if level is not None:
                raise ValueError(f"An insufficient_evidence {label} row must have level=null: {key}")
        elif type(level) is int and level in (1, 2, 3, 4) and status in (None, "scored"):
            pass
        else:
            raise ValueError(f"Invalid {label} rating for {key}: use level 1–4 or insufficient_evidence with level=null")
        indexed[key] = level
    return indexed


def _pairs(keys: set[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"work_id": work, "subcompetency_id": skill} for work, skill in sorted(keys)]


def _rate(count: int, denominator: int) -> dict[str, Any]:
    return {"count": count, "denominator": denominator,
            "rate": count / denominator if denominator else None,
            "undefined_reason": None if denominator else "No paired cases."}


def compute_agreement(predictions: list[dict[str, Any]], references: list[dict[str, Any]],
                      *, expected_cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Join explicit reference cases and report ordinal agreement and abstention.

    Agreement and both abstention rates use matched expected cases only. Missing
    ratings and unexpected ratings are listed separately. Level
    agreement excludes any pair where either rater has insufficient evidence.
    The returned status is reference_pending when no reference was supplied,
    incomplete when pair sets differ from the manifest, and complete when they
    match. Without a manifest, supplied reference keys define expected cases.
    Coverage and exact_matches_over_expected preserve the manifest denominator.
    The latter is an observed exact-match fraction, not an accuracy estimate.
    """
    predicted, reference = _index(predictions, "prediction"), _index(references, "reference")
    prediction_keys, reference_keys = set(predicted), set(reference)
    if expected_cases is None:
        expected_keys = reference_keys
    else:
        if not isinstance(expected_cases, list):
            raise ValueError("expected_cases must be a list")
        expected_keys = set()
        for case in expected_cases:
            if not isinstance(case, dict):
                raise ValueError("Every expected case must be an object")
            key = (case.get("work_id"), case.get("subcompetency_id"))
            if not all(isinstance(part, str) and part.strip() for part in key):
                raise ValueError("Every expected case needs work_id and subcompetency_id")
            if key in expected_keys:
                raise ValueError(f"Duplicate expected case pair: {key}")
            expected_keys.add(key)
    shared = prediction_keys & reference_keys & expected_keys
    jointly_rated = [(reference[key], predicted[key]) for key in sorted(shared)
                     if reference[key] is not None and predicted[key] is not None]
    matrix = [[0] * 4 for _ in range(4)]
    sufficiency_matrix = [[0] * 2 for _ in range(2)]
    for key in shared:
        sufficiency_matrix[int(reference[key] is None)][int(predicted[key] is None)] += 1
    for expected, actual in jointly_rated:
        matrix[expected - 1][actual - 1] += 1
    n = len(jointly_rated)
    exact = sum(expected == actual for expected, actual in jointly_rated)
    within_one = sum(abs(expected - actual) <= 1 for expected, actual in jointly_rated)
    absolute_difference = sum(abs(expected - actual) for expected, actual in jointly_rated)
    reference_counts = [sum(row) for row in matrix]
    prediction_counts = [sum(matrix[i][j] for i in range(4)) for j in range(4)]
    expected_weighted_difference = sum(abs(i - j) * reference_counts[i] * prediction_counts[j]
                                       for i in range(4) for j in range(4))
    if not n:
        kappa, kappa_reason = None, "No jointly rated Level 1–4 cases."
    elif not expected_weighted_difference:
        kappa, kappa_reason = None, "Expected disagreement is zero because both raters use the same single level."
    else:
        kappa, kappa_reason = 1 - absolute_difference * n / expected_weighted_difference, None
    return {
        "status": "reference_pending" if not reference else ("complete" if prediction_keys == reference_keys == expected_keys else "incomplete"),
        "total_expected_cases": len(expected_keys),
        "n_expected": len(expected_keys),
        "submitted_prediction_cases": len(predicted),
        "submitted_reference_cases": len(reference),
        "paired_cases": len(shared),
        "jointly_rated_cases": n,
        "missing_prediction_pairs": _pairs(expected_keys - prediction_keys),
        "missing_reference_pairs": _pairs(expected_keys - reference_keys),
        "unexpected_prediction_pairs": _pairs(prediction_keys - expected_keys),
        "unexpected_reference_pairs": _pairs(reference_keys - expected_keys),
        "expected_case_coverage": {
            "prediction": _rate(len(prediction_keys & expected_keys), len(expected_keys)),
            "reference": _rate(len(reference_keys & expected_keys), len(expected_keys)),
            "paired": _rate(len(shared), len(expected_keys)),
            "jointly_rated": _rate(n, len(expected_keys)),
        },
        "exact_matches_over_expected": _rate(exact, len(expected_keys)),
        "prediction_insufficient_evidence": _rate(sum(predicted[key] is None for key in shared), len(shared)),
        "reference_insufficient_evidence": _rate(sum(reference[key] is None for key in shared), len(shared)),
        "evidence_sufficiency_confusion": {
            "rows": "reference", "columns": "prediction",
            "labels": ["scored", "insufficient_evidence"], "matrix": sufficiency_matrix,
            "denominator": len(shared),
        },
        "exact_agreement": _rate(exact, n),
        "within_one_level_agreement": _rate(within_one, n),
        "mean_absolute_error": {"value": absolute_difference / n if n else None, "denominator": n,
                                "undefined_reason": None if n else "No jointly rated Level 1–4 cases."},
        "level_confusion": {"rows": "reference", "columns": "prediction", "levels": [1, 2, 3, 4],
                            "matrix": matrix, "denominator": n},
        "weighted_cohens_kappa": {"value": kappa, "weighting": "linear", "denominator": n,
                                  "undefined_reason": kappa_reason},
    }
