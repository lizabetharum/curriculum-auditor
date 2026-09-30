# Curriculum auditor

An agent that audits a lesson against a competency framework and scores student work. Claude makes each judgment. Code checks every claim before it counts.

Built with Claude Opus 5.5 and the Claude API in Python. A notebook builds the agent one layer at a time and runs with no API key, from recordings of real calls.

Read the notebook with every output, no install: [curriculum-auditor-orpin.vercel.app](https://curriculum-auditor-orpin.vercel.app)

## What it does

Three jobs, with the same five tools behind all of them:

1. **Checks answer keys.** Deterministic code recomputes every numeric, algebraic, and trig answer. It never calls a model, and it refuses to guess an angle unit.
2. **Maps coverage.** For each section of a Markdown lesson, Claude decides which of the framework's skills the section gives students a real chance to practice, and quotes the words that show it.
3. **Scores student work.** On each skill coverage found, Claude places a response at Level 1 to 4 with quotes from the student's own words, or reports insufficient evidence.

The framework is [XQ Competencies](https://xqcompetencies.xqsuperschool.org/): 115 component skills, each with four level descriptors, published by XQ Institute. A small original demo rubric in the same format lets everything run offline.

## Claude judges, code verifies

Every tool call Claude makes passes through a validator before it is accepted.

- **Quotes must exist.** A quote has to appear character for character in the right source: the lesson section for coverage, the student's own words for scoring. Text the student copied from the task instructions does not count.
- **IDs must be real and complete.** A coverage submission needs exactly one row per skill. Missing, duplicate, and unknown IDs come back as a list of fixes.
- **Missing evidence is never Level 1.** A score is a level with evidence, or insufficient evidence with no level.
- **Absence has to be earned.** A skill is reported as not evidenced only when every section finished. After three rejected submissions a section is marked for review, and any skill it might have held stays unresolved.

The rest of the design follows from those checks. Tool schemas are strict. Each lesson section gets its own agent pass, so one section's failure stays contained. Reports carry hashes of the framework and the lesson, and scoring refuses a coverage report built from different inputs.

## Run it

You need [uv](https://docs.astral.sh/uv/). It installs Python 3.12 for the project.

```sh
git clone https://github.com/lizabetharum/curriculum-auditor.git && cd curriculum-auditor
uv sync --frozen
uv run pytest
uv run jupyter lab notebooks/build_the_agent.ipynb
```

Everything above runs in replay mode: no key, no network. The tests execute the notebook end to end. From a fresh clone with an empty package cache, install and all 198 tests took 34 seconds on a Mac in testing.

| Notebook section | What you build |
|---|---|
| 1 | One tool call |
| 2 | The agent loop by hand, where the math check catches a planted radian-mode error |
| 3 | Lookup tools versus pasting every descriptor into the prompt |
| 4 | The validators, rejecting a fabricated quote, a missing ID, and copied instructions |
| 5 | The same agent with the SDK's Tool Runner |
| 6 | Scoring student work, and the agreement report |
| 7 | The same tools over MCP |
| 8 | Optional live run on your own lesson |

### Live runs

Copy `.env.example` to `.env` and add `ANTHROPIC_API_KEY`. Then:

```sh
uv run curriculum-auditor fetch                                   # XQ into data/
uv run curriculum-auditor audit my-lesson.md --rubric xq --backend live --budget 3
```

`--budget` stops the run when estimated spend passes the amount in dollars. The command line also has `math`, `score`, `describe`, and `agreement`.

### From Claude Code

The same tools run as an MCP server. No API key is needed, because Claude Code is the model:

```sh
claude mcp add curriculum-auditor -- uv run curriculum-auditor-mcp
```

## What it found

The test material is synthetic: a one-period lesson on right-triangle trigonometry and 16 student responses, all in `content/`. The lesson's answer key has three planted errors.

- **The math checker caught two:** a height computed with the calculator in radian mode (6.15 m instead of 13.22 m) and a sum that dropped the 1.5 m eye height.
- **Claude caught the third,** which the checker cannot see: the arithmetic is right, but the key uses cosine where the height needs sine.
- **Claude also caught an error nobody planted.** Two data sets in Task B gave heights 1 m apart under a prompt asking whether they agree. The lesson was fixed.

On XQ, coverage cost about $1.50 (7 sections, 115 skills each), and each scoring run about $2.75 to $2.90 (120 response-skill pairs), estimated from token usage.

### Agreement with a human rater

One rater blind-labeled 32 response-skill pairs on four XQ skills before any model scores existed. The labels are committed in `labels/`. Claude then scored the same responses three times.

| Measure | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| Exact match, every paired case, insufficient evidence as its own category | 55% (17/31) | 52% (16/31) | 65% (20/31) |
| Exact match, where both gave a level | 77% (17/22) | 73% (16/22) | 95% (20/21) |
| Within one level, where both gave a level | 100% | 100% | 100% |
| Weighted kappa (linear), where both gave a level | 0.78 | 0.75 | 0.96 |

Three findings, in order of how much they matter:

1. **The main disagreement sits at one boundary, and it is stable.** In all three runs, the same 9 pairs came back as insufficient evidence where the rater gave Level 1: responses such as a bare "0.31" or a copy of the task instructions. The project's rule is that missing evidence is never Level 1. A scoring team would need to settle that boundary before trusting any scorer, human or model.
2. **Claude disagrees with itself.** Across the three runs, 8 of 31 pairs changed: 7 moved by one level, and one moved between Level 1 and insufficient evidence. 74% (23 of 31) got the same result every time. With only 21 or 22 pairs where both gave a level, those one-level changes move kappa from 0.75 to 0.96. One run's kappa on a sample this small is not a stable number.
3. **Where both gave a level, Claude was never more than one level from the rater.**

One labeled pair is missing from all three runs: each time, Claude's three attempts to score it were rejected. In run 1, the first attempt gave four quotes when the limit is three, and the next two each had a quote that broke at a degree sign (Claude wrote `0", ` for "0° to 1°"). The validator rejected them rather than accept an approximate quote.

The full report, with every pair and run, is in `results/`.

### What this does not show

This is a demonstration of the method, not evidence the scorer works on real student work. Claude wrote the 16 responses, one person labeled them, and 32 pairs is a small sample. No pass mark was set in advance. The target levels the responses were written toward are sealed in a hash (`content/targets.sha256`) so they cannot be adjusted after the fact, but they reflect one author's intent, not ground truth.

## XQ Competencies: source and terms

XQ Institute publishes the XQ Competencies in the [XQ Competency Navigator](https://xqcompetencies.xqsuperschool.org/). Its [Terms of Use](https://xqsuperschool.org/terms/) (last updated November 11, 2024) provide that content for noncommercial use only. Individuals may keep personal copies if they do not modify them and credit XQ. Nonprofit and government organizations may copy and use the content for their mission, including education, on the same conditions and free of charge to others.

This project is noncommercial, and it is built around those terms:

- The repository contains no XQ descriptor text. A pre-commit check blocks any complete descriptor from being committed.
- `curriculum-auditor fetch` downloads a copy of the framework for your own use into `data/`, which Git ignores. It converts XQ's HTML to plain text in that local copy so quotes can be matched.
- Reports and the committed agreement results use XQ skill IDs and short names only, credited to XQ.

Read the terms before you fetch. This summary is not legal advice.

## Repository map

| Path | What is there |
|---|---|
| `src/curriculum_auditor/` | The package: tools and validators, the agent loop, the Tool Runner version, the orchestrator, replay, the MCP server, the math checker |
| `notebooks/` | The notebook, generated by `scripts/build_notebook.py` |
| `content/` | Synthetic lesson, answer key, and student responses |
| `labels/` | The human rater's blind labels |
| `recordings/` | Recorded demo-rubric API traffic for replay. XQ recordings stay in `data/` |
| `results/` | Agreement report and token counts |
| `tests/` | 198 tests. None call the API or XQ |

## Not in this version

- Checking whether a word problem's setup is right. The math checker confirms an answer matches an expression, and Claude may flag a setup error, but a teacher confirms it.
- Judging which level a task demands.
- The Batches API, and charts.
