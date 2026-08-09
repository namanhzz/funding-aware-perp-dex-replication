from __future__ import annotations

import pandas as pd
import pytest

from perp_mm_funding.build_intrabar_bridge import build_causal_intrabar_bridge


def _frames(venue_close: float = 105.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    venue = pd.DataFrame(
        {
            "open_time": [pd.Timestamp("2026-01-01T00:00:00Z")],
            "close_time": [pd.Timestamp("2026-01-01T00:02:59.999Z")],
            "coin": ["SOL"],
            "open": [100.0],
            "close": [venue_close],
        }
    )
    reference = pd.DataFrame(
        {
            "open_time": pd.date_range("2026-01-01", periods=3, freq="1min", tz="UTC"),
            "close_time": pd.date_range(
                "2026-01-01T00:00:59.999Z", periods=3, freq="1min"
            ),
            "open": [200.0, 202.0, 204.0],
            "close": [202.0, 204.0, 206.0],
        }
    )
    return venue, reference


def test_bridge_uses_reference_returns_and_venue_boundary() -> None:
    venue, reference = _frames()
    bridge = build_causal_intrabar_bridge(venue, reference)

    assert bridge["close"].tolist() == pytest.approx([101.0, 102.0, 105.0])
    assert bridge.iloc[-1]["close_time"] == venue.iloc[0]["close_time"]


def test_future_venue_close_changes_only_completed_boundary() -> None:
    venue_a, reference = _frames(105.0)
    venue_b, _ = _frames(115.0)

    close_a = build_causal_intrabar_bridge(venue_a, reference)["close"].tolist()
    close_b = build_causal_intrabar_bridge(venue_b, reference)["close"].tolist()

    assert close_a[:-1] == close_b[:-1]
    assert close_a[-1] == 105.0
    assert close_b[-1] == 115.0


def test_bridge_rejects_missing_reference_minutes() -> None:
    venue, reference = _frames()
    with pytest.raises(ValueError, match="2/3 rows"):
        build_causal_intrabar_bridge(venue, reference.iloc[:-1])
