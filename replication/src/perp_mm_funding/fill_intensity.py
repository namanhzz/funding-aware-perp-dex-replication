from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import typer
from scipy.optimize import minimize

from perp_mm_funding.io import ensure_parent
from perp_mm_funding.s3_fills import (
    HyperliquidS3Error,
    HyperliquidS3MissingObject,
    download_hourly_fill_file,
    iter_fill_trades,
    iter_lz4_json_records,
    local_hourly_path,
)


app = typer.Typer(help="Calibrate proxy fill-arrival intensity from official Hyperliquid S3 fills.")


@dataclass(slots=True)
class IntensityFit:
    lambda_base_per_hour: float
    intensity_k_bps: float
    intensity_k_price: float
    median_mid: float
    log_likelihood: float
    observations: int
    total_hits: int
    exposure_hours_per_side: float
    converged: bool

    def as_dict(self) -> dict[str, float | int | bool]:
        return {
            "lambda_base_per_hour": self.lambda_base_per_hour,
            "intensity_k_bps": self.intensity_k_bps,
            "intensity_k_price": self.intensity_k_price,
            "median_mid": self.median_mid,
            "log_likelihood": self.log_likelihood,
            "observations": self.observations,
            "total_hits": self.total_hits,
            "exposure_hours_per_side": self.exposure_hours_per_side,
            "converged": self.converged,
        }


def _normalize_date(value: str) -> datetime:
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise typer.BadParameter(f"Invalid date {value!r}; expected YYYYMMDD or YYYY-MM-DD")


def _iter_days(start: datetime, end: datetime):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _parse_float_list(value: str) -> list[float]:
    parsed = sorted({float(item.strip()) for item in value.split(",") if item.strip()})
    if not parsed or any(item < 0 for item in parsed):
        raise typer.BadParameter("distance grid must contain nonnegative values")
    return parsed


def _fit_exponential_intensity(counts: pd.DataFrame, median_mid: float) -> IntensityFit:
    valid = counts[(counts["hits"] > 0) & (counts["exposure_hours"] > 0)].copy()
    if len(valid) < 3:
        raise ValueError("Need at least three positive-hit distance observations")
    distance = valid["distance_bps"].to_numpy(dtype=float)
    hits = valid["hits"].to_numpy(dtype=float)
    exposure = valid["exposure_hours"].to_numpy(dtype=float)
    observed_rate = hits / exposure
    log_lambda0 = float(np.log(max(observed_rate[0], 1e-12)))
    slope = np.polyfit(distance, np.log(np.maximum(observed_rate, 1e-12)), deg=1)[0]
    log_k0 = float(np.log(max(-slope, 1e-6)))

    def objective(params: np.ndarray) -> float:
        log_lambda, log_k = params
        lam = np.exp(log_lambda)
        k_bps = np.exp(log_k)
        rate = exposure * lam * np.exp(-k_bps * distance)
        rate = np.maximum(rate, 1e-300)
        return -float(np.sum(hits * np.log(rate) - rate))

    result = minimize(
        objective,
        x0=np.array([log_lambda0, log_k0]),
        method="L-BFGS-B",
        bounds=[(np.log(1e-12), np.log(1e8)), (np.log(1e-8), np.log(10.0))],
    )
    log_lambda, log_k = result.x
    lam = float(np.exp(log_lambda))
    k_bps = float(np.exp(log_k))
    return IntensityFit(
        lambda_base_per_hour=lam,
        intensity_k_bps=k_bps,
        intensity_k_price=float(k_bps * 10_000.0 / median_mid),
        median_mid=float(median_mid),
        log_likelihood=float(-result.fun),
        observations=int(len(valid)),
        total_hits=int(hits.sum()),
        exposure_hours_per_side=float(exposure.max()),
        converged=bool(result.success),
    )


