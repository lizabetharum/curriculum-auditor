import pytest

from curriculum_auditor.segment import SegmentError, segment_markdown

DOC = """Intro line before any heading.

# Lesson 2: Right triangles
Warm-up text.

## Practice
Problem 1.

```python
# not a heading
```

## Practice
Second practice block.

### Exit ticket ###
Last line without newline"""


def test_sections_rebuild_the_document_exactly():
    assert segment_markdown(DOC, "lesson").text() == DOC


def test_ids_and_offsets():
    curriculum = segment_markdown(DOC, "lesson")
    ids = [s.id for s in curriculum.sections]
    assert ids[0] == "preamble"
    assert ids[2] == "lesson-2-right-triangles/practice"
    assert ids[3] == "lesson-2-right-triangles/practice-2"
    assert ids[4].endswith("/exit-ticket")
    assert "# not a heading" in curriculum.sections[2].text
    for s in curriculum.sections:
        assert DOC[s.start:s.end] == s.text


def test_editing_one_body_changes_only_that_hash():
    before = segment_markdown(DOC, "lesson")
    after = segment_markdown(DOC.replace("Problem 1.", "Problem 1 revised."), "lesson")
    assert [s.id for s in before.sections] == [s.id for s in after.sections]
    changed = [a.id for a, b in zip(before.sections, after.sections) if a.sha256 != b.sha256]
    assert changed == ["lesson-2-right-triangles/practice"]
    assert before.sha256 != after.sha256


def test_no_preamble_when_document_starts_with_heading():
    curriculum = segment_markdown("# A\ntext\n# B\nmore\n", "doc")
    assert [s.id for s in curriculum.sections] == ["a", "b"]


def test_long_documents_are_rejected_not_truncated():
    with pytest.raises(SegmentError, match="longer"):
        segment_markdown("x" * 500_001, "big")


def test_empty_document_is_rejected():
    with pytest.raises(SegmentError):
        segment_markdown("  \n", "empty")
