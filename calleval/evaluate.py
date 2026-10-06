"""Evaluation discipline.

1. Inter-annotator agreement first: two humans agreeing with each other is the
   ceiling. A system that agrees with a human as often as humans agree with each
   other is at ceiling, and chasing more is chasing noise.
2. Iterate on the 200-call dev split only.
3. The noise floor: bootstrap CI over dev calls (sampling noise), plus the
   run-to-run spread of the same model and questions run twice.
4. The 100-call holdout is sealed. `holdout` evaluates a run on it once,
   records a hash of the predictions in a ledger, and refuses a second time
   unless forced (a forced run is recorded as forced).
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

from calleval import paths
from calleval.metrics import bootstrap_ci, confusion, exact, kappa, mae, within_one
from calleval.pipeline import code_version, load_predictions, predictions_hash
from calleval.schema import INTENTS, SENTIMENTS

CSAT = [1, 2, 3, 4, 5]
SENT = list(SENTIMENTS)


def wk(a, b):
    return kappa(a, b, CSAT, "quadratic")


def sk(a, b):
    return kappa(a, b, SENT)


def load_golden(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("a_csat", "b_csat", "adj_csat"):
            r[k] = int(r[k])
    return rows


def load_truth() -> dict[str, dict]:
    return {d["call_id"]: d for d in (json.loads(l) for l in paths.ANSWER_KEY.read_text(encoding="utf-8").splitlines())}


def annotator_ceiling(gold: list[dict]) -> dict:
    a, b = [g["a_csat"] for g in gold], [g["b_csat"] for g in gold]
    sa, sb = [g["a_sentiment"] for g in gold], [g["b_sentiment"] for g in gold]
    return {"n": len(gold),
            "csat_weighted_kappa": round(wk(a, b), 3), "csat_weighted_kappa_ci": bootstrap_ci(a, b, wk),
            "csat_exact": round(exact(a, b), 3), "csat_within_one": round(within_one(a, b), 3),
            "sentiment_kappa": round(sk(sa, sb), 3), "sentiment_kappa_ci": bootstrap_ci(sa, sb, sk),
            "sentiment_exact": round(exact(sa, sb), 3)}


def score_run(preds: dict[str, dict], gold: list[dict], truth: dict[str, dict] | None = None) -> dict:
    scored = [g for g in gold if preds.get(g["call_id"], {}).get("status") == "scored"]
    ids = [g["call_id"] for g in scored]
    p_csat = [preds[i]["csat"] for i in ids]
    p_cal = [min(5, max(1, int(preds[i]["satisfaction_calibrated"] + 0.5))) if preds[i].get("satisfaction_calibrated")
             is not None else preds[i]["csat"] for i in ids]
    p_sent = [preds[i]["sentiment"] for i in ids]
    adj, adj_s = [g["adj_csat"] for g in scored], [g["adj_sentiment"] for g in scored]
    a, b = [g["a_csat"] for g in scored], [g["b_csat"] for g in scored]
    sa, sb = [g["a_sentiment"] for g in scored], [g["b_sentiment"] for g in scored]
    out = {
        "n_golden": len(gold), "n_scored": len(scored), "coverage": round(len(scored) / max(1, len(gold)), 3),
        "csat_weighted_kappa_vs_adjudicated": round(wk(p_csat, adj), 3),
        "csat_weighted_kappa_vs_adjudicated_ci": bootstrap_ci(p_csat, adj, wk),
        "csat_weighted_kappa_vs_annotators": round((wk(p_csat, a) + wk(p_csat, b)) / 2, 3),
        "csat_calibrated_weighted_kappa_vs_adjudicated": round(wk(p_cal, adj), 3),
        "csat_exact_vs_adjudicated": round(exact(p_csat, adj), 3),
        "csat_within_one_vs_adjudicated": round(within_one(p_csat, adj), 3),
        "csat_mae_vs_adjudicated": round(mae(p_csat, adj), 3),
        "sentiment_kappa_vs_adjudicated": round(sk(p_sent, adj_s), 3),
        "sentiment_kappa_vs_adjudicated_ci": bootstrap_ci(p_sent, adj_s, sk),
        "sentiment_kappa_vs_annotators": round((sk(p_sent, sa) + sk(p_sent, sb)) / 2, 3),
        "sentiment_exact_vs_adjudicated": round(exact(p_sent, adj_s), 3),
        "confusion_csat": {"labels": CSAT, "rows_are": "adjudicated", "cols_are": "predicted",
                           "matrix": confusion(adj, p_csat, CSAT)},
        "confusion_sentiment": {"labels": SENT, "rows_are": "adjudicated", "cols_are": "predicted",
                                "matrix": confusion(adj_s, p_sent, SENT)},
    }
    q_true = [g["adj_csat"] <= 2 and g["adj_sentiment"] != "not_happy" for g in scored]
    q_pred = [preds[i]["churn_risk"] for i in ids]
    tp = sum(t and p for t, p in zip(q_true, q_pred))
    out["churn_quadrant"] = {"true": sum(q_true), "flagged": sum(q_pred), "hit": tp,
                             "precision": round(tp / max(1, sum(q_pred)), 3), "recall": round(tp / max(1, sum(q_true)), 3)}
    if truth:
        out["diagnostics_vs_latent_truth"] = diagnostics(preds, ids, truth)
    return out


def diagnostics(preds, ids, truth) -> dict:
    """Synthetic-only: compare extracted fields to the generator's latent truth."""
    tp = fp = fn = 0
    res_ok = res_n = 0
    eff = {"repeats": [0, 0], "transfers": [0, 0], "holds": [0, 0], "callback": [0, 0]}
    per_intent = {i: [0, 0] for i in INTENTS}
    for cid in ids:
        t = {x["intent"]: x for x in truth[cid]["intents"]}
        p = {x["intent"]: x for x in preds[cid]["intents"]}
        tp += len(t.keys() & p.keys())
        fp += len(p.keys() - t.keys())
        fn += len(t.keys() - p.keys())
        for i in t.keys() & p.keys():
            ok = t[i]["resolved"] == p[i]["resolved"]
            res_ok += ok
            res_n += 1
            per_intent[i][0] += ok
            per_intent[i][1] += 1
            for k in eff:
                eff[k][0] += int(t[i][k]) == int(p[i][k])
                eff[k][1] += 1
    return {
        "intent_precision": round(tp / max(1, tp + fp), 3), "intent_recall": round(tp / max(1, tp + fn), 3),
        "resolved_accuracy": round(res_ok / max(1, res_n), 3),
        "resolved_accuracy_by_intent": {i: round(v[0] / v[1], 3) for i, v in per_intent.items() if v[1]},
        "effort_exact_accuracy": {k: round(v[0] / max(1, v[1]), 3) for k, v in eff.items()},
    }


