from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from itertools import product
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import typer
import yaml

from perp_mm_funding.backtest.benchmarks import BenchmarkDeltas, funding_aware, pure_as
from perp_mm_funding.backtest.metrics import summarize_backtest
from perp_mm_funding.backtest.simulator import BacktestConfig, run_event_backtest
from perp_mm_funding.io import ensure_parent
from perp_mm_funding.model.hjb_fd import HJBFDSolverParams, solve_hjb_fd
from perp_mm_funding.model.riccati import RiccatiParams, solve_lq_funding_coefficients
from perp_mm_funding.run_backtest import (
    _as_benchmark_deltas,
    _filter_inputs,
    _finite_delta,
    _funding_scale,
    _funding_signal,
    _funding_state_bounds,
    _funding_state_samples,
    _policy_time,
    _time_column,
)
from perp_mm_funding.strategy.carry_overlay import CarryOverlayParams, carry_overlay_deltas
from perp_mm_funding.strategy.quotes import risk_calibrated_deltas

app = typer.Typer(help="Run train-validation sweeps for model-side backtest variants.")


@dataclass(frozen=True, slots=True)
class VariantTrial:
    name: str
    variant: str
    params: dict[str, Any]


def _default_grids() -> dict[str, dict[str, list[float]]]:
    return {
        "risk_calibrated": {
            "risk_widening": [0.5, 1.0, 1.5],
            "risk_skew_cap": [0.25, 0.5],
        },
        "carry_overlay": {
            "carry_target_inventory_per_cash_funding": [10.0, 25.0, 50.0],
            "carry_max_skew": [0.25, 0.5],
        },
        "hjb_fd": {
            "terminal_penalty": [0.0005, 0.001, 0.002],
            "running_penalty": [0.00005, 0.0001],
        },
    }


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}".replace("-", "neg").replace(".", "p")
    return str(value).replace("-", "neg").replace(".", "p")


def _grid_trials(grids: dict[str, dict[str, list[Any]]]) -> list[VariantTrial]:
    trials: list[VariantTrial] = []
    for variant, grid in grids.items():
        keys = list(grid)
        if not keys:
            trials.append(VariantTrial(name=variant, variant=variant, params={}))
            continue
        for values in product(*(grid[key] for key in keys)):
            params = dict(zip(keys, values, strict=True))
            suffix = "__".join(f"{key}={_format_value(value)}" for key, value in params.items())
            trials.append(VariantTrial(name=f"{variant}__{suffix}", variant=variant, params=params))
    return trials


def _load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_json(path_value: str | None, key: str | None = None) -> dict[str, Any]:
    if not path_value:
        return {}
    path = Path(path_value)
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if key is None:
        return value
    return value.get(key, {})


