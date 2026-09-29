import pytest

from curriculum_auditor.agreement import compute_agreement


def row(work, level, skill="FL.MST.1.e"):
    return {"work_id": work, "subcompetency_id": skill, "level": level,
            "status": "insufficient_evidence" if level is None else "scored"}


def test_ordinal_metrics_and_linear_kappa_match_hand_calculation():
    references = [row(str(i), level) for i, level in enumerate([1, 2, 3, 4])]
    predictions = [row(str(i), level) for i, level in enumerate([1, 3, 3, 2])]
    result = compute_agreement(predictions, references)
    assert result["status"] == "complete"
    assert result["exact_agreement"] == {"count": 2, "denominator": 4, "rate": 0.5, "undefined_reason": None}
    assert result["within_one_level_agreement"]["rate"] == 0.75
    assert result["mean_absolute_error"]["value"] == 0.75
    # Observed distance = 3/4, expected distance = 18/16, so kappa = 1/3.
    assert result["weighted_cohens_kappa"]["value"] == pytest.approx(1 / 3)
    assert result["level_confusion"]["matrix"] == [[1, 0, 0, 0], [0, 0, 1, 0], [0, 0, 1, 0], [0, 1, 0, 0]]


def test_missing_evidence_is_separate_from_level_one_and_missing_cases():
    references = [row("a", 1), row("b", None), row("c", None), row("d", 2), row("missing", 3)]
    predictions = [row("a", None), row("b", 1), row("c", None), row("d", 2), row("extra", 4)]
    result = compute_agreement(predictions, references)
    assert result["status"] == "incomplete"
    assert result["total_expected_cases"] == 5
    assert result["paired_cases"] == 4
    assert result["jointly_rated_cases"] == 1
    assert result["prediction_insufficient_evidence"]["rate"] == 0.5
    assert result["reference_insufficient_evidence"]["rate"] == 0.5
    assert result["evidence_sufficiency_confusion"]["matrix"] == [[1, 1], [1, 1]]
    assert result["missing_prediction_pairs"][0]["work_id"] == "missing"
    assert result["unexpected_prediction_pairs"][0]["work_id"] == "extra"


def test_join_uses_both_identifiers_and_is_order_independent():
    references = [row("same", 1, "skill-a"), row("same", 4, "skill-b")]
    result = compute_agreement(list(reversed(references)), references)
    assert result["jointly_rated_cases"] == 2
    assert result["exact_agreement"]["rate"] == 1
    assert result["weighted_cohens_kappa"]["value"] == 1


def test_empty_reference_is_pending_with_no_fabricated_statistics():
    result = compute_agreement([row("a", 2)], [])
    assert result["status"] == "reference_pending"
    assert result["exact_agreement"]["rate"] is None
    assert result["weighted_cohens_kappa"]["value"] is None
    assert result["weighted_cohens_kappa"]["undefined_reason"]


def test_degenerate_and_abstention_only_kappa_are_undefined():
    result = compute_agreement([row("a", 2)], [row("a", 2)])
    assert result["exact_agreement"]["rate"] == 1
    assert result["weighted_cohens_kappa"]["value"] is None
    result = compute_agreement([row("a", None)], [row("a", None)])
    assert result["jointly_rated_cases"] == 0
    assert result["exact_agreement"]["rate"] is None
    assert result["mean_absolute_error"]["value"] is None
    assert result["evidence_sufficiency_confusion"]["matrix"] == [[0, 0], [0, 1]]


@pytest.mark.parametrize("side", ["prediction", "reference"])
def test_duplicate_pairs_are_rejected(side):
    duplicate = [row("a", 2), row("a", 3)]
    with pytest.raises(ValueError, match="Duplicate"):
        compute_agreement(duplicate if side == "prediction" else [], duplicate if side == "reference" else [])


@pytest.mark.parametrize("bad", [
    {"work_id": "a", "subcompetency_id": "b", "level": 0},
    {"work_id": "a", "subcompetency_id": "b", "level": 5},
    {"work_id": "a", "subcompetency_id": "b", "level": True},
    {"work_id": "a", "subcompetency_id": "b", "level": None},
    {"work_id": "a", "subcompetency_id": "b", "level": 1, "status": "insufficient_evidence"},
    {"work_id": "a", "level": 1},
])
def test_malformed_reference_ratings_are_rejected(bad):
    with pytest.raises(ValueError):
        compute_agreement([], [bad])


def test_plain_reference_levels_are_accepted():
    result = compute_agreement([row("a", 3)], [{"work_id": "a", "subcompetency_id": "FL.MST.1.e", "level": 3}])
    assert result["exact_agreement"]["rate"] == 1


def test_expected_manifest_retains_missing_reference_and_prediction_cases():
    manifest = [{"work_id": work, "subcompetency_id": "FL.MST.1.e"} for work in ("a", "b", "c", "d")]
    result = compute_agreement([row("a", 2), row("b", 3), row("extra", 4)],
                               [row("a", 2), row("c", 1)], expected_cases=manifest)
    assert result["n_expected"] == 4
    assert result["jointly_rated_cases"] == 1
    assert result["exact_agreement"]["rate"] == 1
    assert result["exact_matches_over_expected"]["denominator"] == 4
    assert result["exact_matches_over_expected"]["rate"] == 0.25
    assert [p["work_id"] for p in result["missing_reference_pairs"]] == ["b", "d"]
    assert [p["work_id"] for p in result["missing_prediction_pairs"]] == ["c", "d"]
    assert result["expected_case_coverage"]["reference"]["rate"] == 0.5
    assert result["expected_case_coverage"]["jointly_rated"]["rate"] == 0.25


def test_empty_references_with_manifest_stay_pending():
    manifest = [{"work_id": "a", "subcompetency_id": "FL.MST.1.e"}]
    result = compute_agreement([row("a", 3)], [], expected_cases=manifest)
    assert result["status"] == "reference_pending"
    assert result["n_expected"] == 1
    assert len(result["missing_reference_pairs"]) == 1
    assert result["exact_matches_over_expected"]["rate"] == 0


def test_expected_manifest_rejects_duplicates():
    case = {"work_id": "a", "subcompetency_id": "FL.MST.1.e"}
    with pytest.raises(ValueError, match="Duplicate expected"):
        compute_agreement([], [], expected_cases=[case, case])
