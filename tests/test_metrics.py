from calleval.metrics import kappa


def test_perfect_agreement():
    a = [1, 2, 3, 4, 5, 3]
    assert kappa(a, a, [1, 2, 3, 4, 5], "quadratic") == 1.0
    assert kappa(a, a, [1, 2, 3, 4, 5]) == 1.0


def test_known_cohen_kappa():
    # classic 2x2 example: po = 0.7, pe = 0.5 -> kappa 0.4
    a = ["y"] * 25 + ["n"] * 25
    b = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
    assert abs(kappa(a, b, ["y", "n"]) - 0.4) < 1e-9


def test_weighted_kappa_penalises_far_misses_more():
    truth = [1, 2, 3, 4, 5] * 10
    near = [min(5, t + 1) for t in truth]
    far = [1 if t >= 4 else 5 for t in truth]
    assert kappa(truth, near, [1, 2, 3, 4, 5], "quadratic") > kappa(truth, far, [1, 2, 3, 4, 5], "quadratic")
