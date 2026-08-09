from __future__ import annotations

import pandas as pd

from perp_mm_funding.baselight_fills import (
    build_candles_from_baselight_parquet,
    parse_s3_listing,
    select_objects_for_window,
)


def test_parse_s3_listing_extracts_partitioned_objects():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
      <IsTruncated>false</IsTruncated>
      <Contents>
        <Key>root/year=2026/month=4/day=29/file.parquet</Key>
        <LastModified>2026-04-30T03:02:51.000Z</LastModified>
        <Size>123</Size>
      </Contents>
    </ListBucketResult>
    """

    objects, truncated, token = parse_s3_listing(xml, bucket_url="https://example.com")

    assert not truncated
    assert token is None
    assert len(objects) == 1
    assert objects[0].date.strftime("%Y-%m-%d") == "2026-04-29"
    assert objects[0].size == 123
    assert objects[0].url == "https://example.com/root/year=2026/month=4/day=29/file.parquet"


def test_select_objects_for_window_uses_day_partitions():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
      <IsTruncated>false</IsTruncated>
      <Contents><Key>root/year=2026/month=4/day=28/file.parquet</Key><Size>1</Size></Contents>
      <Contents><Key>root/year=2026/month=4/day=29/file.parquet</Key><Size>1</Size></Contents>
      <Contents><Key>root/year=2026/month=4/day=30/file.parquet</Key><Size>1</Size></Contents>
    </ListBucketResult>
    """
    objects, _, _ = parse_s3_listing(xml, bucket_url="https://example.com")
    start_ms = int(pd.Timestamp("2026-04-29T12:00:00Z").timestamp() * 1000)
    end_ms = int(pd.Timestamp("2026-04-29T12:01:00Z").timestamp() * 1000)

    selected = select_objects_for_window(objects, start_ms, end_ms)

    assert [item.date.strftime("%Y-%m-%d") for item in selected] == ["2026-04-29"]


def test_build_candles_from_baselight_parquet_filters_crossed_and_aggregates(tmp_path):
    path = tmp_path / "fills.parquet"
    frame = pd.DataFrame(
        [
            {"event_time_ms": 1_000, "tid": 1, "coin": "ETH", "crossed": True, "px": 100.0, "sz": 1.0},
            {"event_time_ms": 2_000, "tid": 2, "coin": "ETH", "crossed": False, "px": 999.0, "sz": 10.0},
            {"event_time_ms": 30_000, "tid": 3, "coin": "ETH", "crossed": True, "px": 101.0, "sz": 2.0},
            {"event_time_ms": 60_000, "tid": 4, "coin": "ETH", "crossed": True, "px": 102.0, "sz": 3.0},
            {"event_time_ms": 61_000, "tid": 5, "coin": "BTC", "crossed": True, "px": 50.0, "sz": 4.0},
        ]
    )
    frame.to_parquet(path, index=False)

    candles = build_candles_from_baselight_parquet(str(path), coin="ETH", crossed_only=True)

    assert len(candles) == 2
    first = candles.iloc[0]
    assert first["open"] == 100.0
    assert first["high"] == 101.0
    assert first["low"] == 100.0
    assert first["close"] == 101.0
    assert first["volume"] == 3.0
    assert first["n_trades"] == 2
    assert str(first["open_time"]) == "1970-01-01 00:00:00+00:00"
