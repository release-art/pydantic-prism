"""Every example under examples/ ships an up-to-date generated README.md.

Runs the generator in `--check` mode as a subprocess: importing the example
modules happens in the child process, so their unrun ``demo()`` / ``__main__``
lines never touch this suite's coverage. Mirrors `prism check`.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_example_readmes_are_fresh() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "gen_example_readmes.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"example READMEs are stale — run `python bin/gen_example_readmes.py`\n"
        f"{result.stdout}{result.stderr}"
    )
