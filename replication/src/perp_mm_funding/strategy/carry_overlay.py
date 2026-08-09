from __future__ import annotations

from dataclasses import dataclass

from perp_mm_funding.model.riccati import QuadraticCoefficients
from perp_mm_funding.strategy.quotes import optimal_deltas


@dataclass(frozen=True, slots=True)
class CarryOverlayParams:
    target_inventory_per_cash_funding: float
    max_target_inventory: float
    skew_per_inventory: float
    max_skew: float


@dataclass(frozen=True, slots=True)
class CarryOverlayDeltas:
    bid_delta: float
    ask_delta: float
    target_inventory: float
    skew: float


def _clip(value: float, bound: float) -> float:
    if bound < 0:
        raise ValueError("bounds must be non-negative")
    return min(max(value, -bound), bound)


def _validate_params(params: CarryOverlayParams) -> None:
    if params.target_inventory_per_cash_funding < 0:
        raise ValueError("target_inventory_per_cash_funding must be non-negative")
    if params.max_target_inventory < 0:
        raise ValueError("max_target_inventory must be non-negative")
    if params.skew_per_inventory < 0:
        raise ValueError("skew_per_inventory must be non-negative")
    if params.max_skew < 0:
        raise ValueError("max_skew must be non-negative")


def carry_target_inventory(funding_signal: float, params: CarryOverlayParams) -> float:
    """Return the carry target inventory implied by the funding signal.

    Positive funding means long perp inventory pays funding, so the carry target
    is short. Negative funding means long perp inventory earns funding.
    """
    _validate_params(params)
    target = -float(funding_signal) * params.target_inventory_per_cash_funding
    return _clip(target, params.max_target_inventory)


def apply_carry_overlay(
    bid_delta: float,
    ask_delta: float,
    inventory: float,
    funding_signal: float,
    params: CarryOverlayParams,
    min_delta: float = 0.0,
) -> CarryOverlayDeltas:
    target = carry_target_inventory(funding_signal, params)
    inventory_error = float(inventory) - target
    skew = _clip(inventory_error * params.skew_per_inventory, params.max_skew)
    return CarryOverlayDeltas(
        bid_delta=float(max(min_delta, bid_delta + skew)),
        ask_delta=float(max(min_delta, ask_delta - skew)),
        target_inventory=float(target),
        skew=float(skew),
    )


def carry_overlay_deltas(
    coefficients: QuadraticCoefficients,
    t_hours: float,
    q: float,
    funding_signal: float,
    intensity_k: float,
    params: CarryOverlayParams,
    min_delta: float = 0.0,
) -> CarryOverlayDeltas:
    base_bid, base_ask = optimal_deltas(
        coefficients=coefficients,
        t_hours=t_hours,
        q=q,
        f=0.0,
        intensity_k=intensity_k,
        min_delta=min_delta,
    )
    return apply_carry_overlay(
        bid_delta=base_bid,
        ask_delta=base_ask,
        inventory=q,
        funding_signal=funding_signal,
        params=params,
        min_delta=min_delta,
    )
