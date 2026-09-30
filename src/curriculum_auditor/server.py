"""MCP server. The same five tools the agent uses, plus three for working from
Claude Code: load_curriculum, get_section, and coverage_report.

No API key is needed. The MCP host (Claude Code, for example) is the model, so
Claude does the judging and this server does the verifying.

File access is limited to the directory the server starts in, or to
CURRICULUM_AUDITOR_ROOT if set. stdout is reserved for MCP messages.

Register it with Claude Code from the repo folder:
    claude mcp add curriculum-auditor -- uv run curriculum-auditor-mcp
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .rollup import CoverageMismatch, coverage_report as _coverage_report, load_coverage_report
from .reports import write_report
from .rubric import RubricError, load_rubric
from .segment import SegmentError, load_curriculum as _load_curriculum
from .tools import TOOL_DEFINITIONS, Session, ToolRejected, check_answer_item
from .work import load_responses

INSTRUCTIONS = """Audit a Markdown curriculum against XQ Competencies (or the offline demo rubric).
1. load_curriculum. 2. For each section: get_section, look up only the skills you need with
list_competencies and get_descriptors, then submit_section_coverage with one row per skill.
3. coverage_report. 4. To score student work, load responses and use record_score.
Quotes must be exact text with character offsets. Code checks every quote and ID."""

server = MCPServer("curriculum-auditor", instructions=INSTRUCTIONS)
_state: dict[str, Session | None] = {"session": None}
DESCRIPTIONS = {tool["name"]: tool["description"] for tool in TOOL_DEFINITIONS}


def _root() -> Path:
    return Path(os.environ.get("CURRICULUM_AUDITOR_ROOT", os.getcwd())).resolve()


def _inside_root(path: str) -> Path:
    root = _root()
    resolved = (root / path).resolve()
    if resolved != root and root not in resolved.parents:
        raise ToolError(f"{path} is outside the allowed folder {root}.")
    if not resolved.is_file():
        raise ToolError(f"No file at {path}.")
    return resolved


def _session() -> Session:
    session = _state["session"]
    if session is None:
        raise ToolError("No curriculum is loaded. Call load_curriculum first.")
    return session


def _run(fn, *args, **kwargs) -> dict[str, Any]:
    try:
        return fn(*args, **kwargs)
    except ToolRejected as exc:
        raise ToolError(exc.message()) from exc


@server.tool(description="Load a Markdown curriculum and pick the rubric: 'xq' (needs the local cache from "
                         "`curriculum-auditor fetch`) or 'demo'. Optionally load student responses (JSON) and a "
                         "saved coverage report. Starts a new session.")
def load_curriculum(curriculum_path: str, rubric: Literal["xq", "demo"] = "xq",
                    responses_path: str | None = None, coverage_report_path: str | None = None) -> dict[str, Any]:
    try:
        loaded_rubric = load_rubric(rubric, _root() / "data")
        curriculum = _load_curriculum(_inside_root(curriculum_path))
        responses = load_responses(_inside_root(responses_path)) if responses_path else None
        session = Session(loaded_rubric, curriculum, responses)
        if coverage_report_path:
            load_coverage_report(session, json.loads(_inside_root(coverage_report_path).read_text()))
    except (RubricError, SegmentError, CoverageMismatch, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    _state["session"] = session
    return {"rubric": loaded_rubric.title, "source_url": loaded_rubric.source_url,
            "skill_count": len(loaded_rubric.skills), "curriculum": curriculum.name,
            "sections": [{"id": s.id, "heading": s.heading, "chars": len(s.text)} for s in curriculum.sections],
            "responses": sorted(session.responses)}


@server.tool(description="Get one section's exact text. Quote offsets are relative to this text.")
def get_section(section_id: str) -> dict[str, Any]:
    session = _session()
    section = session.curriculum.section(section_id)
    if section is None:
        raise ToolError(f"Unknown section_id '{section_id}'.")
    return {"id": section.id, "heading": section.heading, "text": section.text, "sha256": section.sha256,
            "coverage_status": session.sections[section_id].status}


@server.tool(description="Roll up accepted sections into a coverage report. Set save=true to write JSON and "
                         "Markdown to reports/. Existing reports are never overwritten.")
def coverage_report(save: bool = False) -> dict[str, Any]:
    report = _coverage_report(_session())
    if save:
        json_path, md_path = write_report(report, _root() / "reports", "coverage")
        report["saved_to"] = [str(json_path), str(md_path)]
    return report


@server.tool(description=DESCRIPTIONS["list_competencies"])
def list_competencies(outcome_id: str | None = None) -> dict[str, Any]:
    return _run(_session().list_competencies, outcome_id)


@server.tool(description=DESCRIPTIONS["get_descriptors"])
def get_descriptors(skill_ids: list[str]) -> dict[str, Any]:
    return _run(_session().get_descriptors, skill_ids)


@server.tool(description=DESCRIPTIONS["check_answer"])
def check_answer(item: dict[str, Any]) -> dict[str, Any]:
    # Math needs no session, so this works before load_curriculum.
    return check_answer_item(item)


@server.tool(description=DESCRIPTIONS["submit_section_coverage"])
def submit_section_coverage(section_id: str, rows: list[dict[str, Any]], notes: str = "") -> dict[str, Any]:
    return _run(_session().submit_section_coverage, section_id, rows, notes)


@server.tool(description=DESCRIPTIONS["record_score"])
def record_score(response_id: str, skill_id: str, status: Literal["scored", "insufficient_evidence"],
                 level: int | None, descriptor_id: str | None, evidence: list[dict[str, Any]],
                 rationale: str) -> dict[str, Any]:
    return _run(_session().record_score, response_id, skill_id, status, level, descriptor_id, evidence, rationale)


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    server.run("stdio")


if __name__ == "__main__":
    main()
