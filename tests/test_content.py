"""The committed test content stays consistent with itself and with the code."""
import csv
import importlib.util
import json
from pathlib import Path

from curriculum_auditor.mathcheck import check_answer_key
from curriculum_auditor.segment import load_curriculum
from curriculum_auditor.work import load_responses

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "content"
TASK_A = "measuring-heights-you-cannot-reach/task-a-the-ramp"
TASK_B = "measuring-heights-you-cannot-reach/task-b-something-tall-outside"


def test_answer_key_catches_two_planted_errors_and_misses_the_setup_error():
    results = {r["id"]: r["status"] for r in check_answer_key(json.loads((CONTENT / "answer-key.json").read_text()))["results"]}
    assert results == {"A3 stage height": "correct", "A4 flat distance": "correct", "A4 Pythagorean check": "correct",
                       "B4 height, example data": "incorrect", "B extension height": "incorrect",
                       "Exit ticket kite height": "correct"}


def test_responses_point_at_real_task_sections():
    lesson = load_curriculum(CONTENT / "lesson-heights.md")
    responses = load_responses(CONTENT / "responses.json")
    assert len(responses) == 16
    for r in responses:
        section = lesson.section(r.task_section_id)
        assert section is not None
        assert r.instructions in section.text
    assert sum(r.task_section_id == TASK_A for r in responses) == 8


def test_one_response_copies_the_instructions():
    # r13 restates the task. A score may not quote that part as the student's evidence.
    r13 = next(r for r in load_responses(CONTENT / "responses.json") if r.id == "r13")
    assert "Measure the distance from your feet to the base" in r13.student_work


def test_label_sheet_covers_every_pair_once_and_is_blank():
    rows = list(csv.DictReader((ROOT / "labels/xq-labels.csv").open()))
    assert len(rows) == 32 and len({(r["response_id"], r["skill_id"]) for r in rows}) == 32
    assert {r["skill_id"] for r in rows} == {"FL.MST.2.a", "FL.MST.1.e", "FL.ID.3.b", "FL.MST.2.c"}
    assert all(r["level"] in ("", "1", "2", "3", "4", "IE") for r in rows)


def test_readable_copy_matches_the_json():
    spec = importlib.util.spec_from_file_location("render", ROOT / "scripts/render_responses.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (CONTENT / "responses.md").read_text() == module.render()


def test_target_hash_is_committed():
    digest, name = (CONTENT / "targets.sha256").read_text().split()
    assert len(digest) == 64 and name == "data/targets.json"
