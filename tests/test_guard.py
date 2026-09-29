"""Repository guard, run against a throwaway Git repo. No XQ text is used."""
import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("guard", ROOT / "scripts/guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

SYNTHETIC_DESCRIPTOR = "Student plans a synthetic investigation and revises it after peer review."


def make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    count, hashed = guard.fingerprint(SYNTHETIC_DESCRIPTOR)
    (tmp_path / "scripts").mkdir()
    (tmp_path / guard.FINGERPRINTS).write_text(json.dumps({"fingerprints_by_word_count": {str(count): [hashed]}}))
    for name, text in {**files}.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    subprocess.run(["git", "add", "-A", "-f"], cwd=tmp_path, check=True)
    return tmp_path


def test_clean_repo_passes(tmp_path):
    assert guard.staged_problems(make_repo(tmp_path, {"README.md": "Nothing to see."})) == []


def test_descriptor_is_caught_across_case_and_punctuation(tmp_path):
    reworded = "STUDENT plans a synthetic investigation, and revises it after peer-review!"
    problems = guard.staged_problems(make_repo(tmp_path, {"notes.md": f"Intro. {reworded} Outro."}))
    assert any("descriptor" in p for p in problems)


def test_api_key_is_caught(tmp_path):
    fake = "sk-" + "ant-" + "api03-" + "x" * 30
    problems = guard.staged_problems(make_repo(tmp_path, {"config.py": f"KEY = '{fake}'"}))
    assert any("API key" in p for p in problems)


def test_local_only_paths_are_caught(tmp_path):
    problems = guard.staged_problems(make_repo(tmp_path, {"data/xq_framework.json": "{}", ".env": "A=1",
                                                          "reports/r.json": "{}", ".env.example": "A="}))
    assert sorted(p.split(":")[0] for p in problems) == [".env", "data/xq_framework.json", "reports/r.json"]


def test_notebook_output_is_caught(tmp_path):
    nb = {"cells": [{"cell_type": "code", "source": "1", "outputs": [{"text": "1"}], "execution_count": 1}]}
    problems = guard.staged_problems(make_repo(tmp_path, {"nb.ipynb": json.dumps(nb)}))
    assert any("saved output" in p for p in problems)
