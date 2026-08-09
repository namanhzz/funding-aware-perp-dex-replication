from __future__ import annotations

import csv
import gzip
import math
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd
import typer

from perp_mm_funding.io import ensure_parent, write_parquet


app = typer.Typer(help="Build Hyperliquid L2 manifests, quality reports, and clean panels.")


@dataclass(frozen=True, slots=True)
class Partition:
    coin: str
    date: str
    hour: int
    raw_base: Path
    feature_base: Path

    @property
    def raw_path(self) -> Path:
        return self.raw_base / self.coin / self.date / str(self.hour) / f"{self.coin}.lz4"

    @property
    def feature_path(self) -> Path:
        return self.feature_base / self.coin / self.date / f"{self.hour:02d}.csv.gz"


def _parse_coins(value: str) -> list[str]:
    return [coin.strip().upper() for coin in value.split(",") if coin.strip()]


def _normalize_date(value: str) -> str:
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    raise typer.BadParameter(f"Invalid date {value!r}; expected YYYYMMDD or YYYY-MM-DD")


def _iter_dates(start_date: str, end_date: str) -> Iterable[str]:
    start = datetime.strptime(_normalize_date(start_date), "%Y%m%d")
    end = datetime.strptime(_normalize_date(end_date), "%Y%m%d")
    if end < start:
        raise typer.BadParameter("end_date must be on or after start_date")
    current = start
    while current <= end:
        yield current.strftime("%Y%m%d")
        current += timedelta(days=1)


def _build_partitions(
    coins: list[str],
    start_date: str,
    end_date: str,
    raw_base: Path,
    feature_base: Path,
) -> list[Partition]:
    return [
        Partition(coin=coin, date=date, hour=hour, raw_base=raw_base, feature_base=feature_base)
        for coin in coins
        for date in _iter_dates(start_date, end_date)
        for hour in range(24)
    ]


def _as_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _as_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _scan_feature_file(path: Path) -> dict[str, object]:
    rows = 0
    first_time: int | None = None
    last_time: int | None = None
    previous_time: int | None = None
    seen_times: set[int] = set()
    duplicate_times = 0
    nonmonotone_times = 0
    invalid_timestamps = 0
    invalid_mid = 0
    nonpositive_bid = 0
    nonpositive_ask = 0
    negative_spread = 0
    min_mid: float | None = None
    max_mid: float | None = None
    min_spread: float | None = None
    max_spread: float | None = None
    spread_bps_sum = 0.0
    spread_bps_count = 0

    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows += 1
            timestamp = _as_int(row.get("exchange_time_ms"))
            if timestamp is None:
                invalid_timestamps += 1
            else:
                if first_time is None:
                    first_time = timestamp
                if previous_time is not None and timestamp < previous_time:
                    nonmonotone_times += 1
                if timestamp in seen_times:
                    duplicate_times += 1
                seen_times.add(timestamp)
                previous_time = timestamp
                last_time = timestamp

            best_bid = _as_float(row.get("best_bid_px"))
            best_ask = _as_float(row.get("best_ask_px"))
            mid = _as_float(row.get("mid"))
            spread = _as_float(row.get("spread"))
            spread_bps = _as_float(row.get("spread_bps"))

            if best_bid is None or best_bid <= 0:
                nonpositive_bid += 1
            if best_ask is None or best_ask <= 0:
                nonpositive_ask += 1
            if mid is None or mid <= 0:
                invalid_mid += 1
            else:
                min_mid = mid if min_mid is None else min(min_mid, mid)
                max_mid = mid if max_mid is None else max(max_mid, mid)
            if spread is None:
                negative_spread += 1
            else:
                if spread < 0:
                    negative_spread += 1
                min_spread = spread if min_spread is None else min(min_spread, spread)
                max_spread = spread if max_spread is None else max(max_spread, spread)
            if spread_bps is not None:
                spread_bps_sum += spread_bps
                spread_bps_count += 1

    return {
        "feature_rows": rows,
        "first_exchange_time_ms": first_time,
        "last_exchange_time_ms": last_time,
        "invalid_timestamp_count": invalid_timestamps,
        "nonmonotone_timestamp_count": nonmonotone_times,
        "duplicate_exchange_time_count": duplicate_times,
        "invalid_mid_count": invalid_mid,
        "nonpositive_best_bid_count": nonpositive_bid,
        "nonpositive_best_ask_count": nonpositive_ask,
        "negative_spread_count": negative_spread,
        "min_mid": min_mid,
        "max_mid": max_mid,
        "min_spread": min_spread,
        "max_spread": max_spread,
        "mean_spread_bps": spread_bps_sum / spread_bps_count if spread_bps_count else None,
        "scan_error": "",
    }


