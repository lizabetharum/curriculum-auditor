"""Split a Markdown curriculum into sections at headings.

Rules:
- A section starts at a heading line (# through ######) outside a fenced code
  block and runs to the next heading. Text before the first heading is its own
  section, "preamble".
- Nothing is dropped or truncated. Joining the section texts in order gives back
  the original document exactly. A test checks this.
- Section IDs come from the heading path, for example "lesson-2/practice".
  Editing one section's body does not change any ID. Repeated paths get -2, -3.
- Every section and the whole document carry a SHA-256 hash, so a report can
  prove which text it was built from.
"""
from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path

from .rubric import StrictModel

HEADING = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t#]*$")
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
MAX_DOCUMENT_CHARS = 500_000


class SegmentError(ValueError):
    pass


class Section(StrictModel):
    id: str
    heading: str
    level: int
    start: int
    end: int
    text: str
    sha256: str


class Curriculum(StrictModel):
    name: str
    sha256: str
    sections: list[Section]

    def section(self, section_id: str) -> Section | None:
        return next((s for s in self.sections if s.id == section_id), None)

    def text(self) -> str:
        return "".join(s.text for s in self.sections)


def _hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value[:48].rstrip("-") or "section"


def segment_markdown(text: str, name: str) -> Curriculum:
    if not isinstance(text, str) or not text.strip():
        raise SegmentError("The curriculum is empty.")
    if len(text) > MAX_DOCUMENT_CHARS:
        raise SegmentError(f"The curriculum is longer than {MAX_DOCUMENT_CHARS:,} characters. Split it into files.")
    headings: list[tuple[int, int, str]] = []  # (offset, level, title)
    fence: str | None = None
    offset = 0
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        fence_match = FENCE.match(bare)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
        elif fence is None:
            match = HEADING.fullmatch(bare)
            if match:
                headings.append((offset, len(match.group(1)), (match.group(2) or "").strip()))
        offset += len(line)

    bounds: list[tuple[int, int, str]] = []
    if not headings or headings[0][0] > 0:
        bounds.append((0, 0, ""))
    bounds += headings
    sections: list[Section] = []
    seen: dict[str, int] = {}
    path: list[tuple[int, str]] = []
    for index, (start, level, title) in enumerate(bounds):
        end = bounds[index + 1][0] if index + 1 < len(bounds) else len(text)
        if level == 0:
            section_id = "preamble"
        else:
            path = [(lvl, part) for lvl, part in path if lvl < level] + [(level, slug(title))]
            section_id = "/".join(part for _, part in path)
        seen[section_id] = seen.get(section_id, 0) + 1
        if seen[section_id] > 1:
            section_id = f"{section_id}-{seen[section_id]}"
        body = text[start:end]
        sections.append(Section(id=section_id, heading=title or "(before first heading)", level=level,
                                start=start, end=end, text=body, sha256=_hash(body)))
    curriculum = Curriculum(name=name, sha256=_hash(text), sections=sections)
    if curriculum.text() != text:
        raise SegmentError("Internal error: sections do not rebuild the document.")
    return curriculum


def load_curriculum(path: str | Path) -> Curriculum:
    path = Path(path)
    if path.suffix.lower() not in (".md", ".markdown", ".txt"):
        raise SegmentError("The curriculum must be a Markdown file (.md).")
    return segment_markdown(path.read_text(encoding="utf-8"), path.stem)
