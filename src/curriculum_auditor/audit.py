"""The orchestrator. Code decides the order of work. Claude judges one item at a time.

Coverage: code loops over the sections. Each section gets its own agent pass
with a fresh conversation, so one long section cannot crowd out the others and
a failure stays contained to one section.

Scoring: code loops over the student responses. Each response gets its own pass
and scores only the skills coverage marked supported for that response's task.

When the budget runs out, the run stops, and every unfinished item is reported
as unfinished. Absence is never inferred from work that did not run.
"""
from __future__ import annotations

from typing import Any, Callable, Literal

from anthropic import Anthropic

from . import prompts
from .agent import run_tool_runner
from .client import EFFORT, MODEL, BudgetExceeded, Meter
from .loop import LoopResult, run_manual_loop
from .rollup import coverage_report, score_report
from .tools import Session

Runner = Literal["manual", "tool_runner"]
RUNNERS = {"manual": run_manual_loop, "tool_runner": run_tool_runner}


def _is_empty(text: str) -> bool:
    lines = text.splitlines()
    body = lines[1:] if lines and lines[0].lstrip().startswith("#") else lines
    return not "".join(body).strip()


def _run_info(runner: Runner, backend: str, meter: Meter, stopped: str | None) -> dict[str, Any]:
    return {"model": MODEL, "effort": EFFORT, "runner": runner, "backend": backend,
            "stopped_early": stopped, "usage": meter.summary()}


def run_coverage(client: Anthropic, session: Session, *, runner: Runner = "tool_runner", backend: str = "replay",
                 meter: Meter | None = None, progress: Callable[[str], None] = print) -> dict[str, Any]:
    meter = meter or Meter()
    loop = RUNNERS[runner]
    system = prompts.coverage_system(session.rubric)
    stopped = None
    passes: dict[str, dict[str, Any]] = {}
    for section in session.curriculum.sections:
        state = session.sections[section.id]
        if state.status != "pending":
            continue
        if _is_empty(section.text):
            session.accept_empty_section(section.id)
            progress(f"{section.id}: empty, marked not_evidenced by code")
            continue
        session.context = section.id
        try:
            result: LoopResult = loop(client, session, system=system, user=prompts.coverage_message(section),
                                      meter=meter, done=lambda sid=section.id: session.sections[sid].status != "pending",
                                      nudge=prompts.COVERAGE_NUDGE.format(section_id=section.id))
        except BudgetExceeded as exc:
            stopped = str(exc)
            progress(stopped)
            break
        if state.status == "pending":
            state.note = f"No accepted submission (agent stopped: {result.stop})."
        passes[section.id] = {"turns": result.turns, "tool_calls": result.tool_calls,
                              "rejected_calls": result.rejected_calls, "stop": result.stop}
        progress(f"{section.id}: {state.status} after {result.turns} turn(s), "
                 f"{result.rejected_calls} rejected call(s), ${meter.usd:.2f} so far")
    session.context = None
    report = coverage_report(session)
    report["answer_checks"] = session.answer_checks
    report["passes"] = passes
    report["run"] = _run_info(runner, backend, meter, stopped)
    return report


def run_scoring(client: Anthropic, session: Session, *, runner: Runner = "tool_runner", backend: str = "replay",
                meter: Meter | None = None, coverage: dict[str, Any] | None = None,
                progress: Callable[[str], None] = print) -> dict[str, Any]:
    meter = meter or Meter()
    loop = RUNNERS[runner]
    system = prompts.scoring_system(session.rubric)
    stopped = None
    passes: dict[str, dict[str, Any]] = {}
    for response_id, response in session.responses.items():
        skills = session.scorable_skills(response_id)
        if not skills:
            progress(f"{response_id}: no supported skills for task {response.task_section_id}, skipped")
            continue

        def remaining(rid: str = response_id, wanted: list[str] = skills) -> list[str]:
            return [s for s in wanted if (rid, s) not in session.scores]

        def finished(rid: str = response_id) -> bool:
            return not remaining() or session.response_states[rid].status == "needs_review"

        session.context = response_id
        try:
            result = loop(client, session, system=system,
                          user=prompts.scoring_message(response, session.rubric, skills), meter=meter,
                          done=finished,
                          nudge=prompts.SCORING_NUDGE.format(response_id=response_id, skills=", ".join(skills)))
        except BudgetExceeded as exc:
            stopped = str(exc)
            progress(stopped)
            break
        passes[response_id] = {"turns": result.turns, "tool_calls": result.tool_calls,
                               "rejected_calls": result.rejected_calls, "stop": result.stop}
        progress(f"{response_id}: {len(skills) - len(remaining())}/{len(skills)} scored after {result.turns} "
                 f"turn(s), ${meter.usd:.2f} so far")
    session.context = None
    report = score_report(session, coverage)
    report["passes"] = passes
    report["run"] = _run_info(runner, backend, meter, stopped)
    return report
