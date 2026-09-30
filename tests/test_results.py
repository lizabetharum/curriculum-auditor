"""Agreement report: labels versus runs, consistency, and no descriptor text."""
import json

from curriculum_auditor import cli
from curriculum_auditor.reports import render_markdown
from curriculum_auditor.results import agreement_report
from curriculum_auditor.rubric import load_demo

RUBRIC = load_demo()


def run(levels, when="2026-09-30T00:00:00+00:00"):
    rows = [{"response_id": r, "skill_id": s, "level": lvl,
             "status": "insufficient_evidence" if lvl is None else "scored", "rationale": "secret rationale",
             "evidence": [], "descriptor_id": None} for (r, s), lvl in levels.items()]
    return {"rows": rows, "created_at": when, "curriculum_sha256": "c" * 64,
            "rubric": {"content_sha256": RUBRIC.content_sha256},
            "run": {"model": "claude-opus-5-5", "effort": "high", "usage": {"models": {"claude-opus-5-5": 1}, "usd_estimate": 1.0}}}


LABELS = [{"response_id": "r1", "skill_id": "DEMO.1.a", "level": 3, "status": "scored"},
          {"response_id": "r2", "skill_id": "DEMO.1.a", "level": 1, "status": "scored"},
          {"response_id": "r3", "skill_id": "DEMO.1.a", "level": None, "status": "insufficient_evidence"}]


def test_agreement_counts_levels_and_abstentions_apart():
    one = run({("r1", "DEMO.1.a"): 3, ("r2", "DEMO.1.a"): 2, ("r3", "DEMO.1.a"): 1, ("r9", "DEMO.2.a"): 4})
    report = agreement_report([one], LABELS, rubric=RUBRIC)
    a = report["agreement_with_labels"][0]
    assert a["jointly_rated_cases"] == 2 and a["exact_agreement"]["count"] == 1
    assert a["reference_insufficient_evidence"]["count"] == 1
    assert report["consistency"] is None and report["labeled_pairs"] == 3


def test_consistency_across_runs_and_missing_pairs():
    one = run({("r1", "DEMO.1.a"): 3, ("r2", "DEMO.1.a"): 2, ("r3", "DEMO.1.a"): None})
    two = run({("r1", "DEMO.1.a"): 3, ("r2", "DEMO.1.a"): 1})
    report = agreement_report([one, two], LABELS, rubric=RUBRIC)
    c = report["consistency"]
    assert c["pairs_in_every_run"] == 2 and c["identical_in_every_run"]["count"] == 1
    assert report["pairs"][2]["runs"] == [None, "missing"]


def test_report_holds_no_rationales_or_descriptor_text(tmp_path):
    report = agreement_report([run({("r1", "DEMO.1.a"): 3})], LABELS, rubric=RUBRIC)
    text = json.dumps(report) + render_markdown(report)
    assert "secret rationale" not in text
    for skill in RUBRIC.skills:
        assert skill.description not in text and all(v not in text for v in skill.levels.values())
    assert "not whether the scorer is accurate" in render_markdown(report)


def test_all_identical_levels_leave_kappa_undefined_with_a_reason():
    labels = [{"response_id": f"r{i}", "skill_id": "DEMO.1.a", "level": 2, "status": "scored"} for i in range(3)]
    report = agreement_report([run({(f"r{i}", "DEMO.1.a"): 2 for i in range(3)})], labels, rubric=RUBRIC)
    kappa = report["agreement_with_labels"][0]["weighted_cohens_kappa"]
    assert kappa["value"] is None and "same single level" in kappa["undefined_reason"]
    assert "undefined" in render_markdown(report)


def test_agreement_command_writes_a_report(tmp_path):
    scores = tmp_path / "scores.json"
    scores.write_text(json.dumps(run({("r1", "DEMO.1.a"): 3, ("r2", "DEMO.1.a"): 1})))
    labels = tmp_path / "labels.csv"
    labels.write_text("response_id,skill_id,skill_name,level\nr1,DEMO.1.a,x,3\nr2,DEMO.1.a,x,1\n")
    assert cli.main(["agreement", str(scores), "--labels", str(labels), "--rubric", "demo", "--out", str(tmp_path / "out")]) == 0
    assert len(list((tmp_path / "out").glob("agreement-demo-*.md"))) == 1


def test_ie_as_a_category_counts_every_paired_case():
    one = run({("r1", "DEMO.1.a"): 3, ("r2", "DEMO.1.a"): None, ("r3", "DEMO.1.a"): None})
    report = agreement_report([one], LABELS, rubric=RUBRIC)
    assert report["exact_with_ie_as_a_category"][0]["count"] == 2
    assert report["exact_with_ie_as_a_category"][0]["denominator"] == 3
    assert "IE treated as a fifth category" in render_markdown(report)
