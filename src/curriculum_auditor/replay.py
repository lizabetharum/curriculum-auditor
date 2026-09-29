"""Record real Claude API traffic once, then replay it with no key and no network.

Replay works at the HTTP layer. It sits under the Anthropic SDK as an httpx2
transport, so the manual loop, the Tool Runner, and the orchestrator run the
same code in replay mode as in live mode.

Each request is matched on a hash of its method, path, beta header, and
canonical JSON body. If the code now sends a request that was never recorded,
replay fails with StaleRecordingError and names the first field that differs.
It never falls back to the live API.

Recordings hold request bodies and response bodies. They hold no headers from
the request, so no API key is ever written.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx2
from anthropic import AnthropicError

RECORDING_VERSION = 1
KEPT_RESPONSE_HEADERS = ("content-type", "request-id")


class StaleRecordingError(AnthropicError):
    """The code sent a request the recording does not contain.

    Subclasses AnthropicError so the SDK re-raises it as is, instead of
    wrapping it in a generic connection error.
    """


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def request_key(method: str, path: str, beta: str, body: Any) -> str:
    return sha256(canonical([method, path, beta, body]).encode()).hexdigest()


def _body(request: httpx2.Request) -> Any:
    raw = request.read()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw.decode("utf-8", "replace")


def first_difference(old: Any, new: Any, path: str = "") -> str | None:
    """Return a short description of the first place two JSON values differ."""
    if type(old) is not type(new):
        return f"{path or 'body'}: type changed from {type(old).__name__} to {type(new).__name__}"
    if isinstance(old, dict):
        for key in sorted(set(old) | set(new)):
            if key not in old:
                return f"{path}.{key}: added" if path else f"{key}: added"
            if key not in new:
                return f"{path}.{key}: removed" if path else f"{key}: removed"
            found = first_difference(old[key], new[key], f"{path}.{key}" if path else key)
            if found:
                return found
        return None
    if isinstance(old, list):
        for index, (a, b) in enumerate(zip(old, new)):
            found = first_difference(a, b, f"{path}[{index}]")
            if found:
                return found
        if len(old) != len(new):
            return f"{path}: length changed from {len(old)} to {len(new)}"
        return None
    if old != new:
        if isinstance(old, str):
            at = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
            start = max(0, at - 20)
            return (f"{path}: at character {at}, recorded ...{old[start:at + 20]!r}... "
                    f"but sent ...{new[start:at + 20]!r}...")
        return f"{path}: {old!r} became {new!r}"
    return None


@dataclass
class Recording:
    path: Path
    entries: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> Recording:
        path = Path(path)
        if not path.exists():
            raise StaleRecordingError(f"No recording at {path}. Record one with --backend live --record {path}.")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("version") != RECORDING_VERSION:
            raise StaleRecordingError(f"{path} was written by a different recording format. Record it again.")
        return cls(path, raw["entries"], raw.get("meta", {}))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": RECORDING_VERSION, "meta": self.meta, "entries": self.entries}
        self.path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


class ReplayTransport(httpx2.BaseTransport):
    """Serve recorded responses. Identical requests are served in recorded order."""

    def __init__(self, recording: Recording):
        self.recording = recording
        self.served: dict[str, int] = {}
        self.count = 0

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        body = _body(request)
        beta = request.headers.get("anthropic-beta", "")
        key = request_key(request.method, request.url.path, beta, body)
        matches = [e for e in self.recording.entries if e["key"] == key]
        position = self.served.get(key, 0)
        self.count += 1
        if position >= len(matches):
            raise StaleRecordingError(self._explain(body, len(matches)))
        self.served[key] = position + 1
        entry = matches[position]
        return httpx2.Response(entry["status"], headers=entry["headers"],
                               content=entry["body"].encode("utf-8"), request=request)

    def _explain(self, body: Any, found: int) -> str:
        where = f"Request {self.count} is not in the recording {self.recording.path}."
        if found:
            return (f"{where} The recording has {found} response(s) for this exact request, and all were used. "
                    "Record again.")
        if self.count <= len(self.recording.entries):
            diff = first_difference(self.recording.entries[self.count - 1]["request"], body)
            if diff:
                return f"The recording is stale. {where} First difference from recorded request {self.count}: {diff}"
        return f"The recording is stale. {where} The code sends more requests than were recorded. Record again."


class RecordingTransport(httpx2.BaseTransport):
    """Forward to the real API and save each exchange."""

    def __init__(self, recording: Recording, inner: httpx2.BaseTransport | None = None):
        self.recording = recording
        self.inner = inner or httpx2.HTTPTransport()

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        body = _body(request)
        beta = request.headers.get("anthropic-beta", "")
        response = self.inner.handle_request(request)
        content = response.read()
        headers = {k: response.headers[k] for k in KEPT_RESPONSE_HEADERS if k in response.headers}
        if response.status_code >= 400:
            # Errors are retried by the SDK and never recorded, so replay sees only successes.
            return httpx2.Response(response.status_code, headers=headers, content=content, request=request)
        self.recording.entries.append({
            "key": request_key(request.method, request.url.path, beta, body),
            "request": body, "status": response.status_code, "headers": headers,
            "body": content.decode("utf-8")})
        self.recording.save()
        # The body is already decoded, so drop encoding and length headers.
        passed = {k: v for k, v in response.headers.items()
                  if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")}
        return httpx2.Response(response.status_code, headers=passed, content=content, request=request)

    def close(self) -> None:
        self.inner.close()
