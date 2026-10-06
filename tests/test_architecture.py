"""Mechanical checks of the working agreement in CLAUDE.md."""

import re

from calleval import paths

SRC = paths.ROOT / "calleval"


def _sources():
    return {p.relative_to(paths.ROOT).as_posix(): p.read_text(encoding="utf-8") for p in SRC.rglob("*.py")}


def test_only_the_jev_extractor_calls_a_model():
    users = [f for f, s in _sources().items() if re.search(r"\btypesafe_sdk\b", s)]
    assert users == ["calleval/extract/jev.py"]


def test_only_evaluate_holdout_reads_the_sealed_holdout():
    users = [f for f, s in _sources().items() if "GOLDEN_HOLDOUT" in s and f != "calleval/paths.py"]
    assert users == ["calleval/evaluate.py"]
    src = (SRC / "evaluate.py").read_text(encoding="utf-8")
    body = src.split("def evaluate_holdout")[1]
    assert "GOLDEN_HOLDOUT" in body
    assert src.count("GOLDEN_HOLDOUT") == 1


def test_scoring_never_imports_an_extractor():
    src = (SRC / "scoring.py").read_text(encoding="utf-8")
    assert "calleval.extract" not in src and "typesafe" not in src


def test_answer_key_is_not_used_by_the_pipeline():
    for f, s in _sources().items():
        if "ANSWER_KEY" in s:
            assert f in ("calleval/paths.py", "calleval/evaluate.py"), f
