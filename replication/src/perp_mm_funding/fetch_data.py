from __future__ import annotations

from pathlib import Path

import pandas as pd
import typer

from perp_mm_funding.baselight_fills import (
    build_candles_from_baselight_parquet,
    list_baselight_node_fill_objects,
    select_objects_for_window,
)
from perp_mm_funding.binance_client import BinanceFuturesClient
from perp_mm_funding.hyperliquid_client import HyperliquidClient
from perp_mm_funding.io import ensure_parent, write_jsonl, write_parquet
from perp_mm_funding.schemas import normalize_candle_rows, normalize_funding_rows
from perp_mm_funding.time_utils import MS_PER_DAY, interval_to_ms, ms_days_before, utc_now_ms

app = typer.Typer(help="Fetch and normalize Hyperliquid perp data.")


def _window(days: int, start_ms: int | None, end_ms: int | None) -> tuple[int, int]:
    end = int(end_ms) if end_ms is not None else utc_now_ms()
    start = int(start_ms) if start_ms is not None else ms_days_before(end, days)
    if start >= end:
        raise typer.BadParameter("start_ms must be before end_ms")
    return start, end


def _normalize_binance_mark_rows(symbol: str, interval: str, rows: list[list[object]]) -> pd.DataFrame:
    records = []
    for row in rows:
        records.append(
            {
                "open_time": pd.to_datetime(int(row[0]), unit="ms", utc=True),
                "close_time": pd.to_datetime(int(row[6]), unit="ms", utc=True),
                "coin": symbol.upper(),
                "interval": interval,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": 0.0,
                "n_trades": int(row[8]) if len(row) > 8 else 0,
            }
        )
    if not records:
        return normalize_candle_rows([])
    frame = pd.DataFrame.from_records(records)
    return frame.sort_values("open_time").drop_duplicates(
        subset=["open_time", "coin", "interval"], keep="last"
    ).reset_index(drop=True)


