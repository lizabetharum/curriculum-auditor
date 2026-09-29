"""Claude judges, code verifies: every rejection path for the five tools."""
import json

import pytest

from helpers import all_rows, quote, session
from curriculum_auditor.tools import MAX_REJECTIONS, TOOL_DEFINITIONS, ToolRejected, dispatch

RAMP = {"DEMO.2.a": "Draw and label a diagram", "DEMO.2.b": "use a trig ratio to find the height"}


def rejected(fn, *args, **kwargs):
    with pytest.raises(ToolRejected) as info:
        fn(*args, **kwargs)
    return info.value


# ---- lookup ---------------------------------------------------------------

def test_list_and_descriptor_caps():
    s = session()
    assert s.list_competencies()["skill_count"] == 8
    assert s.list_competencies("DEMO")["skill_count"] == 8
    assert "Unknown outcome_id" in rejected(s.list_competencies, "ZZ").summary
    levels = s.get_descriptors(["DEMO.2.b"])["skills"][0]["levels"]
    assert [l["descriptor_id"] for l in levels] == ["DEMO.2.b.1", "DEMO.2.b.2", "DEMO.2.b.3", "DEMO.2.b.4"]
    assert "at most 8" in rejected(s.get_descriptors, ["DEMO.1.a"] * 9).problems[0]
    assert "Unknown skill IDs: NOPE" in rejected(s.get_descriptors, ["NOPE"]).problems[0]


def test_check_answer_tool_ignores_null_fields():
    s = session()
    result = s.check_answer({"id": "q", "mode": "numeric", "expected": "sin(30)", "actual": "0.5",
                             "unit": "dimensionless", "actual_unit": "dimensionless",
                             "angle_convention": "degrees", "absolute_tolerance": "0.001", "relative_tolerance": None})
    assert result["status"] == "correct"


# ---- coverage ---------------------------------------------------------------

def test_valid_coverage_is_accepted_once():
    s = session()
    result = s.submit_section_coverage("ramp-task", all_rows(s, "ramp-task", RAMP))
    assert result == {"accepted": True, "section_id": "ramp-task", "supported": 2, "not_evidenced": 6, "needs_review": 0}
    assert "already accepted" in rejected(s.submit_section_coverage, "ramp-task", all_rows(s, "ramp-task")).summary


def test_fabricated_quote_is_rejected():
    s = session()
    rows = all_rows(s, "ramp-task", RAMP)
    rows[3]["evidence"] = [{"quote": "Students compare three methods.", "start": 0, "end": 31}]
    error = rejected(s.submit_section_coverage, "ramp-task", rows)
    assert any("does not appear" in p for p in error.problems) and error.counted


def test_wrong_offsets_get_the_right_offsets_back():
    s = session()
    rows = all_rows(s, "ramp-task", RAMP)
    rows[3]["evidence"][0]["start"] += 1
    rows[3]["evidence"][0]["end"] += 1
    problem = rejected(s.submit_section_coverage, "ramp-task", rows).problems[0]
    text = s.curriculum.section("ramp-task").text
    good = quote(text, RAMP["DEMO.2.b"])
    assert f"appears at {good['start']}-{good['end']}" in problem


def test_quote_from_another_section_is_rejected():
    s = session()
    other = s.curriculum.section("reflection").text
    rows = all_rows(s, "ramp-task", RAMP)
    rows[0] = {"skill_id": "DEMO.1.a", "status": "supported", "rationale": "x",
               "evidence": [quote(other, "how you know your answer is reasonable")]}
    assert any("DEMO.1.a" in p and ("does not appear" in p or "outside" in p)
               for p in rejected(s.submit_section_coverage, "ramp-task", rows).problems)


def test_missing_duplicate_and_unknown_ids_are_listed():
    s = session()
    rows = all_rows(s, "ramp-task")
    rows = [r for r in rows if r["skill_id"] != "DEMO.3.c"]
    rows.append(dict(rows[0]))
    rows.append({"skill_id": "XQ.FAKE.1.a", "status": "not_evidenced", "evidence": [], "rationale": ""})
    problems = rejected(s.submit_section_coverage, "ramp-task", rows).problems
    assert problems[0].startswith("Missing rows for 1 skill(s): DEMO.3.c")
    assert problems[1].startswith("Duplicate rows: DEMO.1.a")
    assert problems[2].startswith("Unknown skill IDs: XQ.FAKE.1.a")