def run_to_run(run_a: str, run_b: str, ids: list[str]) -> dict | None:
    """Same model, same questions, run twice: how much moves by itself."""
    try:
        pa, pb = load_predictions(run_a), load_predictions(run_b)
    except FileNotFoundError:
        return None
    both = [i for i in ids if pa.get(i, {}).get("status") == "scored" and pb.get(i, {}).get("status") == "scored"]
    if not both:
        return None
    ca, cb = [pa[i]["csat"] for i in both], [pb[i]["csat"] for i in both]
    sa, sb = [pa[i]["sentiment"] for i in both], [pb[i]["sentiment"] for i in both]
    ra = [x["resolved"] for i in both for x in pa[i]["intents"]]
    rb_map = {(i, x["intent"]): x["resolved"] for i in both for x in pb[i]["intents"]}
    pairs = [(x["resolved"], rb_map.get((i, x["intent"]))) for i in both for x in pa[i]["intents"]]
    pairs = [p for p in pairs if p[1] is not None]
    gold = {g["call_id"]: g for g in load_golden(paths.GOLDEN_DEV)}
    g_ids = [i for i in both if i in gold]
    ka = wk([pa[i]["csat"] for i in g_ids], [gold[i]["adj_csat"] for i in g_ids])
    kb = wk([pb[i]["csat"] for i in g_ids], [gold[i]["adj_csat"] for i in g_ids])
    sa_k = sk([pa[i]["sentiment"] for i in g_ids], [gold[i]["adj_sentiment"] for i in g_ids])
    sb_k = sk([pb[i]["sentiment"] for i in g_ids], [gold[i]["adj_sentiment"] for i in g_ids])
    return {"runs": [run_a, run_b], "n_calls": len(both), "n_intents_compared": len(pairs) or len(ra),
            "csat_identical": round(exact(ca, cb), 3), "sentiment_identical": round(exact(sa, sb), 3),
            "resolved_identical": round(sum(x == y for x, y in pairs) / max(1, len(pairs)), 3),
            "csat_weighted_kappa_vs_adjudicated": [round(ka, 3), round(kb, 3)],
            "csat_kappa_spread": round(abs(ka - kb), 3),
            "sentiment_kappa_vs_adjudicated": [round(sa_k, 3), round(sb_k, 3)],
            "sentiment_kappa_spread": round(abs(sa_k - sb_k), 3)}


