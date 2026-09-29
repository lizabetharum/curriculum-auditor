"""Write content/responses.md, a readable copy of content/responses.json for labeling.

Run after editing responses.json. A test fails if the two drift apart.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render() -> str:
    responses = json.loads((ROOT / "content/responses.json").read_text())
    lines = ["# Student responses (synthetic)", "",
             "Written for this repository. Not real student work. The task text for each response is in "
             "`lesson-heights.md`.", ""]
    for r in responses:
        task = "Task A: The ramp" if r["task_section_id"].endswith("task-a-the-ramp") else "Task B: Something tall outside"
        lines += [f"## {r['id']} ({task})", "", r["student_work"], ""]
    return "\n".join(lines)


if __name__ == "__main__":
    (ROOT / "content/responses.md").write_text(render())
    print("Wrote content/responses.md")
