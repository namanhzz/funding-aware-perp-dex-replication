import numpy as np
import pandas as pd

from perp_mm_funding.calibration.jump_ou import fit_ou_jump_mle, ou_jump_log_likelihood, threshold_ou_jump_diagnostic
from perp_mm_funding.calibration.ou import OUFit


def test_threshold_ou_jump_diagnostic_counts_large_standardized_residuals():
    fit = OUFit(
        kappa=0.1,
        theta=0.0,
        sigma=1.0,
        log_likelihood=0.0,
        half_life_hours=6.9,
        n_obs=6,
        dt_mean_hours=1.0,
        residuals=np.array([0.1, 0.2, 5.0, -4.0, 0.0]),
        standardized_residuals=np.array([0.1, 0.2, 5.0, -4.0, 0.0]),
    )
    diagnostic = threshold_ou_jump_diagnostic(fit, threshold_z=3.0)
    assert diagnostic.jump_count == 2
    assert diagnostic.jump_fraction == 0.4
    assert diagnostic.jump_intensity_per_hour == 0.4


def test_ou_jump_log_likelihood_is_finite_for_valid_parameters():
    values = np.array([0.0, 0.1, -0.05, 0.03, 0.2])
    ll = ou_jump_log_likelihood(
        values,
        kappa=0.5,
        theta=0.0,
        sigma=0.1,
        jump_intensity_per_hour=0.05,
        jump_mean=0.0,
        jump_sigma=0.2,
    )
    assert np.isfinite(ll)


def test_fit_ou_jump_mle_runs_on_jump_sample():
    rng = np.random.default_rng(1)
    n_obs = 80
    values = [0.0]
    for index in range(1, n_obs):
        shock = rng.normal(0.0, 0.01)
        if index in {20, 50}:
            shock += 0.08
        values.append(0.85 * values[-1] + shock)
    times = pd.date_range("2024-01-01", periods=n_obs, freq="h", tz="UTC")

    fit = fit_ou_jump_mle(values, times=times)

    assert fit.n_obs == n_obs
    assert np.isfinite(fit.log_likelihood)
    assert fit.jump_intensity_per_hour > 0
