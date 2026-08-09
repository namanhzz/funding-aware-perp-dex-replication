from __future__ import annotations

from pathlib import Path

from perp_mm_funding.official_fills_cache import _parse_hours, build_objects


def test_parse_hours_accepts_ranges_and_lists():
    assert _parse_hours("0,2-4,23") == [0, 2, 3, 4, 23]


def test_build_objects_creates_hourly_paths():
    objects = build_objects("20250727", "20250728", "0-1", Path("raw"))

    assert len(objects) == 4
    assert objects[0].key == "node_fills_by_block/hourly/20250727/0.lz4"
    assert str(objects[0].local_path).endswith("raw/20250727/0.lz4") or str(objects[0].local_path).endswith("raw\\20250727\\0.lz4")