def available_runs() -> list[str]:
    if not paths.RUNS.exists():
        return []
    return sorted(p.name for p in paths.RUNS.iterdir() if (p / "predictions.jsonl").exists())


def evaluate_dev(runs: list[str] | None = None) -> dict:
    gold = load_golden(paths.GOLDEN_DEV)
    truth = load_truth()
    report = {"split": "dev", "annotator_ceiling": annotator_ceiling(gold), "runs": {}}
    for r in runs or available_runs():
        preds = load_predictions(r)
        if not any(g["call_id"] in preds for g in gold):
            continue
        report["runs"][r] = score_run(preds, gold, truth)
    ids = [g["call_id"] for g in gold]
    for a, b in (("jev", "jev-r2"), ("offline", "offline-r2")):
        rr = run_to_run(a, b, ids)
        if rr:
            report.setdefault("noise_floor_run_to_run", {})[a] = rr
    paths.RUNS.mkdir(parents=True, exist_ok=True)
    with open(paths.RUNS / "dev_report.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=1)
    return report


class HoldoutAlreadyUsed(RuntimeError):
    pass


def read_ledger() -> list[dict]:
    if paths.LEDGER.exists():
        return json.loads(paths.LEDGER.read_text(encoding="utf-8"))
    return []


def evaluate_holdout(run_id: str, force: bool = False) -> dict:
    ledger = read_ledger()
    prior = [e for e in ledger if e["run_id"] == run_id]
    if prior and not force:
        raise HoldoutAlreadyUsed(
            f"the sealed holdout was already used for run '{run_id}' at {prior[0]['timestamp']} "
            f"(predictions sha256 {prior[0]['predictions_sha256'][:12]}...). Re-using it turns it into a dev set. "
            "Pass --force only if you accept that; the forced run is recorded in the ledger.")
    gold = load_golden(paths.GOLDEN_HOLDOUT)
    preds = load_predictions(run_id)
    res = score_run(preds, gold, load_truth())
    entry = {"run_id": run_id, "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "predictions_sha256": predictions_hash(run_id), "code_version": code_version(),
             "versions": next(iter(preds.values()))["versions"], "forced": bool(prior), "n_prior_uses": len(prior),
             "annotator_ceiling": annotator_ceiling(gold), "result": res}
    ledger.append(entry)
    paths.LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(paths.LEDGER, "w", encoding="utf-8", newline="\n") as f:
        json.dump(ledger, f, indent=1)
    return entry