def _empty_scan(scan_error: str = "") -> dict[str, object]:
    return {
        "feature_rows": 0,
        "first_exchange_time_ms": None,
        "last_exchange_time_ms": None,
        "invalid_timestamp_count": 0,
        "nonmonotone_timestamp_count": 0,
        "duplicate_exchange_time_count": 0,
        "invalid_mid_count": 0,
        "nonpositive_best_bid_count": 0,
        "nonpositive_best_ask_count": 0,
        "negative_spread_count": 0,
        "min_mid": None,
        "max_mid": None,
        "min_spread": None,
        "max_spread": None,
        "mean_spread_bps": None,
        "scan_error": scan_error,
    }


def _partition_manifest_row(partition: Partition) -> dict[str, object]:
    raw_path = partition.raw_path
    feature_path = partition.feature_path
    raw_exists = raw_path.exists()
    feature_exists = feature_path.exists()
    scan = _empty_scan()

    if feature_exists:
        try:
            scan = _scan_feature_file(feature_path)
        except Exception as exc:
            scan = _empty_scan(type(exc).__name__)

    if raw_exists and feature_exists and scan["scan_error"] == "" and int(scan["feature_rows"]) > 0:
        missing_reason = ""
        usable = True
    elif not raw_exists and not feature_exists:
        missing_reason = "upstream_archive_missing_partition"
        usable = False
    elif raw_exists and not feature_exists:
        missing_reason = "feature_missing"
        usable = False
    elif not raw_exists and feature_exists:
        missing_reason = "raw_missing_feature_present"
        usable = False
    elif scan["scan_error"]:
        missing_reason = "feature_read_error"
        usable = False
    else:
        missing_reason = "feature_empty"
        usable = False

    return {
        "coin": partition.coin,
        "date": partition.date,
        "hour": partition.hour,
        "raw_path": str(raw_path),
        "feature_path": str(feature_path),
        "raw_exists": raw_exists,
        "feature_exists": feature_exists,
        "raw_size_bytes": raw_path.stat().st_size if raw_exists else 0,
        "feature_size_bytes": feature_path.stat().st_size if feature_exists else 0,
        "usable": usable,
        "missing_reason": missing_reason,
        **scan,
    }


def _compress_spans(values: list[int]) -> str:
    if not values:
        return ""
    spans: list[str] = []
    start = prev = values[0]
    for value in values[1:]:
        if value == prev + 1:
            prev = value
            continue
        spans.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = value
    spans.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(spans)


def _compress_full_day_runs(dates: list[str]) -> list[str]:
    if not dates:
        return []
    parsed = [datetime.strptime(date, "%Y%m%d") for date in sorted(dates)]
    runs: list[str] = []
    start = prev = parsed[0]
    for current in parsed[1:]:
        if current == prev + timedelta(days=1):
            prev = current
            continue
        runs.append(start.strftime("%Y%m%d") if start == prev else f"{start:%Y%m%d}..{prev:%Y%m%d}")
        start = prev = current
    runs.append(start.strftime("%Y%m%d") if start == prev else f"{start:%Y%m%d}..{prev:%Y%m%d}")
    return runs


def _append_missing_sections(lines: list[str], manifest: pd.DataFrame) -> None:
    missing = manifest[manifest["missing_reason"] == "upstream_archive_missing_partition"]
    lines.extend(["## Missing Partitions", ""])
    if missing.empty:
        lines.extend(["- No upstream archive missing partitions in the requested grid.", ""])
        return

    for coin, coin_frame in missing.groupby("coin", sort=True):
        lines.extend([f"### {coin}", ""])
        by_date = coin_frame.groupby("date")["hour"].apply(lambda s: sorted(int(x) for x in s)).to_dict()
        full_days = [date for date, hours in by_date.items() if hours == list(range(24))]
        partial_days = [(date, hours) for date, hours in sorted(by_date.items()) if hours != list(range(24))]
        lines.append(f"- missing_partitions: {len(coin_frame)}")
        if full_days:
            lines.append("- full_missing_days:")
            for run in _compress_full_day_runs(full_days):
                lines.append(f"  - {run}")
        if partial_days:
            lines.append("- partial_missing_days:")
            for date, hours in partial_days:
                lines.append(f"  - {date}: hours {_compress_spans(hours)}")
        lines.append("")


