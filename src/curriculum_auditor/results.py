"""The agreement report: Claude's scores against one person's blind labels,
plus run-to-run consistency.

What this measures, and what it does not:
- Agreement with the labels shows how closely Claude's levels match one rater
  on 16 synthetic responses. It is a demonstration of the method. It is not
  evidence that the scorer is accurate on real student work.
- Consistency compares repeated runs of the same model on the same inputs. It
  measures stability, not validity. A scorer can be consistently wrong.
- No pass mark was set in advance, so none is applied here.

The report holds skill IDs, short names, and levels only. No descriptor text,
rationales, or quotes, so it can be committed without reproducing XQ's text.
"""
from __future__ import annotations

from datetime import datetime, timezone
from itertools import combinations
from typing import Any

from .agreement import compute_agreement

FRAMING = ("Method demonstration on 16 synthetic responses scored by one rater. Agreement shows how closely "
           "Claude matched that rater, not whether the scorer is accurate on real student work. Consistency "
           "compares repeated runs of the same model and measures stability, not validity. No pass mark was "
           "set in advance.")


def _rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"work_id": r["response_id"], "subcompetency_id": r["skill_id"], "level": r["level"],
             "status": r.get("status") or ("insufficient_evidence" if r["level"] is None else "scored")}
            for r in rows]


def _headline(result: dict[str, Any]) -> dict[str, Any]:
    keys = ("status", "paired_cases", "jointly_rated_cases", "exact_agreement", "within_one_level_agreement",
            "mean_absolute_error", "weighted_cohens_kappa", "prediction_insufficient_evidence",
            "reference_insufficient_evidence", "evidence_sufficiency_confusion", "level_confusion",
            "missing_prediction_pairs", "missing_reference_pairs")
    return {k: result[k] for k in keys}


def agreement_report(runs: list[dict[str, Any]], labels: list[dict[str, Any]], *,
                     rubric: Any, notes: dict[str, Any] | None = None) -> dict[str, Any]:
    """runs: score reports from `score`. labels: rows from the label CSV."""
    if not runs:
        raise ValueError("Give at least one score report.")
    label_rows = _rows(labels)
    expected = [{"work_id": r["work_id"], "subcompetency_id": r["subcompetency_id"]} for r in label_rows]
    wanted = {(r["work_id"], r["subcompetency_id"]) for r in label_rows}
    run_rows = [[r for r in _rows(run["rows"]) if (r["work_id"], r["subcompetency_id"]) in wanted] for run in runs]
    for run in runs:
        if run["rubric"]["content_sha256"] != rubric.content_sha256:
            raise ValueError("A score report was built from a different rubric snapshot than the one loaded.")

    vs_labels = [_headline(compute_agreement(rows, label_rows, expected_cases=expected)) for rows in run_rows]
    consistency = None
    if len(runs) > 1:
        pairwise = []
        for (i, a), (j, b) in combinations(enumerate(run_rows), 2):
            result = compute_agreement(a, b, expected_cases=expected)
            pairwise.append({"runs": [i + 1, j + 1], **_headline(result)})
        levels = [{(r["work_id"], r["subcompetency_id"]): r["level"] for r in rows} for rows in run_rows]
        in_all = [k for k in wanted if all(k in run for run in levels)]
        identical = sum(len({run[k] for run in levels}) == 1 for k in in_all)
        consistency = {"runs": len(runs), "pairs_in_every_run": len(in_all),
                       "identical_in_every_run": {"count": identical, "denominator": len(in_all),
                                                  "rate": identical / len(in_all) if in_all else None},
                       "pairwise": pairwise}

    label_index = {(r["work_id"], r["subcompetency_id"]): r["level"] for r in label_rows}
    run_index = [{(r["work_id"], r["subcompetency_id"]): r["level"] for r in rows} for rows in run_rows]
    table = []
    for key in sorted(wanted):
        table.append({"response_id": key[0], "skill_id": key[1], "skill_name": rubric.skill(key[1]).name,
                      "label": label_index[key],
                      "runs": [run.get(key, "missing") for run in run_index]})
    all_categories = []
    for run in run_index:
        paired = [k for k in wanted if k in run]
        same = sum(run[k] == label_index[k] for k in paired)
        all_categories.append({"count": same, "denominator": len(paired),
                               "rate": same / len(paired) if paired else None,
                               "undefined_reason": None if paired else "No paired cases."})
    first = runs[0]
    return {
        "report_type": "agreement", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "framing": FRAMING,
        "rubric": {"title": rubric.title, "source_url": rubric.source_url, "content_sha256": rubric.content_sha256},
        "curriculum_sha256": first.get("curriculum_sha256"),
        "model_runs": [{"run": i + 1, "created_at": run["created_at"], "model": run["run"]["model"],
                        "effort": run["run"]["effort"], "models_served": run["run"]["usage"]["models"],
                        "usd_estimate": run["run"]["usage"]["usd_estimate"]} for i, run in enumerate(runs)],
        "labeled_pairs": len(wanted),
        "agreement_with_labels": vs_labels,
        "exact_with_ie_as_a_category": all_categories,
        "consistency": consistency,
        "pairs": table,
        "notes": notes or {},
    }


