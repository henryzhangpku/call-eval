"""Rule-based offline extractor. Deterministic, no network, no key.

It exists so every part of the system runs anywhere, and as the baseline the
model backend has to beat. Its lexicons were written by reading dev-set
transcripts only; it has never seen the sealed holdout.
"""

from __future__ import annotations

import time

from calleval.extract import locate as L
from calleval.schema import CallExtraction, IntentExtraction, Span, Transcript
from calleval.segment import closing_turn, segment

RULES_VERSION = "rules-v1"

OUTCOME_PARTIAL = ["business days", "requested", "submitted", "escalated", "review", "estimate", "ticket",
                   "half of the fee", "won't post until", "the rest will need", "supervisor approval",
                   "i'll email", "isn't loading", "until tonight", "ordered separately"]
OUTCOME_NO = ["can't", "cannot", "not able", "unable", "not authorized", "won't accept", "declined",
              "nothing i can do", "don't qualify", "have to be requested by", "stands", "as far as i can take it",
              "locked"]
OUTCOME_YES = ["scheduled", "confirmation", "went through", "all set", "removed", "reversed", "spread",
               "on its way", "sent", "approved", "you qualify", "currently owe", "balance is", "remaining",
               "correction", "it's showing", "is on its way", "forbearance. i'll send"]


def classify_outcome(text: str) -> tuple[str, str, float] | None:
    """(label, matched phrase, confidence) for an agent turn, or None if it states no outcome."""
    low = text.lower()
    hits = {}
    for label, kws in (("partial", OUTCOME_PARTIAL), ("no", OUTCOME_NO), ("yes", OUTCOME_YES)):
        found = [k for k in kws if k in low]
        if found:
            hits[label] = found[0]
    if not hits:
        return None
    # precedence: a deferral beats a refusal ("I can't adjust it until the review"), a refusal beats a success word
    for label in ("partial", "no", "yes"):
        if label in hits:
            return label, hits[label], (0.9 if len(hits) == 1 else 0.6)
    return None


class RuleExtractor:
    backend = "offline"
    model_id = RULES_VERSION
    question_version = RULES_VERSION

    def extract_calls(self, transcripts: list[Transcript]) -> list[CallExtraction]:
        return [self.extract(tr) for tr in transcripts]

    def extract(self, tr: Transcript) -> CallExtraction:
        t0 = time.perf_counter()
        intents = []
        for seg in segment(tr):
            intents.append(self.extract_intent(tr, seg.intent, seg.start, seg.end))
        close = closing_turn(tr)
        closing = L.sentiment_cues(tr, close + 1, len(tr.turns) - 1) if close is not None else []
        meta = {"backend": self.backend, "model_id": self.model_id, "question_version": self.question_version,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 3), "requests": 0,
                "input_tokens": 0, "segment_sources": {x.intent: "keyword" for x in intents}}
        return CallExtraction(tr.call_id, intents, closing, meta)

    def extract_intent(self, tr: Transcript, intent: str, lo: int, hi: int) -> IntentExtraction:
        resolved, conf, spans = None, 0.3, []
        for t in reversed(L.not_caller(tr, lo, hi)):
            out = classify_outcome(t.text)
            if out:
                resolved, phrase, conf = out
                spans = [Span.find(t, phrase)]
                break
        claimed = False
        contest = L.claim_contested(tr, lo, hi)
        if contest:
            resolved, conf, spans, claimed = "no", 0.8, list(contest), True
        if resolved is None:
            # no outcome statement found: say so, cite the last agent turn of the segment
            agent_turns = L.not_caller(tr, lo, hi) or tr.turns[lo:hi + 1]
            resolved, spans = "partial", [Span.whole_turn(agent_turns[-1])]
        rep, tra, hol, cb = L.repeats(tr, lo, hi), L.transfers(tr, lo, hi), L.holds(tr, lo, hi), L.callbacks(tr, lo, hi)
        return IntentExtraction(
            intent=intent, segment=(lo, hi), resolved=resolved, resolved_spans=spans,
            repeats=len(rep), repeat_spans=rep, transfers=len(tra), transfer_spans=tra,
            holds=len(hol), hold_spans=hol, callback=bool(cb), callback_spans=cb[:1],
            sentiment_cues=L.sentiment_cues(tr, lo, hi), confidence=conf, agent_claimed_resolved=claimed,
        )
