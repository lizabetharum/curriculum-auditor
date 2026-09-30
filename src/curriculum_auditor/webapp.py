"""The teacher web app: upload a lesson, check it against XQ, score student work.

How it stays inside Vercel's 5-minute request limit: the browser sends one
lesson section, or one student response, per request, and shows progress as
each finishes. The server keeps nothing between requests. Uploads and student
work are processed in memory, sent to the Claude API, and discarded.

Safeguards:
- A password (APP_PASSWORD) gates every request. With no password set, the
  app refuses all work.
- Each section, and each scoring run, has a spending limit
  (SECTION_BUDGET_USD, RESPONSE_BUDGET_USD, default $1 each).
- Each student response is scored three times, in parallel, and the most
  common result wins. When the runs disagree, the teacher is told to look.
  One run's score is not the final word, so the app does not rely on one.
- Scoring requires the teacher to confirm the work has no student names or
  identifying details and that they have permission to use it.
- XQ's framework is fetched and cached by the server. Responses carry skill IDs,
  short names, and quotes from the teacher's own text, never descriptor text.
"""
from __future__ import annotations

import os
import secrets
from hashlib import sha256
from importlib import resources
from typing import Any, Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import client as client_module
from .audit import run_coverage, run_scoring
from .client import BudgetExceeded, Meter
from .ingest import load_upload
from .rubric import Rubric, RubricError, load_demo
from .segment import Curriculum, SegmentError, Section
from .tools import CoverageRow, Session
from .work import StudentResponse

MAX_UPLOAD_BYTES = 4_000_000          # Vercel caps request bodies at 4.5 MB
MAX_SKILLS_PER_RESPONSE = 20
MAX_WORK_CHARS = 20_000
app = FastAPI(title="Curriculum Auditor", docs_url=None, redoc_url=None)
_rubrics: dict[str, Rubric] = {}


# ---- setup -------------------------------------------------------------------

def _budget(name: str) -> float:
    try:
        return float(os.environ.get(name, "1.0"))
    except ValueError:
        return 1.0


def check_password(given: str | None) -> None:
    expected = os.environ.get("APP_PASSWORD", "")
    if not expected:
        raise HTTPException(503, "The app has no password set, so it is switched off.")
    if not given or not secrets.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(401, "Wrong password.")


def get_rubric(name: str) -> Rubric:
    if name not in ("xq", "demo"):
        raise HTTPException(400, "Choose the XQ framework or the demo rubric.")
    if name not in _rubrics:
        if name == "demo":
            _rubrics[name] = load_demo()
        else:
            from .framework_fetch import SourceFormatError, fetch
            data_dir = os.environ.get("CURRICULUM_AUDITOR_DATA", "/tmp/curriculum-auditor-data")
            try:
                _rubrics[name], _ = fetch(data_dir)
            except SourceFormatError as exc:
                raise HTTPException(502, f"Could not load XQ Competencies: {exc}") from exc
    return _rubrics[name]


def new_client():
    """One Claude client per request. Tests replace this with a fake."""
    return client_module.make_client("live")


def _section(section: "SectionIn") -> Section:
    text = section.text
    return Section(id=section.id, heading=section.heading, level=1, start=0, end=len(text), text=text,
                   sha256=sha256(text.encode()).hexdigest())


def _one_section_curriculum(name: str, section: Section) -> Curriculum:
    return Curriculum(name=name, sha256=section.sha256, sections=[section])


def _rubric_info(rubric: Rubric) -> dict[str, Any]:
    outcomes: dict[str, dict[str, Any]] = {}
    for skill in rubric.skills:
        entry = outcomes.setdefault(skill.outcome_id, {"id": skill.outcome_id, "name": skill.outcome_name,
                                                       "skill_count": 0})
        entry["skill_count"] += 1
    return {"kind": rubric.kind, "title": rubric.title, "source_url": rubric.source_url,
            "skill_count": len(rubric.skills), "outcomes": list(outcomes.values())}


@app.middleware("http")
async def password_first(request, call_next):
    """Check the password before reading anything else in an /api/ request."""
    if request.url.path.startswith("/api/"):
        try:
            check_password(request.headers.get("x-app-password"))
        except HTTPException as exc:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return await call_next(request)


# ---- request shapes ----------------------------------------------------------

