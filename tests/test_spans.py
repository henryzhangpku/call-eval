"""Span integrity: every piece of evidence points at real transcript text."""

import json

from calleval import paths
from calleval.extract.jev import JevExtractor
from calleval.extract.offline import RuleExtractor
from calleval.pipeline import load_calls, load_splits
from calleval.quality import check
from calleval.schema import all_spans, validate_call


def _check_spans(ex, tr):
    validate_call(ex, tr)
    for x in ex.intents:
        lo, hi = x.segment
        for s in all_spans(x):
            assert tr.turns[s.turn].text[s.start:s.end] == s.text
        for s in x.resolved_spans:
            assert lo <= s.turn <= hi, "outcome evidence must lie inside the segment of that intent"


def test_offline_spans_point_at_real_text():
    for tr in load_calls():
        if check(tr).passed:
            ex = RuleExtractor().extract(tr)
            if ex.intents:  # calls with no detected intent go to review, not scoring
                _check_spans(ex, tr)


def test_jev_cached_spans_point_at_real_text():
    """Replays the committed Jev cache (no network, no key) on the dev split."""
    dev = set(load_splits()["dev"])
    calls = [tr for tr in load_calls() if tr.call_id in dev and check(tr).passed]
    exs = JevExtractor(offline_only=True).extract_calls(calls)
    by = {c.call_id: c for c in calls}
    errors = [ex.meta["error"] for ex in exs if ex.meta.get("error")]
    assert not errors, errors[:3]
    for ex in exs:
        if ex.intents:
            _check_spans(ex, by[ex.call_id])


def test_prediction_rows_spans_match_transcripts():
    calls = {tr.call_id: tr for tr in load_calls()}
    for run in ("offline", "jev"):
        p = paths.RUNS / run / "predictions.jsonl"
        for line in p.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            for s in row.get("satisfaction_spans", []) + row.get("sentiment_spans", []):
                assert calls[row["call_id"]].turns[s["turn"]].text[s["start"]:s["end"]] == s["text"]
