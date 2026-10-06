import json

from calleval import paths
from calleval.pipeline import load_calls
from calleval.quality import check
from calleval.schema import Transcript


def make(turns, duration=200):
    return Transcript.from_dict({"call_id": "X", "date": "2026-09-14", "agent_id": "A01", "duration_s": duration,
                                 "turns": [{"speaker": s, "t": i * 5.0, "text": t, "conf": c}
                                           for i, (s, t, c) in enumerate(turns)]})


CLEAN = [("agent", "Thank you for calling, how can I help?", 0.92), ("caller", "I need my balance.", 0.9),
         ("agent", "Sure, let me look.", 0.93), ("agent", "Your balance is $120,000.", 0.9),
         ("caller", "Great, thank you so much.", 0.91), ("agent", "Is there anything else I can help you with today?", 0.92),
         ("caller", "No, that's it.", 0.9), ("agent", "Thank you for calling, have a good day.", 0.93)]


def test_clean_call_passes():
    assert check(make(CLEAN)).passed


def test_missing_speaker_labels_blocked():
    r = check(make([(None, t, c) for _, t, c in CLEAN]))
    assert not r.passed and any("speaker" in x for x in r.reasons)


def test_too_short_blocked():
    r = check(make(CLEAN[:4]))
    assert not r.passed and any("too short" in x for x in r.reasons)


def test_low_confidence_and_garbled_blocked():
    r = check(make([(s, "[inaudible] [inaudible] " + t, 0.5) for s, t, _ in CLEAN]))
    assert not r.passed
    assert any("confidence" in x for x in r.reasons) and any("garbled" in x for x in r.reasons)


def test_dropped_call_blocked():
    r = check(make(CLEAN[:-1] + [("agent", "Let me just pull up the ...", 0.9)]))
    assert not r.passed and any("abruptly" in x for x in r.reasons)


def test_gate_catches_every_bad_transcript_in_the_data():
    truth = {json.loads(l)["call_id"]: json.loads(l) for l in paths.ANSWER_KEY.read_text(encoding="utf-8").splitlines()}
    for tr in load_calls():
        bad = {"no_speaker_labels", "garbled_audio", "dropped_call"} & set(truth[tr.call_id]["mess"])
        if bad:
            assert not check(tr).passed, (tr.call_id, bad)
