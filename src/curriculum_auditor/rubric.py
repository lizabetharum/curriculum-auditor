"""One rubric format for both the demo rubric and the XQ framework.

Every code path takes a Rubric, so the demo rubric exercises the same code that
runs on XQ. A skill has four level descriptors. Descriptor IDs are the skill ID
plus the level number, for example DEMO.1.a.3.
"""
from __future__ import annotations

import json
from hashlib import sha256
from importlib import resources
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, PrivateAttr

LEVELS = ("1", "2", "3", "4")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RubricError(ValueError):
    """The rubric is malformed or its content does not match its hash."""


class Skill(StrictModel):
    id: str
    name: str
    outcome_id: str
    outcome_name: str
    competency_id: str
    competency_name: str
    description: str
    levels: dict[str, str]

    def descriptor_id(self, level: int) -> str:
        return f"{self.id}.{level}"


class Rubric(StrictModel):
    kind: Literal["xq", "demo"]
    title: str
    source_url: str | None
    content_sha256: str
    metadata: dict
    skills: list[Skill]
    _by_id: dict[str, Skill] = PrivateAttr(default_factory=dict)

    def skill(self, skill_id: str) -> Skill | None:
        return self._index().get(skill_id)

    def ids(self) -> list[str]:
        return [s.id for s in self.skills]

    def _index(self) -> dict[str, Skill]:
        if not self._by_id:
            self._by_id = {s.id: s for s in self.skills}
        return self._by_id


def digest(value: object) -> str:
    """Hash of canonical JSON. Key order and whitespace do not change it."""
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256(canonical.encode()).hexdigest()


def content_hash(skills: list[Skill]) -> str:
    return digest([s.model_dump() for s in skills])


def validate_rubric(rubric: Rubric) -> None:
    ids = rubric.ids()
    if not ids or len(ids) != len(set(ids)):
        raise RubricError("Rubric skills must have unique IDs.")
    for s in rubric.skills:
        if not s.name.strip() or not s.description.strip():
            raise RubricError(f"{s.id}: name and description must not be empty.")
        if set(s.levels) != set(LEVELS) or any(not v.strip() for v in s.levels.values()):
            raise RubricError(f"{s.id}: needs four nonempty level descriptors, numbered 1 to 4.")
    if content_hash(rubric.skills) != rubric.content_sha256:
        raise RubricError("Rubric content does not match its hash. The file was edited or corrupted.")


def load_demo() -> Rubric:
    """The committed demo rubric. Original content, not XQ."""
    raw = json.loads(resources.files("curriculum_auditor.rubrics").joinpath("demo.json").read_text())
    skills = [Skill.model_validate(s) for s in raw["skills"]]
    rubric = Rubric(kind="demo", title=raw["title"], source_url=None,
                    content_sha256=content_hash(skills), metadata={"note": raw["note"]}, skills=skills)
    validate_rubric(rubric)
    return rubric


def load_rubric(name: str, data_dir: str | Path = "data") -> Rubric:
    """Load 'demo' from the package or 'xq' from the local cache. Never fetches."""
    if name == "demo":
        return load_demo()
    if name == "xq":
        from .framework_fetch import load_cached
        return load_cached(data_dir)
    raise RubricError("Rubric must be 'demo' or 'xq'.")
