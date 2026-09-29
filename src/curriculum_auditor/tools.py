"""The five agent tools. Claude judges. Code verifies before accepting.

One Session holds the rubric, the curriculum, student responses, and what has
been accepted so far. The agent loop, the Tool Runner, and the MCP server all
call these same methods.

A rejected call raises ToolRejected with a list of fixes. The caller returns
that list to Claude as an error tool_result so Claude can correct and resubmit.
After MAX_REJECTIONS rejected submissions for one section or one response, that
item is marked needs_review and the run moves on.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from .evidence import quote_problem
from .mathcheck import check_answer as _check_answer
from .rubric import Rubric, StrictModel
from .segment import Curriculum
from .work import StudentResponse

MAX_REJECTIONS = 3
MAX_DESCRIPTOR_IDS = 8
MAX_EVIDENCE = 3
MAX_RATIONALE_CHARS = 400
CoverageStatus = Literal["supported", "not_evidenced", "needs_review"]


class ToolRejected(Exception):
    def __init__(self, summary: str, problems: list[str] | None = None, *, counted: bool = False):
        self.summary, self.problems, self.counted = summary, problems or [], counted
        super().__init__(self.message())

    def message(self) -> str:
        return json.dumps({"accepted": False, "summary": self.summary, "fix": self.problems}, indent=1)


class Quote(StrictModel):
    quote: str
    start: int
    end: int


class CoverageRow(StrictModel):
    skill_id: str
    status: CoverageStatus
    evidence: list[Quote]
    rationale: str


class ScoreRow(StrictModel):
    response_id: str
    skill_id: str
    status: Literal["scored", "insufficient_evidence"]
    level: int | None
    descriptor_id: str | None
    evidence: list[Quote]
    rationale: str


@dataclass
class SectionState:
    status: Literal["pending", "accepted", "needs_review"] = "pending"
    rejections: int = 0
    rows: list[CoverageRow] = field(default_factory=list)


@dataclass
class ResponseState:
    status: Literal["open", "needs_review"] = "open"
    rejections: int = 0


class Session:
    def __init__(self, rubric: Rubric, curriculum: Curriculum | None = None,
                 responses: list[StudentResponse] | None = None):
        self.rubric = rubric
        self.curriculum = curriculum
        self.sections: dict[str, SectionState] = {s.id: SectionState() for s in curriculum.sections} if curriculum else {}
        self.responses = {r.id: r for r in responses or []}
        self.response_states = {r: ResponseState() for r in self.responses}
        self.scores: dict[tuple[str, str], ScoreRow] = {}

    # ---- lookup tools -------------------------------------------------

    def list_competencies(self, outcome_id: str | None = None) -> dict[str, Any]:
        skills = [s for s in self.rubric.skills if outcome_id is None or s.outcome_id == outcome_id]
        if outcome_id is not None and not skills:
            outcomes = sorted({s.outcome_id for s in self.rubric.skills})
            raise ToolRejected(f"Unknown outcome_id '{outcome_id}'.", [f"Use one of: {', '.join(outcomes)}, or null for all."])
        return {"rubric": self.rubric.title, "skill_count": len(skills),
                "skills": [{"id": s.id, "name": s.name, "competency_id": s.competency_id,
                            "competency_name": s.competency_name, "outcome_id": s.outcome_id} for s in skills]}

    def get_descriptors(self, skill_ids: list[str]) -> dict[str, Any]:
        problems = []
        if not skill_ids:
            problems.append("Ask for at least one skill ID.")
        if len(skill_ids) > MAX_DESCRIPTOR_IDS:
            problems.append(f"Ask for at most {MAX_DESCRIPTOR_IDS} skill IDs per call. You asked for {len(skill_ids)}.")
        unknown = [i for i in skill_ids if self.rubric.skill(i) is None]
        if unknown:
            problems.append(f"Unknown skill IDs: {', '.join(unknown)}. Use list_competencies to see valid IDs.")
        if problems:
            raise ToolRejected("get_descriptors was not run.", problems)
        result = []
        for skill_id in dict.fromkeys(skill_ids):
            s = self.rubric.skill(skill_id)
            result.append({"id": s.id, "name": s.name, "description": s.description,
                           "levels": [{"descriptor_id": s.descriptor_id(int(n)), "level": int(n), "text": s.levels[n]}
                                      for n in sorted(s.levels)]})
        return {"skills": result}

    @staticmethod
    def check_answer(item: dict[str, Any]) -> dict[str, Any]:
        cleaned = {k: v for k, v in item.items() if v is not None}
        return _check_answer(cleaned)

    # ---- coverage -----------------------------------------------------

    def submit_section_coverage(self, section_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if self.curriculum is None:
            raise ToolRejected("No curriculum is loaded.")
        section = self.curriculum.section(section_id)
        if section is None:
            raise ToolRejected(f"Unknown section_id '{section_id}'.",
                               [f"Valid IDs: {', '.join(s.id for s in self.curriculum.sections)}"])
        state = self.sections[section_id]
        if state.status == "accepted":
            raise ToolRejected(f"Section '{section_id}' is already accepted. Do not resubmit it.")
        if state.status == "needs_review":
            raise ToolRejected(f"Section '{section_id}' is marked needs_review after {MAX_REJECTIONS} rejected "
                               "submissions. Stop submitting it.")
        parsed, problems = self._validate_coverage(section.text, rows)
        if problems:
            state.rejections += 1
            if state.rejections >= MAX_REJECTIONS:
                state.status = "needs_review"
                raise ToolRejected(f"Rejected {MAX_REJECTIONS} times. Section '{section_id}' is now needs_review. "
                                   "Stop submitting it.", problems, counted=True)
            left = MAX_REJECTIONS - state.rejections
            raise ToolRejected(f"Rejected. Fix every item below and resubmit the full row list. "
                               f"{left} attempt(s) left.", problems, counted=True)
        state.status, state.rows = "accepted", parsed
        counts = {s: sum(r.status == s for r in parsed) for s in ("supported", "not_evidenced", "needs_review")}
        return {"accepted": True, "section_id": section_id, **counts}

    def _validate_coverage(self, text: str, rows: list[dict[str, Any]]) -> tuple[list[CoverageRow], list[str]]:
        problems: list[str] = []
        parsed: list[CoverageRow] = []
        seen: dict[str, int] = {}
        valid_ids = set(self.rubric.ids())
        for index, raw in enumerate(rows):
            try:
                row = CoverageRow.model_validate(raw)
            except ValueError:
                problems.append(f"Row {index + 1}: needs skill_id, status, evidence, and rationale in the documented shape.")
                continue
            seen[row.skill_id] = seen.get(row.skill_id, 0) + 1
            if row.skill_id not in valid_ids:
                continue
            label = row.skill_id
            if row.status == "supported" and not row.evidence:
                problems.append(f"{label}: supported needs at least one quote from this section.")
            if row.status == "not_evidenced" and row.evidence:
                problems.append(f"{label}: not_evidenced rows cannot carry quotes. Use supported or needs_review.")
            if len(row.evidence) > MAX_EVIDENCE:
                problems.append(f"{label}: give at most {MAX_EVIDENCE} quotes.")
            if row.status != "not_evidenced" and not row.rationale.strip():
                problems.append(f"{label}: give a one-sentence rationale.")
            if len(row.rationale) > MAX_RATIONALE_CHARS:
                problems.append(f"{label}: keep the rationale under {MAX_RATIONALE_CHARS} characters.")
            for n, q in enumerate(row.evidence[:MAX_EVIDENCE], 1):
                problem = quote_problem(text, q.quote, q.start, q.end, label=f"{label} quote {n}", source_name="section text")
                if problem:
                    problems.append(problem)
            parsed.append(row)
        unknown = sorted(i for i in seen if i not in valid_ids)
        duplicates = sorted(i for i, n in seen.items() if n > 1 and i in valid_ids)
        missing = [i for i in self.rubric.ids() if i not in seen]
        if unknown:
            problems.insert(0, f"Unknown skill IDs: {', '.join(unknown)}. Remove them.")
        if duplicates:
            problems.insert(0, f"Duplicate rows: {', '.join(duplicates)}. Give each skill exactly one row.")
        if missing:
            problems.insert(0, f"Missing rows for {len(missing)} skill(s): {', '.join(missing)}. "
                               "Every rubric skill needs one row, including not_evidenced.")
        return parsed, problems

    # ---- scoring ------------------------------------------------------

    def record_score(self, response_id: str, skill_id: str, status: str, level: int | None,
                     descriptor_id: str | None, evidence: list[dict[str, Any]], rationale: str) -> dict[str, Any]:
        response = self.responses.get(response_id)
        if response is None:
            raise ToolRejected(f"Unknown response_id '{response_id}'.", [f"Valid IDs: {', '.join(self.responses)}"])
        state = self.response_states[response_id]
        if state.status == "needs_review":
            raise ToolRejected(f"Response '{response_id}' is marked needs_review. Stop scoring it.")
        skill = self.rubric.skill(skill_id)
        if skill is None:
            raise ToolRejected(f"Unknown skill_id '{skill_id}'.")
        if skill_id not in self.scorable_skills(response_id):
            raise ToolRejected(f"{skill_id} is not supported by coverage for task '{response.task_section_id}'. "
                               f"Score only: {', '.join(self.scorable_skills(response_id)) or 'nothing'}.")
        if (response_id, skill_id) in self.scores:
            raise ToolRejected(f"A score for {response_id} on {skill_id} is already recorded.")
        problems: list[str] = []
        try:
            row = ScoreRow(response_id=response_id, skill_id=skill_id, status=status, level=level,
                           descriptor_id=descriptor_id, rationale=rationale,
                           evidence=[Quote.model_validate(q) for q in evidence])
        except ValueError:
            raise ToolRejected("Rejected. The arguments do not match the documented shape.", counted=False)
        if row.status == "scored":
            if row.level not in (1, 2, 3, 4):
                problems.append("A scored result needs a level from 1 to 4.")
            elif row.descriptor_id != skill.descriptor_id(row.level):
                problems.append(f"descriptor_id must be {skill.descriptor_id(row.level)} for level {row.level}.")
            if not row.evidence:
                problems.append("A scored result needs at least one quote from the student's work.")
        else:
            if row.level is not None or row.descriptor_id is not None:
                problems.append("insufficient_evidence must have level null and descriptor_id null. "
                                "Missing evidence is never Level 1.")
        if len(row.evidence) > MAX_EVIDENCE:
            problems.append(f"Give at most {MAX_EVIDENCE} quotes.")
        if not row.rationale.strip() or len(row.rationale) > MAX_RATIONALE_CHARS:
            problems.append(f"Give a rationale of 1 to {MAX_RATIONALE_CHARS} characters.")
        for n, q in enumerate(row.evidence[:MAX_EVIDENCE], 1):
            problem = quote_problem(response.student_work, q.quote, q.start, q.end,
                                    label=f"quote {n}", source_name="student's work")
            if problem and q.quote and q.quote in response.instructions:
                problem = (f"quote {n}: this text comes from the teacher's instructions, not the student's work. "
                           "Only the student's own words count as evidence.")
            if problem:
                problems.append(problem)
        if problems:
            state.rejections += 1
            if state.rejections >= MAX_REJECTIONS:
                state.status = "needs_review"
                raise ToolRejected(f"Rejected {MAX_REJECTIONS} times. Response '{response_id}' is now needs_review.",
                                   problems, counted=True)
            raise ToolRejected(f"Rejected. {MAX_REJECTIONS - state.rejections} attempt(s) left.", problems, counted=True)
        self.scores[(response_id, skill_id)] = row
        return {"accepted": True, "response_id": response_id, "skill_id": skill_id,
                "status": row.status, "level": row.level}

    def scorable_skills(self, response_id: str) -> list[str]:
        response = self.responses[response_id]
        state = self.sections.get(response.task_section_id)
        if state is None or state.status != "accepted":
            return []
        return [r.skill_id for r in state.rows if r.status == "supported"]


# ---- JSON schemas for strict tool use ------------------------------------
# Strict mode supports enum, anyOf, and null, but not min/max or length limits.
# Those limits are enforced in the methods above.

def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


_QUOTE = {"type": "object", "additionalProperties": False, "required": ["quote", "start", "end"],
          "properties": {"quote": {"type": "string", "description": "Exact text, character for character."},
                         "start": {"type": "integer", "description": "Zero-based offset of the first character."},
                         "end": {"type": "integer", "description": "Offset one past the last character."}}}


def _object(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "additionalProperties": False,
            "required": required if required is not None else list(properties), "properties": properties}


_TOLERANCES = {"absolute_tolerance": _nullable({"type": "string"}), "relative_tolerance": _nullable({"type": "string"})}
_ANSWER_ITEM = {"anyOf": [
    _object({"id": {"type": "string"}, "mode": {"type": "string", "enum": ["arithmetic"]},
             "expected": {"type": "string"}, "actual": {"type": "string"}}),
    _object({"id": {"type": "string"}, "mode": {"type": "string", "enum": ["equivalence"]},
             "expected": {"type": "string"}, "actual": {"type": "string"}, "variable": {"type": "string"}}),
    _object({"id": {"type": "string"}, "mode": {"type": "string", "enum": ["equation"]},
             "equation": {"type": "string"}, "actual": {"type": "array", "items": {"type": "string"}},
             "variable": {"type": "string"}}),
    _object({"id": {"type": "string"}, "mode": {"type": "string", "enum": ["numeric"]},
             "expected": {"type": "string"}, "actual": {"type": "string"},
             "unit": {"type": "string"}, "actual_unit": {"type": "string"},
             "angle_convention": _nullable({"type": "string", "enum": ["degrees", "radians"]}),
             **_TOLERANCES}),
]}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {"name": "list_competencies",
     "description": ("List skill IDs and short names in the loaded rubric (XQ Competencies or the demo rubric). "
                     "No descriptor text. Pass an outcome_id to filter, or null for all."),
     "input_schema": _object({"outcome_id": _nullable({"type": "string"})})},
    {"name": "get_descriptors",
     "description": (f"Get the description and four level descriptors for up to {MAX_DESCRIPTOR_IDS} skill IDs. "
                     "Look up only the skills you need."),
     "input_schema": _object({"skill_ids": {"type": "array", "items": {"type": "string"}}})},
    {"name": "check_answer",
     "description": ("Check one answer-key item with deterministic code, never a model. Modes: arithmetic and "
                     "equivalence (exact rational), equation (rational roots), numeric (tolerance, supports sqrt, "
                     "pi, sin, cos, tan, asin, acos, atan). Trig needs angle_convention. Returns correct, "
                     "incorrect, unsupported, or indeterminate."),
     "input_schema": _object({"item": _ANSWER_ITEM})},
    {"name": "submit_section_coverage",
     "description": ("Submit coverage for one curriculum section. Give exactly one row for every rubric skill. "
                     "status: supported (the section gives students a real chance to practice or show the skill; "
                     "quote it), not_evidenced (no quotes), or needs_review (ambiguous). Quotes must be exact text "
                     "from this section with offsets relative to the section text. Code checks every row and "
                     f"returns a list of fixes if anything is wrong. After {MAX_REJECTIONS} rejections the section "
                     "is marked needs_review."),
     "input_schema": _object({"section_id": {"type": "string"},
                              "rows": {"type": "array", "items": _object({
                                  "skill_id": {"type": "string"},
                                  "status": {"type": "string", "enum": ["supported", "not_evidenced", "needs_review"]},
                                  "evidence": {"type": "array", "items": _QUOTE},
                                  "rationale": {"type": "string"}})}})},
    {"name": "record_score",
     "description": ("Record one level for one student response on one skill that coverage marked supported for "
                     "that task. scored needs a level 1-4, the matching descriptor_id, and quotes from the "
                     "student's work only, never the instructions. If the work does not show the skill, use "
                     "insufficient_evidence with level null and descriptor_id null. Missing evidence is never "
                     "Level 1."),
     "input_schema": _object({"response_id": {"type": "string"}, "skill_id": {"type": "string"},
                              "status": {"type": "string", "enum": ["scored", "insufficient_evidence"]},
                              "level": _nullable({"type": "integer", "enum": [1, 2, 3, 4]}),
                              "descriptor_id": _nullable({"type": "string"}),
                              "evidence": {"type": "array", "items": _QUOTE},
                              "rationale": {"type": "string"}})},
]


def dispatch(session: Session, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run a tool by name. Raises ToolRejected on a rejected call."""
    handlers = {"list_competencies": session.list_competencies, "get_descriptors": session.get_descriptors,
                "check_answer": session.check_answer, "submit_section_coverage": session.submit_section_coverage,
                "record_score": session.record_score}
    if name not in handlers:
        raise ToolRejected(f"Unknown tool '{name}'.")
    try:
        return handlers[name](**arguments)
    except TypeError as exc:
        raise ToolRejected(f"Arguments for {name} do not match its schema.", [str(exc)]) from exc
