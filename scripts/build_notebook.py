"""Write notebooks/build_the_agent.ipynb from the cells below.

The notebook is generated so its source stays reviewable as plain Python and
never carries saved outputs. Run this after editing a cell, then run
scripts/execute_notebook.py to check it end to end in replay mode.
"""
from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
cells: list = []


def md(text: str) -> None:
    cells.append(nbf.v4.new_markdown_cell(text.strip("\n")))


def code(text: str) -> None:
    cells.append(nbf.v4.new_code_cell(text.strip("\n")))


# ---------------------------------------------------------------- 0 Setup
md("""
# Build a curriculum auditor: Claude judges, code verifies

This notebook builds an agent that reads a lesson, maps it to a competency framework, and scores student work, one layer at a time. Claude makes the judgment calls. Plain Python checks every claim Claude makes before it is accepted: each quote has to exist in the right source, each skill ID has to be real, and every math answer is recomputed by code that never calls a model.

It runs cold in replay mode, with no API key and no network, from recordings of real Claude Opus 5.5 calls. Executing every cell takes a few minutes. Reading it properly takes about 90.

| Section | What you build | Minutes |
|---|---|---|
| 0 | Setup, and why the framework is fetched instead of bundled | 5 |
| 1 | One tool call | 10 |
| 2 | The agent loop by hand | 15 |
| 3 | Lookup tools versus stuffing the prompt | 10 |
| 4 | Claude judges, code verifies | 15 |
| 5 | The same agent with the SDK's Tool Runner | 10 |
| 6 | Scoring student work, and the agreement report | 15 |
| 7 | The same tools over MCP | 5 |
| 8 | Optional: a live run on your own lesson | 5+ |
""")

md("""
## 0. Setup

Two rubrics share one data format, so every line of code below works with either.

- **The demo rubric** has 8 skills written for this repository. It ships with the code, and every recorded run in this notebook uses it.
- **XQ Competencies** has 115 component skills across 5 learner outcomes, published by XQ Institute in the [XQ Competency Navigator](https://xqcompetencies.xqsuperschool.org/). The framework is XQ's work, so this repository commits none of its descriptor text. `curriculum-auditor fetch` downloads it to `data/`, checks its structure (5 outcomes, 37 competencies, 115 skills, 460 level descriptors), and records hashes so a later run can tell whether the wording changed. A pre-commit guard blocks any complete XQ descriptor from being committed.
""")

code("""
import json
import os
from pathlib import Path

ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
os.chdir(ROOT)

from curriculum_auditor.rubric import load_rubric
from curriculum_auditor.segment import load_curriculum
from curriculum_auditor.work import load_responses

demo = load_rubric("demo")
lesson = load_curriculum("content/lesson-heights.md")
responses = load_responses("content/responses.json")

print(demo.title, "|", len(demo.skills), "skills")
for skill in demo.skills[:3]:
    print(" ", skill.id, skill.name)
print()
print(f"Lesson: {len(lesson.sections)} sections")
for section in lesson.sections:
    print(" ", section.id)

xq_ready = (ROOT / "data/xq_framework.json").exists()
print()
print("XQ cache present:", xq_ready, "(run `uv run curriculum-auditor fetch` to add it)")
""")

md("""
The lesson in `content/lesson-heights.md` is synthetic. Its answer key has three planted errors: a height computed with the calculator in radian mode, a term dropped from a sum, and the wrong trig ratio for the situation. Keep them in mind. Code catches the first two. Only a reader can catch the third.
""")

# ---------------------------------------------------------------- 1 One call
md("""
## 1. One tool call

A tool is a function Claude can ask you to run. You describe it with a name, a description, and a JSON schema for its input. Claude replies with a `tool_use` block naming the tool and its arguments. Your code runs the function and sends back the result.

Every request in this project uses the same settings, defined once in `request_settings()`:

- `claude-opus-5-5` at effort `high`. Opus 5.5 defaults to `medium`, so the setting is explicit.
- Adaptive thinking. Claude decides how much to think.
- `strict: true` on every tool, so arguments always match the schema.
- `tool_choice` left at `auto`. Opus 5.5 rejects forced tool use, so the prompt says which tool to call.
- Prompt caching on, and `fallbacks: "default"`, which reroutes a refused request to another model server-side.
""")