def _load_frames(cfg: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    coin = cfg.get("coin")
    price = _read_price_frame(Path(cfg["price_path"]), coin=coin)
    funding = _read_funding_frame(Path(cfg["funding_path"]), coin=coin)
    start_time = cfg.get("start_time")
    end_time = cfg.get("end_time")
    return (
        _filter_inputs(price, coin=coin, start_time=start_time, end_time=end_time),
        _filter_inputs(funding, coin=coin, start_time=start_time, end_time=end_time),
    )


def _parquet_columns(path: Path) -> set[str]:
    return set(pq.ParquetFile(path).schema.names)


def _coin_filter(columns: set[str], coin: str | None) -> list[tuple[str, str, str]] | None:
    if coin is None or "coin" not in columns:
        return None
    return [("coin", "=", str(coin).upper())]


def _read_price_frame(path: Path, coin: str | None = None) -> pd.DataFrame:
    columns = _parquet_columns(path)
    time_col = "time" if "time" in columns else "open_time"
    price_col = "mid" if "mid" in columns else "close"
    selected = [time_col, price_col]
    if "close_time" in columns:
        selected.append("close_time")
    if "coin" in columns:
        selected.append("coin")
    return pd.read_parquet(path, columns=selected, filters=_coin_filter(columns, coin))


def _read_funding_frame(path: Path, coin: str | None = None) -> pd.DataFrame:
    columns = _parquet_columns(path)
    selected = ["time", "funding_rate"]
    if "coin" in columns:
        selected.append("coin")
    return pd.read_parquet(path, columns=selected, filters=_coin_filter(columns, coin))


def _backtest_config(cfg: dict[str, Any], fill_intensity: dict[str, Any]) -> BacktestConfig:
    return BacktestConfig(
        initial_cash=float(cfg.get("initial_cash", 0.0)),
        initial_inventory=float(cfg.get("initial_inventory", 0.0)),
        inventory_limit=float(cfg.get("inventory_limit", 10.0)),
        lambda_base=float(cfg.get("lambda_base", fill_intensity.get("lambda_base_per_hour", 6.0))),
        intensity_k=float(cfg.get("intensity_k", fill_intensity.get("intensity_k_price", 90.0))),
        quote_size=float(cfg.get("quote_size", 1.0)),
        tick_size=float(cfg.get("tick_size", 0.01)),
        seed=int(cfg.get("seed", 7)),
        hedge_spot=bool(cfg.get("hedge_spot", False)),
        maker_fee_rate=float(cfg.get("maker_fee_rate", 0.0)),
        adverse_selection_bps=float(cfg.get("adverse_selection_bps", 0.0)),
        fill_probability_scale=float(cfg.get("fill_probability_scale", 1.0)),
        simulation_frequency=cfg.get("simulation_frequency"),
        funding_accrual_mode=str(cfg.get("funding_accrual_mode", "hourly_boundary")),
    )


def _control_horizon(price: pd.DataFrame, cfg: dict[str, Any]) -> float:
    price_times = pd.to_datetime(price[_time_column(price)], utc=True)
    backtest_horizon = max((price_times.max() - price_times.min()).total_seconds() / 3600.0, 1.0)
    horizon = float(cfg.get("control_horizon_hours", backtest_horizon))
    if horizon <= 0.0:
        raise ValueError("control_horizon_hours must be positive")
    return horizon


def _state_parameters(
    price: pd.DataFrame,
    cfg: dict[str, Any],
    calibration: dict[str, Any],
) -> tuple[float, float, float, float, float, str]:
    funding_signal_mode = str(cfg.get("funding_signal_mode", "fractional")).lower()
    if funding_signal_mode not in {"fractional", "cash"}:
        raise ValueError("funding_signal_mode must be `fractional` or `cash`")
    cash_scale = _funding_scale(price, cfg)
    raw_theta = float(cfg.get("theta_bar", calibration.get("theta", 0.0)))
    raw_sigma = float(cfg.get("sigma_f", calibration.get("sigma", 0.0001)))
    state_scale = cash_scale if funding_signal_mode == "cash" else 1.0
    return (
        raw_theta,
        raw_sigma,
        raw_theta * state_scale,
        raw_sigma * state_scale,
        cash_scale,
        funding_signal_mode,
    )


def _solve_riccati(
    horizon: float,
    kappa: float,
    theta_bar: float,
    sigma_f: float,
    terminal_penalty: float,
    running_penalty: float,
):
    return solve_lq_funding_coefficients(
        RiccatiParams(
            horizon_hours=horizon,
            kappa=kappa,
            theta_bar=theta_bar,
            sigma_f=sigma_f,
            terminal_penalty=terminal_penalty,
            running_penalty=running_penalty,
        )
    )


def _build_policy(
    trial: VariantTrial,
    cfg: dict[str, Any],
    price: pd.DataFrame,
    funding: pd.DataFrame,
) -> tuple[Any, BacktestConfig]:
    calibration = _load_json(cfg.get("calibration_path"), key="ou")
    fill_intensity = _load_json(cfg.get("fill_intensity_path"))
    horizon = _control_horizon(price, cfg)
    policy_time_mode = str(cfg.get("policy_time_mode", "elapsed")).lower()
    if policy_time_mode not in {"elapsed", "rolling"}:
        raise ValueError("policy_time_mode must be `elapsed` or `rolling`")
    raw_theta, raw_sigma, theta_bar, sigma_f, cash_scale, funding_signal_mode = _state_parameters(
        price, cfg, calibration
    )
    kappa = float(cfg.get("kappa", calibration.get("kappa", 0.05)))
    terminal_penalty = float(cfg.get("terminal_penalty", 0.001))
    running_penalty = float(cfg.get("running_penalty", 0.0001))
    bt_config = _backtest_config(cfg, fill_intensity)
    intensity_k = bt_config.intensity_k
    tick = bt_config.tick_size
    pure_as_riccati = _solve_riccati(
        horizon=horizon,
        kappa=kappa,
        theta_bar=0.0,
        sigma_f=0.0,
        terminal_penalty=terminal_penalty,
        running_penalty=running_penalty,
    )

    if trial.variant in {"pure_as", "pure_as_scaled"}:
        return (
            lambda t, q, f, mid: pure_as(pure_as_riccati, _policy_time(t, policy_time_mode), q, intensity_k, tick),
            bt_config,
        )

    if trial.variant == "risk_calibrated":
        riccati = _solve_riccati(
            horizon=horizon,
            kappa=kappa,
            theta_bar=theta_bar,
            sigma_f=sigma_f,
            terminal_penalty=terminal_penalty,
            running_penalty=running_penalty,
        )
        soft_limit = float(cfg.get("risk_soft_limit_fraction", 0.5))
        risk_widening = float(cfg.get("risk_widening", 1.0))
        risk_skew_cap_cfg = cfg.get("risk_skew_cap", 0.5)
        risk_skew_cap = None if risk_skew_cap_cfg is None else float(risk_skew_cap_cfg)

        def policy(t: float, q: float, f: float, mid: float) -> BenchmarkDeltas:
            base = funding_aware(
                riccati,
                _policy_time(t, policy_time_mode),
                q,
                _funding_signal(f, mid, funding_signal_mode),
                intensity_k,
                tick,
            )
            return _as_benchmark_deltas(
                risk_calibrated_deltas(
                    base.bid_delta,
                    base.ask_delta,
                    inventory=q,
                    inventory_limit=bt_config.inventory_limit,
                    soft_limit_fraction=soft_limit,
                    risk_widening=risk_widening,
                    skew_cap=risk_skew_cap,
                )
            )

        return policy, bt_config

    if trial.variant == "carry_overlay":
        carry_params = CarryOverlayParams(
            target_inventory_per_cash_funding=float(cfg.get("carry_target_inventory_per_cash_funding", 25.0)),
            max_target_inventory=float(cfg.get("carry_max_target_inventory", bt_config.inventory_limit)),
            skew_per_inventory=float(cfg.get("carry_skew_per_inventory", 0.05)),
            max_skew=float(cfg.get("carry_max_skew", 0.5)),
        )

        def policy(t: float, q: float, f: float, mid: float):
            return carry_overlay_deltas(
                pure_as_riccati,
                _policy_time(t, policy_time_mode),
                q,
                _funding_signal(f, mid, "cash"),
                intensity_k,
                carry_params,
                min_delta=tick,
            )

        return policy, bt_config

    if trial.variant == "hjb_fd":
        hjb_mode = str(cfg.get("hjb_fd_funding_signal_mode", funding_signal_mode)).lower()
        if hjb_mode not in {"fractional", "cash"}:
            raise ValueError("hjb_fd_funding_signal_mode must be `fractional` or `cash`")
        hjb_state_scale = cash_scale if hjb_mode == "cash" else 1.0
        hjb_theta_bar = raw_theta * hjb_state_scale
        hjb_sigma_f = raw_sigma * hjb_state_scale
        hjb_samples = _funding_state_samples(funding, cash_scale, hjb_mode)
        default_f_min, default_f_max = _funding_state_bounds(hjb_samples, hjb_theta_bar, hjb_sigma_f)
        q_bound = float(bt_config.inventory_limit)
        solution = solve_hjb_fd(
            HJBFDSolverParams(
                horizon_hours=float(cfg.get("hjb_fd_horizon_hours", horizon)),
                q_min=float(cfg.get("hjb_fd_q_min", -q_bound)),
                q_max=float(cfg.get("hjb_fd_q_max", q_bound)),
                f_min=float(cfg.get("hjb_fd_f_min", default_f_min)),
                f_max=float(cfg.get("hjb_fd_f_max", default_f_max)),
                n_f=int(cfg.get("hjb_fd_n_f", 31)),
                n_t=int(cfg.get("hjb_fd_n_t", 1024)),
                kappa=kappa,
                theta_bar=hjb_theta_bar,
                sigma_f=hjb_sigma_f,
                fill_intensity=float(cfg.get("hjb_fd_fill_intensity", bt_config.lambda_base)),
                intensity_k=intensity_k,
                terminal_penalty=terminal_penalty,
                running_penalty=running_penalty,
                min_delta=tick,
                q_step=float(cfg.get("hjb_fd_q_step", bt_config.quote_size)),
            )
        )
        boundary_delta = float(cfg.get("hjb_fd_boundary_delta", 1_000_000.0))

        def policy(t: float, q: float, f: float, mid: float) -> BenchmarkDeltas:
            bid_delta, ask_delta = solution.optimal_deltas(
                _policy_time(t, policy_time_mode),
                q,
                _funding_signal(f, mid, hjb_mode),
            )
            return _as_benchmark_deltas(
                (_finite_delta(bid_delta, boundary_delta), _finite_delta(ask_delta, boundary_delta))
            )

        return policy, bt_config

    raise ValueError(f"unsupported variant: {trial.variant}")


def _run_trial(base_cfg: dict[str, Any], price: pd.DataFrame, funding: pd.DataFrame, trial: VariantTrial) -> dict[str, Any]:
    cfg = deepcopy(base_cfg)
    cfg.update(trial.params)
    policy, bt_config = _build_policy(trial, cfg, price, funding)
    events = run_event_backtest(price, funding, policy, bt_config)
    summary = summarize_backtest(events)
    summary.update({"trial": trial.name, "variant": trial.variant, "params": trial.params})
    return summary


def _mean_std(values: list[float]) -> tuple[float, float]:
    finite = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not finite:
        return float("nan"), float("nan")
    return float(np.mean(finite)), float(np.std(finite, ddof=1)) if len(finite) > 1 else 0.0


def _aggregate_seed_results(
    trial: VariantTrial,
    per_seed_results: list[dict[str, Any]],
    seed_column: str = "seed",
) -> dict[str, Any]:
    metric_keys = [
        "sharpe_hourly",
        "mean_pnl_per_day",
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
        "final_equity",
    ]
    aggregate: dict[str, Any] = {
        "trial": trial.name,
        "variant": trial.variant,
        "params": trial.params,
        "seeds": [int(result[seed_column]) for result in per_seed_results],
        "per_seed_results": per_seed_results,
    }
    for key in metric_keys:
        mean, std = _mean_std([result.get(key) for result in per_seed_results])
        aggregate[key] = mean
        aggregate[f"{key}_std"] = std
    return aggregate


def _run_trial_for_seeds(
    base_cfg: dict[str, Any],
    price: pd.DataFrame,
    funding: pd.DataFrame,
    trial: VariantTrial,
    seeds: list[int],
) -> dict[str, Any]:
    per_seed_results: list[dict[str, Any]] = []
    for seed in seeds:
        cfg = deepcopy(base_cfg)
        cfg["seed"] = int(seed)
        result = _run_trial(cfg, price, funding, trial)
        result["seed"] = int(seed)
        per_seed_results.append(result)
    return _aggregate_seed_results(trial, per_seed_results)


def _select_best_by_variant(
    results: list[dict[str, Any]],
    metric: str,
    top_n: int,
) -> list[dict[str, Any]]:
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    selected: list[dict[str, Any]] = []
    for variant in sorted({result["variant"] for result in results if result["variant"] != "pure_as"}):
        variant_results = [result for result in results if result["variant"] == variant]
        selected.extend(
            sorted(variant_results, key=lambda result: float(result.get(metric, float("-inf"))), reverse=True)[:top_n]
        )
    return selected


def _windowed_config(base_cfg: dict[str, Any], start_time: str, end_time: str) -> dict[str, Any]:
    cfg = deepcopy(base_cfg)
    cfg["start_time"] = start_time
    cfg["end_time"] = end_time
    return cfg


def _result_table(results: list[dict[str, Any]]) -> str:
    lines = [
        "| Trial | Variant | Final equity | Sharpe | MDD | Inv RMS | Funding | Fill rate | Seeds |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in results:
        seed_count = len(result.get("seeds", [])) if isinstance(result.get("seeds"), list) else 1
        lines.append(
            "| {trial} | {variant} | `{final_equity:.2f}` | `{sharpe_hourly:.2f}` | "
            "`{max_drawdown:.2f}` | `{inventory_rms:.2f}` | `{realized_funding_cost:.2f}` | "
            "`{fill_rate:.4f}` | `{seed_count}` |".format(seed_count=seed_count, **result)
        )
    return "\n".join(lines)


def _write_markdown(
    path: Path,
    config_path: Path,
    validation_results: list[dict[str, Any]],
    selected_results: list[dict[str, Any]],
    holdout_results: list[dict[str, Any]],
    metric: str,
) -> None:
    top_validation = sorted(validation_results, key=lambda result: float(result[metric]), reverse=True)[:15]
    text = f"""# ETH Model Variant Train-Validation Sweep

Date: 2026-05-02

Config: `{config_path}`

Selection metric: `{metric}`.

## Validation Top Results

{_result_table(top_validation)}

## Selected Per Variant

{_result_table(selected_results)}

## Holdout Re-Test

{_result_table(holdout_results)}

## Interpretation

This is a train-validation parameter sweep, not a paper-grade robustness claim.
The validation window is used for selection; the holdout window is used only for
the selected per-variant candidates plus `pure_as`.

The next step is to repeat this workflow after BTC/SOL funding files are
cleaned, then decide whether the paper core should use the finite-difference HJB
or a simpler risk-controlled quote rule.
"""
    ensure_parent(path).write_text(text, encoding="utf-8")


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
    config: Path = typer.Option(Path("configs/variant_sweep_eth.yaml"), help="YAML sweep config."),
    out_json: Path = typer.Option(Path("results/variant-sweep-eth.json")),
    out_md: Path = typer.Option(Path("docs/model-variant-sweep-eth.md")),
) -> None:
    sweep_cfg = _load_config(config)
    base_config_path = Path(sweep_cfg["base_config"])
    base_cfg = _load_config(base_config_path)
    grids = sweep_cfg.get("grids") or _default_grids()
    trials = _grid_trials(grids)
    metric = str(sweep_cfg.get("selection_metric", "final_equity"))
    top_n = int(sweep_cfg.get("top_n_per_variant", 1))
    seeds = [int(seed) for seed in sweep_cfg.get("seeds", [base_cfg.get("seed", 7)])]
    if not seeds:
        raise typer.BadParameter("seeds must not be empty")
    baseline_trial = VariantTrial(name="pure_as", variant="pure_as", params={})

    validation_cfg = _windowed_config(
        base_cfg,
        str(sweep_cfg["validation_start_time"]),
        str(sweep_cfg["validation_end_time"]),
    )
    validation_price, validation_funding = _load_frames(validation_cfg)
    if validation_price.empty or validation_funding.empty:
        raise typer.BadParameter("validation window has no price or funding rows")

    validation_results = [
        _run_trial_for_seeds(validation_cfg, validation_price, validation_funding, baseline_trial, seeds)
    ]
    for index, trial in enumerate(trials, start=1):
        typer.echo(f"[validation {index}/{len(trials)}] {trial.name}")
        validation_results.append(_run_trial_for_seeds(validation_cfg, validation_price, validation_funding, trial, seeds))

    selected = _select_best_by_variant(validation_results, metric=metric, top_n=top_n)
    selected_trials = [
        VariantTrial(name=result["trial"], variant=result["variant"], params=result["params"]) for result in selected
    ]

    holdout_results: list[dict[str, Any]] = []
    if "holdout_start_time" in sweep_cfg and "holdout_end_time" in sweep_cfg:
        holdout_cfg = _windowed_config(
            base_cfg,
            str(sweep_cfg["holdout_start_time"]),
            str(sweep_cfg["holdout_end_time"]),
        )
        holdout_price, holdout_funding = _load_frames(holdout_cfg)
        if holdout_price.empty or holdout_funding.empty:
            raise typer.BadParameter("holdout window has no price or funding rows")
        holdout_queue = [baseline_trial, *selected_trials]
        for index, trial in enumerate(holdout_queue, start=1):
            typer.echo(f"[holdout {index}/{len(holdout_queue)}] {trial.name}")
            holdout_results.append(_run_trial_for_seeds(holdout_cfg, holdout_price, holdout_funding, trial, seeds))

    payload = {
        "config": str(config),
        "base_config": str(base_config_path),
        "selection_metric": metric,
        "seeds": seeds,
        "validation_start_time": sweep_cfg["validation_start_time"],
        "validation_end_time": sweep_cfg["validation_end_time"],
        "holdout_start_time": sweep_cfg.get("holdout_start_time"),
        "holdout_end_time": sweep_cfg.get("holdout_end_time"),
        "trials": [asdict(trial) for trial in trials],
        "validation_results": validation_results,
        "selected_results": selected,
        "holdout_results": holdout_results,
    }
    ensure_parent(out_json).write_text(json.dumps(_json_clean(payload), indent=2, sort_keys=True), encoding="utf-8")
    _write_markdown(out_md, config, validation_results, selected, holdout_results, metric)
    typer.echo(f"Wrote sweep JSON to {out_json}")
    typer.echo(f"Wrote sweep note to {out_md}")


if __name__ == "__main__":
    app()
