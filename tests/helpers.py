"""Shared offline fixtures: demo rubric, a two-section lesson, two responses."""
from curriculum_auditor.rubric import load_demo
from curriculum_auditor.segment import segment_markdown
from curriculum_auditor.tools import Session
from curriculum_auditor.work import StudentResponse

LESSON = """# Ramp task
A ramp rises at 12 degrees. Draw and label a diagram, then use a trig ratio to find the height.

# Reflection
Explain in writing how you know your answer is reasonable.
"""

RESPONSES = [
    StudentResponse(id="r1", task_section_id="ramp-task",
                    instructions="Draw and label a diagram, then use a trig ratio to find the height.",
                    student_work="I drew the ramp as a right triangle. sin(12) = h/5, so h = 5*sin(12) = 1.04 m."),
    StudentResponse(id="r2", task_section_id="ramp-task",
                    instructions="Draw and label a diagram, then use a trig ratio to find the height.",
                    student_work="1.04"),
]


def session(with_responses=True):
    return Session(load_demo(), segment_markdown(LESSON, "ramp"), RESPONSES if with_responses else None)


def quote(text, snippet):
    start = text.index(snippet)
    return {"quote": snippet, "start": start, "end": start + len(snippet)}


def all_rows(s, section_id, supported=None, status="not_evidenced"):
    """One row per rubric skill. supported maps skill_id -> snippet from the section."""
    text = s.curriculum.section(section_id).text
    rows = []
    for skill_id in s.rubric.ids():
        if supported and skill_id in supported:
            rows.append({"skill_id": skill_id, "status": "supported",
                         "evidence": [quote(text, supported[skill_id])], "rationale": "The task asks for it."})
        else:
            rows.append({"skill_id": skill_id, "status": status, "evidence": [], "rationale": ""})
    return rows
