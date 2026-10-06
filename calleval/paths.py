"""Where everything lives. All paths are relative to the repository root."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CALLS = DATA / "calls.jsonl"
SURVEYS = DATA / "surveys.csv"
GOLDEN_DEV = DATA / "golden" / "dev.csv"
SPLITS = DATA / "golden" / "splits.json"
GOLDEN_HOLDOUT = DATA / "golden" / "holdout_sealed.csv"
ANSWER_KEY = DATA / "_answer_key" / "truth.jsonl"
CACHE = ROOT / "cache"
JEV_CACHE = CACHE / "jev_cache.jsonl"
RUNS = ROOT / "runs"
LEDGER = ROOT / "runs" / "holdout_ledger.json"
DOCS_DATA = ROOT / "docs" / "data" / "demo.json"
