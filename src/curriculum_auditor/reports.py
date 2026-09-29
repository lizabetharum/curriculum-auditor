"""Write reports as JSON plus Markdown. Never overwrite an existing report.

Markdown uses skill IDs and short names only. No descriptor text, so a report
built on XQ can be shared without reproducing XQ's descriptors.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_report(report: dict[str, Any], out_dir: str | Path, stem: str) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path, md_path = out / f"{stem}-{stamp}.json", out / f"{stem}-{stamp}.md"
    for path in (json_path, md_path):
        if path.exists():
            raise FileExistsError(f"{path} already exists. Reports are never overwritten. Wait a second and rerun.")
    with open(json_path, "x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    with open(md_path, "x", encoding="utf-8") as handle:
        handle.write(render_markdown(report))
    return json_path, md_path


def _source_line(rubric: dict[str, Any]) -> str:
    line = f"Rubric: {rubric['title']}"
    if rubric.get("source_url"):
        line += f" ({rubric['source_url']})"
    return line + f". Content hash `{rubric['content_sha256'][:12]}`."


def render_markdown(report: dict[str, Any]) -> str:
    kind = report.get("report_type")
    if kind == "coverage":
        return _coverage_md(report)
    if kind == "scores":
        return _scores_md(report)
    return "# Report\n\n```json\n" + json.dumps(report, indent=2) + "\n```\n"


def _coverage_md(r: dict[str, Any]) -> str:
    s = r["summary"]
    lines = [f"# Coverage: {r['curriculum']['name']}", "", _source_line(r["rubric"]),
             f"Curriculum hash `{r['curriculum']['sha256'][:12]}`. Created {r['created_at']}.", "",
             f"{s['supported']} supported, {s['not_evidenced']} not evidenced, {s['needs_review']} need review "
             f"out of {r['rubric']['skill_count']} skills.", ""]
    if not r["complete"]:
        lines += ["Some sections did not finish. Skills not found elsewhere are marked needs review, "
                  "not absent.", ""]
    lines += ["## Sections", "", "| Section | Status | Rejected submissions | Offsets corrected | Note |",
              "|---|---|---|---|---|"]
    lines += [f"| {x['id']} | {x['status']} | {x['rejections']} | {x['offset_corrections']} | {x['note']} |"
              for x in r["curriculum"]["sections"]]
    lines += ["", "## Skills", "", "| Skill | Name | Status | Where |", "|---|---|---|---|"]
    for k in r["skills"]:
        where = ", ".join(e["section_id"] for e in k["supported_in"]) or ", ".join(k["needs_review_in"]) or ""
        lines.append(f"| {k['skill_id']} | {k['name']} | {k['status']} | {where} |")
    return "\n".join(lines) + "\n"


def _scores_md(r: dict[str, Any]) -> str:
    s = r["summary"]
    lines = ["# Student work scores", "", _source_line(r["rubric"]), f"Created {r['created_at']}.", "",
             f"{s['scored']} scored, {s['insufficient_evidence']} insufficient evidence, {s['missing']} missing.", "",
             "| Response | Skill | Level | Status |", "|---|---|---|---|"]
    for row in r["rows"]:
        lines.append(f"| {row['response_id']} | {row['skill_id']} | {row['level'] or ''} | {row['status']} |")
    if r["missing"]:
        lines += ["", "## Missing", "", "| Response | Skill | Reason |", "|---|---|---|"]
        lines += [f"| {m['response_id']} | {m['skill_id']} | {m['reason']} |" for m in r["missing"]]
    return "\n".join(lines) + "\n"
