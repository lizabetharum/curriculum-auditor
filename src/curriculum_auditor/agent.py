"""The same agent, with the SDK's Tool Runner driving the loop.

Compare with loop.py. The runner sends requests, runs the tools, and appends
results. This file only wraps each tool and decides when to stop. A rejected
call raises the SDK's ToolError, which the runner returns to Claude as an
is_error tool_result, exactly like the manual loop.

The runner keeps its own copy of the history, so this code mirrors it as it
goes. The mirror is needed for the one reminder sent when Claude stops early.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from anthropic import Anthropic, beta_tool
from anthropic.lib.tools import ToolError

from .client import Meter, request_settings
from .loop import MAX_TURNS, LoopResult, final_text
from .tools import TOOL_DEFINITIONS, Session, ToolRejected, dispatch


def runnable_tools(session: Session, result: LoopResult) -> list[Any]:
    def wrap(definition: dict[str, Any]) -> Any:
        name = definition["name"]

        def run(**arguments: Any) -> str:
            result.tool_calls += 1
            try:
                return json.dumps(dispatch(session, name, arguments))
            except ToolRejected as exc:
                result.rejected_calls += 1
                raise ToolError(exc.message()) from exc

        return beta_tool(run, name=name, description=definition["description"],
                         input_schema=definition["input_schema"], strict=True)

    return [wrap(d) for d in TOOL_DEFINITIONS]


def run_tool_runner(client: Anthropic, session: Session, *, system: str, user: str, meter: Meter,
                    done: Callable[[], bool], nudge: str | None = None, max_turns: int = MAX_TURNS) -> LoopResult:
    result = LoopResult(messages=[{"role": "user", "content": user}])
    tools = runnable_tools(session, result)
    for attempt in range(2 if nudge else 1):
        if attempt == 1:
            result.messages.append({"role": "user", "content": nudge})
        runner = client.beta.messages.tool_runner(**request_settings(), system=system, tools=tools,
                                                  messages=list(result.messages), stream=True,
                                                  max_iterations=max_turns - result.turns)
        message = None
        for stream in runner:
            message = stream.get_final_message()
            result.turns += 1
            meter.add(message)
            result.messages.append({"role": "assistant", "content": message.content})
            if message.stop_reason in ("refusal", "max_tokens"):
                result.stop = message.stop_reason
                return result
            tool_response = runner.generate_tool_call_response()  # runs the tools once; cached for the runner
            if done():
                result.stop, result.final_text = "done", final_text(message.content)
                return result
            if tool_response is not None:
                result.messages.append(tool_response)
        if message is not None:
            result.final_text = final_text(message.content)
        if result.turns >= max_turns:
            result.stop = "turn_limit"
            return result
    result.stop = "ended_without_finishing"
    return result
