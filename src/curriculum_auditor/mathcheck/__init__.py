"""Deterministic answer-key checks. This package never calls a model.

Modes:
- arithmetic, equivalence, equation: exact rational checks (rational.py)
- numeric: values within an explicit tolerance, including trig (numeric.py)

Every result is correct, incorrect, unsupported, or indeterminate. Input the
checker cannot read is unsupported, never a pass. Word-problem setup is out of
scope: the checker confirms an answer matches an expression, not that the
expression models the problem.
"""
from __future__ import annotations

from typing import Any

from .numeric import check_numeric
from .rational import MAX_ITEMS, Undefined, Unsupported, check_exact

MODES = ("arithmetic", "equivalence", "equation", "numeric")


def check_answer(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"id": None, "mode": None, "status": "unsupported", "reason": "Each item must be an object."}
    try:
        result = check_numeric(item) if item.get("mode") == "numeric" else check_exact(item)
    except Unsupported as exc:
        result = {"status": "unsupported", "reason": str(exc)}
    except Undefined as exc:
        result = {"status": "indeterminate", "reason": str(exc)}
    return {"id": item.get("id"), "mode": item.get("mode"), **result}


def check_answer_key(items: Any) -> dict[str, Any]:
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise ValueError(f"items must be a list of at most {MAX_ITEMS} entries.")
    return {"deterministic": True, "results": [check_answer(item) for item in items]}


__all__ = ["MODES", "check_answer", "check_answer_key"]
