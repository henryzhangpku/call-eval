"""Jev backend: TypeSafe's System One model via the typesafe-sdk package.

Jev returns typed answers (Choice labels with probabilities, Noul yes/no
probabilities), never prose and never a score. Two stages per call:

  1. call level   which intents does the caller raise (Noul per intent), and
                  how does the caller sound at the close (Choice)
  2. per intent   resolved yes/partial/no, effort counts, callback, expressed
                  feeling, and which numbered turn is the evidence (Choice over
                  the turn labels, so the model cites real turns)

The SDK reads TYPESAFE_API_KEY from the environment itself. This module never
reads, prints or stores it. Every response is cached on disk keyed by
(model, question version, state, questions), so a run reproduces without a key.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from calleval import paths
from calleval.extract import locate as L
from calleval.schema import (INTENT_LABELS, INTENTS, CallExtraction, Cue, IntentExtraction, Span, Transcript)
from calleval.segment import closing_turn, conversation_range, detect, segments_from_starts

JEV_MODEL = "jev-1.13.0"  # pinned; the API default "jev-latest" moves
QUESTION_VERSION = "q-v2"  # q-v1 -> q-v2: sharper intent definitions, per-type effort evidence (see METHODOLOGY.md)
INTENT_THRESHOLD = 0.8

INTENT_DEFS = {
    "balance": "a balance enquiry: asking how much is currently owed on the loan (not a payoff quote for selling or refinancing)",
    "payment": "making a payment on this call, or having trouble making one",
    "escrow": "an escrow question: an escrow shortage, or why the monthly payment went up",
    "payoff": "a payoff quote or payoff statement, for selling the home or refinancing",
    "hardship": "financial hardship, forbearance, or trouble affording the payments",
    "dispute": "disputing a charge, a fee other than a late fee, or a credit-bureau report",
    "late_fee": "a late fee: why it was charged, or asking for it to be removed",
}
TURN_SNIPPET = 110


def render(tr: Transcript, lo: int, hi: int) -> str:
    lines = ["Loan-servicing phone call transcript (synthetic). Turns are numbered [n]."]
    for t in tr.turns[lo:hi + 1]:
        who = {"agent": "AGENT", "caller": "CALLER"}.get(t.speaker or "", "UNKNOWN SPEAKER")
        lines.append(f"[{t.idx}] {who}: {t.text}")
    return "\n".join(lines)


def turn_options(tr: Transcript, lo: int, hi: int, speaker: str | None, none_text: str) -> dict[str, str]:
    opts = {}
    for t in tr.turns[lo:hi + 1]:
        if speaker is None or t.speaker == speaker:
            txt = t.text if len(t.text) <= TURN_SNIPPET else t.text[:TURN_SNIPPET] + "..."
            opts[f"t{t.idx}"] = f"turn [{t.idx}]: {txt}"
    opts["none"] = none_text
    return opts


def call_questions() -> dict:
    q = {f"intent_{i}": {"type": "noul", "instructions":
                         f"Does the caller themselves raise {INTENT_DEFS[i]}, at any point in this call?"}
         for i in INTENTS}
    q["closing_feel"] = {"type": "choice", "instructions":
                         "In the caller's last turn or two, after the agent asks whether there is anything else, how "
                         "does the caller come across from what they actually say?",
                         "criteria": {"positive": "warm, pleased or genuinely thankful",
                                      "neutral": "flat, matter-of-fact, or polite without real warmth",
                                      "negative": "annoyed, upset, complaining or threatening to complain"}}
    return q


def intent_questions(tr: Transcript, intent: str, lo: int, hi: int) -> dict:
    label = INTENT_LABELS[intent]
    count = lambda what: {"0": f"no {what}", "1": f"one {what}", "2": f"two {what}s",  # noqa: E731
                          "3": f"three or more {what}s"}
    return {
        "resolved": {"type": "choice", "instructions":
                     f"Consider only the caller's {label} request. By the end of this part of the call, was it resolved? "
                     "Judge from the caller's side: if the agent says it is done but the caller disputes that, it is not resolved.",
                     "criteria": {"yes": "fully handled on this call: the caller got the answer or the change they asked for",
                                  "partial": "partly handled, or deferred to a later step such as a review, a ticket, a "
                                             "document still to come, or a callback",
                                  "no": "not handled: refused, not possible, or the caller was left without an answer"}},
        "resolved_turn": {"type": "choice", "instructions":
                          f"Which single turn best shows the outcome of the caller's {label} request?",
                          "criteria": turn_options(tr, lo, hi, None, "no turn states an outcome")},
        "repeats": {"type": "choice", "instructions":
                    f"How many times did the caller have to repeat or restate their {label} request because the agent "
                    "did not hear or understand it? Do not count the first time they asked.",
                    "criteria": count("repeat")},
        "transfers": {"type": "choice", "instructions": "How many times was the caller transferred to another team or person?",
                      "criteria": {"0": "no transfer", "1": "one transfer", "2": "two or more transfers"}},
        "holds": {"type": "choice", "instructions": "How many times did the agent put the caller on hold?",
                  "criteria": {"0": "no hold", "1": "one hold", "2": "two or more holds"}},
        "callback": {"type": "noul", "instructions":
                     "Was the caller told that someone will call them back, or that they will have to call back themselves?"},
        "repeat_turn": {"type": "choice", "instructions":
                        "Which turn shows the caller having to repeat their request, or the agent asking them to?",
                        "criteria": turn_options(tr, lo, hi, None, "the caller never had to repeat themselves")},
        "transfer_turn": {"type": "choice", "instructions": "Which turn shows the caller being transferred?",
                          "criteria": turn_options(tr, lo, hi, None, "no transfer")},
        "hold_turn": {"type": "choice", "instructions": "Which turn shows the agent putting the caller on hold?",
                      "criteria": turn_options(tr, lo, hi, None, "no hold")},
        "callback_turn": {"type": "choice", "instructions":
                          "Which turn tells the caller about a callback, by the company or by them?",
                          "criteria": turn_options(tr, lo, hi, None, "no callback mentioned")},
        "feeling": {"type": "choice", "instructions":
                    f"From what the caller says while dealing with the {label}, how do they come across? Judge only "
                    "their expressed words and tone, not whether the problem was solved.",
                    "criteria": {"happy": "pleased, relieved or warmly thankful",
                                 "mild": "neutral, matter-of-fact, or polite but not warm",
                                 "not_happy": "frustrated, annoyed, upset or complaining"}},
        "feeling_turn": {"type": "choice", "instructions":
                         "Which caller turn most clearly shows how the caller feels?",
                         "criteria": turn_options(tr, lo, hi, "caller", "no caller turn shows any feeling")},
    }


def cache_key(model: str, state: str, questions: dict) -> str:
    blob = json.dumps({"m": model, "qv": QUESTION_VERSION, "s": state, "q": questions}, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class JevCache:
    """Append-only JSONL of responses. Contains answers and timings only, never credentials."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.items: dict[str, dict] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    d = json.loads(line)
                    self.items[d["key"]] = d

    def get(self, key):
        return self.items.get(key)

    def put(self, entry):
        self.items[entry["key"]] = entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")