def _quality_counts(manifest: pd.DataFrame) -> dict[str, int]:
    feature = manifest[manifest["feature_exists"]]
    return {
        "feature_files": int(len(feature)),
        "feature_read_errors": int((feature["scan_error"].fillna("") != "").sum()),
        "empty_feature_files": int((feature["feature_rows"] <= 0).sum()),
        "files_with_invalid_timestamps": int((feature["invalid_timestamp_count"] > 0).sum()),
        "files_with_nonmonotone_timestamps": int((feature["nonmonotone_timestamp_count"] > 0).sum()),
        "files_with_duplicate_timestamps": int((feature["duplicate_exchange_time_count"] > 0).sum()),
        "files_with_invalid_mid": int((feature["invalid_mid_count"] > 0).sum()),
        "files_with_nonpositive_bid": int((feature["nonpositive_best_bid_count"] > 0).sum()),
        "files_with_nonpositive_ask": int((feature["nonpositive_best_ask_count"] > 0).sum()),
        "files_with_negative_spread": int((feature["negative_spread_count"] > 0).sum()),
    }


def write_l2_quality_report(
    manifest: pd.DataFrame,
    out: Path,
    panel_path: Path | None = None,
    panel_frequency: str | None = None,
) -> None:
    expected = len(manifest)
    raw_count = int(manifest["raw_exists"].sum())
    feature_count = int(manifest["feature_exists"].sum())
    usable_count = int(manifest["usable"].sum())
    missing_count = expected - usable_count
    lines = [
        "# Hyperliquid L2 Data Quality",
        "",
        "## Scope",
        "",
        f"- expected_partitions: {expected}",
        f"- raw_partitions: {raw_count}",
        f"- feature_partitions: {feature_count}",
        f"- usable_partitions: {usable_count}",
        f"- dropped_partitions: {missing_count}",
        f"- usable_ratio: {usable_count / expected:.6f}" if expected else "- usable_ratio: 0",
        "- drop_policy: exclude missing or unreadable partitions; no forward-fill and no interpolation",
        "",
        "## Coverage By Coin",
        "",
        "| Coin | Expected | Raw | Feature | Usable | Dropped |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for coin, frame in manifest.groupby("coin", sort=True):
        lines.append(
            f"| {coin} | {len(frame)} | {int(frame['raw_exists'].sum())} | "
            f"{int(frame['feature_exists'].sum())} | {int(frame['usable'].sum())} | "
            f"{len(frame) - int(frame['usable'].sum())} |"
        )
    lines.append("")

    lines.extend(["## Feature File Checks", ""])
    for key, value in _quality_counts(manifest).items():
        lines.append(f"- {key}: {value}")
    lines.append(f"- total_feature_rows: {int(manifest['feature_rows'].sum())}")
    feature_rows = manifest.loc[manifest["feature_exists"], "feature_rows"]
    if not feature_rows.empty:
        lines.extend(
            [
                f"- min_rows_per_file: {int(feature_rows.min())}",
                f"- median_rows_per_file: {float(feature_rows.median()):.1f}",
                f"- max_rows_per_file: {int(feature_rows.max())}",
            ]
        )
    lines.append("")

    _append_missing_sections(lines, manifest)

    if panel_path is not None and panel_path.exists():
        panel = pd.read_parquet(panel_path, columns=["time", "coin", "mid", "spread", "snapshots"])
        usable = manifest[manifest["usable"]][["coin", "date", "hour"]].copy()
        panel_hours = panel[["time", "coin"]].copy()
        panel_hours["date"] = panel_hours["time"].dt.strftime("%Y%m%d")
        panel_hours["hour"] = panel_hours["time"].dt.hour
        minute_counts = panel_hours.groupby(["coin", "date", "hour"]).size().rename("minutes").reset_index()
        merged_counts = usable.merge(minute_counts, on=["coin", "date", "hour"], how="left")
        merged_counts["minutes"] = merged_counts["minutes"].fillna(0).astype(int)
        expected_minutes = len(usable) * 60
        partial_hours = int((merged_counts["minutes"] < 60).sum())
        overfull_hours = int((merged_counts["minutes"] > 60).sum())
        net_missing_minutes = max(expected_minutes - len(panel), 0)
        within_hour_missing_minutes = int((60 - merged_counts["minutes"]).clip(lower=0).sum())
        lines.extend(
            [
                "## Clean Panel",
                "",
                f"- path: `{panel_path}`",
                f"- frequency: {panel_frequency}",
                f"- rows: {len(panel)}",
                f"- expected_minutes_from_usable_hours: {expected_minutes}",
                f"- net_missing_minutes_vs_usable_hour_grid: {net_missing_minutes}",
                f"- within_hour_missing_minutes: {within_hour_missing_minutes}",
                f"- partial_usable_hours: {partial_hours}",
                f"- overfull_usable_hours: {overfull_hours}",
                f"- min_minutes_per_usable_hour: {int(merged_counts['minutes'].min()) if len(merged_counts) else 0}",
                f"- median_minutes_per_usable_hour: {float(merged_counts['minutes'].median()):.1f}" if len(merged_counts) else "- median_minutes_per_usable_hour: 0",
                f"- max_minutes_per_usable_hour: {int(merged_counts['minutes'].max()) if len(merged_counts) else 0}",
                f"- nonpositive_mid_rows: {int((panel['mid'] <= 0).sum())}",
                f"- negative_spread_rows: {int((panel['spread'] < 0).sum())}",
                f"- min_snapshots_per_minute: {int(panel['snapshots'].min()) if len(panel) else 0}",
                f"- median_snapshots_per_minute: {float(panel['snapshots'].median()):.1f}" if len(panel) else "- median_snapshots_per_minute: 0",
                f"- max_snapshots_per_minute: {int(panel['snapshots'].max()) if len(panel) else 0}",
                f"- coins: {','.join(sorted(panel['coin'].dropna().unique()))}",
                f"- start: {panel['time'].min()}",
                f"- end: {panel['time'].max()}",
                "",
            ]
        )

    lines.extend(
        [
            "## Research Use",
            "",
            "- Use only `usable = true` partitions for calibration and backtesting.",
            "- Treat `upstream_archive_missing_partition` as unavailable source data, not a local pipeline failure.",
            "- Split continuous analyses at multi-hour or multi-day archive gaps.",
            "- For complete-day panels across BTC/ETH/SOL, drop any date with one or more missing hourly partitions.",
            "",
        ]
    )

    ensure_parent(out).write_text("\n".join(lines), encoding="utf-8")


@app.command("manifest")
def build_manifest(
    coins: str = typer.Option("BTC,ETH,SOL", help="Comma-separated coin symbols."),
    start_date: str = typer.Option("20240701"),
    end_date: str = typer.Option("20251231"),
    raw_base: Path = typer.Option(Path("data/raw/hyperliquid/l2Book")),
    feature_base: Path = typer.Option(Path("data/processed/hyperliquid/l2Book")),
    out: Path = typer.Option(Path("data/clean/hyperliquid_l2_manifest.parquet")),
    report: Path = typer.Option(Path("docs/l2-data-quality.md")),
    workers: int = typer.Option(32, min=1),
    progress_interval: int = typer.Option(1000, min=1),
) -> None:
    partitions = _build_partitions(_parse_coins(coins), start_date, end_date, raw_base, feature_base)
    rows: list[dict[str, object]] = []
    typer.echo(f"[start] manifest partitions={len(partitions)} workers={workers}")
    if workers == 1:
        for index, partition in enumerate(partitions, start=1):
            rows.append(_partition_manifest_row(partition))
            if index % progress_interval == 0 or index == len(partitions):
                typer.echo(f"[progress] scanned={index}/{len(partitions)}")
    else:
        completed = 0
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_partition_manifest_row, partition) for partition in partitions]
            for future in as_completed(futures):
                rows.append(future.result())
                completed += 1
                if completed % progress_interval == 0 or completed == len(partitions):
                    typer.echo(f"[progress] scanned={completed}/{len(partitions)}")

    frame = pd.DataFrame.from_records(rows).sort_values(["coin", "date", "hour"]).reset_index(drop=True)
    write_parquet(frame, out)
    write_l2_quality_report(frame, report)
    typer.echo(f"[done] wrote manifest rows={len(frame)} to {out}")
    typer.echo(f"[done] wrote L2 data quality report to {report}")


