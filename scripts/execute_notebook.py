"""Execute the notebook in replay mode and save an executed copy to reports/.

Exits nonzero if any cell fails. No API key or network is needed.
"""
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "notebooks/build_the_agent.ipynb"


def main() -> int:
    nb = nbformat.read(SOURCE, as_version=4)
    NotebookClient(nb, timeout=300, kernel_name="python3", resources={"metadata": {"path": str(ROOT)}}).execute()
    out = ROOT / "reports/build_the_agent.executed.ipynb"
    out.parent.mkdir(exist_ok=True)
    nbformat.write(nb, out)
    print(f"Executed {len(nb.cells)} cells. Saved {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
