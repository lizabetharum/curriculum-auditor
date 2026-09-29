import pytest

from curriculum_auditor.rubric import RubricError, load_demo, load_rubric, validate_rubric


def test_demo_rubric_loads_with_eight_skills():
    rubric = load_demo()
    assert rubric.kind == "demo" and len(rubric.skills) == 8
    assert rubric.skill("DEMO.2.b").descriptor_id(3) == "DEMO.2.b.3"
    assert rubric.skill("NOPE") is None


def test_edited_rubric_fails_hash_check():
    rubric = load_demo()
    rubric.skills[0].levels["1"] = "edited"
    with pytest.raises(RubricError, match="hash"):
        validate_rubric(rubric)


def test_unknown_rubric_name():
    with pytest.raises(RubricError):
        load_rubric("other")
