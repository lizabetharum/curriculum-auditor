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
FONT = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&display=swap" rel="stylesheet">'
        "<style>body, .jp-RenderedMarkdown, .jp-RenderedHTMLCommon { font-family: 'Montserrat', sans-serif; }"
        " pre, code, .jp-OutputArea-output pre { font-family: ui-monospace, Menlo, monospace; }</style>")


def main() -> int:
    subprocess.run([sys.executable, str(ROOT / "scripts/execute_notebook.py")], check=True)
    nb = nbformat.read(ROOT / "reports/build_the_agent.executed.ipynb", as_version=4)
    nb.cells.insert(0, nbformat.v4.new_markdown_cell(
        f"*Executed in replay mode on {date.today().isoformat()}, from recordings of real Claude Opus 5.5 calls. "
        f"Source, tests, and setup: [{REPO_URL.removeprefix('https://')}]({REPO_URL}).*"))
    body, _ = HTMLExporter(template_name="lab").from_notebook_node(nb)
    body = body.replace("</head>", FONT + "</head>", 1)
    out = ROOT / "site/index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(body, encoding="utf-8")
    print(f"Wrote {out.relative_to(ROOT)} ({len(body) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
