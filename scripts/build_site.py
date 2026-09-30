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

This tool reads a lesson and finds which XQ skills it gives students a chance to practice. It also scores student work on those skills. Claude, an AI model, makes each decision. Then regular code checks it before it counts: every quote must really be in the lesson, every skill must be real, and every math answer is worked out again by code.

This page is the project's notebook. It shows every step and every result, using saved recordings of real API calls.

## What it found

- **Errors in the answer key.** The test lesson had three planted mistakes. Code found two: a calculator set to radians (6.15 m instead of 13.22 m) and a missing 1.5 m. Claude found the third: cosine used where sine was needed. Claude also found a mistake nobody planted.
- **Claude's scores compared with mine.** AGREEMENT_PLACEHOLDER
- **Claude does not always agree with itself.** CONSISTENCY_PLACEHOLDER
## Limitations

This shows the method. It does not prove the tool works on real student work.

1. **One rater.** Only one teacher scored the work, so there is no measure of how often two teachers agree. Without that baseline, nobody can say whether Claude's agreement is good or bad.
2. **The student work is synthetic, and Claude wrote it.** Real students write differently, and Claude may find its own writing easier to score.
3. **The sample is small.** 16 responses and 32 scores. Changing one or two scores moves the results a lot.
4. **Coverage was never checked against a person.** Only the scores were compared with a teacher. Nobody checked Claude's calls on which skills a lesson teaches.
5. **One lesson, one subject, four skills.** The results may not hold for other subjects, grade levels, or XQ skills.

The full list of ten is in the [README]({repo}#limitations).

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
