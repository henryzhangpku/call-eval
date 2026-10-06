"""The nightly batch, end to end: gate -> segment -> extract -> validate -> score -> calibrate -> store.

Idempotent per call: a run directory is rewritten from scratch, and every row
carries the versions needed to regenerate it.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import time
from pathlib import Path

from calleval import __version__, paths
from calleval.calibration import CALIBRATION_VERSION, calibrate
from calleval.extract import make_extractor
from calleval.metrics import pct
from calleval.quality import GATE_VERSION, check
from calleval.schema import SchemaError, Span, Transcript, validate_call
from calleval.scoring import SCORING_VERSION, score_call
from calleval.segment import SEGMENTER_VERSION

# Published Jev list price, checked 2026-10-06: $0.042 per million input tokens, output free.
# Prices change: verify on the pricing page on the day before quoting a number.
JEV_PRICE_PER_M_INPUT = 0.042
PRICE_CHECKED = "2026-10-06"
LOW_CONFIDENCE = 0.5


def code_version() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=paths.ROOT, capture_output=True,
                             text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "calleval"], cwd=paths.ROOT,
                               capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        sha, dirty = "", ""
    return f"{__version__}+{sha or 'nogit'}{'.dirty' if dirty else ''}"


def load_calls(path: Path = paths.CALLS) -> list[Transcript]:
    return [Transcript.from_dict(json.loads(l)) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def load_surveys(path: Path = paths.SURVEYS) -> dict[str, int]:
    with open(path, encoding="utf-8") as f:
        return {r["call_id"]: int(r["survey_csat"]) for r in csv.DictReader(f)}


def load_splits() -> dict[str, list[str]]:
    return json.loads(paths.SPLITS.read_text(encoding="utf-8"))


def span_dict(s: Span, kind: str) -> dict:
    return {"turn": s.turn, "start": s.start, "end": s.end, "text": s.text, "kind": kind}


def run(backend: str, run_id: str | None = None, call_ids: set[str] | None = None, **extractor_kw) -> dict:
    run_id = run_id or backend
    out_dir = paths.RUNS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    calls = load_calls()
    if call_ids is not None:
        calls = [c for c in calls if c.call_id in call_ids]
    surveys = load_surveys()
    holdout = set(load_splits()["holdout"])
    extractor = make_extractor(backend, **extractor_kw)
    cv = code_version()

    t0 = time.perf_counter()
    gates = {c.call_id: check(c) for c in calls}
    passing = [c for c in calls if gates[c.call_id].passed]
    extractions = extractor.extract_calls(passing)
    wall_extract = time.perf_counter() - t0
    by_id = {c.call_id: c for c in calls}

    rows, scores = {}, {}
    for ex in extractions:
        tr = by_id[ex.call_id]
        reasons = []
        if ex.meta.get("error"):
            reasons.append(f"extractor error: {ex.meta['error']}")
        elif not ex.intents:
            reasons.append("no intent detected: nothing to score (keywords may be mangled by ASR)")
        else:
            try:
                validate_call(ex, tr)
            except SchemaError as e:
                reasons.append(f"schema validation failed: {e}")
        if reasons:
            rows[ex.call_id] = {"status": "review", "review_reasons": reasons, "extractor_meta": ex.meta}
            continue
        sc = score_call(ex)
        scores[ex.call_id] = sc
        flags = []
        low = [x.intent for x in ex.intents if x.confidence < LOW_CONFIDENCE]
        if low:
            flags.append(f"low extraction confidence on: {', '.join(low)}")
        if any(x.agent_claimed_resolved for x in ex.intents):
            flags.append("agent claimed resolution, caller disagreed")
        rows[ex.call_id] = {
            "status": "scored", "review_reasons": flags,
            "csat": sc.csat, "satisfaction_raw": sc.satisfaction_raw, "sentiment": sc.sentiment,
            "satisfaction_explanation": sc.satisfaction_explanation, "sentiment_explanation": sc.sentiment_explanation,
            "satisfaction_spans": [span_dict(s, "satisfaction") for s in sc.satisfaction_spans],
            "sentiment_spans": [span_dict(s, "sentiment") for s in sc.sentiment_spans],
            "intents": [{**x.to_dict(), "satisfaction": isc.satisfaction, "valence": isc.valence,
                         "explanation": isc.explanation} for x, isc in zip(ex.intents, sc.intents)],
            "closing_cues": [{"valence": c.valence, "span": span_dict(c.span, "closing")} for c in ex.closing_cues],
            "extractor_meta": ex.meta,
        }
    wall_total = time.perf_counter() - t0

    # calibration: fit raw -> survey on non-holdout survey calls
    raw_all = {cid: s.satisfaction_raw for cid, s in scores.items()}
    cal = calibrate(raw_all, surveys, exclude=holdout) if sum(c in surveys for c in raw_all) >= 20 else None
    for cid, r in rows.items():
        if r["status"] == "scored":
            r["satisfaction_calibrated"] = round(cal["model"].predict(r["satisfaction_raw"]), 3) if cal else None
            r["low_satisfaction"] = r["csat"] <= 2
            r["churn_risk"] = r["csat"] <= 2 and r["sentiment"] != "not_happy"

    versions = {"code_version": cv, "extractor_backend": extractor.backend, "model_id": extractor.model_id,
                "question_version": extractor.question_version, "scoring_version": SCORING_VERSION,
                "gate_version": GATE_VERSION, "segmenter_version": SEGMENTER_VERSION,
                "calibration_version": CALIBRATION_VERSION if cal else None}
    lines = []
    for c in calls:
        g = gates[c.call_id]
        row = rows.get(c.call_id) or {"status": "review", "review_reasons": list(g.reasons)}
        v = dict(versions)
        meta = row.get("extractor_meta") or {}
        if meta.get("model_id"):
            v["model_id"] = meta["model_id"]  # the model the API says answered, not just the one requested
        lines.append({"call_id": c.call_id, "date": c.date, "agent_id": c.agent_id, "gate": {
            "passed": g.passed, "reasons": g.reasons, "warnings": g.warnings, "stats": g.stats},
            **row, "versions": v})

    with open(out_dir / "predictions.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for l in lines:
            f.write(json.dumps(l) + "\n")

    summary = summarize(run_id, extractor, lines, wall_extract, wall_total, cal, versions)
    with open(out_dir / "summary.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=1)
    if summary.get("live"):
        with open(out_dir / "live_capture.json", "w", encoding="utf-8", newline="\n") as f:
            json.dump(summary["live"], f, indent=1)
    return summary


def summarize(run_id, extractor, lines, wall_extract, wall_total, cal, versions) -> dict:
    scored = [l for l in lines if l["status"] == "scored"]
    metas = [l["extractor_meta"] for l in lines if l.get("extractor_meta")]
    s = {"run_id": run_id, "versions": versions, "calls": len(lines), "scored": len(scored),
         "review": len(lines) - len(scored),
         "gate_failures": sum(not l["gate"]["passed"] for l in lines),
         "wall_seconds_extract_and_score": round(wall_total, 3)}
    if extractor.backend == "offline":
        s["throughput_calls_per_s"] = round(len(metas) / max(wall_extract, 1e-9), 1)
    else:
        log = extractor.request_log
        req_lat = [r["latency_ms"] for r in log]
        call_lat = [m["latency_ms"] for m in metas if m.get("requests")]
        toks = [m["input_tokens"] for m in metas if m.get("requests")]
        tok_per_call = sum(toks) / max(1, len(toks))
        cost_call = tok_per_call * JEV_PRICE_PER_M_INPUT / 1e6
        s["jev"] = {
            "requests": len(log), "live_requests": sum(not r["cached"] for r in log),
            "request_latency_ms_p50": pct(req_lat, 50), "request_latency_ms_p95": pct(req_lat, 95),
            "call_latency_ms_p50": pct(call_lat, 50), "call_latency_ms_p95": pct(call_lat, 95),
            "requests_per_call": round(len(log) / max(1, len(call_lat)), 2),
            "input_tokens_per_call": round(tok_per_call, 1),
            "cost_per_call_usd": round(cost_call, 7),
            "cost_per_20k_calls_usd": round(cost_call * 20_000, 2),
            "price_per_m_input_usd": JEV_PRICE_PER_M_INPUT, "price_checked": PRICE_CHECKED,
            "latency_source": "measured live" if all(not r["cached"] for r in log) else
                              "replayed from cache (latencies as measured at capture)",
            "errors": sum(1 for m in metas if m.get("error")),
        }
        live = [r for r in log if not r["cached"]]
        if live:
            rps = len(live) / max(wall_extract, 1e-9)
            s["live"] = {"live_requests": len(live), "concurrency": extractor.concurrency,
                         "wall_seconds": round(wall_extract, 2), "requests_per_s": round(rps, 1),
                         "requests_per_call": s["jev"]["requests_per_call"],
                         # some requests may have been cache hits, so throughput is derived from live requests only
                         "throughput_calls_per_s": round(rps / max(s["jev"]["requests_per_call"], 1e-9), 2),
                         "request_latency_ms_p50": pct([r["latency_ms"] for r in live], 50),
                         "request_latency_ms_p95": pct([r["latency_ms"] for r in live], 95)}
    if cal:
        s["calibration"] = {k: v for k, v in cal.items() if k != "model"}
    return s


def predictions_hash(run_id: str) -> str:
    return hashlib.sha256((paths.RUNS / run_id / "predictions.jsonl").read_bytes()).hexdigest()


def load_predictions(run_id: str) -> dict[str, dict]:
    p = paths.RUNS / run_id / "predictions.jsonl"
    return {d["call_id"]: d for d in (json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip())}
