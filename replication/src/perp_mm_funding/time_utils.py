from __future__ import annotations

from datetime import datetime, timezone

MS_PER_SECOND = 1_000
MS_PER_MINUTE = 60 * MS_PER_SECOND
MS_PER_HOUR = 60 * MS_PER_MINUTE
MS_PER_DAY = 24 * MS_PER_HOUR


def utc_now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * MS_PER_SECOND)


def ms_days_before(end_ms: int, days: int) -> int:
    return int(end_ms - days * MS_PER_DAY)


def to_utc_datetime(value_ms: int) -> datetime:
    return datetime.fromtimestamp(value_ms / MS_PER_SECOND, tz=timezone.utc)


def interval_to_ms(interval: str) -> int:
    table = {
        "1m": MS_PER_MINUTE,
        "3m": 3 * MS_PER_MINUTE,
        "5m": 5 * MS_PER_MINUTE,
        "15m": 15 * MS_PER_MINUTE,
        "30m": 30 * MS_PER_MINUTE,
        "1h": MS_PER_HOUR,
        "2h": 2 * MS_PER_HOUR,
        "4h": 4 * MS_PER_HOUR,
        "8h": 8 * MS_PER_HOUR,
        "12h": 12 * MS_PER_HOUR,
        "1d": MS_PER_DAY,
    }
    if interval not in table:
        raise ValueError(f"Unsupported interval: {interval}")
    return table[interval]

