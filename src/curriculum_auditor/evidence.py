"""Quote checks. Claude supplies a quote and character offsets. Code confirms
the exact characters are at those offsets in the right source.

Offsets are zero-based Python string indexes into the source text. end is
exclusive, so source[start:end] must equal the quote exactly. No whitespace or
punctuation normalization.
"""
from __future__ import annotations

MAX_QUOTE_CHARS = 600


def quote_problem(source: str, quote: object, start: object, end: object, *, label: str,
                  source_name: str) -> str | None:
    """Return a fix instruction, or None when the quote is exact."""
    if not isinstance(quote, str) or not quote.strip():
        return f"{label}: the quote is empty."
    if len(quote) > MAX_QUOTE_CHARS:
        return f"{label}: the quote is longer than {MAX_QUOTE_CHARS} characters. Quote the shortest span that shows the evidence."
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source):
        return f"{label}: offsets {start}-{end} are outside the {source_name} (length {len(source)})."
    if source[start:end] == quote:
        return None
    found = source.find(quote)
    if found >= 0:
        return (f"{label}: the quote is not at {start}-{end} in the {source_name}. "
                f"It appears at {found}-{found + len(quote)}.")
    return f"{label}: the quote does not appear in the {source_name}. Copy it exactly, character for character."
