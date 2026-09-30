"""Agent layers against a scripted fake API: manual loop, Tool Runner, record, replay, budget."""
import json

import pytest
from anthropic import Anthropic, DefaultHttpxClient

from fake_claude import FakeClaude, transport
from helpers import RESPONSES
from curriculum_auditor import prompts
from curriculum_auditor.audit import run_coverage, run_scoring
from curriculum_auditor.client import Meter, make_client
from curriculum_auditor.replay import Recording, RecordingTransport, StaleRecordingError
from curriculum_auditor.rubric import load_demo
from curriculum_auditor.segment import segment_markdown
from curriculum_auditor.tools import Session

LESSON = """# Ramp task
A ramp rises at 12 degrees. Draw a labeled diagram, then use a trig ratio to find the height.

# Answer key
Height of a 12 m ramp at 30 degrees: 12*sin(30) = 6 m.

# Reflection
Explain in writing how you know your answer is reasonable.

# Notes
"""


def fresh():
    return Session(load_demo(), segment_markdown(LESSON, "ramp"), RESPONSES)


def client_for(fake, record_to=None):
    inner = transport(fake)
    t = RecordingTransport(Recording(record_to), inner=inner) if record_to else inner
    return Anthropic(api_key="test-key", max_retries=0, http_client=DefaultHttpxClient(transport=t))


def strip_times(report):
    report = json.loads(json.dumps(report))
    report.pop("created_at", None)
    return report


@pytest.mark.parametrize("runner", ["manual", "tool_runner"])
def test_coverage_run_end_to_end(runner):
    session = fresh()
    report = run_coverage(client_for(FakeClaude()), session, runner=runner, progress=lambda _: None)
    statuses = {s["id"]: s["status"] for s in report["curriculum"]["sections"]}
    assert statuses == {"ramp-task": "accepted", "answer-key": "accepted", "reflection": "accepted", "notes": "accepted"}
    assert report["complete"]
    skills = {k["skill_id"]: k["status"] for k in report["skills"]}
    assert skills["DEMO.2.b"] == "supported" and skills["DEMO.3.a"] == "supported"
    assert skills["DEMO.1.b"] == "not_evidenced"
    assert report["answer_checks"][0]["context"] == "answer-key"
    assert report["answer_checks"][0]["result"]["status"] == "correct"
    assert report["passes"]["ramp-task"]["turns"] == 2
    assert "notes" not in report["passes"]  # empty section, decided by code
    assert report["run"]["usage"]["calls"] == 6 and report["run"]["runner"] == runner


@pytest.mark.parametrize("runner", ["manual", "tool_runner"])
def test_rejection_is_fixed_and_counted(runner):
    report = run_coverage(client_for(FakeClaude({"missing_row_first"})), fresh(), runner=runner, progress=lambda _: None)
    assert report["passes"]["ramp-task"]["rejected_calls"] == 1
    assert report["curriculum"]["sections"][0]["rejections"] == 1 and report["complete"]


@pytest.mark.parametrize("runner", ["manual", "tool_runner"])
def test_one_reminder_when_claude_stops_early(runner):
    fake = FakeClaude({"text_only_first"})
    report = run_coverage(client_for(fake), fresh(), runner=runner, progress=lambda _: None)
    assert report["complete"]
    assert any(prompts.COVERAGE_NUDGE.split(" ")[0] in json.dumps(r["messages"]) for r in fake.requests)


def test_refusal_leaves_sections_unfinished():
    report = run_coverage(client_for(FakeClaude({"refuse"})), fresh(), runner="manual", progress=lambda _: None)
    assert not report["complete"]
    ramp = report["curriculum"]["sections"][0]
    assert ramp["status"] == "pending" and "refusal" in ramp["note"]
    assert {k["status"] for k in report["skills"]} == {"needs_review"}
    assert report["run"]["usage"]["refusals"] == 3


def test_budget_stops_the_run_and_nothing_is_called_absent():
    report = run_coverage(client_for(FakeClaude()), fresh(), runner="manual", meter=Meter(budget_usd=0.01),
                          progress=lambda _: None)
    assert report["run"]["stopped_early"].startswith("Spent $")
    assert report["summary"]["not_evidenced"] == 0


@pytest.mark.parametrize("runner", ["manual", "tool_runner"])
def test_record_then_replay_gives_the_same_report(tmp_path, runner):
    path = tmp_path / f"{runner}.json"
    live = run_coverage(client_for(FakeClaude(), record_to=path), fresh(), runner=runner, progress=lambda _: None)
    saved = json.loads(path.read_text())
    assert len(saved["entries"]) == 6 and "test-key" not in path.read_text()
    replayed = run_coverage(make_client("replay", recording=path), fresh(), runner=runner, progress=lambda _: None)
    for report in (live, replayed):
        report.pop("run")
    assert strip_times(live) == strip_times(replayed)


def test_changed_prompt_makes_the_recording_stale(tmp_path, monkeypatch):
    path = tmp_path / "rec.json"
    run_coverage(client_for(FakeClaude(), record_to=path), fresh(), runner="manual", progress=lambda _: None)
    monkeypatch.setattr(prompts, "COVERAGE_SYSTEM", prompts.COVERAGE_SYSTEM.replace("real chance", "clear chance"))
    with pytest.raises(StaleRecordingError, match="stale.*system"):
        run_coverage(make_client("replay", recording=path), fresh(), runner="manual", progress=lambda _: None)


def test_replay_never_falls_back_when_the_recording_is_missing(tmp_path):
    with pytest.raises(StaleRecordingError, match="No recording"):
        make_client("replay", recording=tmp_path / "nope.json")


def test_live_without_a_key_explains_what_to_do(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match=r"\.env"):
        make_client("live", env_file=tmp_path / ".env")


@pytest.mark.parametrize("runner", ["manual", "tool_runner"])
def test_scoring_run_end_to_end(runner):
    session = fresh()
    run_coverage(client_for(FakeClaude()), session, runner=runner, progress=lambda _: None)
    report = run_scoring(client_for(FakeClaude()), session, runner=runner, progress=lambda _: None)
    assert report["summary"] == {"scored": 2, "insufficient_evidence": 2, "missing": 0}
    levels = {(r["response_id"], r["skill_id"]): r["level"] for r in report["rows"]}
    assert levels[("r1", "DEMO.2.b")] == 3 and levels[("r2", "DEMO.2.b")] is None


def test_claude_notes_reach_the_report(tmp_path):
    lesson = LESSON.replace("12*sin(30) = 6 m.", "12*sin(30) = 6 m. Kite: 40*cos(55) = 22.94 m.")
    session = Session(load_demo(), segment_markdown(lesson, "ramp"), RESPONSES)
    report = run_coverage(client_for(FakeClaude()), session, runner="manual", progress=lambda _: None)
    notes = {s["id"]: s["claude_notes"] for s in report["curriculum"]["sections"]}
    assert notes["answer-key"] == "Exit ticket uses cos. The height needs sin."
    from curriculum_auditor.reports import render_markdown
    assert "Notes from Claude for teacher review" in render_markdown(report)