class SectionIn(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    heading: str = Field(max_length=300)
    text: str = Field(min_length=1, max_length=200_000)


class AuditIn(BaseModel):
    rubric: Literal["xq", "demo"] = "xq"
    lesson_name: str = Field(default="lesson", max_length=120)
    section: SectionIn


class ScoreIn(BaseModel):
    rubric: Literal["xq", "demo"] = "xq"
    task: SectionIn
    skill_ids: list[str] = Field(min_length=1, max_length=MAX_SKILLS_PER_RESPONSE)
    student_label: str = Field(pattern=r"^Student \d{1,3}$")
    work: str = Field(min_length=1, max_length=MAX_WORK_CHARS)
    consent: bool


# ---- routes ------------------------------------------------------------------

@app.get("/app", response_class=HTMLResponse)
def page() -> str:
    return resources.files("curriculum_auditor.web").joinpath("index.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def notebook_page():
    """The site's home page is the project notebook. The teacher app lives at /app."""
    notebook = resources.files("curriculum_auditor.web").joinpath("notebook.html")
    if notebook.is_file():
        return notebook.read_text(encoding="utf-8")
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/app")


@app.post("/api/lesson")
async def upload_lesson(file: UploadFile = File(...), rubric: str = Form("xq"),
                        x_app_password: str | None = Header(default=None)) -> dict[str, Any]:
    check_password(x_app_password)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "The file is larger than 4 MB.")
    try:
        ingested = load_upload(file.filename or "lesson", data)
    except (SegmentError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # a damaged Word or PDF file
        raise HTTPException(400, "This file could not be read. Try saving it again, or upload the Word version.") from exc
    info = _rubric_info(get_rubric(rubric))
    return {"name": ingested.curriculum.name, "note": ingested.note, "rubric": info,
            "sections": [{"id": s.id, "heading": s.heading, "text": s.text} for s in ingested.curriculum.sections]}


@app.post("/api/audit-section")
def audit_section(body: AuditIn, x_app_password: str | None = Header(default=None)) -> dict[str, Any]:
    check_password(x_app_password)
    rubric = get_rubric(body.rubric)
    section = _section(body.section)
    session = Session(rubric, _one_section_curriculum(body.lesson_name, section))
    meter = Meter(_budget("SECTION_BUDGET_USD"))
    try:
        report = run_coverage(new_client(), session, runner="tool_runner", backend="live", meter=meter,
                              progress=lambda _: None)
    except BudgetExceeded as exc:
        raise HTTPException(402, str(exc)) from exc
    state = report["curriculum"]["sections"][0]
    rows = [r for r in report["section_rows"].get(section.id, []) if r["status"] != "not_evidenced"]
    return {
        "section_id": section.id,
        "status": state["status"],
        "note": state["note"],
        "claude_notes": state["claude_notes"],
        "skills": [{"id": r["skill_id"], "name": rubric.skill(r["skill_id"]).name,
                    "competency": rubric.skill(r["skill_id"]).competency_name,
                    "outcome_id": rubric.skill(r["skill_id"]).outcome_id, "status": r["status"],
                    "quotes": [q["quote"] for q in r["evidence"]], "reason": r["rationale"]} for r in rows],
        "answer_checks": [c["result"] for c in report["answer_checks"]],
        "usd": round(meter.usd, 4),
    }


SCORING_RUNS = 3


def _label(row: dict[str, Any] | None) -> str | None:
    """One run's result for one skill: '1'-'4', 'IE' for too little to score, None if unscored."""
    if row is None:
        return None
    return "IE" if row["status"] == "insufficient_evidence" else str(row["level"])


def majority(labels: list[str | None]) -> tuple[str | None, str]:
    """The most common result across runs, and how much the runs agreed.

    agreed: every run gave the same result. majority: at least two runs agree,
    but not all. split: no two runs agree, or fewer than two runs scored it.
    """
    votes = [x for x in labels if x is not None]
    if not votes:
        return None, "split"
    top = max(set(votes), key=votes.count)
    count = votes.count(top)
    if count < 2:
        return None, "split"
    return top, ("agreed" if count == len(labels) else "majority")


def _score_once(body: "ScoreIn", rubric: Rubric, section: Section) -> tuple[dict[str, Any], float]:
    response = StudentResponse(id=body.student_label, task_section_id=section.id,
                               instructions=section.text, student_work=body.work)
    session = Session(rubric, _one_section_curriculum("task", section), [response])
    state = session.sections[section.id]
    state.status = "accepted"
    state.rows = [CoverageRow(skill_id=s, status="supported", evidence=[], rationale="Chosen by the teacher.")
                  for s in dict.fromkeys(body.skill_ids)]
    meter = Meter(_budget("RESPONSE_BUDGET_USD"))
    try:
        report = run_scoring(new_client(), session, runner="tool_runner", backend="live", meter=meter,
                             progress=lambda _: None)
    except BudgetExceeded:
        return {"rows": []}, meter.usd
    return report, meter.usd


@app.post("/api/score")
def score_response(body: ScoreIn, x_app_password: str | None = Header(default=None)) -> dict[str, Any]:
    check_password(x_app_password)
    if not body.consent:
        raise HTTPException(400, "Confirm the work has no student names or identifying details, "
                                 "and that you have permission to use it.")
    rubric = get_rubric(body.rubric)
    unknown = [s for s in body.skill_ids if rubric.skill(s) is None]
    if unknown:
        raise HTTPException(400, f"Unknown skill IDs: {', '.join(unknown)}")
    section = _section(body.task)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=SCORING_RUNS) as pool:
        runs = list(pool.map(lambda _: _score_once(body, rubric, section), range(SCORING_RUNS)))
    scores = []
    for skill_id in dict.fromkeys(body.skill_ids):
        rows = [next((r for r in report["rows"] if r["skill_id"] == skill_id), None) for report, _ in runs]
        labels = [_label(r) for r in rows]
        result, agreement = majority(labels)
        example = next((r for r, lab in zip(rows, labels) if r is not None and lab == result), None)
        scores.append({
            "skill_id": skill_id, "name": rubric.skill(skill_id).name,
            "result": result,                       # '1'-'4', 'IE', or None when a teacher should score
            "level": int(result) if result and result.isdigit() else None,
            "agreement": agreement, "runs": labels,
            "quotes": [q["quote"] for q in example["evidence"]] if example else [],
            "reason": example["rationale"] if example else "",
        })
    return {"student": body.student_label, "scores": scores, "runs": SCORING_RUNS,
            "usd": round(sum(usd for _, usd in runs), 4)}


@app.exception_handler(RubricError)
def rubric_error(_, exc: RubricError):
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": str(exc)}, status_code=502)
