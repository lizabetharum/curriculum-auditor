"""Command line. Phase 1-5 commands: fetch, math, agreement.
audit and score arrive with the agent layer."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agreement import compute_agreement
from .framework_fetch import SourceFormatError, fetch
from .mathcheck import check_answer_key


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


def _math(args: argparse.Namespace) -> int:
    items = json.loads(Path(args.answer_key).read_text())
    result = check_answer_key(items)
    print(json.dumps(result, indent=2))
    return 0 if all(r["status"] == "correct" for r in result["results"]) else 2


def _agreement(args: argparse.Namespace) -> int:
    predictions = json.loads(Path(args.predictions).read_text())
    predictions = predictions.get("rows", predictions) if isinstance(predictions, dict) else predictions
    labels = json.loads(Path(args.labels).read_text()) if args.labels else []
    labels = labels.get("rows", labels) if isinstance(labels, dict) else labels
    rename = lambda rows: [{"work_id": r.get("response_id", r.get("work_id")),  # noqa: E731
                            "subcompetency_id": r.get("skill_id", r.get("subcompetency_id")),
                            "level": r.get("level"), "status": r.get("status")} for r in rows]
    print(json.dumps(compute_agreement(rename(predictions), rename(labels)), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="curriculum-auditor",
                                     description="Check answer keys, curriculum coverage, and student work against XQ Competencies.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("fetch", help="Fetch XQ Competencies into data/ (uses the cache unless --refresh).")
    p.add_argument("--refresh", action="store_true", help="Fetch again and report whether the wording changed.")
    p.add_argument("--data-dir", default="data")
    p.set_defaults(run=_fetch)
    p = sub.add_parser("math", help="Check an answer key (JSON list of items). Never calls a model.")
    p.add_argument("answer_key")
    p.set_defaults(run=_math)
    p = sub.add_parser("agreement", help="Compare model scores with your labels.")
    p.add_argument("predictions")
    p.add_argument("--labels")
    p.set_defaults(run=_agreement)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
