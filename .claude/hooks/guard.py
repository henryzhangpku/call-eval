"""PreToolUse guard for Edit / Write / MultiEdit.

Reads the hook payload (JSON) from stdin and blocks edits to paths that must
never be hand-edited by an agent:

  - the generated golden set, sealed holdout and answer key (regenerate with
    `python -m calleval generate` instead; editing labels by hand is leakage)
  - the holdout ledger (it is the audit trail of the one-time holdout reads)
  - the acceptance tests (an agent must not weaken the tests it is judged by;
    new edge-case tests go in tests/test_edge_cases.py, which is allowed)

Exit codes follow the hook contract: 0 allows, 2 blocks and the message on
stderr is shown to the agent. A payload with no file path is allowed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]

PROTECTED_PREFIXES = (
    "data/golden/",
    "data/_answer_key/",
)
PROTECTED_FILES = {
    "data/calls.jsonl",
    "data/surveys.csv",
    "runs/holdout_ledger.json",
}
ACCEPTANCE_TESTS = "tests/test_"
ALLOWED_TESTS = {"tests/test_edge_cases.py"}


def relative(path_str: str) -> str | None:
    """Repo-relative POSIX path, or None if the path is outside the repository."""
    p = Path(path_str)
    if not p.is_absolute():
        p = ROOT / p
    try:
        rel = p.resolve().relative_to(ROOT)
    except ValueError:
        return None
    return PurePosixPath(rel.as_posix()).as_posix()


def verdict(path_str: str) -> str | None:
    """A reason to block, or None to allow."""
    rel = relative(path_str)
    if rel is None:
        return None
    if rel in PROTECTED_FILES or rel.startswith(PROTECTED_PREFIXES):
        return (f"{rel} is generated data or an audit record. Do not edit it by hand: change "
                "calleval/generate.py and run `python -m calleval generate`, or leave the ledger alone.")
    if rel.startswith(ACCEPTANCE_TESTS) and rel.endswith(".py") and rel not in ALLOWED_TESTS:
        return (f"{rel} is an acceptance test. Never weaken a test to make code pass. If the test is "
                "wrong, stop and ask the owner. New edge-case tests go in tests/test_edge_cases.py.")
    return None


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        print("guard.py: hook payload was not JSON; allowing", file=sys.stderr)
        return 1  # non-blocking error
    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not path:
        return 0
    reason = verdict(path)
    if reason:
        print(f"BLOCKED by .claude/hooks/guard.py: {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
