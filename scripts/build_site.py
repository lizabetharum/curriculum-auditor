"""Build site/index.html: the notebook, executed in replay mode, as one static page.

Deploy the site/ folder as static files. Rebuild before every deploy so the
page matches the code. No API key is used.
"""
import subprocess
import sys
from datetime import date
from pathlib import Path

import nbformat
from nbconvert import HTMLExporter

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/lizabetharum/curriculum-auditor"
HEADER = """
# Curriculum auditor

An agent that reads a lesson, maps it to XQ Competencies, and scores student work. Claude makes every judgment. Code checks each one before it counts: a quote has to exist in the right source, a skill ID has to be real, and every answer in an answer key is recomputed by code that never calls a model. Built on the Claude API with Claude Opus 5.5. This page is the project's notebook, run from recordings of real calls.

## What it found

- **Answer-key errors.** The test lesson's key had three planted errors. The math checker caught two: a height worked out with the calculator in radian mode (6.15 m instead of 13.22 m) and a sum that dropped a 1.5 m term. Claude caught the third, which arithmetic cannot see: cosine used where the height needs sine.
- **An error nobody planted.** Claude flagged two data sets in one task that gave heights 1 m apart under a prompt asking whether they agree. The lesson was fixed.
- **Agreement with a blind human rater.** On 32 response-skill pairs, wherever both gave a level, Claude was never more than one level off, with exact agreement from 73% to 95% across three runs. The disagreements sit at one boundary: 9 pairs Claude called insufficient evidence in every run, and the rater called Level 1. Claude also disagreed with itself on 8 of 31 pairs between runs, so one run's numbers on a sample this small are not stable. With 16 synthetic responses and one rater, this shows the method, not accuracy on real student work.

## Where to look

- [Section 2: the agent loop by hand](#2.-The-loop-by-hand), where the math check catches the radian-mode error
- [Section 4: Claude judges, code verifies](#4.-Claude-judges,-code-verifies), where the validators reject a fabricated quote, a missing skill, and copied instructions
- [Section 6: the agreement report](#Agreement-report:-XQ-Competencies), with every pair and all three runs
- [Source, tests, and setup on GitHub]({repo})

*Executed in replay mode on {today}, from recordings of real Claude Opus 5.5 calls.*

---
"""
FONT = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&display=swap" rel="stylesheet">'
        "<style>body, .jp-RenderedMarkdown, .jp-RenderedHTMLCommon { font-family: 'Montserrat', sans-serif; }"
        " pre, code, .jp-OutputArea-output pre { font-family: ui-monospace, Menlo, monospace; }</style>")


def main() -> int:
    subprocess.run([sys.executable, str(ROOT / "scripts/execute_notebook.py")], check=True)
    nb = nbformat.read(ROOT / "reports/build_the_agent.executed.ipynb", as_version=4)
    nb.cells.insert(0, nbformat.v4.new_markdown_cell(HEADER.format(repo=REPO_URL, today=date.today().isoformat())))
    body, _ = HTMLExporter(template_name="lab").from_notebook_node(
        nb, resources={"metadata": {"name": "Curriculum auditor: Claude judges, code verifies"}})
    body = body.replace("</head>", FONT + "</head>", 1)
    out = ROOT / "site/index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(body, encoding="utf-8")
    print(f"Wrote {out.relative_to(ROOT)} ({len(body) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