def _pct(rate: dict[str, Any]) -> str:
    if rate.get("rate") is None:
        return f"undefined ({rate.get('undefined_reason') or 'no cases'})"
    return f"{rate['rate']:.0%} ({rate['count']}/{rate['denominator']})"


def _value(metric: dict[str, Any], digits: int = 2) -> str:
    if metric.get("value") is None:
        return f"undefined ({metric.get('undefined_reason')})"
    return f"{metric['value']:.{digits}f} (n = {metric['denominator']})"


def render_agreement(r: dict[str, Any]) -> str:
    lines = [f"# Agreement report: {r['rubric']['title']}", "", r["framing"], "",
             f"Rubric: {r['rubric']['title']} ({r['rubric']['source_url']}). Content hash "
             f"`{r['rubric']['content_sha256'][:12]}`. {r['labeled_pairs']} labeled response-skill pairs.", ""]
    for run in r["model_runs"]:
        lines.append(f"- Run {run['run']}: {run['model']}, effort {run['effort']}, {run['created_at']}, "
                     f"about ${run['usd_estimate']:.2f}. Served by: {run['models_served']}")
    lines += ["", "## Claude against the human labels", "",
              "| Run | Exact, every paired case (IE as a category) | Exact, both gave a level | Within one level | "
              "Mean absolute error | Weighted kappa (linear) |", "|---|---|---|---|---|---|"]
    for i, a in enumerate(r["agreement_with_labels"], 1):
        lines.append(f"| {i} | {_pct(r['exact_with_ie_as_a_category'][i - 1])} | {_pct(a['exact_agreement'])} | "
                     f"{_pct(a['within_one_level_agreement'])} | {_value(a['mean_absolute_error'])} | "
                     f"{_value(a['weighted_cohens_kappa'])} |")
    first = r["agreement_with_labels"][0]
    suff = first["evidence_sufficiency_confusion"]["matrix"]
    lines += ["", "Level statistics use only pairs where both gave a level. Insufficient evidence (IE) is counted apart:", "",
              f"- Claude said IE: {_pct(first['prediction_insufficient_evidence'])}",
              f"- The rater said IE: {_pct(first['reference_insufficient_evidence'])}",
              f"- Missing from Claude's scores: {len(first['missing_prediction_pairs'])} pair(s)",
              f"- Exact agreement with IE treated as a fifth category, over every paired case: "
              f"{_pct(r['exact_with_ie_as_a_category'][0])}", "",
              "### Scored or IE, run 1 (rows: rater, columns: Claude)", "",
              "| | Scored | IE |", "|---|---|---|",
              f"| Scored | {suff[0][0]} | {suff[0][1]} |", f"| IE | {suff[1][0]} | {suff[1][1]} |", "",
              "### Level confusion, run 1 (rows: rater, columns: Claude)", "", "| | 1 | 2 | 3 | 4 |", "|---|---|---|---|---|"]
    for level, row in zip((1, 2, 3, 4), first["level_confusion"]["matrix"]):
        lines.append(f"| {level} | " + " | ".join(str(v) for v in row) + " |")
    if r["consistency"]:
        c = r["consistency"]
        lines += ["", "## Consistency across runs", "",
                  f"Identical level in all {c['runs']} runs: {_pct(c['identical_in_every_run'])}", "",
                  "| Runs | Exact | Within one level | Weighted kappa (linear) |", "|---|---|---|---|"]
        for p in c["pairwise"]:
            lines.append(f"| {p['runs'][0]} vs {p['runs'][1]} | {_pct(p['exact_agreement'])} | "
                         f"{_pct(p['within_one_level_agreement'])} | {_value(p['weighted_cohens_kappa'])} |")
    lines += ["", "## Every pair", "", "IE means insufficient evidence.", "",
              "| Response | Skill | Rater | " + " | ".join(f"Run {m['run']}" for m in r["model_runs"]) + " |",
              "|---|---|---|" + "---|" * len(r["model_runs"])]
    show = lambda v: "IE" if v is None else str(v)  # noqa: E731
    for p in r["pairs"]:
        lines.append(f"| {p['response_id']} | {p['skill_id']} {p['skill_name']} | {show(p['label'])} | "
                     + " | ".join(show(v) for v in p["runs"]) + " |")
    return "\n".join(lines) + "\n"
