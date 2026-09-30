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

This notebook builds a tool that reads a lesson, finds which skills it gives students a chance to practice, and scores student work. You build it one piece at a time.

Claude, an AI model, makes each judgment. Plain Python code checks each one before it is accepted:

- Every quote has to appear, word for word, in the right text.
- Every skill ID has to be real.
- Every math answer is worked out again by code that never asks the model.

You do not need an API key. The notebook replays saved recordings of real calls to Claude Opus 5.5, so it runs offline and costs nothing. Running every cell takes a few minutes. Reading it carefully takes about 90.

| Section | What you build | Minutes |
|---|---|---|
| 0 | Setup, and why the skill framework is downloaded instead of included | 5 |
| 1 | One tool call | 10 |
| 2 | The agent loop, written by hand | 15 |
| 3 | Looking up skills versus putting them all in the prompt | 10 |
| 4 | Claude judges, code verifies | 15 |
| 5 | The same agent with the SDK's Tool Runner | 10 |
| 6 | Scoring student work, and comparing it with a teacher | 15 |
| 7 | The same tools in Claude Code, over MCP | 5 |
| 8 | Optional: a live run on your own lesson | 5+ |
""")

md("""
## 0. Setup

The tool works with two skill frameworks. Both use the same data format, so every line of code below works with either one.

