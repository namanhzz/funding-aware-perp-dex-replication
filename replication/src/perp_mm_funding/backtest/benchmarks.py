from __future__ import annotations

from dataclasses import dataclass

from perp_mm_funding.model.riccati import QuadraticCoefficients
from perp_mm_funding.strategy.quotes import optimal_deltas


@dataclass(slots=True)
class BenchmarkDeltas:
    bid_delta: float
    ask_delta: float


def symmetric_constant(_t_hours: float, _q: float, _f: float, spread_bps: float, mid_price: float) -> BenchmarkDeltas:
    delta = mid_price * spread_bps / 10_000.0
    return BenchmarkDeltas(bid_delta=float(delta), ask_delta=float(delta))


def funding_aware(
    coefficients: QuadraticCoefficients,
    t_hours: float,
    q: float,
    f: float,
    intensity_k: float,
    min_delta: float,
) -> BenchmarkDeltas:
    bid, ask = optimal_deltas(coefficients, t_hours, q, f, intensity_k, min_delta=min_delta)
    return BenchmarkDeltas(bid_delta=bid, ask_delta=ask)


def pure_as(
    coefficients: QuadraticCoefficients,
    t_hours: float,
    q: float,
    intensity_k: float,
    min_delta: float,
) -> BenchmarkDeltas:
    bid, ask = optimal_deltas(coefficients, t_hours, q, 0.0, intensity_k, min_delta=min_delta)
    return BenchmarkDeltas(bid_delta=bid, ask_delta=ask)