code("""
from curriculum_auditor import prompts
from curriculum_auditor.client import make_client, request_settings, strict_tools
from curriculum_auditor.tools import TOOL_DEFINITIONS, Session, dispatch

print(json.dumps(request_settings(), indent=1))
print()
print([tool["name"] for tool in TOOL_DEFINITIONS])
""")

code("""
RECORDING = "recordings/coverage-lesson-heights-demo-manual.json"
client = make_client("replay", recording=RECORDING)   # swap "replay" for "live" to call the API

answer_key = lesson.section("measuring-heights-you-cannot-reach/answer-key")
session = Session(demo, lesson)
system = prompts.coverage_system(demo)
messages = [{"role": "user", "content": prompts.coverage_message(answer_key)}]

with client.beta.messages.stream(**request_settings(), system=system,
                                 tools=strict_tools(TOOL_DEFINITIONS), messages=messages) as stream:
    reply = stream.get_final_message()

print("stop_reason:", reply.stop_reason)
for block in reply.content:
    print("-", block.type, getattr(block, "name", ""), json.dumps(getattr(block, "input", ""))[:160])
""")

md("""
Claude asked for several tool calls in one reply. The `thinking` block holds its reasoning. On Opus 5.5 the text is omitted by default, but the block has to go back to the API unchanged on the next turn.

Run one of the calls yourself. `dispatch` looks up the tool by name and calls it with Claude's arguments.
""")

code("""
first_call = next(b for b in reply.content if b.type == "tool_use")
result = dispatch(session, first_call.name, first_call.input)
print(first_call.name)
print(json.dumps(result, indent=1)[:900])
""")

# ---------------------------------------------------------------- 2 Loop by hand
md("""
## 2. The loop by hand

An agent is that exchange in a loop: send, run the tools Claude asked for, send the results back, repeat until the job is done. The loop below is the whole agent. `curriculum_auditor/loop.py` has the same code with a few more stop conditions.

Three rules matter:

1. **History is append-only.** Each reply goes back exactly as received, thinking blocks included. Opus 5.5 rejects a conversation whose earlier turns were edited.
2. **Every tool call gets a result,** all in one user message. A rejected call still gets a result, marked `is_error`, with the list of fixes.
3. **Code decides when the job is done.** Here that is when the section's coverage is accepted.
""")

code("""
from curriculum_auditor.tools import ToolRejected

client = make_client("replay", recording=RECORDING)   # a fresh replay client starts from the first request
session = Session(demo, lesson)
messages = [{"role": "user", "content": prompts.coverage_message(answer_key)}]

for turn in range(1, 10):
    with client.beta.messages.stream(**request_settings(), system=system,
                                     tools=strict_tools(TOOL_DEFINITIONS), messages=messages) as stream:
        reply = stream.get_final_message()
    messages.append({"role": "assistant", "content": reply.content})

    results = []
    for block in reply.content:
        if block.type != "tool_use":
            continue
        try:
            output = dispatch(session, block.name, block.input)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(output)})
            print(f"turn {turn}: {block.name} accepted")
        except ToolRejected as rejected:
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": rejected.message(), "is_error": True})
            print(f"turn {turn}: {block.name} REJECTED: {rejected.summary}")

    if session.sections[answer_key.id].status != "pending" or not results:
        break
    messages.append({"role": "user", "content": results})

print()
print("Section status:", session.sections[answer_key.id].status)
""")

md("""
Claude checked the answer key with `check_answer`. That tool is deterministic: it parses each expression into a SymPy tree from a whitelist of operations (no `eval`, no string parsing by SymPy), evaluates it, and compares it with the stated answer within an explicit tolerance. It never calls a model.
""")

code("""
for check in session.answer_checks:
    r = check["result"]
    print(f"{str(r.get('id')):28} {r['status']:13} expected {r.get('expected_value')}  key says {r.get('actual_value')}")
""")

md("""
One check came back `unsupported`: Claude wrote `0.31^2`, and the checker accepts only `**` for powers. It refused instead of guessing, Claude read the reason, and the retry passed.

B4 is the planted radian-mode error: 15 × tan(38°) + 1.5 is 13.22 m, but tan(38) in radians gives 6.15. The extension is the dropped term. The exit ticket passes, because its arithmetic is right. Its error is the setup (cosine where the height needs sine), which the checker cannot see.

Claude can. The coverage tool has a `notes` field for anything a teacher should check.
""")

