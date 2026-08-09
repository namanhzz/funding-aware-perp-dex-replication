from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

import boto3
import lz4.frame
import pandas as pd
import typer
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

from perp_mm_funding.io import ensure_parent, write_parquet
from perp_mm_funding.schemas import CANDLE_COLUMNS
from perp_mm_funding.time_utils import MS_PER_DAY, ms_days_before, utc_now_ms

HYPERLIQUID_NODE_DATA_BUCKET = "hl-mainnet-node-data"
NODE_FILLS_BY_BLOCK_PREFIX = "node_fills_by_block/hourly"

app = typer.Typer(help="Build candles from official Hyperliquid S3 node_fills_by_block data.")


class HyperliquidS3Error(RuntimeError):
    """Raised when official Hyperliquid S3 data cannot be read."""


class HyperliquidS3MissingObject(HyperliquidS3Error):
    """Raised when an expected hourly S3 object is absent."""


@dataclass(slots=True)
class FillTrade:
    time_ms: int
    coin: str
    price: float
    size: float
    side: str | None
    crossed: bool | None


def _window(days: int, start_ms: int | None, end_ms: int | None) -> tuple[int, int]:
    end = int(end_ms) if end_ms is not None else utc_now_ms()
    start = int(start_ms) if start_ms is not None else ms_days_before(end, days)
    if start >= end:
        raise typer.BadParameter("start_ms must be before end_ms")
    return start, end