def _fit_exponential_bernoulli_intensity(counts: pd.DataFrame, median_mid: float) -> IntensityFit:
    valid = counts[(counts["hits"] >= 0) & (counts["exposure_minutes"] > 0)].copy()
    if len(valid) < 3 or valid["hits"].sum() <= 0:
        raise ValueError("Need at least three distance observations with positive successes")
    distance = valid["distance_bps"].to_numpy(dtype=float)
    successes = valid["hits"].to_numpy(dtype=float)
    trials = valid["exposure_minutes"].to_numpy(dtype=float)
    observed_prob = np.clip(successes / trials, 1e-9, 1.0 - 1e-9)
    observed_rate = -np.log1p(-observed_prob) * 60.0
    log_lambda0 = float(np.log(max(observed_rate[0], 1e-12)))
    slope = np.polyfit(distance, np.log(np.maximum(observed_rate, 1e-12)), deg=1)[0]
    log_k0 = float(np.log(max(-slope, 1e-6)))

    def objective(params: np.ndarray) -> float:
        log_lambda, log_k = params
        lam = np.exp(log_lambda)
        k_bps = np.exp(log_k)
        hourly_rate = lam * np.exp(-k_bps * distance)
        probability = 1.0 - np.exp(-hourly_rate / 60.0)
        probability = np.clip(probability, 1e-12, 1.0 - 1e-12)
        return -float(np.sum(successes * np.log(probability) + (trials - successes) * np.log1p(-probability)))

    result = minimize(
        objective,
        x0=np.array([log_lambda0, log_k0]),
        method="L-BFGS-B",
        bounds=[(np.log(1e-12), np.log(1e8)), (np.log(1e-8), np.log(10.0))],
    )
    log_lambda, log_k = result.x
    lam = float(np.exp(log_lambda))
    k_bps = float(np.exp(log_k))
    return IntensityFit(
        lambda_base_per_hour=lam,
        intensity_k_bps=k_bps,
        intensity_k_price=float(k_bps * 10_000.0 / median_mid),
        median_mid=float(median_mid),
        log_likelihood=float(-result.fun),
        observations=int(len(valid)),
        total_hits=int(successes.sum()),
        exposure_hours_per_side=float(valid["exposure_hours"].max()),
        converged=bool(result.success),
    )


def _load_l2_panel_hour(panel: pd.DataFrame, coin: str, day: datetime, hour: int) -> pd.DataFrame:
    start = pd.Timestamp(datetime.combine(day.date(), time(hour=hour), tzinfo=timezone.utc))
    end = start + pd.Timedelta(hours=1)
    subset = panel[(panel["coin"] == coin) & (panel["time"] >= start) & (panel["time"] < end)].copy()
    if subset.empty:
        return subset
    subset["minute"] = subset["time"].dt.floor("1min")
    return subset[["minute", "mid"]].drop_duplicates(subset=["minute"], keep="last")


def _hour_timestamp(day: datetime, hour: int) -> pd.Timestamp:
    return pd.Timestamp(datetime.combine(day.date(), time(hour=hour), tzinfo=timezone.utc))


def _build_panel_hour_lookup(panel: pd.DataFrame) -> dict[pd.Timestamp, pd.DataFrame]:
    panel = panel.copy()
    panel["hour"] = panel["time"].dt.floor("h")
    panel["minute"] = panel["time"].dt.floor("1min")
    lookup: dict[pd.Timestamp, pd.DataFrame] = {}
    for hour, hour_frame in panel.groupby("hour", sort=False):
        lookup[pd.Timestamp(hour)] = hour_frame[["minute", "mid"]].drop_duplicates(subset=["minute"], keep="last")
    return lookup


def _official_fills_for_hour(
    day: datetime,
    hour: int,
    coin: str,
    raw_dir: Path,
    overwrite_raw: bool,
    local_only: bool,
) -> pd.DataFrame:
    if local_only and not overwrite_raw:
        path = local_hourly_path(raw_dir, day.date(), hour)
        if not path.exists():
            raise HyperliquidS3MissingObject(f"Missing local cached fill file {path}")
    else:
        path = download_hourly_fill_file(
            day.date(),
            hour,
            raw_dir=raw_dir,
            requester_pays=True,
            overwrite=overwrite_raw,
        )
    trades = iter_fill_trades(iter_lz4_json_records(path), coin=coin, crossed_only=True)
    rows = [
        {
            "minute": pd.to_datetime(trade.time_ms, unit="ms", utc=True).floor("1min"),
            "price": trade.price,
            "size": trade.size,
            "side": trade.side,
        }
        for trade in trades
    ]
    return pd.DataFrame.from_records(rows)


