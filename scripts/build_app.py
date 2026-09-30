"""Build deploy/app/: the teacher web app, ready for `vercel deploy`.

Copies only what the app needs: the package code, an entry file, and a pinned
requirements list. No notebooks, recordings, tests, or XQ data. Rebuild before
every deploy. deploy/ is gitignored.

Environment variables to set on the Vercel project:
  ANTHROPIC_API_KEY   the key that pays for Claude calls
  APP_PASSWORD        the password teachers type in
  SECTION_BUDGET_USD  optional, default 1.0 per lesson section
  RESPONSE_BUDGET_USD optional, default 1.0 per student response
"""
import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deploy" / "app"
PACKAGES = ["anthropic", "httpx", "httpx2", "fastapi", "python-multipart", "python-docx", "pypdf",
            "pydantic", "sympy"]


def main() -> int:
    link = None
    if OUT.exists():
        if (OUT / ".vercel").exists():            # keep the Vercel project link between builds
            link = OUT.parent / ".vercel-link"
            shutil.rmtree(link, ignore_errors=True)
            shutil.move(str(OUT / ".vercel"), link)
        shutil.rmtree(OUT)
    shutil.copytree(ROOT / "src" / "curriculum_auditor", OUT / "curriculum_auditor",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "server.py"))
    if link is not None:
        shutil.move(str(link), OUT / ".vercel")
    notebook = ROOT / "site" / "index.html"
    if not notebook.exists():
        print("Run scripts/build_site.py first: the site's home page is the notebook.")
        return 1
    shutil.copy(notebook, OUT / "curriculum_auditor" / "web" / "notebook.html")
    (OUT / "api").mkdir()
    (OUT / "api" / "index.py").write_text(
        '"""Vercel entry point. Every path is routed here by vercel.json."""\n'
        "import os\nimport sys\n\n"
        "sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n\n"
        "from curriculum_auditor.webapp import app  # noqa: E402,F401\n")
    (OUT / "vercel.json").write_text(
        '{\n  "$schema": "https://openapi.vercel.sh/vercel.json",\n'
        '  "functions": {"api/index.py": {"includeFiles": "curriculum_auditor/**", "maxDuration": 300}},\n'
        '  "rewrites": [{"source": "/(.*)", "destination": "/api/index"}]\n}\n')
    (OUT / "requirements.txt").write_text("".join(f"{p}=={version(p)}\n" for p in PACKAGES))
    (OUT / ".python-version").write_text("3.12\n")
    # Prove the copy imports on its own, outside the repo's environment path.
    check = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'api'); import index; "
                            "print(len(index.app.routes), 'routes')"], cwd=OUT, capture_output=True, text=True)
    if check.returncode:
        print(check.stderr)
        return 1
    print(f"Built {OUT.relative_to(ROOT)}: {check.stdout.strip()}")
    print((OUT / "requirements.txt").read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
