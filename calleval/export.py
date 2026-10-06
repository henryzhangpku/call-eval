"""Build docs/data/demo.json for the static web demo from real runs on disk."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from calleval import aggregate, paths
from calleval.evaluate import available_runs, evaluate_dev, load_golden, read_ledger
from calleval.generate import SEED
from calleval.pipeline import load_calls, load_predictions, load_surveys

SPEAKER = {"agent": "A", "caller": "C", None: "?"}


def _spans(p: dict) -> list:
    out = []
    for x in p.get("intents", []):
        for key, kind in (("resolved_spans", "outcome"), ("repeat_spans", "repeat"), ("transfer_spans", "transfer"),
                          ("hold_spans", "hold"), ("callback_spans", "callback")):
            out += [[s["turn"], s["start"], s["end"], kind, x["intent"]] for s in x[key]]
        out += [[c["span"]["turn"], c["span"]["start"], c["span"]["end"], "feeling-" + c["valence"], x["intent"]]
                for c in x["sentiment_cues"]]
    out += [[c["span"]["turn"], c["span"]["start"], c["span"]["end"], "feeling-" + c["valence"], "closing"]
            for c in p.get("closing_cues", [])]
    return out


def _slim(p: dict) -> dict:
    if p["status"] != "scored":
        return {"status": p["status"], "review": p["review_reasons"]}
    return {"status": "scored", "csat": p["csat"], "raw": p["satisfaction_raw"], "cal": p.get("satisfaction_calibrated"),
            "sentiment": p["sentiment"], "sx": p["satisfaction_explanation"], "tx": p["sentiment_explanation"],
            "churn": p["churn_risk"], "review": p["review_reasons"], "spans": _spans(p),
            "intents": [{"intent": x["intent"], "resolved": x["resolved"], "segment": x["segment"],
                         "conf": x["confidence"], "sat": x["satisfaction"], "why": x["explanation"]}
                        for x in p["intents"]],
            "v": p["versions"]}


def _first_holdout(run_id: str) -> dict | None:
    for e in read_ledger():
        if e["run_id"] == run_id and not e["forced"]:
            return e
    return None


def _agreement(r: dict) -> dict:
    keys = ["coverage", "n_scored", "csat_weighted_kappa_vs_adjudicated", "csat_weighted_kappa_vs_adjudicated_ci",
            "csat_weighted_kappa_vs_annotators", "csat_exact_vs_adjudicated", "csat_within_one_vs_adjudicated",
            "sentiment_kappa_vs_adjudicated", "sentiment_kappa_vs_adjudicated_ci", "sentiment_kappa_vs_annotators",
            "sentiment_exact_vs_adjudicated", "churn_quadrant", "confusion_csat", "confusion_sentiment",
            "diagnostics_vs_latent_truth"]
    return {k: r[k] for k in keys if k in r}


def export_demo() -> dict:
    runs = [r for r in ("offline", "jev") if r in available_runs()]
    if not runs:
        raise SystemExit("no runs found: run `python -m calleval run --backend offline` first")
    primary = "jev" if "jev" in runs else "offline"
    dev = evaluate_dev()
    calls = load_calls()
    surveys = load_surveys()
    dev_gold = {g["call_id"]: g for g in load_golden(paths.GOLDEN_DEV)}
    preds = {r: load_predictions(r) for r in runs}
    summaries = {r: json.loads((paths.RUNS / r / "summary.json").read_text(encoding="utf-8")) for r in runs}
    live = None
    if (paths.RUNS / "jev" / "live_capture.json").exists():
        live = json.loads((paths.RUNS / "jev" / "live_capture.json").read_text(encoding="utf-8"))

    rows = list(preds[primary].values())
    queue = aggregate.review_queue(rows)
    out_calls = []
    for c in calls:
        g = dev_gold.get(c.call_id)
        out_calls.append({
            "id": c.call_id, "date": c.date, "agent": c.agent_id, "dur": c.duration_s,
            "turns": [[SPEAKER[t.speaker], t.text] for t in c.turns],
            "gate": {"passed": preds[primary][c.call_id]["gate"]["passed"],
                     "reasons": preds[primary][c.call_id]["gate"]["reasons"]},
            "survey": surveys.get(c.call_id),
            "gold": ({"a": [g["a_csat"], g["a_sentiment"]], "b": [g["b_csat"], g["b_sentiment"]],
                      "adj": [g["adj_csat"], g["adj_sentiment"]]} if g else None),
            "split": "dev" if g else None,
            "pred": {r: _slim(preds[r][c.call_id]) for r in runs},
        })

    demo = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "synthetic": True, "seed": SEED, "primary": primary, "runs": runs,
        "versions": {r: summaries[r]["versions"] for r in runs},
        "summary": {r: {k: v for k, v in summaries[r].items() if k not in ("calibration", "versions")} for r in runs},
        "jev_live_capture": live,
        "ceiling": dev["annotator_ceiling"],
        "agreement": {
            "dev": {r: _agreement(dev["runs"][r]) for r in runs if r in dev["runs"]},
            "holdout": {r: ({"result": _agreement(e["result"]), "ceiling": e["annotator_ceiling"],
                             "timestamp": e["timestamp"], "sha": e["predictions_sha256"][:12]}
                            if (e := _first_holdout(r)) else None) for r in runs},
        },
        "noise_floor": dev.get("noise_floor_run_to_run", {}),
        "calibration": {r: summaries[r].get("calibration") for r in runs},
        "quadrant": {r: aggregate.quadrant(list(preds[r].values())) for r in runs},
        "by_agent": aggregate.by_agent(rows), "by_intent": aggregate.by_intent(rows), "by_day": aggregate.by_day(rows),
        "review_queue": queue, "review_reason_counts": aggregate.reason_counts(queue),
        "churn_risk_calls": [r["call_id"] for r in rows if r["status"] == "scored" and r["churn_risk"]],
        "calls": out_calls,
    }
    paths.DOCS_DATA.parent.mkdir(parents=True, exist_ok=True)
    with open(paths.DOCS_DATA, "w", encoding="utf-8", newline="\n") as f:
        json.dump(demo, f, separators=(",", ":"))
    return {"path": str(paths.DOCS_DATA), "bytes": paths.DOCS_DATA.stat().st_size, "primary": primary, "runs": runs}