def _process_hour_job(job: dict[str, Any]) -> dict[str, Any]:
    day = _normalize_date(str(job["date"]))
    hour = int(job["hour"])
    panel_hour = pd.DataFrame.from_records(job["panel_hour"])
    if panel_hour.empty:
        return {
            "status": "no_panel",
            "date": str(job["date"]),
            "hour": hour,
            "fills": 0,
            "exposure_minutes": 0,
            "counts": [],
        }
    try:
        fills = _official_fills_for_hour(
            day,
            hour,
            str(job["coin"]),
            Path(str(job["raw_dir"])),
            overwrite_raw=bool(job["overwrite_raw"]),
            local_only=bool(job["local_only"]),
        )
    except HyperliquidS3MissingObject:
        return {
            "status": "missing",
            "date": str(job["date"]),
            "hour": hour,
            "fills": 0,
            "exposure_minutes": 0,
            "counts": [],
        }
    hour_counts, hour_exposure = _hit_counts_for_hour(
        fills,
        panel_hour,
        list(job["distance_bps"]),
        fit_mode=str(job["fit_mode"]),
        quote_size=float(job["quote_size"]),
    )
    return {
        "status": "processed",
        "date": str(job["date"]),
        "hour": hour,
        "fills": int(len(fills)),
        "exposure_minutes": int(hour_exposure),
        "counts": hour_counts.to_dict(orient="records") if not hour_counts.empty else [],
    }


def _hit_counts_for_hour(
    fills: pd.DataFrame,
    panel_hour: pd.DataFrame,
    distance_bps: list[float],
    fit_mode: str = "count",
    quote_size: float = 1.0,
) -> tuple[pd.DataFrame, int]:
    if fills.empty or panel_hour.empty:
        return pd.DataFrame(), len(panel_hour)
    joined = fills.merge(panel_hour, on="minute", how="inner")
    if joined.empty:
        return pd.DataFrame(), len(panel_hour)

    rows: list[dict[str, object]] = []
    for distance in distance_bps:
        threshold = joined["mid"] * distance / 10_000.0
        bid = joined[joined["price"] <= joined["mid"] - threshold]
        ask = joined[joined["price"] >= joined["mid"] + threshold]
        if fit_mode == "count":
            bid_hits = int(len(bid))
            ask_hits = int(len(ask))
        elif fit_mode == "minute_hit":
            bid_hits = int(bid["minute"].nunique())
            ask_hits = int(ask["minute"].nunique())
        elif fit_mode == "volume_minute":
            bid_size = bid["size"] if "size" in bid.columns else pd.Series(1.0, index=bid.index)
            ask_size = ask["size"] if "size" in ask.columns else pd.Series(1.0, index=ask.index)
            bid_hits = int(bid.assign(_size=bid_size).groupby("minute")["_size"].sum().ge(quote_size).sum())
            ask_hits = int(ask.assign(_size=ask_size).groupby("minute")["_size"].sum().ge(quote_size).sum())
        else:
            raise ValueError(f"Unsupported fit_mode {fit_mode!r}")
        rows.append({"distance_bps": distance, "side": "bid", "hits": bid_hits})
        rows.append({"distance_bps": distance, "side": "ask", "hits": ask_hits})
    return pd.DataFrame.from_records(rows), len(panel_hour)