code("""
print(session.sections[answer_key.id].claude_notes)
""")

md("""
The checker never guesses an angle unit. Leave `angle_convention` out and it refuses. Give it radians for a degree problem and it computes what you asked for, with a warning.
""")

code("""
from curriculum_auditor.mathcheck import check_answer

base = {"id": "demo", "mode": "numeric", "expected": "sin(30)", "actual": "0.5",
        "unit": "dimensionless", "actual_unit": "dimensionless", "absolute_tolerance": "0.001"}
for convention in (None, "degrees", "radians"):
    r = check_answer({**base, "angle_convention": convention})
    print(f"{str(convention):8} -> {r['status']:12} {r.get('warnings') or r.get('reason', '')}")
""")

# ---------------------------------------------------------------- 3 Lookup
md("""
## 3. Lookup tools versus stuffing the prompt

The system prompt lists every skill ID and short name, but no descriptors. Claude reads descriptors with `get_descriptors`, up to 8 skills per call, only for skills that might apply. The alternative is to paste every descriptor into the prompt.

These counts come from the token counting endpoint, measured once on the first request for Task A. The file stores numbers only.
""")

code("""
counts = json.loads(Path("results/token-counts.json").read_text())
for name in ("demo", "xq"):
    c = counts[name]
    ratio = c["all_descriptors_in_prompt_tokens"] / c["lookup_design_tokens"]
    print(f"{name:5} {c['skills']:4} skills   lookup: {c['lookup_design_tokens']:6,} tokens   "
          f"all descriptors in prompt: {c['all_descriptors_in_prompt_tokens']:6,}   ({ratio:.1f}x)")
""")

md("""
On the demo rubric the difference is small. On XQ, pasting every descriptor makes each request about 10 times larger.

Caching narrows the cost gap. Opus 5.5 bills cache reads at $0.20 per million input tokens instead of $4, so a stuffed prompt that stays cached is cheap to resend. Two costs remain. The first request in each 5-minute cache window pays a write premium on the whole prompt, and every request fills Claude's context with 114 skills that do not apply, for the sake of the one that does. Lookup keeps each request small and puts only the relevant descriptors in front of the model.

Here is what Claude actually looked up in the recorded demo run:
""")

code("""
from curriculum_auditor.replay import Recording

looked_up = {}
for entry in Recording.load(RECORDING).entries:
    for message in entry["request"]["messages"]:
        if message["role"] != "assistant":
            continue
        for block in message["content"]:
            if block.get("type") == "tool_use" and block["name"] == "get_descriptors":
                for skill_id in block["input"]["skill_ids"]:
                    looked_up[skill_id] = looked_up.get(skill_id, 0) + 1
print(looked_up)
""")

# ---------------------------------------------------------------- 4 Verify
md("""
## 4. Claude judges, code verifies

Claude decides whether a section gives students a real chance to practice a skill. Code decides whether that decision is well formed. Every coverage submission needs one row per skill, and every `supported` row needs a quote that exists in the section.

This section calls the tools directly, with no model, to show what gets rejected. `strict_offsets=True` also rejects wrong character offsets. The recorded runs use the default, which corrects offsets on a quote that appears exactly once, because models count characters poorly.
""")

code("""
task_a = lesson.section("measuring-heights-you-cannot-reach/task-a-the-ramp")
strict = Session(demo, lesson, responses, strict_offsets=True)

def rows(supported=None):
    supported = supported or {}
    out = []
    for skill_id in demo.ids():
        if skill_id in supported:
            text = supported[skill_id]
            start = task_a.text.find(text)
            out.append({"skill_id": skill_id, "status": "supported", "rationale": "The task asks for it.",
                        "evidence": [{"quote": text, "start": start, "end": start + len(text)}]})
        else:
            out.append({"skill_id": skill_id, "status": "not_evidenced", "evidence": [], "rationale": ""})
    return out

def attempt(label, submission):
    try:
        print(label, "->", strict.submit_section_coverage(task_a.id, submission))
    except ToolRejected as rejected:
        print(label, "-> rejected:", rejected.summary)
        for fix in rejected.problems:
            print("     ", fix)
""")

