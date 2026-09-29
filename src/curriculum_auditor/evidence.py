"""Quote checks. Claude supplies a quote and character offsets. Code confirms
the exact characters exist in the right source.

Offsets are zero-based Python string indexes into the source text. end is
exclusive, so source[start:end] must equal the quote exactly. No whitespace or
punctuation normalization.

Models count characters poorly. By default, when the quote is exact but the
offsets are wrong, and the quote appears exactly once in the source, code
corrects the offsets and records the correction. A quote that is not in the
source, or appears more than once, is always rejected. strict_offsets=True
rejects any wrong offset, which the notebook uses to show the check.
"""
from __future__ import annotations

from dataclasses import dataclass

MAX_QUOTE_CHARS = 600
MAX_LISTED = 5


@dataclass
class QuoteCheck:
    problem: str | None
    start: int | None = None
    end: int | None = None
    corrected: bool = False


def _occurrences(source: str, quote: str) -> list[int]:
    found, at = [], source.find(quote)
    while at >= 0:
        found.append(at)
        at = source.find(quote, at + 1)
    return found


def check_quote(source: str, quote: object, start: object, end: object, *, label: str,
                source_name: str, strict_offsets: bool = False) -> QuoteCheck:
    if not isinstance(quote, str) or not quote.strip():
        return QuoteCheck(f"{label}: the quote is empty.")
    if len(quote) > MAX_QUOTE_CHARS:
        return QuoteCheck(f"{label}: the quote is longer than {MAX_QUOTE_CHARS} characters. "
                          "Quote the shortest span that shows the evidence.")
    offsets_valid = type(start) is int and type(end) is int and 0 <= start < end <= len(source)
    if offsets_valid and source[start:end] == quote:
        return QuoteCheck(None, start, end)
    found = _occurrences(source, quote)
    if not found:
        return QuoteCheck(f"{label}: the quote does not appear in the {source_name}. "
                          "Copy it exactly, character for character.")
    spans = ", ".join(f"{i}-{i + len(quote)}" for i in found[:MAX_LISTED])
    if len(found) > 1:
        return QuoteCheck(f"{label}: the quote appears {len(found)} times in the {source_name} (at {spans}) and "
                          f"offsets {start}-{end} match none of them. Use the offsets of the one you mean, "
                          "or quote a longer span.")
    if strict_offsets:
        return QuoteCheck(f"{label}: the quote is not at {start}-{end} in the {source_name}. It appears at {spans}.")
    return QuoteCheck(None, found[0], found[0] + len(quote), corrected=True)