def _write_report(out: Path, summary: dict[str, object], counts: pd.DataFrame) -> None:
    fit_mode = str(summary.get("fit_mode", "count"))
    if fit_mode == "count":
        counting_method = (
            "For each minute and distance `d` in basis points from mid, it counts every crossed fill with "
            "`price <= mid - d` as a bid-side hit and every crossed fill with `price >= mid + d` as an ask-side hit."
        )
        likelihood = "It then fits `lambda(d) = Lambda exp(-k_bps d)` using a Poisson threshold-hit count likelihood."
    elif fit_mode == "minute_hit":
        counting_method = (
            "For each minute and distance `d` in basis points from mid, it records whether at least one crossed fill "
            "hit the bid-side or ask-side threshold."
        )
        likelihood = "It then fits `lambda(d) = Lambda exp(-k_bps d)` using a Bernoulli minute-hit likelihood."
    elif fit_mode == "volume_minute":
        counting_method = (
            "For each minute and distance `d` in basis points from mid, it records whether cumulative crossed volume "
            f"at the bid-side or ask-side threshold reached quote_size `{summary.get('quote_size')}`."
        )
        likelihood = "It then fits `lambda(d) = Lambda exp(-k_bps d)` using a Bernoulli minute-volume-hit likelihood."
    else:
        counting_method = "The hit-counting mode was not recognized by the report writer."
        likelihood = "The likelihood specification was not recognized by the report writer."
    lines = [
        "# Fill Intensity Calibration",
        "",
        "## Method",
        "",
        "This calibration uses official Hyperliquid requester-pays S3 `node_fills_by_block` crossed fills joined to the local Hyperliquid L2 1-minute panel.",
        counting_method,
        likelihood,
        "",
        "Limitations:",
        "",
        "- Distance buckets are nested rather than independent.",
        "- This does not model queue position, latency, or maker priority.",
        "- This is a source-pure official-S3 proxy calibration, not a full microstructure fill model.",
        "",
        "## Summary",
        "",
    ]
    for key, value in summary.items():
        if key != "distance_counts":
            lines.append(f"- {key}: {value}")
    lines.extend(["", "## Distance Counts", "", "| Distance bps | Side | Hits | Exposure hours | Intensity per hour |", "| ---: | --- | ---: | ---: | ---: |"])
    for row in counts.sort_values(["distance_bps", "side"]).itertuples(index=False):
        lines.append(
            f"| {row.distance_bps:g} | {row.side} | {int(row.hits)} | "
            f"{float(row.exposure_hours):.6f} | {float(row.intensity_per_hour):.6f} |"
        )
    ensure_parent(out).write_text("\n".join(lines) + "\n", encoding="utf-8")