code("""
fabricated = rows()
fabricated[3] = {"skill_id": "DEMO.2.b", "status": "supported", "rationale": "It asks for a ratio.",
                 "evidence": [{"quote": "Students compare sine and cosine graphs.", "start": 0, "end": 41}]}
attempt("Fabricated quote", fabricated)

missing = rows({"DEMO.2.b": "Choose sine, cosine, or tangent."})[:-1]
attempt("Missing skill", missing)
""")

md("""
Each rejection comes back as a list of fixes, and after three rejections the section is marked `needs_review` and the run moves on. A section that never finishes cannot prove a skill is absent, so the roll-up reports those skills as `needs_review`, never as `not_evidenced`.
""")

code("""
attempt("Third bad try", missing)
attempt("Correct submission after three strikes", rows({"DEMO.2.b": "Choose sine, cosine, or tangent."}))
""")

md("""
Scoring has the same kind of check with one more rule: evidence must come from the student's own words. r13 copied the task instructions into its answer, so a quote of that text is rejected, even though it appears in the student's work.
""")

code("""
from curriculum_auditor.rollup import load_coverage_report

coverage = json.loads(Path("recordings/coverage-report-lesson-heights-demo.json").read_text())
scoring = Session(demo, lesson, responses)
load_coverage_report(scoring, coverage)

r13 = scoring.responses["r13"]
copied = "Measure the distance from your feet to the base with the tape measure."
start = r13.student_work.find(copied)
try:
    scoring.record_score("r13", "DEMO.3.a", "scored", 2, "DEMO.3.a.2",
                         [{"quote": copied, "start": start, "end": start + len(copied)}], "Lists steps.")
except ToolRejected as rejected:
    print(rejected.problems[0])

try:
    scoring.record_score("r13", "DEMO.3.a", "insufficient_evidence", 1, "DEMO.3.a.1", [], "No reasoning shown.")
except ToolRejected as rejected:
    print(rejected.problems[0])
""")

# ---------------------------------------------------------------- 5 Tool Runner
md("""
## 5. The same agent with the Tool Runner

The SDK's Tool Runner (`client.beta.messages.tool_runner`) runs the loop from section 2 for you. You hand it functions wrapped with `@beta_tool`. It sends requests, runs the tools, and appends results. `curriculum_auditor/agent.py` wraps the same five tools. A rejected call raises the SDK's `ToolError`, which the runner returns to Claude as an `is_error` result, exactly like the hand-written loop.

The orchestrator in `audit.py` stays in charge of the order of work. Code loops over the sections, and each section gets its own fresh conversation, so one long section cannot crowd out another and a failure stays contained to one section.
""")

code("""
from curriculum_auditor.audit import run_coverage

tool_runner_report = run_coverage(
    make_client("replay", recording="recordings/coverage-lesson-heights-demo-tool_runner.json"),
    Session(demo, lesson), runner="tool_runner", backend="replay", progress=lambda _: None)

print(tool_runner_report["summary"])
for skill in tool_runner_report["skills"]:
    where = ", ".join(s["section_id"].split("/")[-1] for s in skill["supported_in"])
    print(f"  {skill['skill_id']:9} {skill['status']:14} {where}")
""")

md("""
The Tool Runner recording and the manual recording come from separate live runs, so their judgments can differ slightly. Replay reproduces each run exactly. It does not make the model deterministic.
""")

# ---------------------------------------------------------------- 6 Scoring
md("""
## 6. Scoring student work

Scoring runs one agent pass per response. Each pass scores only the skills coverage marked `supported` for that response's task. For each skill, Claude reads the levels, then calls `record_score` with a level from 1 to 4 and quotes from the student's work, or with `insufficient_evidence` and no level. Missing evidence is never Level 1.
""")

code("""
from collections import Counter
from curriculum_auditor.audit import run_scoring

scoring_session = Session(demo, lesson, responses)
load_coverage_report(scoring_session, coverage)   # hashes must match, or scoring refuses the coverage report
scores = run_scoring(make_client("replay", recording="recordings/scores-responses-demo-tool_runner.json"),
                     scoring_session, runner="tool_runner", backend="replay", coverage=coverage,
                     progress=lambda _: None)

print(scores["summary"])
print(Counter("IE" if row["level"] is None else row["level"] for row in scores["rows"]))
print()
for row in scores["rows"]:
    if row["response_id"] in ("r02", "r06") and row["skill_id"] == "DEMO.1.a":
        print(row["response_id"], row["skill_id"], "level", row["level"])
        print("   quote:", row["evidence"][0]["quote"][:100] if row["evidence"] else "(none)")
        print("   why:  ", row["rationale"])
""")

