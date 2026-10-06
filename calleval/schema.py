"""The fixed, typed schema that every extractor must fill, and its validation.

An extractor (rule-based or model) never produces a score. It produces an
`IntentExtraction` per intent: categorical and count fields, each backed by
evidence spans that point at real transcript text. Scoring happens later, in
code (`calleval.scoring`).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

INTENTS = ("balance", "payment", "escrow", "payoff", "hardship", "dispute", "late_fee")
RESOLVED = ("yes", "partial", "no")
SENTIMENTS = ("happy", "mild", "not_happy")
CUE_VALENCE = ("positive", "neutral", "negative")
SPEAKERS = ("agent", "caller")

INTENT_LABELS = {
    "balance": "balance enquiry",
    "payment": "making a payment",
    "escrow": "escrow change",
    "payoff": "payoff quote",
    "hardship": "hardship / forbearance",
    "dispute": "disputed charge or credit report",
    "late_fee": "late fee",
}


class SchemaError(ValueError):
    """An extraction that does not satisfy the schema."""


@dataclass(frozen=True)
class Turn:
    idx: int
    speaker: str | None  # None when the ASR lost speaker labels
    t: float
    text: str
    conf: float  # ASR confidence, 0..1


@dataclass
class Transcript:
    call_id: str
    date: str
    agent_id: str
    duration_s: int
    turns: list[Turn]

    @classmethod
    def from_dict(cls, d: dict) -> "Transcript":
        turns = [Turn(idx=i, speaker=t.get("speaker"), t=float(t["t"]), text=t["text"], conf=float(t["conf"]))
                 for i, t in enumerate(d["turns"])]
        return cls(d["call_id"], d["date"], d["agent_id"], int(d["duration_s"]), turns)


@dataclass(frozen=True)
class Span:
    """A quoted piece of a transcript turn: turns[turn].text[start:end] == text."""

    turn: int
    start: int
    end: int
    text: str

    @classmethod
    def whole_turn(cls, turn: Turn) -> "Span":
        return cls(turn.idx, 0, len(turn.text), turn.text)

    @classmethod
    def find(cls, turn: Turn, needle: str) -> "Span":
        """Span of the first case-insensitive occurrence of needle, else the whole turn."""
        i = turn.text.lower().find(needle.lower())
        if i < 0:
            return cls.whole_turn(turn)
        return cls(turn.idx, i, i + len(needle), turn.text[i:i + len(needle)])


@dataclass
class Cue:
    valence: str
    span: Span


@dataclass
class IntentExtraction:
    intent: str
    segment: tuple[int, int]  # first and last turn index, inclusive
    resolved: str
    resolved_spans: list[Span] = field(default_factory=list)
    repeats: int = 0
    repeat_spans: list[Span] = field(default_factory=list)
    transfers: int = 0
    transfer_spans: list[Span] = field(default_factory=list)
    holds: int = 0
    hold_spans: list[Span] = field(default_factory=list)
    callback: bool = False
    callback_spans: list[Span] = field(default_factory=list)
    sentiment_cues: list[Cue] = field(default_factory=list)
    confidence: float = 1.0  # extractor's confidence in `resolved`, 0..1
    agent_claimed_resolved: bool = False  # agent said it was fixed (scored from the caller side instead)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["segment"] = list(self.segment)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "IntentExtraction":
        sp = lambda xs: [Span(**s) for s in xs]  # noqa: E731
        return cls(
            intent=d["intent"], segment=tuple(d["segment"]), resolved=d["resolved"],
            resolved_spans=sp(d["resolved_spans"]), repeats=d["repeats"], repeat_spans=sp(d["repeat_spans"]),
            transfers=d["transfers"], transfer_spans=sp(d["transfer_spans"]), holds=d["holds"],
            hold_spans=sp(d["hold_spans"]), callback=d["callback"], callback_spans=sp(d["callback_spans"]),
            sentiment_cues=[Cue(c["valence"], Span(**c["span"])) for c in d["sentiment_cues"]],
            confidence=d["confidence"], agent_claimed_resolved=d.get("agent_claimed_resolved", False),
        )


@dataclass
class CallExtraction:
    call_id: str
    intents: list[IntentExtraction]
    closing_cues: list[Cue] = field(default_factory=list)
    meta: dict = field(default_factory=dict)  # backend, model id, question version, latency, tokens


def validate_span(span: Span, transcript: Transcript) -> None:
    if not (0 <= span.turn < len(transcript.turns)):
        raise SchemaError(f"span turn {span.turn} out of range")
    text = transcript.turns[span.turn].text
    if not (0 <= span.start <= span.end <= len(text)):
        raise SchemaError(f"span offsets {span.start}:{span.end} out of range for turn {span.turn}")
    if text[span.start:span.end] != span.text:
        raise SchemaError(f"span text does not match turn {span.turn}: {span.text!r}")
    if not span.text.strip():
        raise SchemaError(f"empty span at turn {span.turn}")


def validate_intent(x: IntentExtraction, transcript: Transcript) -> None:
    if x.intent not in INTENTS:
        raise SchemaError(f"unknown intent {x.intent!r}")
    if x.resolved not in RESOLVED:
        raise SchemaError(f"resolved must be one of {RESOLVED}, got {x.resolved!r}")
    lo, hi = x.segment
    if not (0 <= lo <= hi < len(transcript.turns)):
        raise SchemaError(f"segment {x.segment} out of range")
    for name in ("repeats", "transfers", "holds"):
        v = getattr(x, name)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise SchemaError(f"{name} must be a non-negative int, got {v!r}")
    if not isinstance(x.callback, bool):
        raise SchemaError("callback must be a bool")
    if not (0.0 <= x.confidence <= 1.0):
        raise SchemaError("confidence must be in [0, 1]")
    for c in x.sentiment_cues:
        if c.valence not in CUE_VALENCE:
            raise SchemaError(f"cue valence {c.valence!r}")
    if not x.resolved_spans:
        raise SchemaError(f"intent {x.intent}: resolved needs at least one evidence span")
    if x.transfers and not x.transfer_spans:
        raise SchemaError(f"intent {x.intent}: transfers > 0 needs evidence")
    if x.holds and not x.hold_spans:
        raise SchemaError(f"intent {x.intent}: holds > 0 needs evidence")
    if x.callback and not x.callback_spans:
        raise SchemaError(f"intent {x.intent}: callback needs evidence")
    for s in all_spans(x):
        validate_span(s, transcript)


def all_spans(x: IntentExtraction) -> list[Span]:
    out = list(x.resolved_spans) + x.repeat_spans + x.transfer_spans + x.hold_spans + x.callback_spans
    out += [c.span for c in x.sentiment_cues]
    return out


def validate_call(ex: CallExtraction, transcript: Transcript) -> None:
    if ex.call_id != transcript.call_id:
        raise SchemaError("call id mismatch")
    if not ex.intents:
        raise SchemaError("a scored call needs at least one intent")
    seen = set()
    for x in ex.intents:
        if x.intent in seen:
            raise SchemaError(f"duplicate intent {x.intent}")
        seen.add(x.intent)
        validate_intent(x, transcript)
    for c in ex.closing_cues:
        if c.valence not in CUE_VALENCE:
            raise SchemaError(f"cue valence {c.valence!r}")
        validate_span(c.span, transcript)
