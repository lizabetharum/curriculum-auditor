"""Fetch the XQ Competencies framework into a local cache.

Why fetch instead of bundling: the framework is XQ's work. This repo commits no
descriptor text. Each user fetches the public page, and the cache stays in
data/, which Git ignores.

The XQ Competency Navigator has no public API. It embeds its data in a
__NEXT_DATA__ JSON script. This module reads that one script without running
any page code, then checks the whole hierarchy before anything is cached:
5 outcomes, 37 competencies, 115 component skills, 460 level descriptors,
unique IDs, correct parent links, and four numbered levels per skill.

A failed refresh keeps the old cache. A successful refresh reports whether the
descriptor wording changed, because counts alone cannot detect that.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

import httpx

from .rubric import Rubric, RubricError, Skill, content_hash, digest, validate_rubric

SOURCE_URL = "https://xqcompetencies.xqsuperschool.org/"
TITLE = "XQ Competencies"
EXPECTED = {"outcomes": 5, "competencies": 37, "skills": 115, "descriptors": 460}
PARSER_VERSION = "2"
MAX_PAGE_BYTES = 5_000_000
CACHE_NAME = "xq_framework.json"


class SourceFormatError(RubricError):
    """The XQ page or the local cache no longer matches the supported structure."""


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {"p", "br", "li", "div"}:
            self.parts.append(" ")


def plain_text(value: object) -> str:
    if not isinstance(value, str):
        raise SourceFormatError("Expected text in an XQ name or descriptor.")
    parser = _Text()
    parser.feed(value)
    text = " ".join("".join(parser.parts).split())
    if not text:
        raise SourceFormatError("An XQ name or descriptor is empty.")
    return text


class _NextData(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.inside = False
        self.found = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self.found += 1
            self.inside = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)


def _nonempty_list(obj: dict, key: str) -> list:
    value = obj[key]
    if not isinstance(value, list) or not value:
        raise SourceFormatError(f"Expected a nonempty {key} list.")
    return value


def counts(skills: list[Skill]) -> dict[str, int]:
    return {"outcomes": len({s.outcome_id for s in skills}),
            "competencies": len({s.competency_id for s in skills}),
            "skills": len(skills),
            "descriptors": sum(len(s.levels) for s in skills)}


def parse_page(html: str) -> Rubric:
    """Read the one JSON script and check the full hierarchy. Never runs page code."""
    try:
        if len(html.encode()) > MAX_PAGE_BYTES:
            raise SourceFormatError("The XQ page is larger than the supported size.")
        parser = _NextData()
        parser.feed(html)
        if parser.found != 1:
            raise SourceFormatError("Expected exactly one __NEXT_DATA__ script on the XQ page.")
        payload = json.loads("".join(parser.parts))
        props = payload["props"]
        seen: set[str] = set()
        skills: list[Skill] = []
        for outcome in _nonempty_list(props, "learnerOutcomes"):
            oid = outcome["id"]
            if not re.fullmatch(r"[A-Z]{2}", oid) or oid in seen:
                raise SourceFormatError("Invalid or duplicate outcome ID.")
            seen.add(oid)
            outcome_name = plain_text(outcome["name"])
            for area in _nonempty_list(outcome, "outcomeAreas"):
                plain_text(area["name"])
                for competency in _nonempty_list(area, "competencies"):
                    cid = competency["id"]
                    if not re.fullmatch(re.escape(oid) + r"\.[A-Za-z]+\.[1-9][0-9]*", cid) or cid in seen:
                        raise SourceFormatError("Invalid, duplicate, or misplaced competency ID.")
                    seen.add(cid)
                    competency_name = plain_text(competency["name"])
                    for raw in _nonempty_list(competency, "subCompetencies"):
                        sid = raw["id"]
                        if not re.fullmatch(re.escape(cid) + r"\.[a-z]", sid) or sid in seen:
                            raise SourceFormatError("Invalid, duplicate, or misplaced component skill ID.")
                        seen.add(sid)
                        levels = {}
                        for level in range(1, 5):
                            lid = raw[f"performanceLevel{level}Id"]
                            if lid != f"{sid}.{level}" or lid in seen:
                                raise SourceFormatError("Descriptor IDs must match their skill and level.")
                            seen.add(lid)
                            levels[str(level)] = plain_text(raw[f"performanceLevel{level}Description"])
                        skills.append(Skill(
                            id=sid, name=plain_text(raw["name"]), outcome_id=oid, outcome_name=outcome_name,
                            competency_id=cid, competency_name=competency_name,
                            description=plain_text(raw["description"]), levels=levels))
        found = counts(skills)
        if found != EXPECTED:
            raise SourceFormatError(f"XQ counts changed. Expected {EXPECTED}, found {found}.")
        skills.sort(key=lambda s: s.id)
        return Rubric(kind="xq", title=TITLE, source_url=SOURCE_URL, content_sha256=content_hash(skills),
                      skills=skills, metadata={
                          "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "parser_version": PARSER_VERSION,
                          "build_id": payload.get("buildId"),
                          "source_payload_sha256": digest(props),
                          "counts": found})
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SourceFormatError("The XQ page structure changed. Expected data is missing. "
                                "No cache was replaced.") from exc


def validate_xq(rubric: Rubric) -> None:
    validate_rubric(rubric)
    if rubric.kind != "xq" or rubric.source_url != SOURCE_URL:
        raise SourceFormatError("This cache is not an XQ snapshot from the supported source.")
    if counts(rubric.skills) != EXPECTED or rubric.metadata.get("counts") != EXPECTED:
        raise SourceFormatError(f"XQ cache counts must match {EXPECTED}.")
    if rubric.metadata.get("parser_version") != PARSER_VERSION:
        raise SourceFormatError("The cache was written by a different parser version. Run fetch --refresh.")
    for s in rubric.skills:
        if not re.fullmatch(re.escape(s.outcome_id) + r"\.[A-Za-z]+\.[1-9][0-9]*", s.competency_id) \
                or not re.fullmatch(re.escape(s.competency_id) + r"\.[a-z]", s.id):
            raise SourceFormatError("The cached XQ hierarchy is invalid.")


def fetch_page() -> str:
    headers = {"User-Agent": "curriculum-auditor/0.1 (+educator prototype)", "Accept": "text/html"}
    try:
        with httpx.Client(timeout=30, follow_redirects=False, headers=headers) as client:
            with client.stream("GET", SOURCE_URL) as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_PAGE_BYTES:
                        raise SourceFormatError("The XQ page is larger than the supported size.")
                    chunks.append(chunk)
                return b"".join(chunks).decode("utf-8")
    except httpx.HTTPError as exc:
        raise SourceFormatError(f"Could not fetch the XQ page ({type(exc).__name__}). "
                                "The existing cache was kept.") from exc


def load_cached(data_dir: str | Path = "data") -> Rubric:
    """Load and check the cache. Makes no network request."""
    path = Path(data_dir) / CACHE_NAME
    if not path.exists():
        raise SourceFormatError(f"No XQ cache at {path}. Run: curriculum-auditor fetch")
    try:
        rubric = Rubric.model_validate_json(path.read_text())
        validate_xq(rubric)
    except (ValueError, OSError) as exc:
        raise SourceFormatError(f"The XQ cache at {path} is invalid. Run fetch --refresh. "
                                "No network request was made.") from exc
    return rubric


def fetch(data_dir: str | Path = "data", *, refresh: bool = False,
          fetcher: Callable[[], str] = fetch_page) -> tuple[Rubric, dict]:
    """Return the rubric and a snapshot report. Fetches only with no cache or refresh=True."""
    path = Path(data_dir) / CACHE_NAME
    previous = None
    if path.exists():
        try:
            previous = load_cached(data_dir)
        except SourceFormatError:
            if not refresh:
                raise
        if previous is not None and not refresh:
            return previous, snapshot_report(previous, fetched=False, previous_hash=None)
    rubric = parse_page(fetcher())
    validate_xq(rubric)
    _atomic_write(path, rubric.model_dump_json(indent=2))
    return rubric, snapshot_report(rubric, fetched=True,
                                   previous_hash=previous.content_sha256 if previous else None)


def snapshot_report(rubric: Rubric, *, fetched: bool, previous_hash: str | None) -> dict:
    return {"source_url": rubric.source_url, "fetched_now": fetched,
            "retrieved_at": rubric.metadata["fetched_at"],
            "parser_version": rubric.metadata["parser_version"],
            "site_build_id": rubric.metadata["build_id"],
            "source_payload_sha256": rubric.metadata["source_payload_sha256"],
            "content_sha256": rubric.content_sha256,
            "counts": rubric.metadata["counts"],
            "previous_content_sha256": previous_hash,
            "wording_changed": None if previous_hash is None else previous_hash != rubric.content_sha256}


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
