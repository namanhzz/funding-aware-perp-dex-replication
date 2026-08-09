from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import replace
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import t as student_t
import typer
import yaml

from perp_mm_funding.backtest.metrics import summarize_backtest
from perp_mm_funding.backtest.simulator import run_event_backtest
from perp_mm_funding.io import ensure_parent
from perp_mm_funding.run_variant_sweep import VariantTrial, _build_policy, _load_config, _load_frames

app = typer.Typer(help="Run final selected-parameter robustness backtests.")


METRIC_KEYS = [
    "final_equity",
    "sharpe_hourly",
    "max_drawdown",
    "inventory_rms",
    "realized_funding_cost",
    "realized_trading_fees",
    "realized_execution_cost",
    "turnover",
    "fill_count",
    "net_pnl_bps_turnover",
    "fill_rate",
    "worst_single_hour",
    "mean_pnl_per_day",
]


def _mean_std_ci(values: list[float]) -> tuple[float, float, float]:
    finite = np.array([float(value) for value in values if math.isfinite(float(value))], dtype=float)
    if len(finite) == 0:
        return float("nan"), float("nan"), float("nan")
    mean = float(np.mean(finite))
    std = float(np.std(finite, ddof=1)) if len(finite) > 1 else 0.0
    ci95 = float(1.96 * std / math.sqrt(len(finite))) if len(finite) > 1 else 0.0
    return mean, std, ci95


def _mean_std_t_ci(values: list[float]) -> tuple[float, float, float]:
    """Return a two-sided 95% Student-t interval for independent time blocks."""

    finite = np.array([float(value) for value in values if math.isfinite(float(value))], dtype=float)
    if len(finite) == 0:
        return float("nan"), float("nan"), float("nan")
    mean = float(np.mean(finite))
    std = float(np.std(finite, ddof=1)) if len(finite) > 1 else 0.0
    critical = float(student_t.ppf(0.975, df=len(finite) - 1)) if len(finite) > 1 else 0.0
    ci95 = float(critical * std / math.sqrt(len(finite))) if len(finite) > 1 else 0.0
    return mean, std, ci95


def _hac_mean_ci(values: list[float], max_lag: int = 7) -> tuple[float, float, float]:
    """Return a mean, HAC standard error, and normal 95% half-width."""

    finite = np.array([float(value) for value in values if math.isfinite(float(value))], dtype=float)
    if len(finite) == 0:
        return float("nan"), float("nan"), float("nan")
    mean = float(np.mean(finite))
    if len(finite) == 1:
        return mean, 0.0, 0.0
    centered = finite - mean
    lag_count = min(max(int(max_lag), 0), len(finite) - 1)
    long_run_variance = float(np.dot(centered, centered) / len(finite))
    for lag in range(1, lag_count + 1):
        covariance = float(np.dot(centered[lag:], centered[:-lag]) / len(finite))
        weight = 1.0 - lag / (lag_count + 1.0)
        long_run_variance += 2.0 * weight * covariance
    standard_error = float(math.sqrt(max(long_run_variance, 0.0) / len(finite)))
    return mean, standard_error, float(1.96 * standard_error)


def _moving_block_bootstrap_mean_interval(
    values: list[float],
    block_length: int = 7,
    replications: int = 2_000,
    seed: int = 20260809,
) -> tuple[float, float]:
    """Return a deterministic circular moving-block bootstrap interval."""

    finite = np.array([float(value) for value in values if math.isfinite(float(value))], dtype=float)
    if len(finite) == 0:
        return float("nan"), float("nan")
    if len(finite) == 1:
        return float(finite[0]), float(finite[0])
    resolved_length = min(max(int(block_length), 1), len(finite))
    rng = np.random.default_rng(seed)
    blocks_needed = int(math.ceil(len(finite) / resolved_length))
    bootstrap_means = np.empty(replications, dtype=float)
    offsets = np.arange(resolved_length)
    for replication in range(replications):
        starts = rng.integers(0, len(finite), size=blocks_needed)
        indices = (starts[:, None] + offsets[None, :]) % len(finite)
        sample = finite[indices.ravel()[: len(finite)]]
        bootstrap_means[replication] = float(np.mean(sample))
    lower, upper = np.quantile(bootstrap_means, [0.025, 0.975])
    return float(lower), float(upper)


def _trial_from_config(value: dict[str, Any]) -> VariantTrial:
    return VariantTrial(
        name=str(value["name"]),
        variant=str(value["variant"]),
        params=dict(value.get("params", {})),
    )


