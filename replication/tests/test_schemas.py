from perp_mm_funding.schemas import normalize_candle_rows, normalize_funding_rows


def test_normalize_funding_rows():
    frame = normalize_funding_rows(
        [
            {"coin": "ETH", "fundingRate": "0.0001", "premium": "0.0002", "time": 1_700_000_000_000},
            {"coin": "ETH", "fundingRate": "0.0002", "premium": "0.0003", "time": 1_700_000_000_000},
        ]
    )
    assert len(frame) == 1
    assert frame.loc[0, "funding_rate"] == 0.0002
    assert str(frame.loc[0, "time"].tz) == "UTC"


def test_normalize_candle_rows():
    frame = normalize_candle_rows(
        [
            {
                "t": 1_700_000_000_000,
                "T": 1_700_000_059_999,
                "s": "ETH",
                "i": "1m",
                "o": "100",
                "h": "101",
                "l": "99",
                "c": "100.5",
                "v": "12",
                "n": 7,
            }
        ]
    )
    assert list(frame.columns)[0] == "open_time"
    assert frame.loc[0, "close"] == 100.5
    assert frame.loc[0, "n_trades"] == 7

