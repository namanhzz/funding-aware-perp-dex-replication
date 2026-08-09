from __future__ import annotations

from typing import Literal

FundingGateMode = Literal["absolute", "positive", "negative"]
Deltas = tuple[float, float]


def regime_gated_funding_aware_deltas(
    pure_as_deltas: Deltas,
    funding_aware_deltas: Deltas,
    funding_rate: float,
    threshold: float,
    mode: FundingGateMode = "absolute",
) -> Deltas:
    """Select pure-AS or funding-aware deltas based on the funding regime.

    The funding rate and threshold must use the same units. In ``absolute``
    mode, funding awareness is enabled when ``abs(funding_rate) >= threshold``.
    In ``positive`` and ``negative`` modes, only the corresponding signed tail
    enables funding awareness.
    """
    if threshold < 0:
        raise ValueError("threshold must be non-negative")

    if mode == "absolute":
        use_funding_aware = abs(funding_rate) >= threshold
    elif mode == "positive":
        use_funding_aware = funding_rate >= threshold
    elif mode == "negative":
        use_funding_aware = funding_rate <= -threshold
    else:
        raise ValueError(f"unsupported funding gate mode: {mode!r}")

    bid_delta, ask_delta = (
        funding_aware_deltas if use_funding_aware else pure_as_deltas
    )
    return float(bid_delta), float(ask_delta)
