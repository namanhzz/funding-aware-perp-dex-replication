from __future__ import annotations

from typing import Iterable, Mapping, Any

import pandas as pd


FUNDING_COLUMNS = ["time", "coin", "funding_rate", "premium"]
CANDLE_COLUMNS = [
    "open_time",
    "close_time",
    "coin",
    "interval",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "n_trades",
]


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in columns})


def normalize_funding_rows(rows: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    records = list(rows)
    if not records:
        return _empty_frame(FUNDING_COLUMNS)

    frame = pd.DataFrame.from_records(records)
    if "fundingRate" in frame.columns:
        frame["funding_rate"] = pd.to_numeric(frame["fundingRate"], errors="coerce")
    elif "funding_rate" in frame.columns:
        frame["funding_rate"] = pd.to_numeric(frame["funding_rate"], errors="coerce")
    else:
        raise ValueError("Funding rows are missing fundingRate")

    if "time" not in frame.columns:
        raise ValueError("Funding rows are missing time")
    frame["time"] = pd.to_datetime(pd.to_numeric(frame["time"]), unit="ms", utc=True)

    if "premium" in frame.columns:
        frame["premium"] = pd.to_numeric(frame["premium"], errors="coerce")
    else:
        frame["premium"] = pd.NA

    if "coin" not in frame.columns:
        frame["coin"] = pd.NA

    result = frame[FUNDING_COLUMNS].sort_values("time")
    return result.drop_duplicates(subset=["time", "coin"], keep="last").reset_index(drop=True)


def normalize_candle_rows(rows: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    records = list(rows)
    if not records:
        return _empty_frame(CANDLE_COLUMNS)

    frame = pd.DataFrame.from_records(records)
    rename = {
        "t": "open_time",
        "T": "close_time",
        "s": "coin",
        "i": "interval",
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
        "n": "n_trades",
    }
    frame = frame.rename(columns=rename)
    required = set(CANDLE_COLUMNS)
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Candle rows are missing fields: {sorted(missing)}")

    frame["open_time"] = pd.to_datetime(pd.to_numeric(frame["open_time"]), unit="ms", utc=True)
    frame["close_time"] = pd.to_datetime(pd.to_numeric(frame["close_time"]), unit="ms", utc=True)
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["n_trades"] = pd.to_numeric(frame["n_trades"], errors="coerce").fillna(0).astype("int64")

    result = frame[CANDLE_COLUMNS].sort_values("open_time")
    return result.drop_duplicates(subset=["open_time", "coin", "interval"], keep="last").reset_index(drop=True)

