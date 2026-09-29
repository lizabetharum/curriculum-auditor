"""Synthetic source-shaped data only. No XQ descriptor text is committed."""
import json
import pytest


@pytest.fixture
def page_payload():
    outcomes = []
    remaining = 115
    for oi, oid in enumerate(["FK", "FL", "GC", "LL", "OT"]):
        competencies = []
        for ci in range(8 if oi < 2 else 7):
            cid = f"{oid}.TEST.{ci + 1}"
            count = 4 if oi == 0 and ci < 4 else 3
            skills = []
            for si in range(count):
                sid = f"{cid}.{chr(97+si)}"
                skill = {"id": sid, "name": "Synthetic skill", "description": "Original synthetic parser fixture."}
                for level in range(1, 5):
                    skill[f"performanceLevel{level}Id"] = f"{sid}.{level}"
                    skill[f"performanceLevel{level}Description"] = f"<p>Synthetic test descriptor {sid}, level {level}.</p>"
                skills.append(skill)
            competencies.append({"id": cid, "name": "Synthetic competency", "subCompetencies": skills})
        outcomes.append({"id": oid, "name": "Synthetic outcome", "outcomeAreas": [{"name": "Synthetic area", "competencies": competencies}]})
    return {"props": {"learnerOutcomes": outcomes}, "buildId": "test-build"}


@pytest.fixture
def page_html(page_payload):
    return '<html><script type="application/json" id="__NEXT_DATA__">' + json.dumps(page_payload) + '</script></html>'
