from __future__ import annotations

import pandas as pd

from perp_mm_funding.fill_intensity import (
    _fit_exponential_bernoulli_intensity,
    _fit_exponential_intensity,
    _hit_counts_for_hour,
)


def test_fit_exponential_intensity_returns_positive_parameters():
    counts = pd.DataFrame(
        {
            "distance_bps": [0.0, 0.0, 1.0, 1.0, 5.0, 5.0],
            "side": ["bid", "ask", "bid", "ask", "bid", "ask"],
            "hits": [100, 110, 80, 85, 20, 22],
            "exposure_hours": [10.0] * 6,
        }
    )
    fit = _fit_exponential_intensity(counts, median_mid=3000.0)

    assert fit.lambda_base_per_hour > 0
    assert fit.intensity_k_bps > 0
    assert fit.intensity_k_price > 0


def test_hit_counts_for_day_counts_bid_and_ask_threshold_hits():
    panel = pd.DataFrame(
        {
            "minute": pd.to_datetime(["2025-12-01 00:00:00Z", "2025-12-01 00:01:00Z"]),
            "mid": [100.0, 200.0],
        }
    )
    fills = pd.DataFrame(
        {
            "minute": pd.to_datetime(["2025-12-01 00:00:00Z", "2025-12-01 00:00:00Z", "2025-12-01 00:01:00Z"]),
            "price": [99.0, 101.0, 202.0],
            "sz": [1.0, 1.0, 1.0],
            "tid": [1, 2, 3],
        }
    )

    counts, exposure = _hit_counts_for_hour(fills, panel, [0.0, 50.0])

    assert exposure == 2
    zero = counts[counts["distance_bps"] == 0.0].set_index("side")["hits"].to_dict()
    assert zero["bid"] == 1
    assert zero["ask"] == 2


def test_volume_minute_mode_counts_minutes_above_quote_size():
    panel = pd.DataFrame(
        {
            "minute": pd.to_datetime(["2025-12-01 00:00:00Z", "2025-12-01 00:01:00Z"]),
            "mid": [100.0, 100.0],
        }
    )
    fills = pd.DataFrame(
        {
            "minute": pd.to_datetime(
                [
                    "2025-12-01 00:00:00Z",
                    "2025-12-01 00:00:00Z",
                    "2025-12-01 00:01:00Z",
                ]
            ),
            "price": [99.0, 99.0, 101.0],
            "size": [0.4, 0.7, 2.0],
        }
    )

    counts, exposure = _hit_counts_for_hour(fills, panel, [0.0], fit_mode="volume_minute", quote_size=1.0)

    assert exposure == 2
    zero = counts.set_index("side")["hits"].to_dict()
    assert zero["bid"] == 1
    assert zero["ask"] == 1


def test_bernoulli_intensity_fit_returns_positive_parameters():
    counts = pd.DataFrame(
        {
            "distance_bps": [0.0, 0.0, 5.0, 5.0, 20.0, 20.0],
            "side": ["bid", "ask", "bid", "ask", "bid", "ask"],
            "hits": [900, 910, 420, 430, 80, 85],
            "exposure_minutes": [1000] * 6,
            "exposure_hours": [1000 / 60.0] * 6,
        }
    )

    fit = _fit_exponential_bernoulli_intensity(counts, median_mid=3000.0)

    assert fit.lambda_base_per_hour > 0
    assert fit.intensity_k_bps > 0
    assert fit.intensity_k_price > 0
