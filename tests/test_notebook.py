"""The notebook runs end to end in replay mode: no key, no network."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_notebook_executes_in_replay_mode():
    # A separate process, as in CI. Inside pytest's process the kernel cannot spawn the MCP server.
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY" and not k.startswith("PYTEST")}
    result = subprocess.run([sys.executable, str(ROOT / "scripts/execute_notebook.py")], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]


def test_committed_notebook_has_no_outputs():
    nb = json.loads((ROOT / "notebooks/build_the_agent.ipynb").read_text())
    assert all(not c.get("outputs") and c.get("execution_count") is None for c in nb["cells"] if c["cell_type"] == "code")
