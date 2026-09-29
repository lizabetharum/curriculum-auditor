"""Rebuild the leak-guard fingerprints from the local XQ cache. No fetching.

Writes word-count and SHA-256 pairs only. No descriptor text is written.
Run after `curriculum-auditor fetch --refresh` reports changed wording.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from guard import FINGERPRINTS, fingerprint  # noqa: E402

from curriculum_auditor.framework_fetch import load_cached  # noqa: E402


def build() -> dict:
    rubric = load_cached(ROOT / "data")
    hashes: dict[str, set[str]] = {}
    for skill in rubric.skills:
        for text in [skill.description, *skill.levels.values()]:
            count, hashed = fingerprint(text)
            hashes.setdefault(str(count), set()).add(hashed)
    return {
        "source_url": rubric.source_url,
        "source_payload_sha256": rubric.metadata["source_payload_sha256"],
        "content_sha256": rubric.content_sha256,
        "counts": rubric.metadata["counts"],
        "scope": "Full level descriptors and full component-skill descriptions. No descriptor text.",
        "normalization": "NFKC, HTML-unescape, lowercase Unicode word tokens separated by spaces",
        "fingerprints_by_word_count": {k: sorted(v) for k, v in sorted(hashes.items(), key=lambda kv: int(kv[0]))},
    }


if __name__ == "__main__":
    manifest = build()
    if "--check" in sys.argv:
        current = json.loads((ROOT / FINGERPRINTS).read_text())["fingerprints_by_word_count"]
        same = current == manifest["fingerprints_by_word_count"]
        print("Fingerprints match the cache." if same else "Fingerprints differ from the cache. Run without --check.")
        raise SystemExit(0 if same else 1)
    (ROOT / FINGERPRINTS).write_text(json.dumps(manifest, indent=2) + "\n")
    total = sum(len(v) for v in manifest["fingerprints_by_word_count"].values())
    print(f"Wrote {total} fingerprints. No descriptor text.")
