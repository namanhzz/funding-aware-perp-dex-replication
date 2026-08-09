from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import typer
import yaml

from perp_mm_funding.io import ensure_parent
from perp_mm_funding.run_final_robustness import (
    _add_paired_vs_baseline,
    _asset_table,
    _resolve_jobs,
    _run_policy_for_seeds,
    _trial_from_config,
)
from perp_mm_funding.run_variant_sweep import _filter_inputs, _load_config

app = typer.Typer(help="Run selected policies on automatically chosen stress/calm windows.")


@dataclass(frozen=True, slots=True)
class StressWindow:
    name: str
    start_time: str
    end_time: str
    mean_funding: float
    price_return: float
    realized_vol: float
    days: int


def _load_asset_frames(cfg: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    coin = cfg.get("coin")
    start_time = cfg.get("start_time")
    end_time = cfg.get("end_time")
    price = pd.read_parquet(cfg["price_path"])
    funding = pd.read_parquet(cfg["funding_path"])
    return (
        _filter_inputs(price, coin=coin, start_time=start_time, end_time=end_time),
        _filter_inputs(funding, coin=coin, start_time=start_time, end_time=end_time),
    )


def _time_column(frame: pd.DataFrame) -> str:
    if "time" in frame.columns:
        return "time"
    if "open_time" in frame.columns:
        return "open_time"
    raise ValueError("frame must contain time or open_time")


def _price_column(frame: pd.DataFrame) -> str:
    if "mid" in frame.columns:
        return "mid"
    if "close" in frame.columns:
        return "close"
    raise ValueError("price frame must contain mid or close")


def _daily_panel(price: pd.DataFrame, funding: pd.DataFrame) -> pd.DataFrame:
    prices = price.copy()
    funding = funding.copy()
    prices["time"] = pd.to_datetime(prices[_time_column(prices)], utc=True)
    funding["time"] = pd.to_datetime(funding[_time_column(funding)], utc=True)
    prices["mid"] = prices[_price_column(prices)].astype(float)
    funding = funding[["time", "funding_rate"]].sort_values("time")
    prices = prices[["time", "mid"]].sort_values("time")
    market = pd.merge_asof(prices, funding, on="time", direction="backward")
    market["funding_rate"] = market["funding_rate"].fillna(0.0)
    market["day"] = market["time"].dt.floor("1D")
    market["log_return"] = np.log(market["mid"]).diff().fillna(0.0)

    rows = []
    for day, group in market.groupby("day", sort=True):
        if len(group) < 60:
            continue
        first_mid = float(group["mid"].iloc[0])
        last_mid = float(group["mid"].iloc[-1])
        rows.append(
            {
                "day": day,
                "rows": int(len(group)),
                "mean_funding": float(group["funding_rate"].mean()),
                "abs_mean_funding": float(group["funding_rate"].abs().mean()),
                "price_return": float(last_mid / first_mid - 1.0) if first_mid > 0.0 else float("nan"),
                "realized_vol": float(np.sqrt(np.sum(group["log_return"].to_numpy() ** 2))),
            }
        )
    return pd.DataFrame(rows)


def _rolling_windows(daily: pd.DataFrame, window_days: int) -> pd.DataFrame:
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    if len(daily) < window_days:
        raise ValueError("not enough daily rows for requested stress window")
    rows = []
    daily = daily.sort_values("day").reset_index(drop=True)
    for start_idx in range(0, len(daily) - window_days + 1):
        window = daily.iloc[start_idx : start_idx + window_days]
        start_day = pd.Timestamp(window["day"].iloc[0])
        end_day = pd.Timestamp(window["day"].iloc[-1])
        rows.append(
            {
                "start_time": start_day.isoformat().replace("+00:00", "Z"),
                "end_time": (end_day + pd.Timedelta(days=1) - pd.Timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                "days": int(window_days),
                "mean_funding": float(window["mean_funding"].mean()),
                "price_return": float(np.prod(1.0 + window["price_return"].to_numpy()) - 1.0),
                "realized_vol": float(np.sqrt(np.sum(window["realized_vol"].to_numpy() ** 2))),
                "abs_mean_funding": float(window["abs_mean_funding"].mean()),
            }
        )
    return pd.DataFrame(rows)


def select_stress_windows(price: pd.DataFrame, funding: pd.DataFrame, window_days: int = 3) -> list[StressWindow]:
    daily = _daily_panel(price, funding)
    windows = _rolling_windows(daily, window_days)
    vol = windows["realized_vol"].to_numpy(dtype=float)
    abs_funding = windows["abs_mean_funding"].to_numpy(dtype=float)
    vol_z = (vol - vol.mean()) / (vol.std(ddof=0) or 1.0)
    funding_z = (abs_funding - abs_funding.mean()) / (abs_funding.std(ddof=0) or 1.0)
    windows["calm_score"] = vol_z + funding_z

    chosen: set[int] = set()

    def pick_unique(name: str, ordered_indexes: list[int]) -> tuple[str, int]:
        for idx in ordered_indexes:
            if idx not in chosen:
                chosen.add(idx)
                return name, idx
        idx = ordered_indexes[0]
        return name, idx

    pick_items = [
        pick_unique("high_positive_funding", windows["mean_funding"].sort_values(ascending=False).index.tolist()),
        pick_unique("most_negative_funding", windows["mean_funding"].sort_values(ascending=True).index.tolist()),
        pick_unique("high_volatility", windows["realized_vol"].sort_values(ascending=False).index.tolist()),
        pick_unique("calm", windows["calm_score"].sort_values(ascending=True).index.tolist()),
    ]

    selected = []
    for name, idx in pick_items:
        row = windows.loc[idx]
        selected.append(
            StressWindow(
                name=name,
                start_time=str(row["start_time"]),
                end_time=str(row["end_time"]),
                mean_funding=float(row["mean_funding"]),
                price_return=float(row["price_return"]),
                realized_vol=float(row["realized_vol"]),
                days=int(row["days"]),
            )
        )
    return selected


def _json_clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_clean(item) for item in value]
    if isinstance(value, np.generic):
        return _json_clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _window_summary_table(windows: list[dict[str, Any]]) -> str:
    lines = [
        "| Asset | Window | Start | End | Mean funding | Price return | Realized vol |",
        "| --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for item in windows:
        window = item["window"]
        lines.append(
            "| {asset} | {name} | `{start}` | `{end}` | `{funding:.8f}` | `{ret:.2%}` | `{vol:.2%}` |".format(
                asset=item["asset"],
                name=window["name"],
                start=window["start_time"],
                end=window["end_time"],
                funding=float(window["mean_funding"]),
                ret=float(window["price_return"]),
                vol=float(window["realized_vol"]),
            )
        )
    return "\n".join(lines)


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Stress-Window Backtest",
        "",
        "Date: 2026-05-02",
        "",
        "This run evaluates the final selected policies on automatically chosen",
        "three-day holdout subwindows. Window selection uses only realized",
        "funding and mid-price behavior within each asset's holdout panel.",
        "",
        f"Seeds: `{payload['seeds']}`",
        f"Parallel seed workers per policy: `{payload['jobs']}`",
        "",
        "## Selected Windows",
        "",
        _window_summary_table(payload["windows"]),
        "",
        "## Results",
        "",
    ]
    for item in payload["windows"]:
        lines.extend(
            [
                f"### {item['asset']} - {item['window']['name']}",
                "",
                f"Window: `{item['window']['start_time']}` to `{item['window']['end_time']}`",
                "",
                _asset_table(item["asset"], item["results"]),
                "",
            ]
        )
    lines.extend(
        [
            "## Interpretation",
            "",
            "Use these windows as stress evidence, not as another selection step.",
            "The final paper claim should become stronger only if the selected HJB",
            "policy improves mean performance without simply increasing inventory",
            "risk in the stress windows.",
            "",
        ]
    )
    ensure_parent(path).write_text("\n".join(lines), encoding="utf-8")


@app.command()
def main(
    config: Path = typer.Option(Path("configs/final_hjb_robustness.yaml")),
    out_json: Path = typer.Option(Path("results/stress-window-backtest.json")),
    out_md: Path = typer.Option(Path("docs/stress-window-backtest.md")),
    window_days: int = typer.Option(3, help="Length of automatically selected stress windows."),
    jobs: int = typer.Option(0, help="Parallel seed workers per policy. Use 0 for config/auto."),
) -> None:
    cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
    seeds = [int(seed) for seed in cfg.get("seeds", list(range(1, 11)))]
    if not seeds:
        raise typer.BadParameter("seeds must not be empty")
    requested_jobs = int(cfg.get("jobs", jobs)) if jobs == 0 else jobs
    resolved_jobs = _resolve_jobs(requested_jobs, len(seeds))
    typer.echo(f"[jobs] using {resolved_jobs} seed workers per policy")

    windows_payload: list[dict[str, Any]] = []
    for asset_cfg in cfg["assets"]:
        asset = str(asset_cfg["asset"]).upper()
        base_cfg = _load_config(Path(asset_cfg["base_config"]))
        base_cfg["start_time"] = str(cfg["start_time"])
        base_cfg["end_time"] = str(cfg["end_time"])
        price, funding = _load_asset_frames(base_cfg)
        selected_windows = select_stress_windows(price, funding, window_days=window_days)

        for window in selected_windows:
            typer.echo(f"[window] {asset} {window.name} {window.start_time} -> {window.end_time}")
            window_cfg = dict(base_cfg)
            window_cfg["start_time"] = window.start_time
            window_cfg["end_time"] = window.end_time
            results = []
            for trial_cfg in asset_cfg["trials"]:
                trial = _trial_from_config(trial_cfg)
                typer.echo(f"[trial] {asset} {window.name} {trial.name}")
                results.append(_run_policy_for_seeds(window_cfg, trial, seeds, jobs=resolved_jobs))
            _add_paired_vs_baseline(results)
            windows_payload.append(
                {
                    "asset": asset,
                    "window": {
                        "name": window.name,
                        "start_time": window.start_time,
                        "end_time": window.end_time,
                        "mean_funding": window.mean_funding,
                        "price_return": window.price_return,
                        "realized_vol": window.realized_vol,
                        "days": window.days,
                    },
                    "results": results,
                }
            )

    payload = {
        "config": str(config),
        "seeds": seeds,
        "jobs": resolved_jobs,
        "window_days": int(window_days),
        "windows": windows_payload,
    }
    ensure_parent(out_json).write_text(json.dumps(_json_clean(payload), indent=2, sort_keys=True), encoding="utf-8")
    _write_markdown(out_md, payload)
    typer.echo(f"Wrote stress-window JSON to {out_json}")
    typer.echo(f"Wrote stress-window note to {out_md}")


if __name__ == "__main__":
    app()
