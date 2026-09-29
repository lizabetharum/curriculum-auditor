"""The agent loop written by hand.

    send messages -> Claude replies -> run any tool calls -> send the results -> repeat

Rules this loop follows:
- History is append-only. Each assistant reply goes back exactly as received,
  thinking blocks included. Opus 5.5 checks that earlier turns were not edited.
- Every tool call gets a tool_result in the next user message, all in one
  message. A rejected call returns is_error with the list of fixes.
- tool_choice stays "auto". Opus 5.5 does not accept forced tool use, so if
  Claude stops before the job is done, the loop sends one reminder.
- It stops on: done() returning True, a turn with no tool calls, a refusal,
  hitting max_tokens, the turn limit, or the budget.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from anthropic import Anthropic

from .client import Meter, request_settings, strict_tools
from .tools import TOOL_DEFINITIONS, Session, ToolRejected, dispatch

MAX_TURNS = 24


@dataclass
class LoopResult:
    turns: int = 0
    tool_calls: int = 0
    rejected_calls: int = 0
    stop: str = ""
    final_text: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)


def run_tool_calls(session: Session, content: list[Any], result: LoopResult) -> list[dict[str, Any]]:
    """Run every tool_use block. Return one tool_result per call."""
    results = []
    for block in content:
        if block.type != "tool_use":
            continue
        result.tool_calls += 1
        try:
            output = dispatch(session, block.name, block.input)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(output)})
        except ToolRejected as exc:
            result.rejected_calls += 1
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": exc.message(),
                            "is_error": True})
    return results


def final_text(content: list[Any]) -> str:
    return "\n".join(b.text for b in content if b.type == "text").strip()


def run_manual_loop(client: Anthropic, session: Session, *, system: str, user: str, meter: Meter,
                    done: Callable[[], bool], nudge: str | None = None, max_turns: int = MAX_TURNS) -> LoopResult:
    result = LoopResult(messages=[{"role": "user", "content": user}])
    nudged = False
    tools = strict_tools(TOOL_DEFINITIONS)
    while result.turns < max_turns:
        with client.beta.messages.stream(**request_settings(), system=system, tools=tools,
                                         messages=result.messages) as stream:
            message = stream.get_final_message()
        result.turns += 1
        meter.add(message)
        result.messages.append({"role": "assistant", "content": message.content})
        if message.stop_reason in ("refusal", "max_tokens"):
            result.stop = message.stop_reason
            return result
        tool_results = run_tool_calls(session, message.content, result)
        if done():
            result.stop, result.final_text = "done", final_text(message.content)
            return result
        if tool_results:
            result.messages.append({"role": "user", "content": tool_results})
            continue
        # Claude ended its turn without finishing. Remind it once.
        if nudge and not nudged:
            nudged = True
            result.messages.append({"role": "user", "content": nudge})
            continue
        result.stop, result.final_text = "ended_without_finishing", final_text(message.content)
        return result
    result.stop = "turn_limit"
    return result
