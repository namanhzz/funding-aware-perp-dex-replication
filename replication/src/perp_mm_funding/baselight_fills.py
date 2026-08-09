from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import quote
from xml.etree import ElementTree

import httpx
import pandas as pd

from perp_mm_funding.io import write_parquet
from perp_mm_funding.schemas import CANDLE_COLUMNS

BASELIGHT_NODE_FILLS_BUCKET_URL = "https://588738577887-baselight-crawlers-prod-ue1-datasets.s3.us-east-1.amazonaws.com"
BASELIGHT_NODE_FILLS_PREFIX = (
    "iceberg_catalog/"
    "hyperliquid-blt37a4081ad89371364d267443a9ba7f8776143ca20c247618ed3bc40a65a64f3b/"
    "node_fills/data/parquet/"
)
S3_XML_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}


class BaselightDataError(RuntimeError):
    """Raised when Baselight public mirror metadata or files cannot be read."""


@dataclass(frozen=True, slots=True)
class BaselightObject:
    key: str
    url: str
    date: datetime
    size: int
    last_modified: str


def _empty_candles() -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in CANDLE_COLUMNS})


def _partition_date_from_key(key: str) -> datetime | None:
    marker = "year="
    if marker not in key:
        return None
    parts = key.split("/")
    values: dict[str, int] = {}
    for part in parts:
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        if name in {"year", "month", "day"}:
            try:
                values[name] = int(value)
            except ValueError:
                return None
    if {"year", "month", "day"}.issubset(values):
        return datetime(values["year"], values["month"], values["day"], tzinfo=timezone.utc)
    return None


def parse_s3_listing(xml_text: str, bucket_url: str = BASELIGHT_NODE_FILLS_BUCKET_URL) -> tuple[list[BaselightObject], bool, str | None]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise BaselightDataError(f"Could not parse Baselight S3 listing XML: {exc}") from exc

    objects: list[BaselightObject] = []
    for node in root.findall("s3:Contents", S3_XML_NS):
        key = node.findtext("s3:Key", default="", namespaces=S3_XML_NS)
        size_text = node.findtext("s3:Size", default="0", namespaces=S3_XML_NS)
        last_modified = node.findtext("s3:LastModified", default="", namespaces=S3_XML_NS)
        date = _partition_date_from_key(key)
        if not key or date is None:
            continue
        objects.append(
            BaselightObject(
                key=key,
                url=f"{bucket_url.rstrip('/')}/{key}",
                date=date,
                size=int(size_text),
                last_modified=last_modified,
            )
        )

    truncated = root.findtext("s3:IsTruncated", default="false", namespaces=S3_XML_NS).lower() == "true"
    next_token = root.findtext("s3:NextContinuationToken", default=None, namespaces=S3_XML_NS)
    return objects, truncated, next_token


def list_baselight_node_fill_objects(
    prefix: str = BASELIGHT_NODE_FILLS_PREFIX,
    bucket_url: str = BASELIGHT_NODE_FILLS_BUCKET_URL,
    timeout_s: float = 30.0,
) -> list[BaselightObject]:
    objects: list[BaselightObject] = []
    token: str | None = None
    with httpx.Client(timeout=timeout_s) as client:
        while True:
            query = f"list-type=2&prefix={quote(prefix, safe='')}"
            if token:
                query += f"&continuation-token={quote(token, safe='')}"
            response = client.get(f"{bucket_url.rstrip('/')}/?{query}")
            response.raise_for_status()
            page, truncated, token = parse_s3_listing(response.text, bucket_url=bucket_url)
            objects.extend(page)
            if not truncated:
                break
            if not token:
                raise BaselightDataError("Baselight S3 listing was truncated without a continuation token")
    return sorted(objects, key=lambda item: item.date)


def select_objects_for_window(
    objects: Iterable[BaselightObject],
    start_ms: int,
    end_ms: int,
) -> list[BaselightObject]:
    start_day_ms = int(datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp() * 1000)
    end_day_ms = int(datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp() * 1000)
    selected = []
    for obj in objects:
        day_ms = int(obj.date.timestamp() * 1000)
        if start_day_ms <= day_ms <= end_day_ms:
            selected.append(obj)
    return selected


def build_candles_from_baselight_parquet(
    parquet_url: str,
    coin: str,
    start_ms: int | None = None,
    end_ms: int | None = None,
    crossed_only: bool = True,
) -> pd.DataFrame:
    import duckdb

    filters = ["coin = ?"]
    params: list[object] = [parquet_url, coin.upper()]
    if crossed_only:
        filters.append("crossed = true")
    if start_ms is not None:
        filters.append("event_time_ms >= ?")
        params.append(int(start_ms))
    if end_ms is not None:
        filters.append("event_time_ms <= ?")
        params.append(int(end_ms))
    where_clause = " and ".join(filters)

    query = f"""
        with filtered as (
            select
                floor(event_time_ms / 60000)::BIGINT * 60000 as open_time_ms,
                event_time_ms,
                tid,
                px,
                sz
            from read_parquet(?)
            where {where_clause}
        ),
        candles as (
            select
                open_time_ms,
                first(px order by event_time_ms, tid) as open,
                max(px) as high,
                min(px) as low,
                last(px order by event_time_ms, tid) as close,
                sum(sz) as volume,
                count(*) as n_trades
            from filtered
            group by open_time_ms
        )
        select open_time_ms, open, high, low, close, volume, n_trades
        from candles
        order by open_time_ms
    """

    con = duckdb.connect()
    try:
        if parquet_url.startswith(("http://", "https://", "s3://")):
            con.execute("INSTALL httpfs")
            con.execute("LOAD httpfs")
        frame = con.execute(query, params).fetch_df()
    finally:
        con.close()

    if frame.empty:
        return _empty_candles()

    frame["open_time"] = pd.to_datetime(frame["open_time_ms"], unit="ms", utc=True)
    frame["close_time"] = frame["open_time"] + pd.Timedelta(minutes=1) - pd.Timedelta(milliseconds=1)
    frame["coin"] = coin.upper()
    frame["interval"] = "1m"
    frame["n_trades"] = pd.to_numeric(frame["n_trades"]).astype("int64")
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame[CANDLE_COLUMNS].reset_index(drop=True)


def write_daily_baselight_candles(
    obj: BaselightObject,
    coin: str,
    output_dir: Path,
    start_ms: int | None = None,
    end_ms: int | None = None,
    crossed_only: bool = True,
    overwrite: bool = False,
) -> Path:
    output = output_dir / f"{coin.lower()}-baselight-{obj.date:%Y%m%d}.parquet"
    if output.exists() and not overwrite:
        return output
    frame = build_candles_from_baselight_parquet(
        obj.url,
        coin=coin,
        start_ms=start_ms,
        end_ms=end_ms,
        crossed_only=crossed_only,
    )
    write_parquet(frame, output)
    return output
