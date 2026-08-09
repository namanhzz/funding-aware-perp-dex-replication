import math

import numpy as np
import pandas as pd

from perp_mm_funding.run_backtest import (
    _finite_delta,
    _funding_signal,
    _funding_scale,
    _funding_state_bounds,
    _funding_state_samples,
    _policy_time,
)


def test_cash_funding_signal_scales_fractional_rate_by_mid():
    assert _funding_signal(0.001, 2000.0, "cash") == 2.0


def test_fractional_funding_signal_keeps_raw_rate():
    assert _funding_signal(0.001, 2000.0, "fractional") == 0.001


def test_funding_scale_defaults_to_median_price():
    price = pd.DataFrame({"mid": [100.0, 110.0, 120.0]})

    assert _funding_scale(price, {}) == 110.0


def test_rolling_policy_time_uses_start_of_control_horizon():
    assert _policy_time(36.0, "rolling") == 0.0
    assert _policy_time(36.0, "elapsed") == 36.0


def test_funding_state_samples_use_cash_price_scale_only_in_cash_mode():
    funding = pd.DataFrame({"funding_rate": [0.001, -0.002]})

    np.testing.assert_allclose(_funding_state_samples(funding, 2_000.0, "cash"), np.array([2.0, -4.0]))
    np.testing.assert_allclose(_funding_state_samples(funding, 2_000.0, "fractional"), np.array([0.001, -0.002]))


def test_funding_state_bounds_include_zero_and_model_band():
    lower, upper = _funding_state_bounds(np.array([0.01, 0.02]), theta_bar=0.05, sigma_f=0.02)

    assert lower < 0.0
    assert upper > 0.13


def test_finite_delta_caps_nonfinite_values():
    assert _finite_delta(1.25, 10.0) == 1.25
    assert _finite_delta(math.inf, 10.0) == 10.0