PANEL_COLUMNS = [
    "exchange_time_ms",
    "coin",
    "mid",
    "spread",
    "spread_bps",
    "bid_depth_1",
    "ask_depth_1",
    "imbalance_1",
    "bid_depth_5",
    "ask_depth_5",
    "imbalance_5",
    "bid_depth_10",
    "ask_depth_10",
    "imbalance_10",
]


def _daily_panel_task(args: tuple[str, str, Path, str]) -> pd.DataFrame:
    coin, date, feature_base, frequency = args
    frames: list[pd.DataFrame] = []
    for hour in range(24):
        path = feature_base / coin / date / f"{hour:02d}.csv.gz"
        if not path.exists():
            continue
        frame = pd.read_csv(path, usecols=PANEL_COLUMNS)
        if frame.empty:
            continue
        frames.append(frame)
    if not frames:
        return pd.DataFrame()

    frame = pd.concat(frames, ignore_index=True)
    frame["time"] = pd.to_datetime(frame["exchange_time_ms"], unit="ms", utc=True).dt.floor(frequency)
    frame = frame.sort_values(["time", "exchange_time_ms"])
    aggregations = {column: (column, "last") for column in PANEL_COLUMNS if column not in {"exchange_time_ms", "coin"}}
    panel = frame.groupby(["time", "coin"], sort=True).agg(
        **aggregations,
        snapshots=("exchange_time_ms", "size"),
        first_exchange_time_ms=("exchange_time_ms", "first"),
        last_exchange_time_ms=("exchange_time_ms", "last"),
    ).reset_index()
    panel["date"] = date
    return panel