@app.command()
def main(
    coin: str = typer.Option("ETH"),
    start_date: str = typer.Option("20251201"),
    end_date: str = typer.Option("20251207"),
    hours: str = typer.Option("0-23", help="Hour range like 0-23. Use a full day range for stable estimates."),
    distances_bps: str = typer.Option("0,0.5,1,2,5,10,20"),
    panel: Path = typer.Option(Path("data/clean/hyperliquid_l2_panel_1m.parquet")),
    raw_dir: Path = typer.Option(Path("data/raw/hyperliquid-s3-node-fills")),
    overwrite_raw: bool = typer.Option(False),
    local_only: bool = typer.Option(True, help="Use only locally cached official fill files; missing files are skipped."),
    fit_mode: str = typer.Option("count", help="count, minute_hit, or volume_minute."),
    quote_size: float = typer.Option(1.0, help="Quote size used by volume_minute fit mode."),
    progress_interval_hours: int = typer.Option(24, help="Print progress every N processed/missing hours."),
    workers: int = typer.Option(1, help="Parallel worker processes for hourly parsing."),
    out_json: Path = typer.Option(Path("results/fill-intensity-eth.json")),
    out_md: Path = typer.Option(Path("docs/fill-intensity.md")),
) -> None:
    target_coin = coin.upper()
    start = _normalize_date(start_date)
    end = _normalize_date(end_date)
    hour_start, hour_end = [int(part) for part in hours.split("-", 1)] if "-" in hours else (int(hours), int(hours))
    if hour_start < 0 or hour_end > 23 or hour_start > hour_end:
        raise typer.BadParameter("hours must be a single hour or range in 0-23")
    hour_values = list(range(hour_start, hour_end + 1))
    grid = _parse_float_list(distances_bps)

    panel_frame = pd.read_parquet(panel, columns=["time", "coin", "mid"])
    panel_frame["time"] = pd.to_datetime(panel_frame["time"], utc=True)
    panel_frame["coin"] = panel_frame["coin"].astype(str).str.upper()
    panel_frame = panel_frame[panel_frame["coin"] == target_coin].copy()
    window_start = pd.Timestamp(start)
    window_end = pd.Timestamp(end + timedelta(days=1))
    panel_frame = panel_frame[(panel_frame["time"] >= window_start) & (panel_frame["time"] < window_end)].copy()
    if panel_frame.empty:
        raise typer.BadParameter(f"No {target_coin} rows found in {panel} for requested calibration window")
    panel_by_hour = _build_panel_hour_lookup(panel_frame)
    if workers < 1:
        raise typer.BadParameter("workers must be >= 1")
    if fit_mode not in {"count", "minute_hit", "volume_minute"}:
        raise typer.BadParameter("fit_mode must be count, minute_hit, or volume_minute")
    if quote_size <= 0:
        raise typer.BadParameter("quote_size must be positive")

    typer.echo(f"[start] official fill intensity coin={target_coin} dates={start:%Y%m%d}..{end:%Y%m%d} hours={hours}")
    jobs: list[dict[str, Any]] = []
    for day in _iter_days(start, end):
        for hour in hour_values:
            panel_hour = panel_by_hour.get(_hour_timestamp(day, hour), pd.DataFrame(columns=["minute", "mid"]))
            jobs.append(
                {
                    "date": day.strftime("%Y%m%d"),
                    "hour": hour,
                    "coin": target_coin,
                    "raw_dir": str(raw_dir),
                    "overwrite_raw": overwrite_raw,
                    "local_only": local_only,
                    "fit_mode": fit_mode,
                    "quote_size": quote_size,
                    "distance_bps": grid,
                    "panel_hour": panel_hour.to_dict(orient="records"),
                }
            )

    all_counts: list[pd.DataFrame] = []
    exposure_minutes = 0
    missing_hours = 0
    no_panel_hours = 0
    processed_hours = 0
    attempted_hours = 0

    def consume(result: dict[str, Any]) -> None:
        nonlocal exposure_minutes, missing_hours, no_panel_hours, processed_hours, attempted_hours
        attempted_hours += 1
        status = str(result["status"])
        if status == "missing":
            missing_hours += 1
            if progress_interval_hours <= 1:
                typer.echo(f"[missing] {result['date']} hour={int(result['hour'])}")
        elif status == "no_panel":
            no_panel_hours += 1
        elif status == "processed":
            processed_hours += 1
            exposure_minutes += int(result["exposure_minutes"])
            if result["counts"]:
                all_counts.append(pd.DataFrame.from_records(result["counts"]))
            if progress_interval_hours <= 1:
                typer.echo(
                    f"[hour] {result['date']} {int(result['hour']):02d}: fills={int(result['fills'])} "
                    f"panel_minutes={int(result['exposure_minutes'])}"
                )
        else:
            raise RuntimeError(f"Unexpected worker status {status!r}")

        if progress_interval_hours > 1 and (
            attempted_hours % progress_interval_hours == 0 or attempted_hours == len(jobs)
        ):
            typer.echo(
                f"[progress] attempted={attempted_hours}/{len(jobs)} processed={processed_hours} "
                f"missing={missing_hours} no_panel={no_panel_hours} exposure_minutes={exposure_minutes}"
            )

    if workers == 1:
        for job in jobs:
            consume(_process_hour_job(job))
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_process_hour_job, job) for job in jobs]
            for future in as_completed(futures):
                try:
                    consume(future.result())
                except HyperliquidS3Error as exc:
                    raise typer.BadParameter(str(exc)) from exc

    if not all_counts or exposure_minutes == 0:
        raise typer.BadParameter("No joined official fills/panel exposure found")
    counts = pd.concat(all_counts, ignore_index=True).groupby(["distance_bps", "side"], as_index=False)["hits"].sum()
    exposure_hours = exposure_minutes / 60.0
    counts["exposure_hours"] = exposure_hours
    counts["exposure_minutes"] = int(exposure_minutes)
    counts["intensity_per_hour"] = counts["hits"] / counts["exposure_hours"]
    median_mid = float(panel_frame["mid"].median())
    if fit_mode == "count":
        fit = _fit_exponential_intensity(counts, median_mid=median_mid)
    else:
        fit = _fit_exponential_bernoulli_intensity(counts, median_mid=median_mid)

    summary = {
        "coin": target_coin,
        "start_date": start.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
        "hours": hours,
        "source": "official Hyperliquid S3 node_fills_by_block crossed fills",
        "panel": str(panel),
        "raw_dir": str(raw_dir),
        "local_only": local_only,
        "fit_mode": fit_mode,
        "quote_size": quote_size,
        "processed_hours": processed_hours,
        "missing_hours": missing_hours,
        "no_panel_hours": no_panel_hours,
        "exposure_minutes": int(exposure_minutes),
        "distance_grid_bps": grid,
        **fit.as_dict(),
    }
    ensure_parent(out_json).write_text(
        json.dumps({**summary, "distance_counts": counts.to_dict(orient="records")}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_report(out_md, summary, counts)
    typer.echo(f"[done] wrote official fill intensity calibration to {out_json} and {out_md}")


if __name__ == "__main__":
    app()
