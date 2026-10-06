"""Edge cases. This is the one test file agents (including the reviewer subagent) may extend."""

from calleval.quality import check
from calleval.schema import Span, Transcript, Turn
from calleval.scoring import sentiment_from_cues


def test_span_find_falls_back_to_whole_turn_when_needle_missing():
    t = Turn(idx=3, speaker="agent", t=0.0, text="Your balance is $1,000.", conf=0.9)
    s = Span.find(t, "not in the text")
    assert (s.start, s.end, s.text) == (0, len(t.text), t.text)


def test_span_find_is_case_insensitive_but_quotes_original_case():
    t = Turn(idx=0, speaker="caller", t=0.0, text="This is RIDICULOUS.", conf=0.9)
    s = Span.find(t, "ridiculous")
    assert s.text == "RIDICULOUS" and t.text[s.start:s.end] == s.text


def test_gate_handles_an_empty_transcript():
    tr = Transcript("X", "2026-09-14", "A01", 0, [])
    r = check(tr)
    assert not r.passed and any("too short" in x for x in r.reasons)


def test_sentiment_with_no_cues_is_mild_and_says_why():
    s, why, spans = sentiment_from_cues([[]], [])
    assert s == "mild" and "no clear expression" in why and spans == []
