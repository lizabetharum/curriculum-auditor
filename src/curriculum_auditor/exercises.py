"""Checks for the notebook's exercises.

Each exercise asks the learner to write one small function that the project
already relies on. check(n, fn) runs that function on test cases and prints
what passed or what to fix. It never raises, so an unfinished exercise does not
stop the rest of the notebook. Worked answers are in exercise_solutions.py.
"""
from __future__ import annotations

from typing import Any, Callable

INSTRUCTIONS = "Draw and label a diagram, then use a trig ratio to find the height."
SOURCE = "The ramp rises 5 degrees. Find the height."

CASES: dict[int, list[tuple[tuple, Any, str]]] = {
    1: [
        ((SOURCE, "ramp rises", 4, 14), True, "the quote is exact and at the right position"),
        ((SOURCE, "ramp rises", 0, 10), False, "the words are right but the position is wrong"),
        ((SOURCE, "ramp climbs", 4, 15), False, "the words are not in the text"),
        ((SOURCE, "height", 100, 106), False, "the position is past the end of the text"),
    ],
    2: [
        (("use a trig ratio to find the height", INSTRUCTIONS), True, "a long quote was copied from the instructions"),
        (("height", INSTRUCTIONS), False, "a short word happens to appear in the instructions"),
        (("I drew the ramp as a right triangle and used sine", INSTRUCTIONS), False, "the quote is the student's own words"),
    ],
    3: [
        (("scored", 3, ["sin(12) = h/5"]), [], "the score has a level and evidence"),
        (("scored", None, ["sin(12) = h/5"]), "problems", "the score has no level"),
        (("scored", 3, []), "problems", "the score has a level but no evidence"),
        (("scored", 5, ["sin(12) = h/5"]), "problems", "the level is outside 1 to 4"),
        (("insufficient_evidence", None, []), [], "the work showed too little to score and has no level"),
        (("insufficient_evidence", 1, []), "problems", "the work showed too little to score but was given Level 1"),
    ],
    4: [
        ((["not_evidenced", "supported", None],), "supported", "one section supports the skill"),
        ((["not_evidenced", "needs_review"],), "needs_review", "one section was unsure about the skill"),
        ((["not_evidenced", None],), "needs_review", "a section never finished"),
        ((["not_evidenced", "not_evidenced"],), "not_evidenced", "every section finished and none had the skill"),
    ],
}


def _show(args: tuple) -> str:
    return ", ".join(repr(a) for a in args)


def _expected(want: Any) -> str:
    if want == "problems":
        return "a list with at least one problem"
    if want == []:
        return "an empty list, meaning no problems"
    return repr(want)


def check(n: int, fn: Callable) -> bool:
    """Run exercise n's cases on fn. Print the result. Return True if all pass."""
    cases = CASES[n]
    for args, want, what in cases:
        call = f"{fn.__name__}({_show(args)})"
        try:
            got = fn(*args)
        except NotImplementedError:
            print(f"Exercise {n}: not started yet. Replace the line raise NotImplementedError(...) "
                  f"with your code, then run this cell again.")
            return False
        except Exception as exc:  # the learner's code crashed; say where
            print(f"Exercise {n}: your function stopped with an error when {what}.\n"
                  f"  You called: {call}\n  The error was: {exc!r}")
            return False
        ok = bool(got) if want == "problems" else got == want
        if not ok:
            print(f"Exercise {n}: not yet. Your function gave the wrong answer when {what}.\n"
                  f"  You called: {call}\n"
                  f"  The right answer is {_expected(want)}. Your function returned {got!r}.")
            return False
    print(f"Exercise {n}: all {len(cases)} checks pass.")
    return True
