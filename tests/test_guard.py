"""The edit guard hook: feed it hook payloads, check the exit codes."""

import json
import subprocess
import sys

from calleval import paths

GUARD = paths.ROOT / ".claude" / "hooks" / "guard.py"


def run(payload, raw=None):
    data = raw if raw is not None else json.dumps(payload)
    return subprocess.run([sys.executable, str(GUARD)], input=data, capture_output=True, text=True, timeout=30)


def edit(path):
    return run({"tool_name": "Edit", "tool_input": {"file_path": str(path)}})


def test_blocks_golden_holdout_and_answer_key():
    for rel in ("data/golden/holdout_sealed.csv", "data/golden/dev.csv", "data/_answer_key/truth.jsonl",
                "data/calls.jsonl", "runs/holdout_ledger.json"):
        r = edit(paths.ROOT / rel)
        assert r.returncode == 2, rel
        assert "BLOCKED" in r.stderr


def test_blocks_relative_paths_too():
    assert edit("data/golden/dev.csv").returncode == 2


def test_blocks_acceptance_tests_but_not_the_edge_case_file():
    assert edit(paths.ROOT / "tests" / "test_holdout.py").returncode == 2
    assert edit(paths.ROOT / "tests" / "test_edge_cases.py").returncode == 0


def test_allows_source_docs_and_paths_outside_the_repo():
    for p in (paths.ROOT / "calleval" / "scoring.py", paths.ROOT / "README.md", paths.ROOT / "PLAN.md",
              paths.ROOT.parent / "elsewhere.txt"):
        assert edit(p).returncode == 0, p


def test_payload_without_a_path_is_allowed_and_bad_json_is_a_non_blocking_error():
    assert run({"tool_name": "Write", "tool_input": {}}).returncode == 0
    assert run(None, raw="not json").returncode == 1
