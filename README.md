# Curriculum auditor

This tool reads a lesson and finds which XQ skills it gives students a chance to practice. It also scores student work on those skills. Claude, an AI model, makes each decision. Then regular code checks it before it counts: every quote must really be in the lesson, every skill must be real, and every math answer is worked out again by code.

**Who it's for.** The tool is for teachers and curriculum teams who want to check a lesson against the XQ Competencies and get a first pass on student work. The notebook is for people learning to build AI agents: it teaches how the tool was built, with exercises. Students never use it. Their work is what gets scored.

It is written in Python with the Claude API and Claude Opus 5.5. A step-by-step notebook shows how to build it, and it runs without an API key, using saved recordings of real API calls.

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

Everything above runs in replay mode: no key, no network. The tests execute the notebook end to end. From a fresh clone with an empty package cache, install and the full test suite took 34 seconds on a Mac in testing.

| Notebook section | What you build |
|---|---|
| 1 | One tool call |
| 2 | The agent loop by hand, where the math check catches a planted radian-mode error |
| 3 | Lookup tools versus pasting every descriptor into the prompt |
| 4 | The validators, rejecting a fabricated quote, a missing ID, and copied instructions |
| 4b | Your turn: four exercises where you write the checks yourself, each checked automatically |
| 5 | The same agent with the SDK's Tool Runner |
| 6 | Scoring student work, and the agreement report |
| 7 | The same tools over MCP |
| 8 | Optional live run on your own lesson |

### The teacher app

Teachers can use the tool in a browser at [curriculum-auditor-orpin.vercel.app/app](https://curriculum-auditor-orpin.vercel.app/app), with a password.

1. Upload a lesson as Word, PDF, Markdown, or text. Word files are split at their headings. PDFs are split by page, because PDFs do not store headings.
2. The app checks one section at a time and shows which XQ skills each section gives students a chance to practice, with quotes, plus answer-key problems.
3. Optionally, pick a task and paste student responses. Each response is scored three times, in parallel, on that task's skills: 1 to 4, or "too little to score." The most common result wins. When the runs disagree, the result is flagged for a teacher, and when no two runs agree, no level is given.
4. Download the report as Markdown or JSON.

Safeguards: every request needs the password, spending is capped per section and per scoring run, and scoring requires the teacher to confirm the work has no names or identifying details. Nothing is stored: uploads are processed in memory, sent to the Claude API, and discarded. The app never shows XQ's descriptor text.

To deploy your own copy: `uv run python scripts/build_site.py`, then `uv run python scripts/build_app.py`, then `vercel deploy --prod` from `deploy/app/`. Set `ANTHROPIC_API_KEY` and `APP_PASSWORD` on the Vercel project. The notebook page is served at `/` and the app at `/app`. Deploy only from `deploy/app/`: pushes to GitHub never deploy, because the root `vercel.json` turns Git deployments off, since the repository root has no web page.

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

On XQ, coverage cost about $1.50 (7 sections, 115 skills each), and each scoring run about $2.75 to $3.05 (120 response-skill pairs), estimated from token usage.

### Agreement with a human rater

One rater scored 32 response-skill pairs on four XQ skills before any model scores existed. The labels are committed in `labels/`. Claude then scored the same responses three times.

| Measure | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| Exact match, every paired case, insufficient evidence as its own category | 65% (20/31) | 69% (22/32) | 74% (23/31) |
| Exact match, where both gave a level | 86% (18/21) | 87% (20/23) | 91% (21/23) |
| Within one level, where both gave a level | 100% | 100% | 100% |
| Weighted kappa (linear), where both gave a level | 0.87 | 0.89 | 0.92 |

Findings, in order of how much they matter:

1. **The main disagreement sits at one boundary.** In all three runs, the same 5 pairs came back as insufficient evidence where the rater gave Level 1: responses such as a bare "0.31" or a one-line answer. The project's rule is that missing evidence is never Level 1. A scoring team would need to settle that boundary before trusting any scorer, human or model.
2. **One run's numbers are not stable.** An earlier set of three runs, on the same responses and labels, before a small change to how rejected quotes are handled, gave kappa of 0.78, 0.75, and 0.96. Across all six runs, kappa ranged from 0.75 to 0.96. Within the three runs above, 25 of 30 scores were identical every time: 2 moved by one level, and 3 moved between Level 1 and insufficient evidence.
3. **Where both gave a level, Claude was never more than one level from the rater,** in all six runs.
4. **The most detailed work is the most likely to go unscored.** Runs 1 and 3 each left 2 pairs unscored, on r14 and r06, the two strongest responses. Claude gave four quotes when the limit is three, and on the retry it garbled symbols such as ° and ≈, so the quotes no longer matched the student's text. The validator rejected them rather than accept an approximate quote. When r14 was scored, Claude gave Level 4, matching the rater.

5. **Scoring three times catches uncertainty, not rule disagreements.** The teacher app scores every response three times. Applied to the three runs above, that did not make Claude agree with the rater more: the majority matched the rater on 21 of 32 pairs, about the same as a single run (20, 22, and 23). What it did was flag the 7 pairs where the runs disagreed, which are the calls a teacher should check. It could not fix the biggest disagreement, where all three runs agreed with each other and not with the rater, on work with nothing to judge. Voting catches uncertainty. Only settling the rule with the teacher fixes a disagreement about the rule.

One label changed after model scores existed: r13 was restored to its blind value of 0 (no work to judge) after a colleague's argument. The full history is in the agreement report and in commit `2cd210c`.

The full report, with every pair and run, is in `results/`.

### Limitations

This is a demonstration of the method, not evidence the scorer works on real student work.

1. **One rater.** Only one teacher scored the work, so there is no measure of how often two teachers agree. Without that baseline, nobody can say whether Claude's agreement is good or bad.
2. **The student work is synthetic, and Claude wrote it.** Real students write differently, and Claude may find its own writing easier to score.
3. **The sample is small.** 16 responses and 32 scores. Changing one or two scores moves the results a lot.
4. **Coverage was never checked against a person.** Only the scores were compared with a teacher. Nobody checked Claude's calls on which skills a lesson teaches.
5. **One lesson, one subject, four skills.** The results may not hold for other subjects, grade levels, or XQ skills.
6. **The rule for "no work" was not set in advance.** Most disagreements sit there, and one label (r13) changed twice before settling. The full history is disclosed.
7. **Claude's scores change between runs.** Some scores differed across three runs, and three runs is itself a small number.
8. **The most detailed work is the most likely to go unscored.** When Claude quotes a lot of evidence, it sometimes garbles symbols such as ° on a retry, so the code rejects the quote. Two of three runs each left two scores for the strongest responses empty.
9. **The math check stops at arithmetic.** It confirms an answer matches its expression, not that the expression fits the problem.
10. **The costs are estimates,** calculated from token counts, not taken from a bill.

The target levels the responses were written toward are sealed in a hash (`content/targets.sha256`) so they cannot be adjusted after the fact, but they reflect one author's intent, not ground truth.

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
| `tests/` | 220 tests. None call the API or XQ |

## Not in this version

- Checking whether a word problem's setup is right. The math checker confirms an answer matches an expression, and Claude may flag a setup error, but a teacher confirms it.
- Judging which level a task demands.
- The Batches API, and charts.
