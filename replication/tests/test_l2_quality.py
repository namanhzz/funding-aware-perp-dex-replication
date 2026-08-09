from __future__ import annotations

import csv
import gzip

from perp_mm_funding.l2_quality import _compress_spans, _scan_feature_file


def test_compress_spans_groups_consecutive_values():
    assert _compress_spans([1, 2, 3, 5, 8, 9]) == "1-3,5,8-9"


def test_scan_feature_file_counts_rows_and_basic_quality(tmp_path):
    path = tmp_path / "00.csv.gz"
    rows = [
        {
            "exchange_time_ms": "1000",
            "best_bid_px": "99",
            "best_ask_px": "101",
            "mid": "100",
            "spread": "2",
            "spread_bps": "200",
        },
        {
            "exchange_time_ms": "2000",
            "best_bid_px": "100",
            "best_ask_px": "102",
            "mid": "101",
            "spread": "2",
            "spread_bps": "198.01980198",
        },
    ]
    with gzip.open(path, "wt", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    scan = _scan_feature_file(path)

    assert scan["feature_rows"] == 2
    assert scan["first_exchange_time_ms"] == 1000
    assert scan["last_exchange_time_ms"] == 2000
    assert scan["invalid_mid_count"] == 0
    assert scan["negative_spread_count"] == 0
