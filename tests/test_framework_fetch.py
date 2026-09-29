"""XQ fetch and cache. Uses a synthetic page with XQ's structure. No network."""
import json

import pytest

from curriculum_auditor.framework_fetch import CACHE_NAME, SourceFormatError, fetch, load_cached, parse_page, validate_xq


def wrap(payload):
    return '<script id="__NEXT_DATA__">' + json.dumps(payload) + "</script>"


def first_skill(payload):
    return payload["props"]["learnerOutcomes"][0]["outcomeAreas"][0]["competencies"][0]["subCompetencies"][0]


def test_counts_names_and_clean_text(page_html):
    rubric = parse_page(page_html)
    assert len(rubric.skills) == 115
    assert sum(len(s.levels) for s in rubric.skills) == 460
    assert "<p>" not in rubric.skills[0].levels["1"]
    assert rubric.skills[0].competency_name == "Synthetic competency"
    assert rubric.metadata["build_id"] == "test-build"
    validate_xq(rubric)


@pytest.mark.parametrize("change", ["count", "duplicate", "empty", "level_id", "wrong_parent", "missing_script", "two_scripts"])
def test_rejects_source_drift(page_payload, change):
    skill = first_skill(page_payload)
    if change == "count":
        page_payload["props"]["learnerOutcomes"].pop()
    if change == "duplicate":
        skills = page_payload["props"]["learnerOutcomes"][0]["outcomeAreas"][0]["competencies"][0]["subCompetencies"]
        skills[1] = skills[0]
    if change == "empty":
        skill["performanceLevel3Description"] = "<p> </p>"
    if change == "level_id":
        skill["performanceLevel4Id"] = "wrong"
    if change == "wrong_parent":
        skill["id"] = "FL.TEST.1.a"
    html = wrap(page_payload)
    if change == "missing_script":
        html = "<html>redesigned</html>"
    if change == "two_scripts":
        html = html + html
    with pytest.raises(SourceFormatError):
        parse_page(html)


def test_fetches_once_then_uses_cache(tmp_path, page_html):
    calls = []

    def fetcher():
        calls.append(1)
        return page_html

    first, report1 = fetch(tmp_path, fetcher=fetcher)
    second, report2 = fetch(tmp_path, fetcher=fetcher)
    assert len(calls) == 1
    assert report1["fetched_now"] and not report2["fetched_now"]
    assert first.content_sha256 == second.content_sha256


def test_failed_refresh_keeps_old_cache(tmp_path, page_html):
    fetch(tmp_path, fetcher=lambda: page_html)
    before = (tmp_path / CACHE_NAME).read_bytes()
    with pytest.raises(SourceFormatError):
        fetch(tmp_path, refresh=True, fetcher=lambda: "<html>gone</html>")
    assert (tmp_path / CACHE_NAME).read_bytes() == before


def test_corrupt_cache_is_rejected_without_network(tmp_path, page_html):
    fetch(tmp_path, fetcher=lambda: page_html)
    path = tmp_path / CACHE_NAME
    cached = json.loads(path.read_text())
    cached["skills"][0]["levels"]["1"] = "changed"
    path.write_text(json.dumps(cached))
    with pytest.raises(SourceFormatError, match="invalid"):
        load_cached(tmp_path)
    with pytest.raises(SourceFormatError):
        fetch(tmp_path, fetcher=lambda: pytest.fail("must not fetch"))


def test_truncated_cache_is_rejected(tmp_path, page_html):
    fetch(tmp_path, fetcher=lambda: page_html)
    path = tmp_path / CACHE_NAME
    path.write_text(path.read_text()[:500])
    with pytest.raises(SourceFormatError):
        load_cached(tmp_path)


def test_corrupt_cache_can_be_replaced_by_refresh(tmp_path, page_html):
    (tmp_path / CACHE_NAME).write_text("not json")
    rubric, report = fetch(tmp_path, refresh=True, fetcher=lambda: page_html)
    assert report["fetched_now"] and report["wording_changed"] is None
    assert load_cached(tmp_path).content_sha256 == rubric.content_sha256


def test_refresh_reports_wording_change(tmp_path, page_html, page_payload):
    _, _ = fetch(tmp_path, fetcher=lambda: page_html)
    _, same = fetch(tmp_path, refresh=True, fetcher=lambda: page_html)
    assert same["wording_changed"] is False
    first_skill(page_payload)["performanceLevel1Description"] = "Different synthetic wording."
    _, changed = fetch(tmp_path, refresh=True, fetcher=lambda: wrap(page_payload))
    assert changed["wording_changed"] is True
    assert changed["previous_content_sha256"] == same["content_sha256"]


def test_missing_cache_message_names_the_command(tmp_path):
    with pytest.raises(SourceFormatError, match="curriculum-auditor fetch"):
        load_cached(tmp_path)