def _utc_date_from_yyyymmdd(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def _date_range(start: date, end: date) -> Iterator[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _ms_to_utc(value_ms: int) -> datetime:
    return datetime.fromtimestamp(value_ms / 1000.0, tz=timezone.utc)


def _day_bounds(day: date) -> tuple[int, int]:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1) - timedelta(milliseconds=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def hourly_fill_key(day: date, hour: int) -> str:
    if hour < 0 or hour > 23:
        raise ValueError("hour must be in [0, 23]")
    return f"{NODE_FILLS_BY_BLOCK_PREFIX}/{day:%Y%m%d}/{hour}.lz4"


def local_hourly_path(raw_dir: Path, day: date, hour: int) -> Path:
    return raw_dir / f"{day:%Y%m%d}" / f"{hour}.lz4"


def _s3_client(unsigned: bool = False):
    if unsigned:
        return boto3.client("s3", config=Config(signature_version=UNSIGNED))
    return boto3.client("s3")


def download_hourly_fill_file(
    day: date,
    hour: int,
    raw_dir: Path,
    bucket: str = HYPERLIQUID_NODE_DATA_BUCKET,
    requester_pays: bool = True,
    unsigned: bool = False,
    overwrite: bool = False,
) -> Path:
    key = hourly_fill_key(day, hour)
    output = local_hourly_path(raw_dir, day, hour)
    if output.exists() and not overwrite:
        return output

    ensure_parent(output)
    extra_args = {"RequestPayer": "requester"} if requester_pays else {}
    client = _s3_client(unsigned=unsigned)
    try:
        client.download_file(bucket, key, str(output), ExtraArgs=extra_args)
    except NoCredentialsError as exc:
        raise HyperliquidS3Error(
            "AWS credentials are required for this requester-pays bucket. "
            "Set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY or configure an AWS profile."
        ) from exc
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            raise HyperliquidS3MissingObject(f"Missing s3://{bucket}/{key}") from exc
        if output.exists() and output.stat().st_size == 0:
            output.unlink()
        raise HyperliquidS3Error(f"Failed to download s3://{bucket}/{key}: {exc}") from exc
    except BotoCoreError as exc:
        if output.exists() and output.stat().st_size == 0:
            output.unlink()
        raise HyperliquidS3Error(f"Failed to download s3://{bucket}/{key}: {exc}") from exc
    return output


def iter_lz4_json_records(path: Path) -> Iterator[dict[str, Any]]:
    try:
        with lz4.frame.open(path, mode="rt", encoding="utf-8") as handle:
            buffer: list[str] = []
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                    if isinstance(record, dict):
                        yield record
                    elif isinstance(record, list):
                        for item in record:
                            if isinstance(item, dict):
                                yield item
                    continue
                except json.JSONDecodeError:
                    buffer.append(stripped)
            if buffer:
                parsed = json.loads("".join(buffer))
                if isinstance(parsed, dict):
                    yield parsed
                elif isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict):
                            yield item
    except Exception as exc:
        raise HyperliquidS3Error(f"Failed to parse LZ4 JSON records from {path}: {exc}") from exc


def _event_to_fill(event: Any) -> tuple[str | None, dict[str, Any]] | None:
    if isinstance(event, dict):
        return None, event
    if isinstance(event, list) and len(event) >= 2 and isinstance(event[1], dict):
        address = str(event[0]) if event[0] is not None else None
        return address, event[1]
    return None


def iter_fill_trades(
    records: Iterable[dict[str, Any]],
    coin: str,
    crossed_only: bool = True,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> Iterator[FillTrade]:
    target = coin.upper()
    for record in records:
        events = record.get("events", [])
        if isinstance(events, str):
            try:
                events = json.loads(events)
            except json.JSONDecodeError:
                continue
        if not isinstance(events, list):
            continue
        for event in events:
            parsed = _event_to_fill(event)
            if parsed is None:
                continue
            _address, fill = parsed
            if str(fill.get("coin", "")).upper() != target:
                continue
            crossed = fill.get("crossed")
            if crossed_only and crossed is not True:
                continue
            try:
                time_ms = int(fill["time"])
                if start_ms is not None and time_ms < start_ms:
                    continue
                if end_ms is not None and time_ms > end_ms:
                    continue
                yield FillTrade(
                    time_ms=time_ms,
                    coin=target,
                    price=float(fill["px"]),
                    size=float(fill["sz"]),
                    side=str(fill.get("side")) if fill.get("side") is not None else None,
                    crossed=bool(crossed) if crossed is not None else None,
                )
            except (KeyError, TypeError, ValueError):
                continue


def aggregate_trades_to_1m_candles(trades: Iterable[FillTrade], coin: str) -> pd.DataFrame:
    rows = [
        {
            "trade_time": pd.to_datetime(trade.time_ms, unit="ms", utc=True),
            "coin": trade.coin,
            "price": trade.price,
            "size": trade.size,
        }
        for trade in trades
    ]
    if not rows:
        return pd.DataFrame({column: pd.Series(dtype="object") for column in CANDLE_COLUMNS})

    frame = pd.DataFrame.from_records(rows).sort_values("trade_time")
    frame["open_time"] = frame["trade_time"].dt.floor("1min")
    grouped = frame.groupby("open_time", sort=True)
    candles = grouped.agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        volume=("size", "sum"),
        n_trades=("price", "size"),
    ).reset_index()
    candles["close_time"] = candles["open_time"] + pd.Timedelta(minutes=1) - pd.Timedelta(milliseconds=1)
    candles["coin"] = coin.upper()
    candles["interval"] = "1m"
    return candles[CANDLE_COLUMNS].reset_index(drop=True)


def build_daily_candles_from_s3(
    day: date,
    coin: str,
    raw_dir: Path,
    bucket: str = HYPERLIQUID_NODE_DATA_BUCKET,
    requester_pays: bool = True,
    unsigned: bool = False,
    overwrite_raw: bool = False,
    crossed_only: bool = True,
    skip_missing: bool = True,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> pd.DataFrame:
    day_start, day_end = _day_bounds(day)
    window_start = max(day_start, start_ms) if start_ms is not None else day_start
    window_end = min(day_end, end_ms) if end_ms is not None else day_end
    trades: list[FillTrade] = []

    for hour in range(24):
        hour_start = int(datetime.combine(day, time(hour=hour), tzinfo=timezone.utc).timestamp() * 1000)
        hour_end = hour_start + 60 * 60 * 1000 - 1
        if hour_end < window_start or hour_start > window_end:
            continue
        try:
            path = download_hourly_fill_file(
                day=day,
                hour=hour,
                raw_dir=raw_dir,
                bucket=bucket,
                requester_pays=requester_pays,
                unsigned=unsigned,
                overwrite=overwrite_raw,
            )
        except HyperliquidS3MissingObject:
            if skip_missing:
                continue
            raise
        records = iter_lz4_json_records(path)
        trades.extend(iter_fill_trades(records, coin=coin, crossed_only=crossed_only, start_ms=window_start, end_ms=window_end))

    return aggregate_trades_to_1m_candles(trades, coin=coin)


@app.command()
def probe(
    day: str = typer.Option("20260322", help="UTC date in YYYYMMDD."),
    hour: int = typer.Option(0, min=0, max=23),
    coin: str = typer.Option("ETH"),
    raw_dir: Path = typer.Option(Path("data/raw/hyperliquid-s3-node-fills")),
    requester_pays: bool = typer.Option(True),
    unsigned: bool = typer.Option(False, help="Try unsigned S3 access. Requester-pays usually requires signed AWS credentials."),
) -> None:
    parsed_day = _utc_date_from_yyyymmdd(day)
    try:
        path = download_hourly_fill_file(parsed_day, hour, raw_dir, requester_pays=requester_pays, unsigned=unsigned)
        records = iter_lz4_json_records(path)
        trades = list(iter_fill_trades(records, coin=coin, crossed_only=True))
    except HyperliquidS3Error as exc:
        typer.echo(f"S3 probe failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Downloaded {path}")
    typer.echo(f"Extracted {len(trades)} crossed {coin.upper()} fills")
    if trades:
        sample = trades[0]
        typer.echo(f"First fill: time={_ms_to_utc(sample.time_ms)} price={sample.price} size={sample.size}")


@app.command("candles")
def candles(
    coin: str = typer.Option("ETH"),
    days: int = typer.Option(540, min=1),
    start_ms: int | None = typer.Option(None),
    end_ms: int | None = typer.Option(None),
    raw_dir: Path = typer.Option(Path("data/raw/hyperliquid-s3-node-fills")),
    parts_dir: Path = typer.Option(Path("data/clean/hyperliquid-s3-candle-parts")),
    out: Path = typer.Option(Path("data/clean/eth-hyperliquid-s3-1m.parquet")),
    requester_pays: bool = typer.Option(True),
    unsigned: bool = typer.Option(False, help="Try unsigned S3 access. Requester-pays usually requires signed AWS credentials."),
    overwrite_raw: bool = typer.Option(False),
    overwrite_parts: bool = typer.Option(False),
    crossed_only: bool = typer.Option(True, help="Use only crossed/taker fills to avoid maker+taker double-counted volume."),
    skip_missing: bool = typer.Option(True, help="Skip missing hourly objects, useful before node_fills_by_block coverage begins."),
) -> None:
    start, end = _window(days, start_ms, end_ms)
    start_day = _ms_to_utc(start).date()
    end_day = _ms_to_utc(end).date()
    parts_dir.mkdir(parents=True, exist_ok=True)
    part_paths: list[Path] = []

    for day in _date_range(start_day, end_day):
        part_path = parts_dir / f"{coin.lower()}-1m-{day:%Y%m%d}.parquet"
        part_paths.append(part_path)
        if part_path.exists() and not overwrite_parts:
            frame = pd.read_parquet(part_path)
            typer.echo(f"{day:%Y-%m-%d}: skipped existing rows={len(frame)}")
            continue
        try:
            frame = build_daily_candles_from_s3(
                day=day,
                coin=coin,
                raw_dir=raw_dir,
                requester_pays=requester_pays,
                unsigned=unsigned,
                overwrite_raw=overwrite_raw,
                crossed_only=crossed_only,
                skip_missing=skip_missing,
                start_ms=start,
                end_ms=end,
            )
        except HyperliquidS3Error as exc:
            typer.echo(f"{day:%Y-%m-%d}: S3 download/parse failed: {exc}", err=True)
            raise typer.Exit(1) from exc
        write_parquet(frame, part_path)
        typer.echo(f"{day:%Y-%m-%d}: wrote rows={len(frame)}")

    frames = [pd.read_parquet(path) for path in part_paths if path.exists()]
    if not frames:
        raise typer.BadParameter("No daily candle parts were produced")
    combined = pd.concat(frames, ignore_index=True).sort_values("open_time")
    combined = combined.drop_duplicates(subset=["open_time", "coin", "interval"], keep="last")
    write_parquet(combined.reset_index(drop=True), out)
    typer.echo(f"Wrote {len(combined)} S3-derived Hyperliquid 1m candles to {out}")


if __name__ == "__main__":
    app()
