from pathlib import Path

import lz4.frame
import pandas as pd

from perp_mm_funding.s3_fills import aggregate_trades_to_1m_candles, iter_fill_trades, iter_lz4_json_records


def test_parse_lz4_json_records_and_filter_crossed_eth(tmp_path: Path):
    path = tmp_path / "0.lz4"
    payload = (
        '{"events":[["0x1",{"coin":"ETH","px":"100.0","sz":"2.0","side":"B","time":1700000000000,"crossed":true}],'
        '["0x2",{"coin":"ETH","px":"100.0","sz":"2.0","side":"A","time":1700000000000,"crossed":false}],'
        '["0x3",{"coin":"BTC","px":"50000.0","sz":"0.1","side":"B","time":1700000000000,"crossed":true}]]}\n'
    )
    with lz4.frame.open(path, mode="wt", encoding="utf-8") as handle:
        handle.write(payload)

    records = list(iter_lz4_json_records(path))
    trades = list(iter_fill_trades(records, coin="ETH", crossed_only=True))

    assert len(trades) == 1
    assert trades[0].price == 100.0
    assert trades[0].size == 2.0


def test_aggregate_trades_to_1m_candles():
    rows = [
        {"events": [["0x1", {"coin": "ETH", "px": "100.0", "sz": "1.0", "time": 1700000000000, "crossed": True}]]},
        {"events": [["0x2", {"coin": "ETH", "px": "101.0", "sz": "3.0", "time": 1700000030000, "crossed": True}]]},
        {"events": [["0x3", {"coin": "ETH", "px": "99.0", "sz": "2.0", "time": 1700000060000, "crossed": True}]]},
    ]
    trades = list(iter_fill_trades(rows, coin="ETH", crossed_only=True))
    candles = aggregate_trades_to_1m_candles(trades, coin="ETH")

    assert len(candles) == 2
    first = candles.iloc[0]
    assert first["open"] == 100.0
    assert first["high"] == 101.0
    assert first["low"] == 100.0
    assert first["close"] == 101.0
    assert first["volume"] == 4.0
    assert first["n_trades"] == 2
    assert isinstance(first["open_time"], pd.Timestamp)

