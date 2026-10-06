"""Quality gate: decide whether a transcript is fit to score.

A scoring system run on a bad transcript produces confident garbage, so a call
that fails any blocking check goes to the human-review queue with its reasons
and is never scored. Warnings are recorded but do not block.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from calleval.schema import Transcript

GATE_VERSION = "gate-v1"
MIN_TURNS = 8
MIN_DURATION_S = 45
MIN_MEAN_CONF = 0.70
MAX_INAUDIBLE_SHARE = 0.15
MAX_UNLABELLED_SHARE = 0.5


@dataclass
class GateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)  # blocking
    warnings: list[str] = field(default_factory=list)  # non-blocking
    stats: dict = field(default_factory=dict)


def check(tr: Transcript) -> GateResult:
    reasons, warnings = [], []
    n = len(tr.turns)
    words = [w for t in tr.turns for w in t.text.split()]
    inaudible = sum(w == "[inaudible]" for w in words) / max(1, len(words))
    mean_conf = sum(t.conf for t in tr.turns) / max(1, n)
    unlabelled = sum(t.speaker is None for t in tr.turns) / max(1, n)
    crosstalk = sum("[crosstalk]" in t.text for t in tr.turns)
    last = tr.turns[-1].text.rstrip() if n else ""

    if unlabelled > MAX_UNLABELLED_SHARE:
        reasons.append("no speaker labels: cannot tell caller from agent")
    if n < MIN_TURNS or tr.duration_s < MIN_DURATION_S:
        reasons.append(f"too short: {n} turns, {tr.duration_s}s")
    if last.endswith("...") or last.endswith("…"):
        reasons.append("call ended abruptly (dropped mid-sentence)")
    if mean_conf < MIN_MEAN_CONF:
        reasons.append(f"low ASR confidence: mean {mean_conf:.2f}")
    if inaudible > MAX_INAUDIBLE_SHARE:
        reasons.append(f"garbled: {inaudible:.0%} of words inaudible")
    if crosstalk > 1:
        reasons.append(f"heavy cross-talk: {crosstalk} overlapped turns")
    elif crosstalk == 1:
        warnings.append("one overlapped turn (cross-talk)")
    stats = {"turns": n, "mean_conf": round(mean_conf, 3), "inaudible_share": round(inaudible, 3),
             "unlabelled_share": round(unlabelled, 3), "crosstalk_turns": crosstalk}
    return GateResult(not reasons, reasons, warnings, stats)