def _complete_week_pnl(events, initial_equity: float) -> dict[str, float]:
    """Return non-overlapping seven-day PnL blocks, excluding a short tail."""

    frame = events[["time", "equity"]].copy()
    start = frame["time"].iloc[0]
    frame["week"] = ((frame["time"] - start).dt.total_seconds() // (7 * 86_400)).astype(int)
    weekly: dict[str, float] = {}
    previous_equity = float(initial_equity)
    for week, group in frame.groupby("week", sort=True):
        if (group["time"].iloc[-1] - group["time"].iloc[0]).total_seconds() < 6 * 86_400:
            break
        ending_equity = float(group["equity"].iloc[-1])
        weekly[str(int(week))] = ending_equity - previous_equity
        previous_equity = ending_equity
    return weekly


def _complete_day_pnl(events, initial_equity: float) -> dict[str, float]:
    """Return non-overlapping 24-hour PnL blocks, excluding a short tail."""

    frame = events[["time", "equity"]].copy()
    start = frame["time"].iloc[0]
    frame["day"] = ((frame["time"] - start).dt.total_seconds() // 86_400).astype(int)
    daily: dict[str, float] = {}
    previous_equity = float(initial_equity)
    for day, group in frame.groupby("day", sort=True):
        if (group["time"].iloc[-1] - group["time"].iloc[0]).total_seconds() < 23 * 3_600:
            break
        ending_equity = float(group["equity"].iloc[-1])
        daily[str(int(day))] = ending_equity - previous_equity
        previous_equity = ending_equity
    return daily


def _asset_base_config(asset_cfg: dict[str, Any], global_cfg: dict[str, Any]) -> dict[str, Any]:
    base_cfg = _load_config(Path(asset_cfg["base_config"]))
    base_cfg.update(dict(asset_cfg.get("base_overrides", {})))
    base_cfg["start_time"] = str(global_cfg["start_time"])
    base_cfg["end_time"] = str(global_cfg["end_time"])
    return base_cfg


def _resolve_jobs(requested_jobs: int, seed_count: int) -> int:
    if requested_jobs < 0:
        raise ValueError("jobs must be non-negative")
    if seed_count <= 0:
        return 1
    if requested_jobs == 0:
        cpu_count = os.cpu_count() or 1
        requested_jobs = max(1, cpu_count - 2)
    return max(1, min(requested_jobs, seed_count))


def _seed_chunks(seeds: list[int], jobs: int) -> list[list[int]]:
    worker_count = _resolve_jobs(jobs, len(seeds))
    chunks = [[] for _ in range(worker_count)]
    for index, seed in enumerate(seeds):
        chunks[index % worker_count].append(seed)
    return [chunk for chunk in chunks if chunk]


def _run_seed_chunk(
    base_cfg: dict[str, Any],
    trial: VariantTrial,
    seeds: list[int],
) -> list[dict[str, Any]]:
    cfg = deepcopy(base_cfg)
    cfg.update(trial.params)
    price, funding = _load_frames(cfg)
    policy, bt_config = _build_policy(trial, cfg, price, funding)

    per_seed_results: list[dict[str, Any]] = []
    for seed in seeds:
        events = run_event_backtest(price, funding, policy, replace(bt_config, seed=int(seed)))
        summary = summarize_backtest(events)
        first_mid = float(events["mid"].iloc[0])
        initial_equity = float(bt_config.initial_cash + bt_config.initial_inventory * first_mid)
        summary["complete_week_pnl"] = _complete_week_pnl(events, initial_equity)
        summary["complete_day_pnl"] = _complete_day_pnl(events, initial_equity)
        summary.update({"seed": int(seed), "trial": trial.name, "variant": trial.variant})
        per_seed_results.append(summary)
    return per_seed_results


def _run_policy_for_seeds(
    base_cfg: dict[str, Any],
    trial: VariantTrial,
    seeds: list[int],
    jobs: int = 1,
) -> dict[str, Any]:
    resolved_jobs = _resolve_jobs(jobs, len(seeds))
    per_seed_results: list[dict[str, Any]] = []
    if resolved_jobs == 1:
        for seed in seeds:
            typer.echo(f"[seed] {trial.name} seed={seed}")
        per_seed_results = _run_seed_chunk(base_cfg, trial, seeds)
    else:
        chunks = _seed_chunks(seeds, resolved_jobs)
        typer.echo(f"[parallel] {trial.name}: {len(seeds)} seeds across {len(chunks)} workers")
        with ProcessPoolExecutor(max_workers=len(chunks)) as executor:
            futures = [executor.submit(_run_seed_chunk, base_cfg, trial, chunk) for chunk in chunks]
            for future in as_completed(futures):
                chunk_results = future.result()
                typer.echo(
                    "[done] {trial} seeds={seeds}".format(
                        trial=trial.name,
                        seeds=",".join(str(result["seed"]) for result in chunk_results),
                    )
                )
                per_seed_results.extend(chunk_results)
    per_seed_results = sorted(per_seed_results, key=lambda result: int(result["seed"]))

    aggregate: dict[str, Any] = {
        "trial": trial.name,
        "variant": trial.variant,
        "params": trial.params,
        "seeds": seeds,
        "per_seed_results": per_seed_results,
    }
    for key in METRIC_KEYS:
        mean, std, ci95 = _mean_std_ci([result[key] for result in per_seed_results])
        aggregate[key] = mean
        aggregate[f"{key}_std"] = std
        aggregate[f"{key}_ci95"] = ci95
    return aggregate


def _add_paired_vs_baseline(
    results: list[dict[str, Any]],
    baseline_variant: str = "pure_as",
    baseline_trial: str | None = None,
    field_suffix: str = "baseline",
) -> None:
    baseline = next(
        (
            result
            for result in results
            if (baseline_trial is not None and result["trial"] == baseline_trial)
            or (baseline_trial is None and result["variant"] == baseline_variant)
        ),
        None,
    )
    if baseline is None:
        return
    baseline_results_by_seed = {
        int(result["seed"]): result for result in baseline["per_seed_results"]
    }
    baseline_by_seed = {
        seed: float(result["final_equity"]) for seed, result in baseline_results_by_seed.items()
    }
    for result in results:
        deltas = []
        weekly_by_week: dict[str, list[float]] = {}
        daily_by_day: dict[str, list[float]] = {}
        wins = 0
        compared = 0
        for seed_result in result["per_seed_results"]:
            seed = int(seed_result["seed"])
            if seed not in baseline_by_seed:
                continue
            delta = float(seed_result["final_equity"]) - baseline_by_seed[seed]
            deltas.append(delta)
            baseline_seed_result = baseline_results_by_seed[seed]
            for week, pnl in seed_result.get("complete_week_pnl", {}).items():
                baseline_weekly = baseline_seed_result.get("complete_week_pnl", {})
                if week in baseline_weekly:
                    weekly_by_week.setdefault(week, []).append(float(pnl) - float(baseline_weekly[week]))
            for day, pnl in seed_result.get("complete_day_pnl", {}).items():
                baseline_daily = baseline_seed_result.get("complete_day_pnl", {})
                if day in baseline_daily:
                    daily_by_day.setdefault(day, []).append(float(pnl) - float(baseline_daily[day]))
            wins += int(delta > 0.0)
            compared += 1
        mean, std, ci95 = _mean_std_ci(deltas)
        result[f"delta_final_equity_vs_{field_suffix}"] = mean
        result[f"delta_final_equity_vs_{field_suffix}_std"] = std
        result[f"delta_final_equity_vs_{field_suffix}_ci95"] = ci95
        result[f"win_rate_vs_{field_suffix}"] = float(wins / compared) if compared else float("nan")
        weekly_means = [float(np.mean(weekly_by_week[key])) for key in sorted(weekly_by_week, key=int)]
        block_mean, block_std, block_ci95 = _mean_std_t_ci(weekly_means)
        result[f"weekly_delta_means_vs_{field_suffix}"] = weekly_means
        result[f"weekly_delta_mean_vs_{field_suffix}"] = block_mean
        result[f"weekly_delta_mean_vs_{field_suffix}_std"] = block_std
        result[f"weekly_delta_mean_vs_{field_suffix}_ci95"] = block_ci95
        result[f"weekly_win_rate_vs_{field_suffix}"] = (
            float(np.mean(np.asarray(weekly_means) > 0.0)) if weekly_means else float("nan")
        )
        daily_means = [float(np.mean(daily_by_day[key])) for key in sorted(daily_by_day, key=int)]
        daily_mean, daily_hac_se, daily_hac_ci95 = _hac_mean_ci(daily_means, max_lag=7)
        bootstrap_lower, bootstrap_upper = _moving_block_bootstrap_mean_interval(
            daily_means,
            block_length=7,
        )
        result[f"daily_delta_means_vs_{field_suffix}"] = daily_means
        result[f"daily_delta_mean_vs_{field_suffix}"] = daily_mean
        result[f"daily_delta_mean_vs_{field_suffix}_hac_se"] = daily_hac_se
        result[f"daily_delta_mean_vs_{field_suffix}_hac_ci95"] = daily_hac_ci95
        result[f"daily_delta_mean_vs_{field_suffix}_block_bootstrap_lower"] = bootstrap_lower
        result[f"daily_delta_mean_vs_{field_suffix}_block_bootstrap_upper"] = bootstrap_upper


def _asset_table(asset: str, results: list[dict[str, Any]]) -> str:
    named_suffix = "risk_matched_as"
    named_label = "nearest-risk AS"
    if results and f"delta_final_equity_vs_{named_suffix}" not in results[0]:
        named_suffix = "frontier_matched_as"
        named_label = "frontier-matched AS"
    lines = [
        f"### {asset}",
        "",
        f"| Policy | Net PnL | Delta vs default AS | 95% paired CI | Delta vs {named_label} | 95% paired CI | Win vs named baseline | Inv. RMS | Turnover | Fees | Net bps/turnover |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in results:
        named_delta = float(result.get(f"delta_final_equity_vs_{named_suffix}", float("nan")))
        named_ci = float(result.get(f"delta_final_equity_vs_{named_suffix}_ci95", float("nan")))
        named_win = float(result.get(f"win_rate_vs_{named_suffix}", float("nan")))
        lines.append(
            "| {trial} | {final_equity:.2f} | {delta_final_equity_vs_baseline:.2f} | "
            "+/-{delta_final_equity_vs_baseline_ci95:.2f} | "
            f"{named_delta:.2f} | +/-{named_ci:.2f} | {named_win:.2f} | "
            "{inventory_rms:.4f} | {turnover:.2f} | {realized_trading_fees:.2f} | "
            "{net_pnl_bps_turnover:.3f} |".format(**result)
        )
    return "\n".join(lines)


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    variants = []
    if payload["assets"]:
        variants = [result["variant"] for result in payload["assets"][0]["results"]]
    analysis_label = str(payload.get("analysis_label") or "Final 2026 evaluation")
    lines = [
        f"# {analysis_label}",
        "",
        "Date: 2026-08-09",
        "",
        f"Seeds: `{payload['seeds']}`",
        "",
        "This run freezes the development-selected parameters and evaluates:",
        f"`{variants}`.",
        "",
        "No parameter search is performed in this evaluation.",
        "",
        "## Results",
        "",
    ]
    for asset in payload["assets"]:
        lines.append(_asset_table(asset["asset"], asset["results"]))
        lines.append("")
    lines.extend(
        [
            "## Interpretation",
            "",
            "Use the paired deltas and inventory RMS jointly. The nearest-risk",
            "AS comparison is the primary economic contrast; default AS remains",
            "a transparent reference. Weekly non-overlapping block statistics",
            "are stored in the JSON for time-clustered inference.",
            "",
        ]
    )
    ensure_parent(path).write_text("\n".join(lines), encoding="utf-8")


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


@app.command()
def main(
    config: Path = typer.Option(Path("configs/final_hjb_robustness.yaml")),
    out_json: Path = typer.Option(Path("results/final-hjb-robustness.json")),
    out_md: Path = typer.Option(Path("docs/final-hjb-robustness.md")),
    jobs: int = typer.Option(0, help="Parallel seed workers per policy. Use 0 for auto."),
) -> None:
    cfg = _load_config(config)
    seeds = [int(seed) for seed in cfg.get("seeds", list(range(1, 11)))]
    if not seeds:
        raise typer.BadParameter("seeds must not be empty")
    requested_jobs = int(cfg.get("jobs", jobs)) if jobs == 0 else jobs
    resolved_jobs = _resolve_jobs(requested_jobs, len(seeds))
    typer.echo(f"[jobs] using {resolved_jobs} seed workers per policy")

    assets_payload = []
    for asset_cfg in cfg["assets"]:
        asset = str(asset_cfg["asset"]).upper()
        typer.echo(f"[asset] {asset}")
        base_cfg = _asset_base_config(asset_cfg, cfg)

        results = []
        for trial_cfg in asset_cfg["trials"]:
            trial = _trial_from_config(trial_cfg)
            typer.echo(f"[trial] {asset} {trial.name}")
            results.append(_run_policy_for_seeds(base_cfg, trial, seeds, jobs=resolved_jobs))
        _add_paired_vs_baseline(results)
        for comparison in cfg.get("paired_baselines", []):
            _add_paired_vs_baseline(
                results,
                baseline_trial=str(comparison["trial"]),
                field_suffix=str(comparison["field_suffix"]),
            )
        assets_payload.append({"asset": asset, "base_config": asset_cfg["base_config"], "results": results})

    payload = {
        "config": str(config),
        "analysis_label": cfg.get("analysis_label"),
        "selection_basis": cfg.get("selection_basis"),
        "frontier_selected_hjb_trial": cfg.get("frontier_selected_hjb_trial"),
        "frontier_selected_as_trial": cfg.get("frontier_selected_as_trial"),
        "frontier_pairs": cfg.get("frontier_pairs", []),
        "start_time": cfg["start_time"],
        "end_time": cfg["end_time"],
        "seeds": seeds,
        "assets": assets_payload,
    }
    ensure_parent(out_json).write_text(json.dumps(_json_clean(payload), indent=2, sort_keys=True), encoding="utf-8")
    _write_markdown(out_md, payload)
    typer.echo(f"Wrote final robustness JSON to {out_json}")
    typer.echo(f"Wrote final robustness note to {out_md}")


if __name__ == "__main__":
    app()
