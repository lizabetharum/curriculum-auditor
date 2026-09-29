"""Repository guard. Runs in the pre-commit hook and in CI.

Checks every file in Git's index for four problems:

1. Local-only paths that are tracked (data/, reports/, .env).
2. Notebooks with saved outputs.
3. Complete XQ descriptors. XQ's descriptor text is fetched into data/ and is
   never committed. This check compares word-sequence fingerprints, so it runs
   without the cache. It catches complete descriptors, including whitespace and
   punctuation changes. It does not catch paraphrases or partial quotes.
4. Anthropic API keys.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import unicodedata
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINGERPRINTS = "scripts/descriptor_fingerprints.json"
LOCAL_ONLY_DIRS = {"data", "reports", ".venv", ".ipynb_checkpoints"}
API_KEY = re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}")


def words(text: str) -> list[str]:
    text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), text)
    text = html.unescape(unicodedata.normalize("NFKC", text)).lower()
    return re.findall(r"\w+", text)


def fingerprint(text: str) -> tuple[int, str]:
    tokens = words(text)
    return len(tokens), sha256(" ".join(tokens).encode()).hexdigest()


def load_fingerprints(root: Path = ROOT) -> dict[str, list[str]]:
    return json.loads((root / FINGERPRINTS).read_text())["fingerprints_by_word_count"]


def contains_descriptor(text: str, fingerprints: dict[str, list[str]]) -> bool:
    tokens = words(text)
    for count, hashes in fingerprints.items():
        length, known = int(count), set(hashes)
        for start in range(len(tokens) - length + 1):
            if sha256(" ".join(tokens[start:start + length]).encode()).hexdigest() in known:
                return True
    return False


def notebook_problems(text: str) -> list[str]:
    problems = []
    for index, cell in enumerate(json.loads(text).get("cells", [])):
        if cell.get("cell_type") == "code" and (cell.get("outputs") or cell.get("execution_count") is not None):
            problems.append(f"cell {index + 1} has saved output")
    return problems


def check_file(name: str, content: str, fingerprints: dict[str, list[str]]) -> list[str]:
    path = Path(name)
    if LOCAL_ONLY_DIRS.intersection(path.parts) or path.name == ".env" or (
            path.name.startswith(".env.") and path.name != ".env.example"):
        return [f"{name}: local-only file is tracked"]
    problems = []
    if path.suffix == ".ipynb":
        problems += [f"{name}: {p}" for p in notebook_problems(content)]
    if name != FINGERPRINTS and contains_descriptor(content, fingerprints):
        problems.append(f"{name}: contains a complete XQ descriptor")
    if API_KEY.search(content):
        problems.append(f"{name}: contains an Anthropic API key")
    return problems


def staged_problems(root: Path = ROOT) -> list[str]:
    fingerprints = load_fingerprints(root)
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    problems = []
    for name in filter(None, names):
        blob = subprocess.check_output(["git", "show", ":" + name], cwd=root)
        try:
            content = blob.decode("utf-8")
        except UnicodeDecodeError:
            problems.append(f"{name}: binary file. The guard cannot inspect it.")
            continue
        problems += check_file(name, content, fingerprints)
    return problems


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    problems = staged_problems()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print("Guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
