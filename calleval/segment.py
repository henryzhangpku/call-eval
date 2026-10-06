"""Intent segmentation: one call becomes N intents, each with a turn range.

Deterministic keyword detection on the caller's side of the transcript. Shared
by both extractor backends; the Jev backend can add intents this misses (for
example when ASR has mangled the keyword).
"""

from __future__ import annotations

from dataclasses import dataclass

from calleval.schema import Transcript

SEGMENTER_VERSION = "seg-v1"

INTENT_KEYWORDS = {
    "balance": ["balance", "how much do i still owe", "how much is left", "principal"],
    "payment": ["make my payment", "make a payment", "pay my mortgage", "trying to pay", "payment for this month"],
    "escrow": ["escrow", "shortage", "payment went up"],
    "payoff": ["payoff", "pay off", "selling the house", "refinance"],
    "hardship": ["hardship", "forbearance", "lost my job", "trouble paying", "money is tight"],
    "dispute": ["dispute", "don't recognize", "credit bureau", "reported me late", "inspection fee"],
    "late_fee": ["late fee", "fee removed", "fee on my account"],
}
CLOSING_MARKERS = ["anything else i can help", "anything else"]
OPENING_END = 4  # turns 0-4 are greeting and verification in this desk's script


@dataclass
class Segment:
    intent: str
    start: int
    end: int  # inclusive
    source: str  # "keyword" or "model"


def closing_turn(tr: Transcript) -> int | None:
    for t in reversed(tr.turns):
        if t.speaker != "caller" and any(m in t.text.lower() for m in CLOSING_MARKERS):
            return t.idx
    return None


def detect(tr: Transcript) -> dict[str, int]:
    """First caller turn that raises each intent."""
    found: dict[str, int] = {}
    for t in tr.turns:
        if t.speaker != "caller":
            continue
        low = t.text.lower()
        for intent, kws in INTENT_KEYWORDS.items():
            if intent not in found and any(k in low for k in kws):
                found[intent] = t.idx
    return found


def segments_from_starts(tr: Transcript, starts: dict[str, int]) -> list[Segment]:
    close = closing_turn(tr)
    last = (close - 1) if close is not None else len(tr.turns) - 1
    order = sorted(starts.items(), key=lambda kv: kv[1])
    out = []
    for i, (intent, s) in enumerate(order):
        e = order[i + 1][1] - 1 if i + 1 < len(order) else last
        out.append(Segment(intent, s, max(s, e), "keyword"))
    return out


def segment(tr: Transcript) -> list[Segment]:
    return segments_from_starts(tr, detect(tr))


def conversation_range(tr: Transcript) -> tuple[int, int]:
    """The body of the call: after verification, before the closing question."""
    close = closing_turn(tr)
    lo = min(OPENING_END + 1, len(tr.turns) - 1)
    hi = (close - 1) if close is not None else len(tr.turns) - 1
    return lo, max(lo, hi)