- **The demo rubric** has 8 skills written for this project. It comes with the code, and every recording in this notebook uses it.
- **XQ Competencies** has 115 skills, published by XQ Institute in the [XQ Competency Navigator](https://xqcompetencies.xqsuperschool.org/). The framework belongs to XQ, so this project does not include its text. Instead, `curriculum-auditor fetch` downloads a copy to your `data/` folder. It checks that nothing is missing (5 outcomes, 37 competencies, 115 skills, 460 level descriptions) and saves a fingerprint, so a later download can tell you whether XQ changed any wording. A check before each commit stops XQ's text from ever being saved to the repository.
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
The lesson in `content/lesson-heights.md` was written for testing. Its answer key has three planted mistakes:

1. A height worked out with the calculator set to radians instead of degrees.
2. A sum that leaves out one number.
3. The wrong trig ratio for the situation.

Watch for them. Code catches the first two. Only a careful reader can catch the third.
""")

# ---------------------------------------------------------------- 1 One call
md("""
## 1. One tool call

A tool is a function Claude can ask your code to run. You describe each tool with three things: a name, a short description, and a schema that lists the inputs it takes. When Claude wants a tool, its reply includes a `tool_use` block with the tool's name and the inputs. Your code runs the function and sends the result back.

Every request in this project uses the same settings, set in one place, `request_settings()`:

- **Model:** `claude-opus-5-5`, with effort set to `high`. Opus 5.5 would use `medium` otherwise, so the setting is written out.
- **Thinking:** adaptive, so Claude decides how much to think before it answers.
- **Strict tools:** `strict: true` on every tool, so Claude's inputs always match the schema.
- **Tool choice:** left on `auto`. Opus 5.5 does not allow forcing a tool call, so the instructions tell Claude which tool to use.
- **Caching and fallbacks:** prompt caching is on, and `fallbacks: "default"` sends a refused request to another model automatically.
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
Claude asked for several tools in one reply. The `thinking` block holds its reasoning. On Opus 5.5 the text is hidden by default, but the block still has to be sent back unchanged on the next turn.

Now run one of those tool calls yourself. `dispatch` finds the tool by name and runs it with Claude's inputs.
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

An agent is that exchange, repeated:

1. Send the conversation to Claude.
2. Run the tools Claude asks for.
3. Send the results back.
4. Repeat until the job is done.

The loop below is the whole agent. `curriculum_auditor/loop.py` has the same code with a few extra ways to stop.

Three rules keep it working:

1. **Never edit the history.** Each reply goes back exactly as Claude sent it, thinking blocks included. Opus 5.5 rejects a conversation whose earlier turns were changed.
2. **Answer every tool call,** all in one message. A rejected call still gets an answer: the list of fixes, marked `is_error`.
3. **Code decides when the job is done.** Here, it is done when the section's coverage is accepted.
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
Claude checked the answer key with `check_answer`. That tool never uses the model. It reads each expression, allows only a short list of math operations, works out the value, and compares it with the key's answer within a stated tolerance. It never runs the text as code, so an answer key cannot run anything harmful.
""")

code("""
for check in session.answer_checks:
    r = check["result"]
    print(f"{str(r.get('id')):28} {r['status']:13} expected {r.get('expected_value')}  key says {r.get('actual_value')}")
""")

md("""
One check came back `unsupported`. Claude wrote `0.31^2`, but the checker only accepts `**` for powers. The checker refused rather than guess, Claude read the reason, and the retry passed.

Now the planted mistakes:

- **B4** is the radian mistake. 15 × tan(38°) + 1.5 is 13.22 m. The key says 6.15, which is what you get with the calculator in radians.
- **The extension** leaves out a number, so its answer does not match its own expression.
- **The exit ticket** passes, because its arithmetic is right. Its mistake is the setup: it uses cosine where the height needs sine. The checker cannot see setup mistakes.

Claude can. The coverage tool has a `notes` field for anything a teacher should check.
""")

code("""
print(session.sections[answer_key.id].claude_notes)
""")

md("""
The checker never guesses whether angles are in degrees or radians. If you leave `angle_convention` out, it refuses. If you give it radians for a degree problem, it does what you asked and adds a warning.
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
## 3. Looking up skills versus putting them all in the prompt

Claude needs each skill's level descriptions to judge it. You can provide them in two ways:

- **Put every description in the prompt,** for every request.
- **Let Claude look them up.** The prompt lists only skill IDs and short names. Claude calls `get_descriptors` for the skills that might apply, up to 8 at a time.

This project uses lookup. The counts below come from Anthropic's token counting tool, measured once on the first request for Task A. The file stores only numbers.
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
On the demo rubric the difference is small. On XQ, putting every description in the prompt makes each request about 10 times larger.

Caching narrows the cost difference. Opus 5.5 charges $0.20 per million tokens to reread cached text, instead of $4, so a large prompt that stays cached is cheap to send again. Two costs remain. The first request in each five-minute window pays extra to store the whole prompt. And every request fills Claude's context with 114 skills that do not apply, for the one that does. Lookup keeps each request small and shows Claude only what it needs.

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

Claude decides whether a section gives students a real chance to practice a skill. Code decides whether Claude's answer is complete and backed by the text. Every coverage submission needs:

- exactly one row for every skill, and
- a quote from the section for every skill marked `supported`, found word for word.

The cells below call the tools directly, without Claude, to show what gets rejected. Here `strict_offsets=True` also rejects wrong character positions for a quote. The recorded runs leave it off: if a quote is exact and appears only once, code fixes its position, because models are poor at counting characters.
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
Each rejection comes back as a list of fixes. After three rejections, the section is marked `needs_review` and the run moves on.

A section that never finishes cannot prove that a skill is missing. The skill might have been in that section. So the final report marks those skills `needs_review`, never `not_evidenced`.
""")

code("""
attempt("Third bad try", missing)
attempt("Correct submission after three strikes", rows({"DEMO.2.b": "Choose sine, cosine, or tangent."}))
""")

md("""
Scoring has the same checks and one more rule: evidence must come from the student's own words. Response r13 copied the task instructions into its answer. So a quote of that copied text is rejected, even though it appears in the student's work.
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

In section 2, you wrote the loop yourself: send the conversation to Claude, run the tools Claude asks for, send back the results, and repeat. The Anthropic SDK can run that loop for you. Its Tool Runner (`client.beta.messages.tool_runner`) repeats three steps until Claude stops asking for tools:

1. Send the conversation to Claude.
2. Run any tools Claude asks for.
3. Add the results to the conversation.

You give it your tools as Python functions. Wrapping a function with `@beta_tool` tells the SDK the tool's name, what it does, and what inputs it takes. `curriculum_auditor/agent.py` wraps the same five tools used in section 2.

Rejections work the same way as before. When a check fails, the tool raises the SDK's `ToolError`. The runner catches it and sends the list of fixes back to Claude, marked as an error, the same way the hand-written loop does.

The Tool Runner handles one conversation. Deciding what to work on next is still your code's job. The orchestrator in `audit.py` goes through the lesson one section at a time, and starts a new conversation for each section. That has two benefits:

- **Each section gets Claude's full attention.** A long section cannot fill up the conversation and crowd out the next one.
- **A failure stays contained.** If one section fails, the other sections are not affected.
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
The Tool Runner recording and the hand-written loop recording come from two separate live runs, so a few judgments differ. Replay repeats each run exactly. It does not make Claude give the same answer twice.
""")

# ---------------------------------------------------------------- 6 Scoring
md("""
## 6. Scoring student work

Scoring works one student response at a time, with a new conversation for each. It scores only the skills that coverage marked `supported` for that response's task. For each skill, Claude:

1. Reads the four level descriptions.
2. Calls `record_score` with a level from 1 to 4 and quotes from the student's work, or
3. Marks it `insufficient_evidence`, with no level, when the work shows too little to judge.

Missing evidence is never scored as Level 1.
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
### Comparing Claude with a teacher, on XQ

A teacher scored the 16 responses on four XQ skills, 32 scores in all, before Claude scored anything. Claude then scored the same responses. The report below compares the two, using only skill IDs and levels.

Read it as a demonstration of the method, not proof of accuracy. The responses were written by Claude for testing, and one teacher scored them. They show how to measure a scorer:

- **Exact match:** how often Claude and the teacher gave the same level.
- **Within one level:** how often they were at most one level apart.
- **Mean absolute error:** the average number of levels between them.
- **Weighted kappa:** agreement, adjusted for how often they would agree by chance.

"Insufficient evidence" is counted separately from the levels. Running Claude three times on the same work measures consistency: whether Claude gives the same answer again. That is not the same as being right.
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

MCP (Model Context Protocol) lets an AI app, such as Claude Code, use outside tools. `curriculum_auditor/server.py` offers the same five tools over MCP, plus three more: `load_curriculum`, `get_section`, and `coverage_report`. No API key is needed, because the app itself is the model. To add it to Claude Code, run this from the project folder:

```sh
claude mcp add curriculum-auditor -- uv run curriculum-auditor-mcp
```

The cell below starts the server and talks to it the way Claude Code would.
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

Everything above replayed saved recordings. To call Claude for real:

1. Copy `.env.example` to `.env` and add your `ANTHROPIC_API_KEY`.
2. Download XQ: `uv run curriculum-auditor fetch`.
3. In the cell below, set `RUN_LIVE = True` and point `LESSON` at any Markdown lesson.

A live coverage run of this lesson against XQ cost about $1.50 in testing. The run stops if spending passes the budget you set. Results go to the `reports/` folder, which is never saved to the repository.
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
