import numpy as np
import pytest

from perp_mm_funding.model.riccati import QuadraticCoefficients
from perp_mm_funding.strategy.quotes import (
    FractionalFundingQuoteConfig,
    explicit_s_fractional_funding_deltas,
    optimal_deltas,
    risk_calibrated_deltas,
)


def test_optimal_deltas_reduce_to_one_over_k_when_value_is_flat():
    coefficients = QuadraticCoefficients(t_grid=np.array([0.0, 1.0]), values=np.zeros((6, 2)))
    bid, ask = optimal_deltas(coefficients, t_hours=0.0, q=0.0, f=0.0, intensity_k=100.0)
    assert bid == 0.01
    assert ask == 0.01


def test_explicit_s_fractional_funding_applies_bounded_cash_skew():
    coefficients = QuadraticCoefficients(t_grid=np.array([0.0, 1.0]), values=np.zeros((6, 2)))
    config = FractionalFundingQuoteConfig(control_horizon_hours=2.0, max_funding_skew=1.5)

    bid, ask = explicit_s_fractional_funding_deltas(
        coefficients,
        t_hours=0.0,
        q=0.0,
        funding_rate=0.001,
        mid_price=2_000.0,
        intensity_k=1.0,
        config=config,
    )

    assert bid == pytest.approx(2.5)
    assert ask == pytest.approx(0.0)


def test_explicit_s_fractional_funding_uses_spot_price_and_horizon():
    coefficients = QuadraticCoefficients(t_grid=np.array([0.0, 1.0]), values=np.zeros((6, 2)))

    bid_short, ask_short = explicit_s_fractional_funding_deltas(
        coefficients,
        t_hours=0.0,
        q=0.0,
        funding_rate=-0.001,
        mid_price=1_000.0,
        intensity_k=1.0,
        config=FractionalFundingQuoteConfig(control_horizon_hours=1.0, max_funding_skew=10.0),
    )
    bid_long, ask_long = explicit_s_fractional_funding_deltas(
        coefficients,
        t_hours=0.0,
        q=0.0,
        funding_rate=-0.001,
        mid_price=1_000.0,
        intensity_k=1.0,
        config=FractionalFundingQuoteConfig(control_horizon_hours=3.0, max_funding_skew=10.0),
    )
    bid_low_spot, ask_low_spot = explicit_s_fractional_funding_deltas(
        coefficients,
        t_hours=0.0,
        q=0.0,
        funding_rate=-0.001,
        mid_price=500.0,
        intensity_k=1.0,
        config=FractionalFundingQuoteConfig(control_horizon_hours=3.0, max_funding_skew=10.0),
    )

    assert bid_short == pytest.approx(0.0)
    assert ask_short == pytest.approx(2.0)
    assert bid_long == pytest.approx(0.0)
    assert ask_long == pytest.approx(4.0)
    assert bid_low_spot == pytest.approx(0.0)
    assert ask_low_spot == pytest.approx(2.5)


def test_explicit_s_fractional_funding_validates_inputs():
    coefficients = QuadraticCoefficients(t_grid=np.array([0.0, 1.0]), values=np.zeros((6, 2)))

    with pytest.raises(ValueError, match="control_horizon_hours"):
        FractionalFundingQuoteConfig(control_horizon_hours=0.0, max_funding_skew=1.0)

    with pytest.raises(ValueError, match="max_funding_skew"):
        FractionalFundingQuoteConfig(control_horizon_hours=1.0, max_funding_skew=-1.0)

    with pytest.raises(ValueError, match="mid_price"):
        explicit_s_fractional_funding_deltas(
            coefficients,
            t_hours=0.0,
            q=0.0,
            funding_rate=0.001,
            mid_price=0.0,
            intensity_k=1.0,
            config=FractionalFundingQuoteConfig(control_horizon_hours=1.0, max_funding_skew=1.0),
        )


def test_risk_calibrated_deltas_leave_quotes_inside_soft_limit():
    bid, ask = risk_calibrated_deltas(
        0.5,
        0.7,
        inventory=2.0,
        inventory_limit=10.0,
        soft_limit_fraction=0.5,
        risk_widening=1.0,
    )
    assert bid == 0.5
    assert ask == 0.7


def test_risk_calibrated_deltas_widen_bid_for_long_inventory():
    bid, ask = risk_calibrated_deltas(
        1.0,
        1.0,
        inventory=8.0,
        inventory_limit=10.0,
        soft_limit_fraction=0.5,
        risk_widening=0.5,
    )
    assert bid == pytest.approx(1.6)
    assert ask == pytest.approx(1.0)


def test_risk_calibrated_deltas_widen_ask_for_short_inventory():
    bid, ask = risk_calibrated_deltas(
        1.0,
        1.0,
        inventory=-10.0,
        inventory_limit=10.0,
        soft_limit_fraction=0.5,
        risk_widening=0.5,
    )
    assert bid == pytest.approx(1.0)
    assert ask == pytest.approx(2.0)


def test_risk_calibrated_deltas_cap_existing_skew_before_inventory_adjustment():
    bid, ask = risk_calibrated_deltas(
        1.0,
        3.0,
        inventory=0.0,
        inventory_limit=10.0,
        soft_limit_fraction=0.5,
        risk_widening=0.0,
        skew_cap=0.25,
    )
    assert bid == pytest.approx(1.75)
    assert ask == pytest.approx(2.25)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"inventory_limit": 0.0}, "inventory_limit must be positive"),
        ({"inventory_limit": 1.0, "soft_limit_fraction": 1.0}, "soft_limit_fraction must be in"),
        ({"inventory_limit": 1.0, "risk_widening": -0.1}, "risk_widening must be non-negative"),
        ({"inventory_limit": 1.0, "skew_cap": -0.1}, "skew_cap must be non-negative"),
    ],
)
def test_risk_calibrated_deltas_validate_parameters(kwargs, message):
    with pytest.raises(ValueError, match=message):
        risk_calibrated_deltas(1.0, 1.0, inventory=0.0, **kwargs)
