import pandas as pd

from perp_mm_funding.run_stress_windows import select_stress_windows


def test_select_stress_windows_returns_named_windows():
    times = pd.date_range("2025-01-01", periods=6 * 24 * 60, freq="1min", tz="UTC")
    price = pd.DataFrame(
        {
            "time": times,
            "mid": [100 + i for i in range(len(times))],
        }
    )
    funding = pd.DataFrame(
        {
            "time": times,
            "funding_rate": [
                0.00001 if ts.day <= 2 else -0.00002 if ts.day <= 4 else 0.0
                for ts in times
            ],
        }
    )

    windows = select_stress_windows(price, funding, window_days=2)

    assert {window.name for window in windows} == {
        "high_positive_funding",
        "most_negative_funding",
        "high_volatility",
        "calm",
    }
    assert all(window.days == 2 for window in windows)
