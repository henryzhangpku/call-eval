import dataclasses
import json

from calleval import paths
from calleval.extract.offline import RuleExtractor
from calleval.pipeline import load_calls
from calleval.quality import check
from calleval.schema import IntentExtraction, Span
from calleval.scoring import score_call, score_intent


def _x(**kw):
    base = dict(intent="payoff", segment=(5, 9), resolved="yes", resolved_spans=[Span(6, 0, 4, "Done")])
    base.update(kw)
    return IntentExtraction(**base)


def test_scoring_is_deterministic():
    calls = [tr for tr in load_calls() if check(tr).passed]
    exs = [RuleExtractor().extract(tr) for tr in calls]
    exs = [e for e in exs if e.intents]
    a = [score_call(e) for e in exs]
    b = [score_call(RuleExtractor().extract(next(t for t in calls if t.call_id == e.call_id))) for e in exs]
    assert [dataclasses.asdict(x) for x in a] == [dataclasses.asdict(x) for x in b]


def test_resolution_orders_satisfaction():
    assert score_intent(_x(resolved="yes")).satisfaction > score_intent(_x(resolved="partial")).satisfaction \
        > score_intent(_x(resolved="no")).satisfaction


def test_effort_lowers_satisfaction_and_is_explained():
    s0 = score_intent(_x(resolved="no"))
    sp = [Span(7, 0, 4, "Done")]
    s1 = score_intent(_x(resolved="no", repeats=3, repeat_spans=sp, transfers=2, transfer_spans=sp))
    assert s1.satisfaction < s0.satisfaction
    assert "payoff quote not resolved" in s1.explanation
    assert "caller had to repeat 3 times" in s1.explanation and "transferred twice" in s1.explanation


def test_score_is_bounded():
    sp = [Span(7, 0, 4, "Done")]
    s = score_intent(_x(resolved="no", repeats=9, repeat_spans=sp, transfers=5, transfer_spans=sp, holds=4,
                        hold_spans=sp, callback=True, callback_spans=sp))
    assert 1.0 <= s.satisfaction <= 5.0


def test_sentiment_ignores_resolution():
    """Sentiment is expressed feeling only: changing resolution must not change it."""
    from calleval.schema import CallExtraction, Cue
    cue = [Cue("neutral", Span(8, 0, 4, "Okay"))]
    a = score_call(CallExtraction("X", [_x(resolved="yes", sentiment_cues=cue)]))
    b = score_call(CallExtraction("X", [_x(resolved="no", sentiment_cues=cue)]))
    assert a.sentiment == b.sentiment == "mild"
    assert a.csat > b.csat


def test_every_scored_call_carries_spans_and_an_explanation():
    for line in (paths.RUNS / "offline" / "predictions.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["status"] == "scored":
            assert row["satisfaction_spans"]
            assert row["satisfaction_explanation"].startswith(f"scored {row['csat']}:")
            assert row["sentiment_explanation"].split(":")[0] in ("happy", "mild", "not happy")
            for k in ("model_id", "question_version", "extractor_backend", "code_version", "scoring_version"):
                assert row["versions"][k]
