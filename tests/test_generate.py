import csv
import json

from calleval import paths
from calleval.generate import generate


def test_generator_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate(out=a)
    generate(out=b)
    for rel in ("calls.jsonl", "surveys.csv", "golden/dev.csv", "golden/holdout_sealed.csv", "_answer_key/truth.jsonl"):
        assert (a / rel).read_bytes() == (b / rel).read_bytes(), rel


def test_committed_data_matches_generator(tmp_path):
    generate(out=tmp_path)
    assert (tmp_path / "calls.jsonl").read_bytes() == paths.CALLS.read_bytes()


def test_shape_of_the_data():
    truth = [json.loads(l) for l in paths.ANSWER_KEY.read_text(encoding="utf-8").splitlines()]
    assert len(truth) == 400
    # the polite-but-unresolved quadrant exists
    assert sum(t["csat"] <= 2 and t["sentiment"] != "not_happy" for t in truth) >= 20
    assert sum(len(t["intents"]) > 1 for t in truth) >= 100  # multi-intent calls
    mess = {m for t in truth for m in t["mess"]}
    assert {"asr_substitutions", "no_speaker_labels", "dropped_call", "cross_talk", "garbled_audio"} <= mess
    with open(paths.SURVEYS, encoding="utf-8") as f:
        surveys = {r["call_id"]: int(r["survey_csat"]) for r in csv.DictReader(f)}
    assert 100 <= len(surveys) <= 170  # about a third
    by = {t["call_id"]: t for t in truth}
    low = [t for t in truth if t["csat"] <= 2]
    high = [t for t in truth if t["csat"] >= 4]
    rate = lambda ts: sum(t["call_id"] in surveys for t in ts) / len(ts)  # noqa: E731
    assert rate(low) > rate(high)  # response bias: unhappy callers answer more
    assert all(by[c] for c in surveys)


def test_golden_split_is_200_100_and_disjoint():
    s = json.loads(paths.SPLITS.read_text(encoding="utf-8"))
    assert len(s["dev"]) == 200 and len(s["holdout"]) == 100
    assert not set(s["dev"]) & set(s["holdout"])
    with open(paths.GOLDEN_DEV, encoding="utf-8") as f:
        dev = list(csv.DictReader(f))
    assert {r["call_id"] for r in dev} == set(s["dev"])
    disagree = sum(r["a_csat"] != r["b_csat"] for r in dev)
    assert 0.2 < disagree / len(dev) < 0.6  # realistic, not perfect, annotator agreement