md("""
### Agreement with a human rater, on XQ

One person blind-labeled the 16 responses on four XQ skills, 32 response-skill pairs, before any model score existed. Claude then scored the same responses against XQ. The committed report compares the two using IDs and levels only.

Read it as a method demonstration. Sixteen synthetic responses, written by Claude and labeled by one rater, cannot show that the scorer is accurate on real student work. They show how to measure it: exact and within-one agreement, mean absolute error, and linearly weighted kappa, with insufficient-evidence counts kept apart from the level statistics. Repeated runs measure consistency, which is stability, not validity.
""")

code("""
from IPython.display import Markdown, display

reports = sorted(Path("results").glob("agreement-xq-*.md"))
if reports:
    display(Markdown(reports[-1].read_text()))
else:
    print("No agreement report yet. It is written by `curriculum-auditor agreement` after a live XQ run.")
""")

# ---------------------------------------------------------------- 7 MCP
md("""
## 7. The same tools over MCP

`curriculum_auditor/server.py` exposes the five tools, plus `load_curriculum`, `get_section`, and `coverage_report`, as an MCP server. It needs no API key, because the MCP host (Claude Code, for example) is the model. Register it from the repository folder:

```sh
claude mcp add curriculum-auditor -- uv run curriculum-auditor-mcp
```

The cell below starts the server as a subprocess and talks to it the way a host would.
""")

code("""
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

params = StdioServerParameters(command=sys.executable, args=["-m", "curriculum_auditor.server"], cwd=str(ROOT),
                               env={**os.environ, "CURRICULUM_AUDITOR_ROOT": str(ROOT)})

async with stdio_client(params) as (reader, writer):
    async with ClientSession(reader, writer) as mcp_session:
        await mcp_session.initialize()
        print(sorted(t.name for t in (await mcp_session.list_tools()).tools))
        loaded = await mcp_session.call_tool("load_curriculum", {"curriculum_path": "content/lesson-heights.md",
                                                                 "rubric": "demo"})
        print(loaded.structured_content["skill_count"], "skills,",
              len(loaded.structured_content["sections"]), "sections")
        check = await mcp_session.call_tool("check_answer", {"item": {
            "id": "B4", "mode": "numeric", "expected": "15*tan(38) + 1.5", "actual": "6.15", "unit": "m",
            "actual_unit": "m", "angle_convention": "degrees", "absolute_tolerance": "0.005"}})
        print("B4:", check.structured_content["status"])
""")

# ---------------------------------------------------------------- 8 Live
md("""
## 8. Optional: a live run on your own lesson

Everything above replayed recorded responses. To run live:

1. Copy `.env.example` to `.env` and add your `ANTHROPIC_API_KEY`.
2. Fetch XQ: `uv run curriculum-auditor fetch`.
3. Set `RUN_LIVE = True` and point `LESSON` at any Markdown lesson.

A live coverage run on this lesson against XQ cost about $1.50 in testing. The budget below stops the run if spend passes it. Output goes to `reports/`, which Git ignores.
""")

code("""
RUN_LIVE = False
LESSON = "content/lesson-heights.md"
BUDGET_USD = 3.0

if RUN_LIVE:
    from curriculum_auditor.client import Meter
    from curriculum_auditor.reports import write_report
    live_report = run_coverage(make_client("live"), Session(load_rubric("xq"), load_curriculum(LESSON)),
                               runner="tool_runner", backend="live", meter=Meter(BUDGET_USD))
    print(write_report(live_report, "reports", "coverage-live"))
else:
    print("Skipped. Set RUN_LIVE = True to call the API.")
""")

nb = nbf.v4.new_notebook(cells=cells, metadata={
    "kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
    "language_info": {"name": "python"}})
out = ROOT / "notebooks/build_the_agent.ipynb"
out.parent.mkdir(exist_ok=True)
nbf.write(nb, out)
print(f"Wrote {out.relative_to(ROOT)} with {len(cells)} cells")