def _expected_candle_count(start_ms: int, end_ms: int, interval: str) -> int:
    step_ms = interval_to_ms(interval)
    first_open = ((int(start_ms) + step_ms - 1) // step_ms) * step_ms
    last_open = (int(end_ms) // step_ms) * step_ms
    if last_open < first_open:
        return 0
    return int((last_open - first_open) // step_ms + 1)


def _partial_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.partial{path.suffix}")


@app.command()
def funding(
    coin: str = typer.Option("ETH", help="Hyperliquid coin symbol."),
    days: int = typer.Option(90, min=1, help="Lookback window if start_ms is omitted."),
    start_ms: int | None = typer.Option(None, help="Unix epoch start in milliseconds."),
    end_ms: int | None = typer.Option(None, help="Unix epoch end in milliseconds."),
    raw_out: Path | None = typer.Option(None, help="Optional raw JSONL output path."),
    out: Path = typer.Option(Path("data/clean/eth-funding-1h.parquet"), help="Clean parquet output path."),
) -> None:
    start, end = _window(days, start_ms, end_ms)
    client = HyperliquidClient()
    rows = client.paginate_funding_history(coin, start, end)
    frame = normalize_funding_rows(rows)

    if raw_out is None:
        raw_out = Path(f"data/raw/{coin.lower()}-funding-{start}-{end}.jsonl")
    write_jsonl(rows, raw_out)
    write_parquet(frame, out)
    typer.echo(f"Wrote {len(rows)} funding rows to {out}")


@app.command()
def candles(
    coin: str = typer.Option("ETH", help="Hyperliquid coin symbol."),
    interval: str = typer.Option("1m", help="Hyperliquid candle interval."),
    days: int = typer.Option(30, min=1, help="Lookback window if start_ms is omitted."),
    start_ms: int | None = typer.Option(None, help="Unix epoch start in milliseconds."),
    end_ms: int | None = typer.Option(None, help="Unix epoch end in milliseconds."),
    raw_out: Path | None = typer.Option(None, help="Optional raw JSONL output path."),
    out: Path = typer.Option(Path("data/clean/eth-perp-1m.parquet"), help="Clean parquet output path."),
) -> None:
    start, end = _window(days, start_ms, end_ms)
    client = HyperliquidClient()
    rows = client.paginate_candles(coin, interval, start, end)
    frame = normalize_candle_rows(rows)

    if raw_out is None:
        raw_out = Path(f"data/raw/{coin.lower()}-candles-{interval}-{start}-{end}.jsonl")
    write_jsonl(rows, raw_out)
    write_parquet(frame, out)
    typer.echo(f"Wrote {len(rows)} candle rows to {out}")


@app.command("candles-long")
def candles_long(
    coin: str = typer.Option("ETH", help="Hyperliquid coin symbol."),
    interval: str = typer.Option("1m", help="Hyperliquid candle interval."),
    days: int = typer.Option(540, min=1, help="Lookback window if start_ms is omitted."),
    start_ms: int | None = typer.Option(None, help="Unix epoch start in milliseconds."),
    end_ms: int | None = typer.Option(None, help="Unix epoch end in milliseconds."),
    chunk_days: int = typer.Option(7, min=1, help="Days per resumable chunk."),
    raw_dir: Path = typer.Option(Path("data/raw/candles-long"), help="Raw JSONL chunk directory."),
    parts_dir: Path = typer.Option(Path("data/clean/candle-parts"), help="Clean parquet chunk directory."),
    out: Path = typer.Option(Path("data/clean/eth-perp-1m.parquet"), help="Combined clean parquet output path."),
    overwrite: bool = typer.Option(False, help="Refetch chunks that already exist."),
    min_coverage: float = typer.Option(0.95, min=0.0, max=1.0, help="Minimum observed/theoretical row ratio."),
    allow_partial: bool = typer.Option(False, help="Write partial output even if coverage is below min_coverage."),
) -> None:
    start, end = _window(days, start_ms, end_ms)
    step_ms = interval_to_ms(interval)
    chunk_ms = chunk_days * MS_PER_DAY
    raw_dir.mkdir(parents=True, exist_ok=True)
    parts_dir.mkdir(parents=True, exist_ok=True)
    part_paths: list[Path] = []

    with HyperliquidClient() as client:
        cursor = start
        chunk_index = 0
        while cursor <= end:
            chunk_end = min(cursor + chunk_ms - 1, end)
            stem = f"{coin.lower()}-{interval}-{cursor}-{chunk_end}"
            raw_path = raw_dir / f"{stem}.jsonl"
            part_path = parts_dir / f"{stem}.parquet"
            part_paths.append(part_path)

            if part_path.exists() and not overwrite:
                frame = pd.read_parquet(part_path)
                typer.echo(f"[{chunk_index:04d}] skipped existing chunk rows={len(frame)} {part_path}")
            else:
                rows = client.paginate_candles(coin, interval, cursor, chunk_end)
                frame = normalize_candle_rows(rows)
                write_jsonl(rows, raw_path)
                write_parquet(frame, part_path)
                typer.echo(f"[{chunk_index:04d}] fetched rows={len(frame)} window={cursor}-{chunk_end}")

            cursor = chunk_end + 1
            chunk_index += 1

    frames = [pd.read_parquet(path) for path in part_paths if path.exists()]
    if not frames:
        raise typer.BadParameter("No candle chunks were fetched or found")
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values("open_time").drop_duplicates(
        subset=["open_time", "coin", "interval"], keep="last"
    )
    expected = _expected_candle_count(start, end, interval)
    coverage = 1.0 if expected == 0 else len(combined) / expected
    if coverage < min_coverage and not allow_partial:
        partial = _partial_path(out)
        write_parquet(combined.reset_index(drop=True), ensure_parent(partial))
        raise typer.BadParameter(
            f"Only fetched {len(combined)}/{expected} candles ({coverage:.2%}). "
            f"Wrote partial output to {partial}. Re-run with --allow-partial to accept it."
        )
    write_parquet(combined.reset_index(drop=True), ensure_parent(out))
    typer.echo(f"Wrote {len(combined)} combined candle rows to {out}")


@app.command("binance-mark-candles")
def binance_mark_candles(
    symbol: str = typer.Option("ETHUSDT", help="Binance USD-M futures symbol."),
    interval: str = typer.Option("1m", help="Binance kline interval."),
    days: int = typer.Option(540, min=1, help="Lookback window if start_ms is omitted."),
    start_ms: int | None = typer.Option(None, help="Unix epoch start in milliseconds."),
    end_ms: int | None = typer.Option(None, help="Unix epoch end in milliseconds."),
    chunk_days: int = typer.Option(7, min=1, help="Days per resumable chunk."),
    raw_dir: Path = typer.Option(Path("data/raw/binance-mark-candles"), help="Raw JSONL chunk directory."),
    parts_dir: Path = typer.Option(Path("data/clean/binance-mark-candle-parts"), help="Clean parquet chunk directory."),
    out: Path = typer.Option(Path("data/clean/binance-ethusdt-mark-1m.parquet"), help="Combined clean parquet output path."),
    overwrite: bool = typer.Option(False, help="Refetch chunks that already exist."),
    min_coverage: float = typer.Option(0.95, min=0.0, max=1.0, help="Minimum observed/theoretical row ratio."),
    allow_partial: bool = typer.Option(False, help="Write partial output even if coverage is below min_coverage."),
) -> None:
    start, end = _window(days, start_ms, end_ms)
    step_ms = interval_to_ms(interval)
    chunk_ms = chunk_days * MS_PER_DAY
    raw_dir.mkdir(parents=True, exist_ok=True)
    parts_dir.mkdir(parents=True, exist_ok=True)
    part_paths: list[Path] = []

    with BinanceFuturesClient() as client:
        cursor = start
        chunk_index = 0
        while cursor <= end:
            chunk_end = min(cursor + chunk_ms - 1, end)
            stem = f"{symbol.lower()}-{interval}-{cursor}-{chunk_end}"
            raw_path = raw_dir / f"{stem}.jsonl"
            part_path = parts_dir / f"{stem}.parquet"
            part_paths.append(part_path)
            if part_path.exists() and not overwrite:
                frame = pd.read_parquet(part_path)
                typer.echo(f"[{chunk_index:04d}] skipped existing Binance chunk rows={len(frame)} {part_path}")
            else:
                rows = client.paginate_mark_price_klines(symbol, interval, cursor, chunk_end)
                frame = _normalize_binance_mark_rows(symbol, interval, rows)
                write_jsonl(({"row": row} for row in rows), raw_path)
                write_parquet(frame, part_path)
                typer.echo(f"[{chunk_index:04d}] fetched Binance rows={len(frame)} window={cursor}-{chunk_end}")
            cursor = chunk_end + 1
            chunk_index += 1

    frames = [pd.read_parquet(path) for path in part_paths if path.exists()]
    if not frames:
        raise typer.BadParameter("No Binance candle chunks were fetched or found")
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values("open_time").drop_duplicates(
        subset=["open_time", "coin", "interval"], keep="last"
    )
    expected = _expected_candle_count(start, end, interval)
    coverage = 1.0 if expected == 0 else len(combined) / expected
    if coverage < min_coverage and not allow_partial:
        partial = _partial_path(out)
        write_parquet(combined.reset_index(drop=True), ensure_parent(partial))
        raise typer.BadParameter(
            f"Only fetched {len(combined)}/{expected} candles ({coverage:.2%}). "
            f"Wrote partial output to {partial}. Re-run with --allow-partial to accept it."
        )
    write_parquet(combined.reset_index(drop=True), ensure_parent(out))
    typer.echo(f"Wrote {len(combined)} combined Binance mark-price candle rows to {out}")


@app.command("baselight-candles")
def baselight_candles(
    coin: str = typer.Option("ETH", help="Hyperliquid coin symbol."),
    days: int = typer.Option(150, min=1, help="Lookback window if start_ms is omitted."),
    start_ms: int | None = typer.Option(None, help="Unix epoch start in milliseconds."),
    end_ms: int | None = typer.Option(None, help="Unix epoch end in milliseconds."),
    parts_dir: Path = typer.Option(
        Path("data/clean/baselight-candle-parts"),
        help="Daily clean parquet candle parts.",
    ),
    out: Path = typer.Option(
        Path("data/clean/eth-hyperliquid-baselight-1m.parquet"),
        help="Combined clean parquet output path.",
    ),
    overwrite: bool = typer.Option(False, help="Recompute daily candle parts that already exist."),
    crossed_only: bool = typer.Option(True, help="Use taker fills only to avoid maker/taker double counting."),
    min_coverage: float = typer.Option(0.95, min=0.0, max=1.0, help="Minimum observed/theoretical row ratio."),
    allow_partial: bool = typer.Option(False, help="Write partial output even if coverage is below min_coverage."),
) -> None:
    objects = list_baselight_node_fill_objects()
    if not objects:
        raise typer.BadParameter("Baselight node_fills listing returned no parquet objects")

    first_available_ms = int(objects[0].date.timestamp() * 1000)
    last_available_ms = int((objects[-1].date.timestamp() + MS_PER_DAY / 1000) * 1000) - 1
    end = int(end_ms) if end_ms is not None else last_available_ms
    start = int(start_ms) if start_ms is not None else max(ms_days_before(end, days), first_available_ms)
    if start >= end:
        raise typer.BadParameter("start_ms must be before end_ms")

    selected = select_objects_for_window(objects, start, end)
    if not selected:
        raise typer.BadParameter(
            f"No Baselight parquet objects overlap requested window. "
            f"Available window is {pd.to_datetime(first_available_ms, unit='ms', utc=True)} to "
            f"{pd.to_datetime(last_available_ms, unit='ms', utc=True)}."
        )

    parts_dir.mkdir(parents=True, exist_ok=True)
    part_paths: list[Path] = []
    total_source_gb = sum(obj.size for obj in selected) / 1_000_000_000
    typer.echo(
        f"Baselight selected {len(selected)} daily files "
        f"({selected[0].date:%Y-%m-%d} to {selected[-1].date:%Y-%m-%d}, {total_source_gb:.2f} GB source)."
    )

    for index, obj in enumerate(selected):
        part_path = parts_dir / f"{coin.lower()}-baselight-{obj.date:%Y%m%d}.parquet"
        part_paths.append(part_path)
        if part_path.exists() and not overwrite:
            frame = pd.read_parquet(part_path)
            typer.echo(f"[{index:04d}] skipped existing Baselight part rows={len(frame)} {part_path}")
            continue
        frame = build_candles_from_baselight_parquet(
            obj.url,
            coin=coin,
            start_ms=start,
            end_ms=end,
            crossed_only=crossed_only,
        )
        write_parquet(frame, part_path)
        typer.echo(f"[{index:04d}] built Baselight rows={len(frame)} date={obj.date:%Y-%m-%d}")

    frames = [pd.read_parquet(path) for path in part_paths if path.exists()]
    if not frames:
        raise typer.BadParameter("No Baselight candle parts were written or found")
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values("open_time").drop_duplicates(
        subset=["open_time", "coin", "interval"], keep="last"
    )
    expected = _expected_candle_count(start, end, "1m")
    coverage = 1.0 if expected == 0 else len(combined) / expected
    if coverage < min_coverage and not allow_partial:
        partial = _partial_path(out)
        write_parquet(combined.reset_index(drop=True), ensure_parent(partial))
        raise typer.BadParameter(
            f"Only built {len(combined)}/{expected} candles ({coverage:.2%}). "
            f"Wrote partial output to {partial}. Re-run with --allow-partial to accept it."
        )
    write_parquet(combined.reset_index(drop=True), ensure_parent(out))
    typer.echo(f"Wrote {len(combined)} combined Baselight Hyperliquid 1m candles to {out}")


if __name__ == "__main__":
    app()
