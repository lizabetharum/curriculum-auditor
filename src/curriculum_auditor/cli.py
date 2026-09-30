"""Command line: fetch, math, audit, score, agreement.

audit and score take --backend replay (default, no key, no network) or
--backend live (calls the Claude API, reads the key from .env, stops at
--budget). Live runs can save a recording with --record for later replay.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agreement import compute_agreement
from .audit import run_coverage, run_scoring
from .client import Meter, MissingKey, make_client
from .framework_fetch import SourceFormatError, fetch
from .mathcheck import check_answer_key
from .replay import StaleRecordingError
from .reports import write_report
from .rollup import CoverageMismatch, load_coverage_report
from .rubric import RubricError, load_rubric
from .segment import load_curriculum
from .tools import Session
from .work import load_responses


def _fetch(args: argparse.Namespace) -> int:
    try:
        rubric, report = fetch(args.data_dir, refresh=args.refresh)
    except SourceFormatError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    c = report["counts"]
    print(f"{rubric.title} from {report['source_url']}")
    print(f"{'Fetched now' if report['fetched_now'] else 'Using cache'}, retrieved {report['retrieved_at']}.")
    print(f"{c['outcomes']} outcomes, {c['competencies']} competencies, {c['skills']} component skills, "
          f"{c['descriptors']} level descriptors.")
    print(f"Content hash {report['content_sha256'][:12]}. Site build {report['site_build_id']}.")
    if report["wording_changed"] is not None:
        print("Descriptor wording changed since the last snapshot." if report["wording_changed"]
              else "Descriptor wording is unchanged since the last snapshot.")
    return 0


def _describe(args: argparse.Namespace) -> int:
    rubric = load_rubric(args.rubric)
    for skill_id in args.skill_ids:
        skill = rubric.skill(skill_id)
        if skill is None:
            print(f"Unknown skill ID: {skill_id}", file=sys.stderr)
            return 1
        print(f"{skill.id} {skill.name} ({skill.competency_name})\n{skill.description}\n")
        for level in sorted(skill.levels):
            print(f"  Level {level}: {skill.levels[level]}")
        print()
    print(f"Source: {rubric.title}" + (f", {rubric.source_url}" if rubric.source_url else ""))
    return 0


def _math(args: argparse.Namespace) -> int:
    items = json.loads(Path(args.answer_key).read_text())
    result = check_answer_key(items)
    print(json.dumps(result, indent=2))
    return 0 if all(r["status"] == "correct" for r in result["results"]) else 2


def _check_record_path(args: argparse.Namespace) -> None:
    if args.backend == "live" and args.record and args.rubric == "xq" \
            and Path("data").resolve() not in Path(args.record).resolve().parents:
        raise ValueError("XQ recordings contain XQ descriptor text. Save them under data/, which Git ignores.")


def _client(args: argparse.Namespace, default_recording: str):
    if args.backend == "replay":
        return make_client("replay", recording=args.recording or default_recording)
    return make_client("live", recording=args.record)


def _finish(report: dict, out: str, stem: str) -> int:
    json_path, md_path = write_report(report, out, stem)
    usage = report["run"]["usage"]
    print(f"Saved {json_path} and {md_path}")
    if report["run"]["backend"] == "replay":
        print(f"Replayed {usage['calls']} recorded call(s). No API charge. "
              f"The recorded run cost about ${usage['usd_estimate']:.2f}.")
    else:
        print(f"{usage['calls']} API call(s), about ${usage['usd_estimate']:.2f}. Models: {usage['models'] or 'none'}")
    if report["run"]["stopped_early"]:
        print(report["run"]["stopped_early"])
        return 3
    return 0


def _audit(args: argparse.Namespace) -> int:
    _check_record_path(args)
    curriculum = load_curriculum(args.curriculum)
    session = Session(load_rubric(args.rubric), curriculum)
    client = _client(args, f"recordings/coverage-{curriculum.name}-{args.rubric}-{args.runner}.json")
    report = run_coverage(client, session, runner=args.runner, backend=args.backend, meter=Meter(args.budget))
    return _finish(report, args.out, f"coverage-{curriculum.name}-{args.rubric}")


def _score(args: argparse.Namespace) -> int:
    _check_record_path(args)
    curriculum = load_curriculum(args.curriculum)
    session = Session(load_rubric(args.rubric), curriculum, load_responses(args.responses))
    coverage = json.loads(Path(args.coverage).read_text())
    load_coverage_report(session, coverage)
    stem = Path(args.responses).stem
    client = _client(args, f"recordings/scores-{stem}-{args.rubric}-{args.runner}.json")
    report = run_scoring(client, session, runner=args.runner, backend=args.backend, meter=Meter(args.budget),
                         coverage=coverage)
    return _finish(report, args.out, f"scores-{stem}-{args.rubric}")


def _agent_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--rubric", choices=["demo", "xq"], default="demo")
    p.add_argument("--backend", choices=["replay", "live"], default="replay",
                   help="replay: saved responses, no key. live: calls the Claude API.")
    p.add_argument("--runner", choices=["tool_runner", "manual"], default="tool_runner")
    p.add_argument("--recording", help="Replay file. Defaults to a name under recordings/.")
    p.add_argument("--record", help="Live only: save this run for later replay.")
    p.add_argument("--budget", type=float, default=5.0, help="Live only: stop when spend passes this many USD.")
    p.add_argument("--out", default="reports")


def read_label_csv(path: str | Path) -> list[dict]:
    """level is 1-4 or IE. Blank rows are unlabeled and skipped."""
    import csv
    rows = []
    for row in csv.DictReader(Path(path).open(encoding="utf-8")):
        value = row["level"].strip().upper()
        if not value:
            continue
        if value == "IE":
            rows.append({"response_id": row["response_id"], "skill_id": row["skill_id"], "level": None,
                         "status": "insufficient_evidence"})
        elif value in ("1", "2", "3", "4"):
            rows.append({"response_id": row["response_id"], "skill_id": row["skill_id"], "level": int(value),
                         "status": "scored"})
        else:
            raise ValueError(f"{path}: level for {row['response_id']} {row['skill_id']} must be 1-4 or IE, not {value!r}.")
    return rows


def _agreement(args: argparse.Namespace) -> int:
    from .results import agreement_report
    runs = [json.loads(Path(p).read_text()) for p in args.score_reports]
    labels = read_label_csv(args.labels)
    report = agreement_report(runs, labels, rubric=load_rubric(args.rubric))
    if args.out:
        json_path, md_path = write_report(report, args.out, f"agreement-{args.rubric}")
        print(f"Saved {json_path} and {md_path}")
    first = report["agreement_with_labels"][0]
    print(f"Run 1 against the labels: exact {first['exact_agreement']['rate']}, "
          f"within one {first['within_one_level_agreement']['rate']}, "
          f"kappa {first['weighted_cohens_kappa']['value']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="curriculum-auditor",
                                     description="Check answer keys, curriculum coverage, and student work against XQ Competencies.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("fetch", help="Fetch XQ Competencies into data/ (uses the cache unless --refresh).")
    p.add_argument("--refresh", action="store_true", help="Fetch again and report whether the wording changed.")
    p.add_argument("--data-dir", default="data")
    p.set_defaults(run=_fetch)
    p = sub.add_parser("describe", help="Print a skill's description and levels from the local rubric.")
    p.add_argument("skill_ids", nargs="+")
    p.add_argument("--rubric", choices=["demo", "xq"], default="xq")
    p.set_defaults(run=_describe)
    p = sub.add_parser("math", help="Check an answer key (JSON list of items). Never calls a model.")
    p.add_argument("answer_key")
    p.set_defaults(run=_math)
    p = sub.add_parser("audit", help="Map a Markdown curriculum to the rubric, section by section.")
    p.add_argument("curriculum")
    _agent_options(p)
    p.set_defaults(run=_audit)
    p = sub.add_parser("score", help="Score student responses on the skills coverage found.")
    p.add_argument("responses")
    p.add_argument("--curriculum", required=True)
    p.add_argument("--coverage", required=True, help="A coverage report JSON from audit.")
    _agent_options(p)
    p.set_defaults(run=_score)
    p = sub.add_parser("agreement", help="Compare score reports with your label CSV, and runs with each other.")
    p.add_argument("score_reports", nargs="+", help="One or more score report JSONs. Run 1 comes first.")
    p.add_argument("--labels", required=True, help="Label CSV: response_id, skill_id, skill_name, level.")
    p.add_argument("--rubric", choices=["demo", "xq"], default="xq")
    p.add_argument("--out", help="Folder for the JSON and Markdown report. Omit to print a summary only.")
    p.set_defaults(run=_agreement)
    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except (StaleRecordingError, MissingKey, RubricError, CoverageMismatch, ValueError, FileExistsError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
