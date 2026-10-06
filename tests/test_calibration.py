import random

from calleval.calibration import ece, fit_isotonic, reliability, response_weights


def test_isotonic_is_monotone():
    rng = random.Random(3)
    x = [rng.uniform(1, 5) for _ in range(300)]
    y = [min(5, max(1, round(xi + rng.gauss(0, 1.2)))) for xi in x]
    w = [rng.uniform(0.5, 3) for _ in x]
    iso = fit_isotonic(x, y, w)
    assert all(a <= b for a, b in zip(iso.ys, iso.ys[1:]))
    grid = [1 + i * 0.01 for i in range(401)]
    preds = [iso.predict(g) for g in grid]
    assert all(a <= b + 1e-12 for a, b in zip(preds, preds[1:]))


def test_isotonic_recovers_a_monotone_map():
    x = [1, 2, 3, 4, 5] * 20
    y = [1, 1, 3, 4, 4] * 20
    iso = fit_isotonic(x, y)
    assert [round(iso.predict(v), 6) for v in (1, 2, 3, 4, 5)] == [1, 1, 3, 4, 4]


def test_perfect_calibration_has_zero_error():
    p = [1, 2, 3, 4, 5, 3, 4]
    assert ece(reliability(p, p)) == 0


def test_response_weights_upweight_rare_responders():
    raw = [1.0] * 50 + [5.0] * 50
    responded = [True] * 30 + [False] * 20 + [True] * 10 + [False] * 40
    w = response_weights(raw, responded)
    assert w[4] > w[0]  # high scorers answered less, so each answer counts more
