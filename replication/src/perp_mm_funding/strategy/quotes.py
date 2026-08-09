from __future__ import annotations

from dataclasses import dataclass
from math import copysign

from perp_mm_funding.model.riccati import QuadraticCoefficients


@dataclass(slots=True)
class Quote:
    bid_delta: float
    ask_delta: float
    bid_price: float
    ask_price: float


@dataclass(frozen=True, slots=True)
class FractionalFundingQuoteConfig:
    control_horizon_hours: float
    max_funding_skew: float
    min_delta: float = 0.0

    def __post_init__(self) -> None:
        if self.control_horizon_hours <= 0:
            raise ValueError("control_horizon_hours must be positive")
        if self.max_funding_skew < 0:
            raise ValueError("max_funding_skew must be non-negative")
        if self.min_delta < 0:
            raise ValueError("min_delta must be non-negative")


def optimal_deltas(
    coefficients: QuadraticCoefficients,
    t_hours: float,
    q: float,
    f: float,
    intensity_k: float,
    min_delta: float = 0.0,
) -> tuple[float, float]:
    if intensity_k <= 0:
        raise ValueError("intensity_k must be positive")
    theta_now = coefficients.theta(t_hours, q, f)
    ask_jump = coefficients.theta(t_hours, q - 1.0, f) - theta_now
    bid_jump = coefficients.theta(t_hours, q + 1.0, f) - theta_now
    ask_delta = max(min_delta, 1.0 / intensity_k - ask_jump)
    bid_delta = max(min_delta, 1.0 / intensity_k - bid_jump)
    return float(bid_delta), float(ask_delta)


def explicit_s_fractional_funding_deltas(
    coefficients: QuadraticCoefficients,
    t_hours: float,
    q: float,
    funding_rate: float,
    mid_price: float,
    intensity_k: float,
    config: FractionalFundingQuoteConfig,
) -> tuple[float, float]:
    """Quote deltas using fractional funding with explicit spot cash exposure.

    The Riccati state receives the raw fractional funding rate. The explicit
    cash term then skews quotes by the bounded expected per-unit funding cash
    over the configured control horizon:

        mid_price * funding_rate * control_horizon_hours

    Positive funding means long perp inventory pays funding, so the bid is
    widened and the ask is tightened. Negative funding does the reverse.
    """
    if mid_price <= 0:
        raise ValueError("mid_price must be positive")

    bid_delta, ask_delta = optimal_deltas(
        coefficients,
        t_hours=t_hours,
        q=q,
        f=funding_rate,
        intensity_k=intensity_k,
        min_delta=config.min_delta,
    )
    cash_skew = mid_price * funding_rate * config.control_horizon_hours
    bounded_skew = max(-config.max_funding_skew, min(config.max_funding_skew, cash_skew))
    return (
        float(max(config.min_delta, bid_delta + bounded_skew)),
        float(max(config.min_delta, ask_delta - bounded_skew)),
    )


def risk_calibrated_deltas(
    bid_delta: float,
    ask_delta: float,
    inventory: float,
    inventory_limit: float,
    soft_limit_fraction: float = 0.5,
    risk_widening: float = 0.0,
    skew_cap: float | None = None,
) -> tuple[float, float]:
    """Apply inventory-limit risk calibration to already-computed quote deltas.

    Positive inventory widens the bid side first to avoid adding more long
    exposure; negative inventory widens the ask side first. Existing skew,
    including funding-induced skew, can be capped before inventory risk is
    applied.
    """
    if bid_delta < 0 or ask_delta < 0:
        raise ValueError("bid_delta and ask_delta must be non-negative")
    if inventory_limit <= 0:
        raise ValueError("inventory_limit must be positive")
    if not 0 <= soft_limit_fraction < 1:
        raise ValueError("soft_limit_fraction must be in [0, 1)")
    if risk_widening < 0:
        raise ValueError("risk_widening must be non-negative")
    if skew_cap is not None and skew_cap < 0:
        raise ValueError("skew_cap must be non-negative")

    center = (bid_delta + ask_delta) / 2.0
    skew = (ask_delta - bid_delta) / 2.0
    if skew_cap is not None:
        skew = min(abs(skew), skew_cap) * copysign(1.0, skew)

    soft_limit = inventory_limit * soft_limit_fraction
    excess_inventory = max(abs(inventory) - soft_limit, 0.0)
    hard_band = inventory_limit - soft_limit
    pressure = min(excess_inventory / hard_band, 1.0)
    widening = risk_widening * pressure

    if inventory > 0:
        skew -= widening
    elif inventory < 0:
        skew += widening
    center += widening

    return float(max(0.0, center - skew)), float(max(0.0, center + skew))


def make_quote(
    mid_price: float,
    coefficients: QuadraticCoefficients,
    t_hours: float,
    q: float,
    f: float,
    intensity_k: float,
    tick_size: float = 0.01,
) -> Quote:
    bid_delta, ask_delta = optimal_deltas(coefficients, t_hours, q, f, intensity_k, min_delta=tick_size)
    bid_price = round((mid_price - bid_delta) / tick_size) * tick_size
    ask_price = round((mid_price + ask_delta) / tick_size) * tick_size
    return Quote(
        bid_delta=float(bid_delta),
        ask_delta=float(ask_delta),
        bid_price=float(bid_price),
        ask_price=float(ask_price),
    )
