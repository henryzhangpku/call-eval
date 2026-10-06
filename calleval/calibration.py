"""Calibration: anchor the code's raw satisfaction score to the post-call survey scale.

A raw score ranks calls; it does not mean what a caller's "4" means until it is
fit against surveys. This module fits a weighted isotonic (monotone) mapping
raw -> expected survey score, reports calibration error out-of-fold, and
corrects for survey response bias with inverse-propensity weights estimated
from who answered (unhappy callers answer more).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

CALIBRATION_VERSION = "iso-v1"


@dataclass
class Isotonic:
    xs: list[float]  # block centres, increasing
    ys: list[float]  # fitted values, non-decreasing

    def predict(self, x: float) -> float:
        xs, ys = self.xs, self.ys
        if x <= xs[0]:
            return ys[0]
        if x >= xs[-1]:
            return ys[-1]
        for i in range(1, len(xs)):
            if x <= xs[i]:
                f = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
                return ys[i - 1] + f * (ys[i] - ys[i - 1])
        return ys[-1]

    def to_dict(self):
        return {"xs": [round(v, 4) for v in self.xs], "ys": [round(v, 4) for v in self.ys]}


def fit_isotonic(x: list[float], y: list[float], w: list[float] | None = None) -> Isotonic:
    """Weighted pool-adjacent-violators. Ties in x are pooled first."""
    w = w or [1.0] * len(x)
    pts: dict[float, list[float]] = {}
    for xi, yi, wi in zip(x, y, w):
        a = pts.setdefault(xi, [0.0, 0.0])
        a[0] += wi * yi
        a[1] += wi
    blocks = [[xi, s / ww, ww, xi * ww] for xi, (s, ww) in sorted(pts.items())]  # x, mean y, weight, sum(x*w)
    out: list[list[float]] = []
    for b in blocks:
        out.append(b)
        while len(out) > 1 and out[-2][1] > out[-1][1]:
            b2, b1 = out.pop(), out.pop()
            wt = b1[2] + b2[2]
            out.append([0.0, (b1[1] * b1[2] + b2[1] * b2[2]) / wt, wt, b1[3] + b2[3]])
    xs = [b[3] / b[2] for b in out]
    ys = [b[1] for b in out]
    if len(xs) == 1:
        xs, ys = [xs[0] - 1e-6, xs[0] + 1e-6], [ys[0], ys[0]]
    return Isotonic(xs, ys)


def response_weights(raw_all: list[float], responded: list[bool], buckets=(1.5, 2.5, 3.5, 4.5)) -> dict[int, float]:
    """Inverse response propensity per raw-score bucket, estimated from who answered the survey."""
    def b(v):
        return sum(v > c for c in buckets)
    n = [0] * (len(buckets) + 1)
    r = [0] * (len(buckets) + 1)
    for v, resp in zip(raw_all, responded):
        n[b(v)] += 1
        r[b(v)] += resp
    overall = sum(r) / max(1, sum(n))
    out = {}
    for i in range(len(n)):
        p = (r[i] + overall) / (n[i] + 1)  # light smoothing toward the overall rate
        out[i] = 1.0 / p
    return out


def bucket_of(v: float, buckets=(1.5, 2.5, 3.5, 4.5)) -> int:
    return sum(v > c for c in buckets)


def reliability(pred: list[float], obs: list[float], w: list[float] | None = None) -> list[dict]:
    """Bins on the 1-5 scale: mean predicted vs (weighted) mean observed survey score."""
    w = w or [1.0] * len(pred)
    bins = []
    for k in range(1, 6):
        ix = [i for i, p in enumerate(pred) if min(5, max(1, math.floor(p + 0.5))) == k]
        if not ix:
            continue
        sw = sum(w[i] for i in ix)
        bins.append({"bin": k, "n": len(ix),
                     "mean_pred": round(sum(pred[i] * w[i] for i in ix) / sw, 3),
                     "mean_obs": round(sum(obs[i] * w[i] for i in ix) / sw, 3)})
    return bins


def ece(bins: list[dict]) -> float:
    """Expected calibration error in survey points: count-weighted |mean_pred - mean_obs| over bins."""
    n = sum(b["n"] for b in bins)
    return round(sum(b["n"] * abs(b["mean_pred"] - b["mean_obs"]) for b in bins) / n, 3) if n else float("nan")


def cross_validated(raw: list[float], survey: list[float], w: list[float], k: int = 5, seed: int = 11) -> list[float]:
    """Out-of-fold calibrated predictions, so the reported error is not measured on the fitting data."""
    idx = list(range(len(raw)))
    random.Random(seed).shuffle(idx)
    out = [0.0] * len(raw)
    for f in range(k):
        test = set(idx[f::k])
        tr = [i for i in idx if i not in test]
        iso = fit_isotonic([raw[i] for i in tr], [survey[i] for i in tr], [w[i] for i in tr])
        for i in test:
            out[i] = iso.predict(raw[i])
    return out


def calibrate(raw_all: dict[str, float], surveys: dict[str, int], exclude: set[str]) -> dict:
    """Fit on survey calls not in `exclude` (the sealed holdout). Returns the model and a report."""
    pool = {c: v for c, v in raw_all.items() if c not in exclude}
    weights_by_bucket = response_weights(list(pool.values()), [c in surveys for c in pool])
    ids = sorted(c for c in pool if c in surveys)
    raw = [pool[c] for c in ids]
    obs = [float(surveys[c]) for c in ids]
    w = [weights_by_bucket[bucket_of(v)] for v in raw]
    oof = cross_validated(raw, obs, w)
    iso = fit_isotonic(raw, obs, w)
    rel_raw = reliability(raw, obs, w)
    rel_cal = reliability(oof, obs, w)
    oof_unweighted = cross_validated(raw, obs, [1.0] * len(raw))
    rel_cal_unw = reliability(oof_unweighted, obs, [1.0] * len(raw))
    return {
        "model": iso,
        "version": CALIBRATION_VERSION,
        "n_survey_calls": len(ids),
        "response_rate_by_bucket": {str(k): round(1 / v, 3) for k, v in weights_by_bucket.items()},
        "ece_raw": ece(rel_raw),
        "ece_calibrated_oof": ece(rel_cal),
        "ece_calibrated_oof_unweighted": ece(rel_cal_unw),
        "reliability_raw": rel_raw,
        "reliability_calibrated": rel_cal,
        "mapping": iso.to_dict(),
        "survey_mean_observed": round(sum(obs) / len(obs), 3) if obs else None,
        "survey_mean_weighted": round(sum(o * wi for o, wi in zip(obs, w)) / sum(w), 3) if obs else None,
    }
