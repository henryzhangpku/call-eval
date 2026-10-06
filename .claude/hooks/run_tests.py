"""PostToolUse hook: run the fast test suite after every edit and report the tail.

Uses the repository's .venv when it exists, otherwise the interpreter running
this script. Exit 0 when tests pass (quiet). Exit 2 when they fail, with the last
lines of pytest output on stderr so the agent sees the failure immediately.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TAIL = 15


def python() -> str:
    for cand in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    return sys.executable


def main() -> int:
    sys.stdin.read()  # the hook payload is not needed
    proc = subprocess.run([python(), "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider"],
                          cwd=ROOT, capture_output=True, text=True, timeout=300)
    tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-TAIL:])
    if proc.returncode == 0:
        print(tail.splitlines()[-1] if tail else "tests passed")
        return 0
    print(f"Tests failed after this edit:\n{tail}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
