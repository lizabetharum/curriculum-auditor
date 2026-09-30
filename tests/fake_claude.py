"""A scripted stand-in for the Messages API, for offline tests only.

It answers streaming requests with server-sent events built from simple
scripted behavior. It also asserts that every request carries the settings the
project promises: Opus 5.5, effort high, adaptive thinking, strict tools,
tool_choice auto (by omission), fallbacks, and caching.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

import httpx2

from curriculum_auditor.client import FALLBACK_BETA

Block = dict[str, Any]


def sse(blocks: list[Block], stop_reason: str, model: str = "claude-opus-5-5", n: int = 0) -> bytes:
    events = [("message_start", {"type": "message_start", "message": {
        "id": f"msg_fake_{n}", "type": "message", "role": "assistant", "model": model, "content": [],
        "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 1000, "output_tokens": 1, "cache_creation_input_tokens": 0,
                  "cache_read_input_tokens": 0}}})]
    for i, block in enumerate(blocks):
        if block["type"] == "text":
            events += [("content_block_start", {"type": "content_block_start", "index": i,
                                                "content_block": {"type": "text", "text": ""}}),
                       ("content_block_delta", {"type": "content_block_delta", "index": i,
                                                "delta": {"type": "text_delta", "text": block["text"]}})]
        elif block["type"] == "thinking":
            events += [("content_block_start", {"type": "content_block_start", "index": i,
                                                "content_block": {"type": "thinking", "thinking": "", "signature": ""}}),
                       ("content_block_delta", {"type": "content_block_delta", "index": i,
                                                "delta": {"type": "signature_delta", "signature": f"sig{n}-{i}"}})]
        elif block["type"] == "tool_use":
            events += [("content_block_start", {"type": "content_block_start", "index": i, "content_block": {
                           "type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}}),
                       ("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {
                           "type": "input_json_delta", "partial_json": json.dumps(block["input"])}})]
        events.append(("content_block_stop", {"type": "content_block_stop", "index": i}))
    events += [("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                                  "usage": {"output_tokens": 500}}),
               ("message_stop", {"type": "message_stop"})]
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


def tool(n: int, i: int, name: str, arguments: dict[str, Any]) -> Block:
    return {"type": "tool_use", "id": f"toolu_{n}_{i}", "name": name, "input": arguments}


def between(text: str, tag: str) -> str:
    return re.search(rf"<{tag}>\n(.*)\n</{tag}>", text, re.S).group(1)


def first_user_text(body: dict[str, Any]) -> str:
    content = body["messages"][0]["content"]
    return content if isinstance(content, str) else content[0]["text"]


def quote(text: str, snippet: str) -> dict[str, Any]:
    start = text.index(snippet)
    return {"quote": snippet, "start": start, "end": start + len(snippet)}


# Which demo skills the fake "sees" in a section, by keyword.
KEYWORDS = {"DEMO.2.a": "diagram", "DEMO.2.b": "trig ratio", "DEMO.3.a": "Explain"}


def coverage_turn(body: dict[str, Any], n: int, behavior: set[str]) -> tuple[list[Block], str]:
    """Turn 1: look up descriptors (and check an answer). Turn 2: submit. Behaviors add mistakes."""
    user = first_user_text(body)
    section_id = re.search(r"Section ID: (\S+)", user).group(1)
    text = between(user, "section_text")
    assistant_turns = sum(m["role"] == "assistant" for m in body["messages"])
    ids = re.findall(r"^(DEMO\.\d\.[a-z]) ", body["system"][0]["text"] if isinstance(body["system"], list)
                     else body["system"], re.M)
    rows = []
    for skill_id in ids:
        keyword = KEYWORDS.get(skill_id)
        if keyword and keyword in text:
            rows.append({"skill_id": skill_id, "status": "supported", "evidence": [quote(text, keyword)],
                         "rationale": "The section asks for this."})
        else:
            rows.append({"skill_id": skill_id, "status": "not_evidenced", "evidence": [], "rationale": ""})
    if assistant_turns == 0:
        if "text_only_first" in behavior:
            return [{"type": "text", "text": "I think this section is mostly about ramps."}], "end_turn"
        blocks = [{"type": "thinking"}, tool(n, 0, "get_descriptors", {"skill_ids": ["DEMO.2.b"]})]
        if "sin(" in text:
            blocks.append(tool(n, 1, "check_answer", {"item": {
                "id": "key-1", "mode": "numeric", "expected": "12*sin(30)", "actual": "6", "unit": "m",
                "actual_unit": "m", "angle_convention": "degrees", "absolute_tolerance": "0.01",
                "relative_tolerance": None}}))
        return blocks, "tool_use"
    last = body["messages"][-1]["content"]
    rejected_before = isinstance(last, list) and any(r.get("is_error") for r in last if isinstance(r, dict))
    if "missing_row_first" in behavior and not rejected_before and assistant_turns == 1:
        return [{"type": "thinking"}, tool(n, 0, "submit_section_coverage",
                                             {"section_id": section_id, "rows": rows[:-1], "notes": ""})], "tool_use"
    notes = "Exit ticket uses cos. The height needs sin." if "cos(" in text else ""
    return [{"type": "thinking"}, tool(n, 0, "submit_section_coverage",
                                         {"section_id": section_id, "rows": rows, "notes": notes})], "tool_use"


def scoring_turn(body: dict[str, Any], n: int, behavior: set[str]) -> tuple[list[Block], str]:
    user = first_user_text(body)
    response_id = re.search(r"Response ID: (\S+)", user).group(1)
    skills = re.findall(r"^- (DEMO\.\d\.[a-z]) ", user, re.M)
    work = between(user, "student_work")
    blocks: list[Block] = [{"type": "thinking"}]
    for i, skill_id in enumerate(skills):
        if len(work) > 20:
            snippet = work.split(".")[0]
            args = {"response_id": response_id, "skill_id": skill_id, "status": "scored", "level": 3,
                    "descriptor_id": f"{skill_id}.3", "evidence": [quote(work, snippet)],
                    "rationale": "The work shows the skill at Level 3."}
        else:
            args = {"response_id": response_id, "skill_id": skill_id, "status": "insufficient_evidence",
                    "level": None, "descriptor_id": None, "evidence": [], "rationale": "Only a number."}
        blocks.append(tool(n, i, "record_score", args))
    return blocks, "tool_use"


class FakeClaude:
    def __init__(self, behavior: set[str] | None = None):
        self.behavior = behavior or set()
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.read())
        self.requests.append(body)
        assert request.url.path == "/v1/messages"
        assert FALLBACK_BETA in request.headers.get("anthropic-beta", "")
        assert body["model"] == "claude-opus-5-5" and body["stream"] is True
        assert body["output_config"] == {"effort": "high"} and body["thinking"] == {"type": "adaptive"}
        assert body["fallbacks"] == "default" and body["cache_control"] == {"type": "ephemeral"}
        assert "tool_choice" not in body and all(t["strict"] is True for t in body["tools"])
        n = len(self.requests)
        if "refuse" in self.behavior:
            blocks, stop = [], "refusal"
        elif "Section ID:" in first_user_text(body):
            blocks, stop = coverage_turn(body, n, self.behavior)
        else:
            blocks, stop = scoring_turn(body, n, self.behavior)
        return httpx2.Response(200, headers={"content-type": "text/event-stream", "request-id": f"req_{n}"},
                               content=sse(blocks, stop, n=n))


def transport(fake: Callable[[httpx2.Request], httpx2.Response]) -> httpx2.MockTransport:
    return httpx2.MockTransport(fake)
