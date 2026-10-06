"""Lexical evidence locators shared by the rule extractor and the Jev backend.

These find candidate turns for effort signals and sentiment cues and return
spans quoting the exact matched text.
"""

from __future__ import annotations

from calleval.schema import Cue, Span, Transcript, Turn

CLARIFY = ["repeat that", "say that again", "breaking up", "are you asking about"]
CALLER_REPEAT = ["as i mentioned", "like i said", "again,", "already told you", "i've said this"]
TRANSFER = ["transfer you", "connect you with"]
HOLD = ["on a brief hold", "hold for a moment", "put you on hold", "place you on hold"]
CALLBACK = ["call you back", "call back", "reach out"]
CLAIM = ["taken care of", "that's sorted", "so that's sorted", "you're all set"]
CONTEST = ["haven't actually", "nothing actually", "doesn't answer", "didn't fix", "that's not what i asked"]

POSITIVE = ["thank you so much", "relief", "perfect", "wonderful", "really helpful", "great", "appreciate",
            "made my day", "thanks so much"]
NEGATIVE = ["ridiculous", "frustrated", "not acceptable", "wasted", "upset", "complaint", "mess",
            "already told you", "said this twice", "hope someone actually"]
NEUTRAL_OVERRIDE = ["thanks for trying", "thank you anyway"]
NEUTRAL = ["okay", "alright", "fine", "got it", "that's it", "that's all", "that's everything"]


def first_match(turn: Turn, needles: list[str]) -> str | None:
    low = turn.text.lower()
    hits = [(low.find(n), n) for n in needles if n in low]
    return min(hits)[1] if hits else None


def turns_in(tr: Transcript, lo: int, hi: int, speaker: str | None = None) -> list[Turn]:
    return [t for t in tr.turns[lo:hi + 1] if speaker is None or t.speaker == speaker]


def locate(tr: Transcript, lo: int, hi: int, needles: list[str], speaker: str | None) -> list[Span]:
    out = []
    for t in turns_in(tr, lo, hi, speaker):
        m = first_match(t, needles)
        if m:
            out.append(Span.find(t, m))
    return out


def not_caller(tr, lo, hi):
    return [t for t in tr.turns[lo:hi + 1] if t.speaker != "caller"]


def repeats(tr: Transcript, lo: int, hi: int) -> list[Span]:
    agent = [Span.find(t, m) for t in not_caller(tr, lo, hi) if (m := first_match(t, CLARIFY))]
    caller = locate(tr, lo, hi, CALLER_REPEAT, "caller")
    return caller if len(caller) >= len(agent) else agent


def transfers(tr, lo, hi):
    return [Span.find(t, m) for t in not_caller(tr, lo, hi) if (m := first_match(t, TRANSFER))]


def holds(tr, lo, hi):
    return [Span.find(t, m) for t in not_caller(tr, lo, hi) if (m := first_match(t, HOLD))]


def callbacks(tr, lo, hi):
    return [Span.find(t, m) for t in not_caller(tr, lo, hi) if (m := first_match(t, CALLBACK))]


def cue_for(turn: Turn) -> Cue | None:
    m = first_match(turn, NEUTRAL_OVERRIDE)
    if m:
        return Cue("neutral", Span.find(turn, m))
    m = first_match(turn, NEGATIVE)
    if m:
        return Cue("negative", Span.find(turn, m))
    m = first_match(turn, POSITIVE)
    if m:
        return Cue("positive", Span.find(turn, m))
    m = first_match(turn, NEUTRAL)
    if m:
        return Cue("neutral", Span.find(turn, m))
    return None


def sentiment_cues(tr: Transcript, lo: int, hi: int) -> list[Cue]:
    return [c for t in turns_in(tr, lo, hi, "caller") if (c := cue_for(t))]


def claim_contested(tr: Transcript, lo: int, hi: int) -> tuple[Span, Span] | None:
    """An agent claims it is done and the caller's next turn says otherwise."""
    ts = tr.turns[lo:hi + 1]
    for a, b in zip(ts, ts[1:]):
        if a.speaker != "caller" and b.speaker == "caller":
            ma, mb = first_match(a, CLAIM), first_match(b, CONTEST)
            if ma and mb:
                return Span.find(a, ma), Span.find(b, mb)
    return None
