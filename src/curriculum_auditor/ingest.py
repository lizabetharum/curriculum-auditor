"""Turn an uploaded lesson into sections: Word, PDF, Markdown, or plain text.

- Word (.docx): paragraphs styled as headings (Heading 1 to 6, or Title) start
  new sections, exactly like Markdown headings. Tables become plain text rows.
- PDF (.pdf): PDFs store text, not headings, so each page becomes a section.
  The result carries a note saying so, and the report shows it.
- Markdown (.md) and text (.txt): split at # headings, as before.

Everything happens in memory. Nothing is written to disk.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

from .segment import Curriculum, SegmentError, segment_markdown

MAX_UPLOAD_BYTES = 10_000_000
PDF_NOTE = ("This PDF was split by page, because PDFs do not store headings. "
            "For section-by-section results, upload the Word version.")


@dataclass
class Ingested:
    curriculum: Curriculum
    note: str | None = None


def _name(filename: str) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", filename.rsplit("/", 1)[-1]) or "lesson"
    return re.sub(r"[^A-Za-z0-9 _.-]", "", stem)[:80] or "lesson"


def docx_to_markdown(data: bytes) -> str:
    import docx  # python-docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(io.BytesIO(data))
    lines: list[str] = []
    for block in document.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(block, document)
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name if para.style is not None else "") or ""
            match = re.match(r"Heading (\d)", style)
            if style == "Title":
                lines.append(f"# {text}")
            elif match:
                lines.append(f"{'#' * min(6, int(match.group(1)))} {text}")
            else:
                lines.append(text)
            lines.append("")
        elif tag == "tbl":
            for row in Table(block, document).rows:
                cells = [c.text.strip() for c in row.cells]
                if any(cells):
                    lines.append(" | ".join(cells))
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def pdf_to_markdown(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts = []
    for number, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if text:
            parts.append(f"# Page {number}\n\n{text}\n")
    if not parts:
        raise SegmentError("No text could be read from this PDF. It may be a scanned image. "
                           "Upload the Word version instead.")
    return "\n".join(parts)


def load_upload(filename: str, data: bytes) -> Ingested:
    if len(data) > MAX_UPLOAD_BYTES:
        raise SegmentError("The file is larger than 10 MB.")
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    name = _name(filename)
    if suffix == "docx":
        text, note = docx_to_markdown(data), None
    elif suffix == "pdf":
        text, note = pdf_to_markdown(data), PDF_NOTE
    elif suffix in ("md", "markdown", "txt"):
        text, note = data.decode("utf-8", errors="replace"), None
    else:
        raise SegmentError("Upload a Word (.docx), PDF, Markdown (.md), or text (.txt) file.")
    if not text.strip():
        raise SegmentError("The file has no text.")
    return Ingested(segment_markdown(text, name), note)