def test_status_evidence_rules():
    s = session()
    rows = all_rows(s, "ramp-task")
    rows[0].update(status="supported")
    rows[1].update(evidence=[quote(s.curriculum.section("ramp-task").text, "ramp")])
    problems = rejected(s.submit_section_coverage, "ramp-task", rows).problems
    assert any("supported needs at least one quote" in p for p in problems)
    assert any("not_evidenced rows cannot carry quotes" in p for p in problems)


def test_three_rejections_mark_section_needs_review():
    s = session()
    bad = all_rows(s, "ramp-task")[:-1]
    for attempt in range(1, MAX_REJECTIONS + 1):
        error = rejected(s.submit_section_coverage, "ramp-task", bad)
    assert "now needs_review" in error.summary
    assert s.sections["ramp-task"].status == "needs_review"
    assert "Stop submitting" in rejected(s.submit_section_coverage, "ramp-task", all_rows(s, "ramp-task")).summary


def test_unknown_section_is_not_counted():
    s = session()
    error = rejected(s.submit_section_coverage, "nope", [])
    assert not error.counted and "ramp-task" in error.problems[0]


# ---- scoring ----------------------------------------------------------------

def scored_session():
    s = session()
    s.submit_section_coverage("ramp-task", all_rows(s, "ramp-task", RAMP))
    return s


def score(s, response_id="r1", skill_id="DEMO.2.b", status="scored", level=3, descriptor_id="DEMO.2.b.3",
          snippet="sin(12) = h/5", rationale="Correct ratio, solved."):
    work = s.responses[response_id].student_work
    evidence = [quote(work, snippet)] if snippet else []
    return s.record_score(response_id, skill_id, status, level, descriptor_id, evidence, rationale)


def test_valid_score_is_accepted_once():
    s = scored_session()
    assert score(s)["accepted"]
    assert "already recorded" in rejected(score, s).summary


def test_quote_from_teacher_instructions_is_rejected():
    s = scored_session()
    instructions = s.responses["r1"].instructions
    snippet = "use a trig ratio to find the height"
    start = instructions.index(snippet)
    error = rejected(s.record_score, "r1", "DEMO.2.b", "scored", 3, "DEMO.2.b.3",
                     [{"quote": snippet, "start": start, "end": start + len(snippet)}], "x")
    assert "teacher's instructions" in error.problems[0]


def test_missing_evidence_is_never_level_1():
    s = scored_session()
    problems = rejected(s.record_score, "r2", "DEMO.2.b", "insufficient_evidence", 1, "DEMO.2.b.1", [], "No work.").problems
    assert "never Level 1" in problems[0]
    assert s.record_score("r2", "DEMO.2.b", "insufficient_evidence", None, None, [], "Only a number.")["level"] is None


def test_scored_needs_evidence_and_matching_descriptor():
    s = scored_session()
    problems = rejected(score, s, descriptor_id="DEMO.2.b.4", snippet=None).problems
    assert any("descriptor_id must be DEMO.2.b.3" in p for p in problems)
    assert any("at least one quote" in p for p in problems)


def test_only_skills_supported_for_the_task_can_be_scored():
    s = scored_session()
    assert "not supported by coverage" in rejected(score, s, skill_id="DEMO.3.a", descriptor_id="DEMO.3.a.3").summary


def test_no_scoring_before_coverage():
    s = session()
    assert "Score only: nothing" in rejected(score, s).summary


# ---- schemas and dispatch -----------------------------------------------------

def _walk(schema):
    yield schema
    for value in schema.values():
        if isinstance(value, dict):
            yield from _walk(value)
        if isinstance(value, list):
            for v in value:
                if isinstance(v, dict):
                    yield from _walk(v)


def test_schemas_are_strict_compatible():
    for tool in TOOL_DEFINITIONS:
        for node in _walk(tool["input_schema"]):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for banned in ("minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"):
                assert banned not in node


def test_dispatch_rejects_bad_arguments():
    s = session()
    assert "do not match" in rejected(dispatch, s, "get_descriptors", {"wrong": 1}).summary
    assert json.loads(ToolRejected("x", ["y"]).message()) == {"accepted": False, "summary": "x", "fix": ["y"]}
