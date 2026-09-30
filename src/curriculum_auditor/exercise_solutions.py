"""Worked answers to the notebook's exercises. Try the exercise first."""
from __future__ import annotations


def quote_is_exact(source: str, quote: str, start: int, end: int) -> bool:
    """Exercise 1: True only if source[start:end] is exactly the quote."""
    if not 0 <= start < end <= len(source):
        return False
    return source[start:end] == quote


def is_copied(quote: str, instructions: str, min_chars: int = 30) -> bool:
    """Exercise 2: a long quote that also appears in the instructions was copied.
    Short quotes can match by chance, so they are not counted."""
    return len(quote.strip()) >= min_chars and quote in instructions


def score_problems(status: str, level: int | None, evidence: list[str]) -> list[str]:
    """Exercise 3: list what is wrong with one score. An empty list means valid."""
    problems = []
    if status == "scored":
        if level not in (1, 2, 3, 4):
            problems.append("A score needs a level from 1 to 4.")
        if not evidence:
            problems.append("A score needs at least one quote from the student's work.")
    elif status == "insufficient_evidence":
        if level is not None:
            problems.append("Too little to score means no level. Missing evidence is never Level 1.")
    else:
        problems.append("status must be scored or insufficient_evidence.")
    return problems


def skill_status(section_marks: list[str | None]) -> str:
    """Exercise 4: combine one skill's marks from every section.
    None means that section never finished."""
    if "supported" in section_marks:
        return "supported"
    if "needs_review" in section_marks or None in section_marks:
        return "needs_review"
    return "not_evidenced"
