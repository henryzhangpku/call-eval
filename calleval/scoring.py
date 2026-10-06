"""Deterministic scoring from extracted fields. Code, not the model.

    satisfaction = f(resolved, effort)       per intent, then a worst-case-weighted roll-up
    sentiment    = g(expressed cues)         separate evidence

Every score carries the spans that produced it and a one-line explanation.
Retuning these weights never requires re-running an extractor.
"""

from __future__ import annotations

import math

from dataclasses import dataclass, field

from calleval.schema import INTENT_LABELS, CallExtraction, Cue, IntentExtraction, Span

SCORING_VERSION = "score-v1"

BASE = {"yes": 5.0, "partial": 3.5, "no": 2.0}
PENALTY = {"repeat": 0.5, "transfer": 0.75, "hold": 0.4, "callback": 0.5}
MAX_REPEATS_COUNTED = 3
WORST_WEIGHT = 0.65  # call score = 0.65 * worst intent + 0.35 * mean intent


@dataclass
class IntentScore:
    intent: str
    satisfaction: float
    valence: str  # positive / neutral / negative, from that intent's cues
    explanation: str
    spans: list[Span] = field(default_factory=list)


@dataclass
class CallScore:
    call_id: str
    satisfaction_raw: float  # continuous, 1..5
    csat: int  # rounded raw score
    sentiment: str
    satisfaction_explanation: str
    sentiment_explanation: str
    satisfaction_spans: list[Span]
    sentiment_spans: list[Span]
    intents: list[IntentScore]


def _times(n: int, word: str) -> str:
    return {1: f"{word} once", 2: f"{word} twice"}.get(n, f"{word} {n} times")


def score_intent(x: IntentExtraction) -> IntentScore:
    s = BASE[x.resolved]
    reps = min(x.repeats, MAX_REPEATS_COUNTED)
    s -= PENALTY["repeat"] * reps + PENALTY["transfer"] * x.transfers + PENALTY["hold"] * x.holds
    s -= PENALTY["callback"] * x.callback
    s = min(5.0, max(1.0, s))

    label = INTENT_LABELS[x.intent]
    parts = [{"yes": f"{label} resolved", "partial": f"{label} only partly resolved",
              "no": f"{label} not resolved"}[x.resolved]]
    if x.agent_claimed_resolved:
        parts[0] += " (agent said it was done, caller disagreed)"
    if reps:
        parts.append(_times(reps, "caller had to repeat"))
    if x.transfers:
        parts.append(_times(x.transfers, "transferred"))
    if x.holds:
        parts.append(_times(x.holds, "put on hold"))
    if x.callback:
        parts.append("told to expect or make a callback")
    spans = list(x.resolved_spans) + x.repeat_spans + x.transfer_spans + x.hold_spans + x.callback_spans

    vals = [c.valence for c in x.sentiment_cues]
    valence = "negative" if "negative" in vals else ("positive" if "positive" in vals else "neutral")
    return IntentScore(x.intent, round(s, 3), valence, "; ".join(parts), spans)


def _quote(c: Cue) -> str:
    return f"\"{c.span.text}\" (turn {c.span.turn})"


def sentiment_from_cues(intent_cues: list[list[Cue]], closing: list[Cue]) -> tuple[str, str, list[Span]]:
    """g: the caller's expressed feeling. Uses only what the caller said, never resolution or effort."""
    all_cues = [c for cs in intent_cues for c in cs]
    neg = [c for c in all_cues + closing if c.valence == "negative"]
    pos = [c for c in all_cues + closing if c.valence == "positive"]
    closing_val = closing[-1].valence if closing else None
    per_intent = ["negative" if any(c.valence == "negative" for c in cs) else
                  "positive" if any(c.valence == "positive" for c in cs) else "neutral" for cs in intent_cues]
    if neg and closing_val != "positive":
        return "not_happy", f"not happy: {_quote(neg[0])}", [c.span for c in neg]
    happy_share = per_intent.count("positive") * 2 >= max(1, len(per_intent))
    if closing_val == "positive" or (pos and happy_share and not neg):
        return "happy", f"happy: {_quote(pos[-1])}", [c.span for c in pos]
    neutral = [c for c in all_cues + closing if c.valence == "neutral"]
    why = f"mild: {_quote(neutral[-1])}" if neutral else "mild: no clear expression of feeling either way"
    spans = [c.span for c in (neutral[-1:] or [])]
    if pos and neg:
        why += ", mixed cues"
    return "mild", why, spans


def score_call(ex: CallExtraction) -> CallScore:
    intents = [score_intent(x) for x in ex.intents]
    sats = [i.satisfaction for i in intents]
    worst = min(intents, key=lambda i: i.satisfaction)
    raw = WORST_WEIGHT * worst.satisfaction + (1 - WORST_WEIGHT) * (sum(sats) / len(sats))
    raw = round(min(5.0, max(1.0, raw)), 3)
    csat = int(min(5, max(1, math.floor(raw + 0.5))))  # half-up, not banker's rounding
    if len(intents) == 1:
        expl = f"scored {csat}: {worst.explanation}"
    else:
        others = "; ".join(f"{i.explanation}" for i in intents if i is not worst)
        expl = f"scored {csat}: {worst.explanation} (worst of {len(intents)} intents; also {others})"
    sent, sent_expl, sent_spans = sentiment_from_cues([x.sentiment_cues for x in ex.intents], ex.closing_cues)
    sat_spans = [s for i in intents for s in i.spans]
    return CallScore(ex.call_id, raw, csat, sent, expl, sent_expl, sat_spans, sent_spans, intents)
