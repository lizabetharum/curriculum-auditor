"""A real stdio round trip through all eight MCP tools. Offline, demo rubric."""
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from helpers import LESSON, RESPONSES, quote
from curriculum_auditor.rubric import load_demo

EXPECTED_TOOLS = {"load_curriculum", "get_section", "coverage_report", "list_competencies", "get_descriptors",
                  "check_answer", "submit_section_coverage", "record_score"}


def payload(result):
    assert not result.is_error, result.content[0].text
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


def rows_for(text, supported):
    rows = []
    for skill_id in load_demo().ids():
        if skill_id in supported:
            rows.append({"skill_id": skill_id, "status": "supported", "evidence": [quote(text, supported[skill_id])],
                         "rationale": "The task asks for it."})
        else:
            rows.append({"skill_id": skill_id, "status": "not_evidenced", "evidence": [], "rationale": ""})
    return rows


def test_all_tools_over_stdio(tmp_path: Path):
    (tmp_path / "lesson.md").write_text(LESSON)
    (tmp_path / "responses.json").write_text(json.dumps([r.model_dump() for r in RESPONSES]))

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "curriculum_auditor.server"],
                                       cwd=str(tmp_path), env={**os.environ, "CURRICULUM_AUDITOR_ROOT": str(tmp_path)})
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                assert {t.name for t in tools} == EXPECTED_TOOLS

                math = payload(await session.call_tool("check_answer", {"item": {
                    "id": "q1", "mode": "numeric", "expected": "sin(30)", "actual": "0.5", "unit": "dimensionless",
                    "actual_unit": "dimensionless", "angle_convention": "radians", "absolute_tolerance": "0.001"}}))
                assert math["status"] == "incorrect" and math["warnings"]

                early = await session.call_tool("list_competencies", {})
                assert early.is_error and "load_curriculum first" in early.content[0].text

                outside = await session.call_tool("load_curriculum", {"curriculum_path": "../../etc/hosts", "rubric": "demo"})
                assert outside.is_error

                loaded = payload(await session.call_tool("load_curriculum", {
                    "curriculum_path": "lesson.md", "rubric": "demo", "responses_path": "responses.json"}))
                assert [s["id"] for s in loaded["sections"]] == ["ramp-task", "reflection"]
                assert payload(await session.call_tool("list_competencies", {}))["skill_count"] == 8
                descriptors = payload(await session.call_tool("get_descriptors", {"skill_ids": ["DEMO.2.b"]}))
                assert len(descriptors["skills"][0]["levels"]) == 4

                ramp = payload(await session.call_tool("get_section", {"section_id": "ramp-task"}))
                bad = await session.call_tool("submit_section_coverage", {"section_id": "ramp-task", "rows": []})
                assert bad.is_error and "Missing rows for 8" in bad.content[0].text
                good_rows = rows_for(ramp["text"], {"DEMO.2.b": "use a trig ratio to find the height"})
                assert payload(await session.call_tool("submit_section_coverage", {
                    "section_id": "ramp-task", "rows": good_rows}))["accepted"]
                reflection = payload(await session.call_tool("get_section", {"section_id": "reflection"}))
                payload(await session.call_tool("submit_section_coverage", {
                    "section_id": "reflection", "rows": rows_for(reflection["text"], {})}))

                work = RESPONSES[0].student_work
                scored = payload(await session.call_tool("record_score", {
                    "response_id": "r1", "skill_id": "DEMO.2.b", "status": "scored", "level": 3,
                    "descriptor_id": "DEMO.2.b.3", "evidence": [quote(work, "sin(12) = h/5")],
                    "rationale": "Correct ratio, solved for h."}))
                assert scored["accepted"]

                report = payload(await session.call_tool("coverage_report", {"save": True}))
                assert report["complete"] and report["summary"]["supported"] == 1
                assert all(Path(p).exists() for p in report["saved_to"])

    asyncio.run(run())
