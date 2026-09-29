"""Student responses. Instructions and student work are stored apart so a
score can only quote what the student wrote."""
from __future__ import annotations

import json
from pathlib import Path

from .rubric import StrictModel

MAX_RESPONSES = 100


class StudentResponse(StrictModel):
    id: str
    task_section_id: str
    instructions: str
    student_work: str


def load_responses(path: str | Path) -> list[StudentResponse]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not 0 < len(raw) <= MAX_RESPONSES:
        raise ValueError(f"The responses file must hold a list of 1 to {MAX_RESPONSES} responses.")
    responses = [StudentResponse.model_validate(r) for r in raw]
    ids = [r.id for r in responses]
    if len(ids) != len(set(ids)):
        raise ValueError("Response IDs must be unique.")
    if any(not r.student_work.strip() for r in responses):
        raise ValueError("Every response needs nonempty student_work.")
    return responses
