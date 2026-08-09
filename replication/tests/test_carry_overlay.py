import numpy as np

from perp_mm_funding.model.riccati import QuadraticCoefficients
from perp_mm_funding.strategy.carry_overlay import (
    CarryOverlayParams,
    apply_carry_overlay,
    carry_overlay_deltas,
    carry_target_inventory,
)


def _params() -> CarryOverlayParams:
    return CarryOverlayParams(
        target_inventory_per_cash_funding=2.0,
        max_target_inventory=3.0,
        skew_per_inventory=0.1,
        max_skew=0.5,
    )


def test_carry_target_is_short_when_positive_funding_is_paid_by_longs():
    assert carry_target_inventory(1.0, _params()) == -2.0
    assert carry_target_inventory(-1.0, _params()) == 2.0


def test_carry_target_inventory_is_bounded():
    assert carry_target_inventory(10.0, _params()) == -3.0
    assert carry_target_inventory(-10.0, _params()) == 3.0


def test_overlay_tightens_ask_and_widens_bid_when_inventory_is_above_target():
    deltas = apply_carry_overlay(
        bid_delta=1.0,
        ask_delta=1.0,
        inventory=0.0,
        funding_signal=1.0,
        params=_params(),
    )

    assert deltas.target_inventory == -2.0
    assert deltas.skew == 0.2
    assert deltas.bid_delta == 1.2
    assert deltas.ask_delta == 0.8


def test_overlay_tightens_bid_and_widens_ask_when_inventory_is_below_target():
    deltas = apply_carry_overlay(
        bid_delta=1.0,
        ask_delta=1.0,
        inventory=0.0,
        funding_signal=-1.0,
        params=_params(),
    )

    assert deltas.target_inventory == 2.0
    assert deltas.skew == -0.2
    assert deltas.bid_delta == 0.8
    assert deltas.ask_delta == 1.2


def test_overlay_skew_and_output_deltas_are_bounded():
    deltas = apply_carry_overlay(
        bid_delta=0.1,
        ask_delta=0.1,
        inventory=10.0,
        funding_signal=0.0,
        params=_params(),
        min_delta=0.01,
    )

    assert deltas.skew == 0.5
    assert deltas.bid_delta == 0.6
    assert deltas.ask_delta == 0.01


def test_carry_overlay_starts_from_pure_as_deltas():
    coefficients = QuadraticCoefficients(t_grid=np.array([0.0, 1.0]), values=np.zeros((6, 2)))

    deltas = carry_overlay_deltas(
        coefficients=coefficients,
        t_hours=0.0,
        q=0.0,
        funding_signal=0.0,
        intensity_k=100.0,
        params=_params(),
        min_delta=0.01,
    )

    assert deltas.bid_delta == 0.01
    assert deltas.ask_delta == 0.01
    assert deltas.target_inventory == 0.0
    assert deltas.skew == 0.0