class JevExtractor:
    backend = "jev"
    question_version = QUESTION_VERSION

    def __init__(self, model: str = JEV_MODEL, concurrency: int = 6, cache_path: Path | None = None,
                 read_cache: bool = True, offline_only: bool = False):
        self.model_id = model
        self.concurrency = concurrency
        self.cache = JevCache(cache_path or paths.JEV_CACHE)
        self.read_cache = read_cache
        self.offline_only = offline_only  # replay the cache; a miss is an error, not a network call
        self.client = None
        self.request_log: list[dict] = []

    # ---- transport -------------------------------------------------------------------------
    def _client(self):
        if self.client is None:
            from typesafe_sdk import AsyncTypeSafeClient
            self.client = AsyncTypeSafeClient(model=self.model_id, timeout=30.0)
        return self.client

    @staticmethod
    def _sdk_questions(spec: dict):
        from typesafe_sdk import Choice, Noul
        out = {}
        for name, q in spec.items():
            if q["type"] == "noul":
                out[name] = Noul(instructions=q["instructions"])
            else:
                out[name] = Choice(instructions=q["instructions"], criteria=dict(q["criteria"]))
        return out

    async def ask(self, sem, state: str, spec: dict, tag: str) -> dict:
        key = cache_key(self.model_id, state, spec)
        if self.read_cache:
            hit = self.cache.get(key)
            if hit:
                self.request_log.append({"tag": tag, "cached": True, "latency_ms": hit["latency_ms"],
                                         "input_tokens": hit["input_tokens"]})
                return {**hit, "_cached": True}
        if self.offline_only:
            raise RuntimeError(f"cache miss for {tag} and --offline-only replay was requested")
        last_err = None
        for attempt in range(4):
            async with sem:
                t0 = time.perf_counter()
                try:
                    resp = await self._client().system_one(state=state, questions=self._sdk_questions(spec))
                except Exception as e:  # noqa: BLE001 - recorded and retried, then surfaced
                    last_err = e
                    await asyncio.sleep(0.5 * 2 ** attempt)
                    continue
                latency = (time.perf_counter() - t0) * 1000.0
            answers = {}
            for name, a in resp.answers.items():
                if a.type == "noul":
                    answers[name] = {"type": "noul", "p": float(a.noul)}
                else:
                    answers[name] = {"type": "choice", "label": a.choice,
                                     "probs": {k: float(v) for k, v in dict(a.probabilities).items()}}
            entry = {"key": key, "model": resp.model, "question_version": QUESTION_VERSION, "answers": answers,
                     "latency_ms": round(latency, 1), "input_tokens": resp.usage.input_tokens or 0,
                     "output_tokens": resp.usage.output_tokens or 0, "attempts": attempt + 1,
                     "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
            self.cache.put(entry)
            self.request_log.append({"tag": tag, "cached": False, "latency_ms": entry["latency_ms"],
                                     "input_tokens": entry["input_tokens"]})
            return {**entry, "_cached": False}
        raise RuntimeError(f"Jev request failed after retries ({tag}): {type(last_err).__name__}: {last_err}")

    # ---- extraction ------------------------------------------------------------------------
    def extract_calls(self, transcripts: list[Transcript]) -> list[CallExtraction]:
        return asyncio.run(self._extract_all(transcripts))

    async def _extract_all(self, transcripts):
        sem = asyncio.Semaphore(self.concurrency)
        return await asyncio.gather(*(self._extract_one(sem, tr) for tr in transcripts))

    async def _extract_one(self, sem, tr: Transcript) -> CallExtraction:
        meta = {"backend": self.backend, "model_id": self.model_id, "question_version": QUESTION_VERSION,
                "requests": 0, "input_tokens": 0, "latency_ms": 0.0, "cached": True, "notes": []}
        try:
            lo, hi = conversation_range(tr)
            r1 = await self.ask(sem, render(tr, 0, len(tr.turns) - 1), call_questions(), f"{tr.call_id}/call")
            self._account(meta, r1)
            a1 = r1["answers"]
            starts = detect(tr)
            sources = {i: "keyword" for i in starts}
            segs = segments_from_starts(tr, starts)
            for i in INTENTS:
                if i not in starts and a1[f"intent_{i}"]["p"] >= INTENT_THRESHOLD:
                    sources[i] = "model"
            ranges = {s.intent: (s.start, s.end) for s in segs}
            for i, src in sources.items():
                if src == "model":
                    ranges[i] = (lo, hi)  # keyword segmenter missed it: give Jev the whole conversation
            jobs = {i: self.ask(sem, render(tr, a, b), intent_questions(tr, i, a, b), f"{tr.call_id}/{i}")
                    for i, (a, b) in ranges.items()}
            results = await asyncio.gather(*jobs.values())
            stage2 = max((r["latency_ms"] for r in results), default=0.0)
            meta["latency_ms"] = round(r1["latency_ms"] + stage2, 1)  # critical path: stage 1, then intents in parallel
            intents = []
            for (i, (a, b)), r in zip(ranges.items(), results):
                self._account(meta, r, add_latency=False)
                intents.append(self._to_intent(tr, i, a, b, r["answers"], meta))
            intents.sort(key=lambda x: x.segment[0])
            closing = []
            close = closing_turn(tr)
            if close is not None:
                caller_close = [t for t in tr.turns[close + 1:] if t.speaker == "caller"]
                if caller_close:
                    val = a1["closing_feel"]["label"]
                    closing = [Cue(val, Span.whole_turn(caller_close[-1]))]
            meta["segment_sources"] = sources
            meta["model_id"] = r1.get("model", self.model_id)
            return CallExtraction(tr.call_id, intents, closing, meta)
        except Exception as e:  # noqa: BLE001 - becomes a review-queue reason, never a silent score
            meta["error"] = f"{type(e).__name__}: {e}"
            return CallExtraction(tr.call_id, [], [], meta)

    @staticmethod
    def _account(meta, r, add_latency=True):
        meta["requests"] += 1
        meta["input_tokens"] += r["input_tokens"]
        meta["cached"] = meta["cached"] and r["_cached"]
        if add_latency:
            meta["latency_ms"] += r["latency_ms"]

    @staticmethod
    def _turn_span(tr: Transcript, label: str | None) -> Span | None:
        if label and label.startswith("t") and label[1:].isdigit():
            idx = int(label[1:])
            if 0 <= idx < len(tr.turns) and tr.turns[idx].text.strip():
                return Span.whole_turn(tr.turns[idx])
        return None

    def _to_intent(self, tr, intent, lo, hi, a, meta) -> IntentExtraction:
        res = a["resolved"]
        resolved = res["label"] if res["label"] in ("yes", "partial", "no") else "partial"
        conf = float(res["probs"].get(resolved, 0.0))
        out_span = self._turn_span(tr, a["resolved_turn"]["label"])
        if out_span is None:
            agent = L.not_caller(tr, lo, hi) or tr.turns[lo:hi + 1]
            out_span = Span.whole_turn(agent[-1])
            meta["notes"].append(f"{intent}: outcome turn not cited by model, used last agent turn")

        def n(label, cap):
            return min(cap, int(label)) if str(label).isdigit() else 0

        reps = n(a["repeats"]["label"], 3)
        trans = n(a["transfers"]["label"], 2)
        hold = n(a["holds"]["label"], 2)
        cb = a["callback"]["p"] >= 0.5

        def evidence(count, cited_label, located):
            """The model-cited turn first, then lexically located turns, up to the asserted count."""
            if not count:
                return []
            spans = []
            cited = self._turn_span(tr, a[cited_label]["label"])
            if cited:
                spans.append(cited)
            for sp in located:
                if len(spans) >= count:
                    break
                if all(sp.turn != x.turn for x in spans):
                    spans.append(sp)
            return spans[:max(count, 1)]

        rep_sp = evidence(reps, "repeat_turn", L.repeats(tr, lo, hi))
        tr_sp = evidence(trans, "transfer_turn", L.transfers(tr, lo, hi))
        ho_sp = evidence(hold, "hold_turn", L.holds(tr, lo, hi))
        cb_sp = evidence(int(cb), "callback_turn", L.callbacks(tr, lo, hi))
        # no evidence, no count: a field the model asserts but nothing in the transcript supports is dropped
        if trans and not tr_sp:
            meta["notes"].append(f"{intent}: transfers={trans} unevidenced, dropped")
            trans = 0
        if hold and not ho_sp:
            meta["notes"].append(f"{intent}: holds={hold} unevidenced, dropped")
            hold = 0
        if cb and not cb_sp:
            meta["notes"].append(f"{intent}: callback unevidenced, dropped")
            cb = False

        feel = a["feeling"]["label"]
        valence = {"happy": "positive", "mild": "neutral", "not_happy": "negative"}.get(feel, "neutral")
        f_span = self._turn_span(tr, a["feeling_turn"]["label"])
        if f_span is None:
            callers = [t for t in tr.turns[lo:hi + 1] if t.speaker == "caller"]
            f_span = Span.whole_turn(callers[-1]) if callers else None
        cues = [Cue(valence, f_span)] if f_span else []
        claimed = L.claim_contested(tr, lo, hi) is not None
        return IntentExtraction(
            intent=intent, segment=(lo, hi), resolved=resolved, resolved_spans=[out_span],
            repeats=reps, repeat_spans=rep_sp, transfers=trans, transfer_spans=tr_sp, holds=hold, hold_spans=ho_sp,
            callback=cb, callback_spans=cb_sp, sentiment_cues=cues, confidence=round(conf, 3),
            agent_claimed_resolved=claimed and resolved != "yes",
        )

    def latency_summary(self) -> dict:
        live = [r for r in self.request_log if not r["cached"]]
        return {"requests": len(self.request_log), "live_requests": len(live),
                "cached_requests": len(self.request_log) - len(live)}
