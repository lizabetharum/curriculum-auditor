"""Roll section results up into one coverage report, and check reports back in.

Rules for each rubric skill:
- supported: at least one accepted section marked it supported, with quotes.
- needs_review: an accepted section marked it needs_review, or any section did
  not finish. An unfinished section might have held the evidence, so absence
  is not proven.
- not_evidenced: every section finished and none marked it supported or
  needs_review. This label has to be earned.

Every skill gets a row. The report carries the rubric and curriculum hashes, so
scoring can refuse a coverage report built from different inputs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .tools import CoverageRow, Session

REPORT_VERSION = "1"


class CoverageMismatch(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def coverage_report(session: Session) -> dict[str, Any]:
    if session.curriculum is None:
        raise ValueError("No curriculum is loaded.")
    unfinished = [sid for sid, st in session.sections.items() if st.status != "accepted"]
    skills = []
    for skill in session.rubric.skills:
        supported, flagged = [], []
        for section_id, state in session.sections.items():
            for row in state.rows:
                if row.skill_id != skill.id:
                    continue
                if row.status == "supported":
                    supported.append({"section_id": section_id, "evidence": [q.model_dump() for q in row.evidence],
                                      "rationale": row.rationale})
                elif row.status == "needs_review":
                    flagged.append(section_id)
        if supported:
            status, reason = "supported", f"Supported in {len(supported)} section(s)."
        elif flagged:
            status, reason = "needs_review", f"Marked needs_review in: {', '.join(flagged)}."
        elif unfinished:
            status, reason = "needs_review", f"Not found, but these sections did not finish: {', '.join(unfinished)}."
        else:
            status, reason = "not_evidenced", "Every section finished. None showed this skill."
        skills.append({"skill_id": skill.id, "name": skill.name, "status": status, "reason": reason,
                       "supported_in": supported, "needs_review_in": flagged})
    return {
        "report_type": "coverage", "report_version": REPORT_VERSION, "created_at": _now(),
        "rubric": {"kind": session.rubric.kind, "title": session.rubric.title,
                   "source_url": session.rubric.source_url, "content_sha256": session.rubric.content_sha256,
                   "skill_count": len(session.rubric.skills)},
        "curriculum": {"name": session.curriculum.name, "sha256": session.curriculum.sha256,
                       "sections": [{"id": s.id, "heading": s.heading, "sha256": s.sha256,
                                     "status": session.sections[s.id].status,
                                     "rejections": session.sections[s.id].rejections,
                                     "offset_corrections": session.sections[s.id].offset_corrections,
                                     "note": session.sections[s.id].note,
                                     "claude_notes": session.sections[s.id].claude_notes}
                                    for s in session.curriculum.sections]},
        "complete": not unfinished,
        "summary": {k: sum(s["status"] == k for s in skills) for k in ("supported", "not_evidenced", "needs_review")},
        "skills": skills,
        "section_rows": {sid: [r.model_dump() for r in st.rows] for sid, st in session.sections.items()},
    }


def load_coverage_report(session: Session, report: dict[str, Any]) -> None:
    """Restore accepted coverage into a session. Refuses mismatched inputs."""
    if session.curriculum is None:
        raise CoverageMismatch("Load the curriculum before loading a coverage report.")
    if report.get("report_type") != "coverage" or report.get("report_version") != REPORT_VERSION:
        raise CoverageMismatch("This file is not a coverage report from this version.")
    problems = []
    if report["rubric"]["content_sha256"] != session.rubric.content_sha256:
        problems.append("rubric hash differs (the report was built from a different rubric or snapshot)")
    if report["curriculum"]["sha256"] != session.curriculum.sha256:
        problems.append("curriculum hash differs (the curriculum was edited after the report was built)")
    if problems:
        raise CoverageMismatch("Coverage report does not match the loaded inputs: " + "; ".join(problems) + ".")
    by_id = {s["id"]: s for s in report["curriculum"]["sections"]}
    for section in session.curriculum.sections:
        saved = by_id.get(section.id)
        if saved is None or saved["sha256"] != section.sha256:
            raise CoverageMismatch(f"Section '{section.id}' does not match the report.")
        state = session.sections[section.id]
        state.status, state.rejections = saved["status"], saved["rejections"]
        state.offset_corrections, state.note = saved["offset_corrections"], saved["note"]
        state.claude_notes = saved["claude_notes"]
        state.rows = [CoverageRow.model_validate(r) for r in report["section_rows"].get(section.id, [])]


def score_report(session: Session, coverage: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every expected (response, skill) pair appears, as a score or as missing."""
    rows, missing = [], []
    for response_id, response in session.responses.items():
        for skill_id in session.scorable_skills(response_id):
            row = session.scores.get((response_id, skill_id))
            if row is None:
                missing.append({"response_id": response_id, "skill_id": skill_id,
                                "reason": "needs_review" if session.response_states[response_id].status == "needs_review"
                                else "not scored"})
            else:
                rows.append(row.model_dump())
    return {
        "report_type": "scores", "report_version": REPORT_VERSION, "created_at": _now(),
        "rubric": {"kind": session.rubric.kind, "title": session.rubric.title,
                   "source_url": session.rubric.source_url, "content_sha256": session.rubric.content_sha256},
        "curriculum_sha256": session.curriculum.sha256 if session.curriculum else None,
        "coverage_created_at": coverage.get("created_at") if coverage else None,
        "responses": {rid: {"status": st.status, "rejections": st.rejections,
                            "offset_corrections": st.offset_corrections}
                      for rid, st in session.response_states.items()},
        "rows": rows,
        "missing": missing,
        "summary": {"scored": sum(r["status"] == "scored" for r in rows),
                    "insufficient_evidence": sum(r["status"] == "insufficient_evidence" for r in rows),
                    "missing": len(missing)},
    }
