"""Agreement metrics. Pure Python, no dependencies."""

from __future__ import annotations

import math
import random


def confusion(a: list, b: list, labels: list) -> list[list[int]]:
    idx = {lab: i for i, lab in enumerate(labels)}
    m = [[0] * len(labels) for _ in labels]
    for x, y in zip(a, b):
        m[idx[x]][idx[y]] += 1
    return m


def kappa(a: list, b: list, labels: list, weights: str | None = None) -> float:
    """Cohen's kappa; weights='quadratic' for ordinal labels (weighted kappa)."""
    n = len(a)
    if n == 0:
        return float("nan")
    k = len(labels)
    m = confusion(a, b, labels)
    ra = [sum(row) for row in m]
    cb = [sum(m[i][j] for i in range(k)) for j in range(k)]

    def w(i, j):
        if weights == "quadratic":
            return ((i - j) ** 2) / ((k - 1) ** 2)
        if weights == "linear":
            return abs(i - j) / (k - 1)
        return 0.0 if i == j else 1.0

    obs = sum(w(i, j) * m[i][j] for i in range(k) for j in range(k)) / n
    exp = sum(w(i, j) * ra[i] * cb[j] for i in range(k) for j in range(k)) / (n * n)
    return 1.0 - obs / exp if exp else float("nan")


def exact(a, b) -> float:
    return sum(x == y for x, y in zip(a, b)) / len(a) if a else float("nan")


def within_one(a, b) -> float:
    return sum(abs(x - y) <= 1 for x, y in zip(a, b)) / len(a) if a else float("nan")


def mae(a, b) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a) if a else float("nan")


def bootstrap_ci(a: list, b: list, fn, n_boot: int = 1000, seed: int = 7, alpha: float = 0.05) -> tuple[float, float]:
    """Percentile CI of fn(a, b) under resampling of items: the sampling noise floor."""
    rng = random.Random(seed)
    n = len(a)
    vals = []
    for _ in range(n_boot):
        ix = [rng.randrange(n) for _ in range(n)]
        v = fn([a[i] for i in ix], [b[i] for i in ix])
        if not math.isnan(v):
            vals.append(v)
    vals.sort()
    lo = vals[int(alpha / 2 * len(vals))]
    hi = vals[min(len(vals) - 1, int((1 - alpha / 2) * len(vals)))]
    return round(lo, 3), round(hi, 3)


def pct(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile."""
    v = sorted(values)
    return v[max(1, math.ceil(p / 100 * len(v))) - 1] if v else None
