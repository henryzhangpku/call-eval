"""Roll-ups for dashboards: by agent, by intent, by day; the satisfaction-vs-sentiment
quadrant; and the human-review queue with reasons.

Satisfaction is shown as calibrated when a calibration exists, and the raw
score alongside, so nobody mistakes a ranking for a level.
"""

from __future__ import annotations

from collections import defaultdict

from calleval.schema import INTENT_LABELS, SENTIMENTS


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def _group(rows, key):
    g = defaultdict(list)
    for r in rows:
        g[key(r)].append(r)
    return g


def _stats(rows):
    scored = [r for r in rows if r["status"] == "scored"]
    ints = [x for r in scored for x in r["intents"]]
    return {
        "calls": len(rows), "scored": len(scored),
        "mean_csat": _mean([r["csat"] for r in scored]),
        "mean_calibrated": _mean([r.get("satisfaction_calibrated") for r in scored]),
        "not_happy_share": round(sum(r["sentiment"] == "not_happy" for r in scored) / len(scored), 3) if scored else None,
        "churn_risk": sum(r["churn_risk"] for r in scored),
        "unresolved_intent_share": round(sum(x["resolved"] != "yes" for x in ints) / len(ints), 3) if ints else None,
        "transfers_per_call": round(sum(x["transfers"] for x in ints) / len(scored), 2) if scored else None,
        "review": len(rows) - len(scored) + sum(bool(r["review_reasons"]) for r in scored),
    }


def by_agent(rows):
    return [{"agent_id": k, **_stats(v)} for k, v in sorted(_group(rows, lambda r: r["agent_id"]).items())]


def by_day(rows):
    return [{"date": k, **_stats(v)} for k, v in sorted(_group(rows, lambda r: r["date"]).items())]


def by_intent(rows):
    g = defaultdict(list)
    for r in rows:
        if r["status"] == "scored":
            for x in r["intents"]:
                g[x["intent"]].append(x)
    out = []
    for intent, xs in sorted(g.items(), key=lambda kv: -len(kv[1])):
        out.append({"intent": intent, "label": INTENT_LABELS[intent], "n": len(xs),
                    "resolved_yes": round(sum(x["resolved"] == "yes" for x in xs) / len(xs), 3),
                    "resolved_partial": round(sum(x["resolved"] == "partial" for x in xs) / len(xs), 3),
                    "resolved_no": round(sum(x["resolved"] == "no" for x in xs) / len(xs), 3),
                    "mean_intent_satisfaction": _mean([x["satisfaction"] for x in xs]),
                    "negative_cue_share": round(sum(x["valence"] == "negative" for x in xs) / len(xs), 3)})
    return out


def sat_band(csat: int) -> str:
    return "low" if csat <= 2 else ("mid" if csat == 3 else "high")


def quadrant(rows):
    """Counts of satisfaction band x expressed sentiment. low x (happy|mild) is the churn-risk cell."""
    grid = {b: {s: 0 for s in SENTIMENTS} for b in ("low", "mid", "high")}
    for r in rows:
        if r["status"] == "scored":
            grid[sat_band(r["csat"])][r["sentiment"]] += 1
    return grid


def review_queue(rows):
    q = []
    for r in rows:
        if r["status"] != "scored":
            q.append({"call_id": r["call_id"], "agent_id": r["agent_id"], "date": r["date"],
                      "kind": "not scored", "reasons": r["review_reasons"]})
        elif r["review_reasons"]:
            q.append({"call_id": r["call_id"], "agent_id": r["agent_id"], "date": r["date"],
                      "kind": "scored, needs a look", "reasons": r["review_reasons"]})
    return q


def reason_counts(queue):
    c = defaultdict(int)
    for item in queue:
        for reason in item["reasons"]:
            c[reason.split(":")[0].removesuffix(" on")] += 1
    return dict(sorted(c.items(), key=lambda kv: -kv[1]))
