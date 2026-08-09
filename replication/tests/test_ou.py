import numpy as np

from perp_mm_funding.calibration.ou import fit_ou_mle


def test_fit_ou_mle_recovers_synthetic_half_life_directionally():
    rng = np.random.default_rng(11)
    kappa = 0.2
    theta = 0.001
    sigma = 0.0005
    x = [theta]
    for _ in range(600):
        phi = np.exp(-kappa)
        mean = theta + phi * (x[-1] - theta)
        var = sigma**2 * (1 - phi**2) / (2 * kappa)
        x.append(float(rng.normal(mean, np.sqrt(var))))

    fit = fit_ou_mle(x)
    assert 0.05 < fit.kappa < 0.5
    assert abs(fit.theta - theta) < 0.0003
    assert fit.half_life_hours > 1.0

