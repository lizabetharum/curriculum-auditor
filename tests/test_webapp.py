"""The teacher web app, end to end against the scripted fake API. No key, no network."""
import pytest
from anthropic import Anthropic, DefaultHttpxClient
from fastapi.testclient import TestClient

from fake_claude import FakeClaude, transport
from test_agent import LESSON
from curriculum_auditor import webapp

PW = {"x-app-password": "open sesame"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "open sesame")
    monkeypatch.setattr(webapp, "new_client", lambda: Anthropic(
        api_key="test", max_retries=0, http_client=DefaultHttpxClient(transport=transport(FakeClaude()))))
    return TestClient(webapp.app)


def upload(client):
    r = client.post("/api/lesson", headers=PW, data={"rubric": "demo"},
                    files={"file": ("ramp.md", LESSON.encode(), "text/markdown")})
    assert r.status_code == 200, r.text
    return r.json()


def test_page_loads_without_a_password(client):
    r = client.get("/app")
    assert r.status_code == 200 and "Upload a lesson" in r.text and "Nothing is saved on this site" in r.text


def test_every_api_call_needs_the_password(client, monkeypatch):
    assert client.post("/api/audit-section", json={}).status_code == 401
    assert client.post("/api/lesson", headers={"x-app-password": "wrong"}, data={"rubric": "demo"},
                       files={"file": ("a.md", b"# A\nx", "text/markdown")}).status_code == 401
    monkeypatch.delenv("APP_PASSWORD")
    assert client.post("/api/lesson", headers=PW, data={"rubric": "demo"},
                       files={"file": ("a.md", b"# A\nx", "text/markdown")}).status_code == 503


def test_upload_returns_sections(client):
    lesson = upload(client)
    assert [s["heading"] for s in lesson["sections"]] == ["Ramp task", "Answer key", "Reflection", "Notes"]
    assert lesson["rubric"]["kind"] == "demo" and lesson["note"] is None


def test_audit_one_section_returns_skills_quotes_and_answer_checks(client):
    lesson = upload(client)
    ramp = lesson["sections"][0]
    r = client.post("/api/audit-section", headers=PW, json={"rubric": "demo", "lesson_name": "ramp", "section": ramp})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "accepted"
    names = {s["id"]: s for s in body["skills"]}
    assert names["DEMO.2.b"]["quotes"] == ["trig ratio"] and names["DEMO.2.b"]["name"] == "Sets up a trig ratio"
    key = client.post("/api/audit-section", headers=PW,
                      json={"rubric": "demo", "lesson_name": "ramp", "section": lesson["sections"][1]}).json()
    assert key["answer_checks"][0]["status"] == "correct"


def test_audit_never_returns_descriptor_text(client):
    from curriculum_auditor.rubric import load_demo
    lesson = upload(client)
    text = client.post("/api/audit-section", headers=PW,
                       json={"rubric": "demo", "section": lesson["sections"][0]}).text
    for skill in load_demo().skills:
        assert skill.description not in text and all(v not in text for v in skill.levels.values())


def test_scoring_requires_consent_and_scores_a_response(client):
    lesson = upload(client)
    body = {"rubric": "demo", "task": lesson["sections"][0], "skill_ids": ["DEMO.2.b"],
            "student_label": "Student 1", "work": "I drew the ramp. sin(12) = h/5, so h = 1.04 m.", "consent": False}
    assert client.post("/api/score", headers=PW, json=body).status_code == 400
    body["consent"] = True
    r = client.post("/api/score", headers=PW, json=body)
    assert r.status_code == 200, r.text
    score = r.json()["scores"][0]
    assert score["skill_id"] == "DEMO.2.b" and score["level"] == 3 and score["quotes"]
    assert score["runs"] == ["3", "3", "3"] and score["agreement"] == "agreed"


def test_scoring_rejects_names_as_labels_and_unknown_skills(client):
    lesson = upload(client)
    body = {"rubric": "demo", "task": lesson["sections"][0], "skill_ids": ["DEMO.2.b"],
            "student_label": "Maria Lopez", "work": "x", "consent": True}
    assert client.post("/api/score", headers=PW, json=body).status_code == 422
    body.update(student_label="Student 2", skill_ids=["NOPE.1"])
    assert client.post("/api/score", headers=PW, json=body).status_code == 400


def test_budget_stop_is_reported(client, monkeypatch):
    monkeypatch.setenv("SECTION_BUDGET_USD", "0.001")
    lesson = upload(client)
    r = client.post("/api/audit-section", headers=PW, json={"rubric": "demo", "section": lesson["sections"][0]})
    assert r.status_code == 200 and r.json()["status"] == "pending"


def test_home_is_the_notebook_or_redirects_to_the_app(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (200, 307)


@pytest.mark.parametrize("labels,result,agreement", [
    (["3", "3", "3"], "3", "agreed"),
    (["3", "3", "2"], "3", "majority"),
    (["IE", "IE", "1"], "IE", "majority"),
    (["3", "2", "1"], None, "split"),
    (["3", None, "2"], None, "split"),
    (["4", "4", None], "4", "majority"),
    ([None, None, None], None, "split"),
])
def test_majority_rule(labels, result, agreement):
    assert webapp.majority(labels) == (result, agreement)


def test_disagreeing_runs_are_flagged(client, monkeypatch):
    import itertools
    behaviors = itertools.cycle([set(), set(), {"level=2"}])
    monkeypatch.setattr(webapp, "new_client", lambda: Anthropic(
        api_key="test", max_retries=0, http_client=DefaultHttpxClient(transport=transport(FakeClaude(next(behaviors))))))
    monkeypatch.setattr(webapp, "SCORING_RUNS", 3)
    lesson = upload(client)
    body = {"rubric": "demo", "task": lesson["sections"][0], "skill_ids": ["DEMO.2.b"],
            "student_label": "Student 1", "work": "I drew the ramp. sin(12) = h/5, so h = 1.04 m.", "consent": True}
    score = client.post("/api/score", headers=PW, json=body).json()["scores"][0]
    assert sorted(score["runs"]) == ["2", "3", "3"]
    assert score["result"] == "3" and score["agreement"] == "majority"
