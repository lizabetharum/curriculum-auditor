"""Roll-up rules, the hash chain into scoring, and never-overwrite reports."""
import json
from datetime import datetime, timezone

import pytest

from helpers import LESSON, RESPONSES, all_rows, quote, session
from curriculum_auditor import reports
from curriculum_auditor.rollup import CoverageMismatch, coverage_report, load_coverage_report, score_report
from curriculum_auditor.rubric import load_demo
from curriculum_auditor.segment import segment_markdown
from curriculum_auditor.tools import MAX_REJECTIONS, Session, ToolRejected

RAMP = {"DEMO.2.a": "Draw and label a diagram", "DEMO.2.b": "use a trig ratio to find the height"}
REFLECT = {"DEMO.3.a": "Explain in writing"}


def finished():
    s = session()
    s.submit_section_coverage("ramp-task", all_rows(s, "ramp-task", RAMP))
    s.submit_section_coverage("reflection", all_rows(s, "reflection", REFLECT))
    return s


def by_id(report):
    return {k["skill_id"]: k for k in report["skills"]}


def test_every_skill_gets_a_row_and_not_evidenced_is_earned():
    report = coverage_report(finished())
    assert report["complete"] and len(report["skills"]) == 8
    skills = by_id(report)
    assert skills["DEMO.2.b"]["status"] == "supported"
    assert skills["DEMO.3.a"]["supported_in"][0]["section_id"] == "reflection"
    assert skills["DEMO.1.a"]["status"] == "not_evidenced"
    assert report["summary"] == {"supported": 3, "not_evidenced": 5, "needs_review": 0}


def test_unfinished_section_turns_absence_into_needs_review():
    s = session()
    s.submit_section_coverage("ramp-task", all_rows(s, "ramp-task", RAMP))
    for _ in range(MAX_REJECTIONS):
        with pytest.raises(ToolRejected):
            s.submit_section_coverage("reflection", [])
    report = coverage_report(s)
    assert not report["complete"]
    assert by_id(report)["DEMO.1.a"]["status"] == "needs_review"
    assert "did not finish: reflection" in by_id(report)["DEMO.1.a"]["reason"]
    assert by_id(report)["DEMO.2.b"]["status"] == "supported"


def test_pending_section_also_blocks_not_evidenced():
    s = session()
    s.submit_section_coverage("ramp-task", all_rows(s, "ramp-task", RAMP))
    assert coverage_report(s)["summary"]["not_evidenced"] == 0


def test_needs_review_row_beats_absence():
    s = session()
    s.submit_section_coverage("ramp-task", all_rows(s, "ramp-task", RAMP))
    rows = all_rows(s, "reflection")
    rows[0].update(status="needs_review", rationale="Reasonableness is implied, not required.")
    s.submit_section_coverage("reflection", rows)
    assert by_id(coverage_report(s))["DEMO.1.a"]["status"] == "needs_review"


def test_coverage_round_trips_into_a_scoring_session():
    report = json.loads(json.dumps(coverage_report(finished())))
    fresh = session()
    load_coverage_report(fresh, report)
    assert fresh.scorable_skills("r1") == ["DEMO.2.a", "DEMO.2.b"]


def test_edited_curriculum_is_refused():
    report = coverage_report(finished())
    edited = Session(load_demo(), segment_markdown(LESSON.replace("12 degrees", "15 degrees"), "ramp"), RESPONSES)
    with pytest.raises(CoverageMismatch, match="curriculum hash differs"):
        load_coverage_report(edited, report)


def test_different_rubric_is_refused():
    report = coverage_report(finished())
    report["rubric"]["content_sha256"] = "0" * 64
    with pytest.raises(CoverageMismatch, match="rubric hash differs"):
        load_coverage_report(session(), report)


def test_score_report_lists_missing_pairs():
    s = finished()
    work = s.responses["r1"].student_work
    s.record_score("r1", "DEMO.2.b", "scored", 3, "DEMO.2.b.3", [quote(work, "sin(12) = h/5")], "Correct ratio.")
    report = score_report(s)
    assert report["summary"] == {"scored": 1, "insufficient_evidence": 0, "missing": 3}
    assert {"response_id": "r2", "skill_id": "DEMO.2.b", "reason": "not scored"} in report["missing"]


def test_reports_are_never_overwritten(tmp_path, monkeypatch):
    fixed = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(reports, "datetime", Frozen)
    report = coverage_report(finished())
    json_path, md_path = reports.write_report(report, tmp_path, "coverage")
    assert json.loads(json_path.read_text())["summary"]["supported"] == 3
    assert "| DEMO.2.b | Sets up a trig ratio | supported | ramp-task |" in md_path.read_text()
    with pytest.raises(FileExistsError):
        reports.write_report(report, tmp_path, "coverage")


def test_markdown_has_no_descriptor_text(tmp_path):
    rubric = load_demo()
    _, md_path = reports.write_report(coverage_report(finished()), tmp_path, "coverage")
    text = md_path.read_text()
    for skill in rubric.skills:
        assert skill.description not in text
        assert all(level not in text for level in skill.levels.values())