@app.command("panel")
def build_panel(
    coins: str = typer.Option("BTC,ETH,SOL", help="Comma-separated coin symbols."),
    start_date: str = typer.Option("20240701"),
    end_date: str = typer.Option("20251231"),
    frequency: str = typer.Option("1min", help="Pandas frequency, e.g. 1s, 5s, 1min."),
    feature_base: Path = typer.Option(Path("data/processed/hyperliquid/l2Book")),
    out: Path = typer.Option(Path("data/clean/hyperliquid_l2_panel_1m.parquet")),
    manifest: Path = typer.Option(Path("data/clean/hyperliquid_l2_manifest.parquet")),
    report: Path = typer.Option(Path("docs/l2-data-quality.md")),
    workers: int = typer.Option(32, min=1),
    progress_interval: int = typer.Option(100, min=1),
) -> None:
    dates = list(_iter_dates(start_date, end_date))
    tasks = [(coin, date, feature_base, frequency) for coin in _parse_coins(coins) for date in dates]
    frames: list[pd.DataFrame] = []
    typer.echo(f"[start] panel tasks={len(tasks)} workers={workers} frequency={frequency}")
    if workers == 1:
        for index, task in enumerate(tasks, start=1):
            frame = _daily_panel_task(task)
            if not frame.empty:
                frames.append(frame)
            if index % progress_interval == 0 or index == len(tasks):
                typer.echo(f"[progress] panel_tasks={index}/{len(tasks)}")
    else:
        completed = 0
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_daily_panel_task, task) for task in tasks]
            for future in as_completed(futures):
                frame = future.result()
                if not frame.empty:
                    frames.append(frame)
                completed += 1
                if completed % progress_interval == 0 or completed == len(tasks):
                    typer.echo(f"[progress] panel_tasks={completed}/{len(tasks)}")

    if not frames:
        raise typer.BadParameter("No panel rows were produced")

    panel = pd.concat(frames, ignore_index=True).sort_values(["coin", "time"]).reset_index(drop=True)
    write_parquet(panel, out)
    typer.echo(f"[done] wrote panel rows={len(panel)} to {out}")

    if manifest.exists():
        manifest_frame = pd.read_parquet(manifest)
        write_l2_quality_report(manifest_frame, report, panel_path=out, panel_frequency=frequency)
        typer.echo(f"[done] updated L2 data quality report with panel summary at {report}")


if __name__ == "__main__":
    app()
