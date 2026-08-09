from __future__ import annotations

from dataclasses import replace
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import typer
import yaml

from perp_mm_funding.backtest.benchmarks import BenchmarkDeltas, funding_aware, pure_as, symmetric_constant
from perp_mm_funding.backtest.metrics import summarize_backtest
from perp_mm_funding.backtest.simulator import BacktestConfig, run_event_backtest
from perp_mm_funding.io import ensure_parent
from perp_mm_funding.model.hjb_fd import HJBFDSolverParams, solve_hjb_fd
from perp_mm_funding.model.riccati import RiccatiParams, solve_lq_funding_coefficients
from perp_mm_funding.strategy.carry_overlay import CarryOverlayParams, carry_overlay_deltas
from perp_mm_funding.strategy.model_variants import regime_gated_funding_aware_deltas
from perp_mm_funding.strategy.quotes import (
    FractionalFundingQuoteConfig,
    explicit_s_fractional_funding_deltas,
    risk_calibrated_deltas,
)

app = typer.Typer(help="Run funding-aware market-making backtests.")


def _time_column(frame: pd.DataFrame) -> str:
    if "open_time" in frame.columns:
        return "open_time"
    if "time" in frame.columns:
        return "time"
    raise ValueError("frame must contain `open_time` or `time`")


def _utc_timestamp(value: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _filter_inputs(frame: pd.DataFrame, coin: str | None, start_time: str | None, end_time: str | None) -> pd.DataFrame:
    filtered = frame.copy()
    if coin and "coin" in filtered.columns:
        filtered = filtered[filtered["coin"].astype(str).str.upper() == coin.upper()].copy()
    time_col = _time_column(filtered)
    filtered[time_col] = pd.to_datetime(filtered[time_col], utc=True)
    if start_time:
        filtered = filtered[filtered[time_col] >= _utc_timestamp(start_time)]
    if end_time:
        filtered = filtered[filtered[time_col] <= _utc_timestamp(end_time)]
    return filtered.sort_values(time_col).reset_index(drop=True)


def _price_column(frame: pd.DataFrame) -> str:
    if "close" in frame.columns:
        return "close"
    if "mid" in frame.columns:
        return "mid"
    raise ValueError("price frame must contain `close` or `mid`")


def _funding_scale(price: pd.DataFrame, cfg: dict) -> float:
    configured = cfg.get("funding_state_price_scale")
    if configured is None or str(configured).lower() in {"median", "median_price"}:
        return float(price[_price_column(price)].median())
    return float(configured)


def _funding_signal(raw_funding_rate: float, mid: float, mode: str) -> float:
    if mode == "fractional":
        return raw_funding_rate
    if mode == "cash":
        return mid * raw_funding_rate
    raise ValueError("funding_signal_mode must be `fractional` or `cash`")


def _policy_time(elapsed_hours: float, mode: str) -> float:
    if mode == "elapsed":
        return elapsed_hours
    if mode == "rolling":
        return 0.0
    raise ValueError("policy_time_mode must be `elapsed` or `rolling`")


def _json_clean(value):
    if isinstance(value, dict):
        return {key: _json_clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_clean(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _as_benchmark_deltas(deltas: tuple[float, float]) -> BenchmarkDeltas:
    bid_delta, ask_delta = deltas
    return BenchmarkDeltas(bid_delta=float(bid_delta), ask_delta=float(ask_delta))


def _benchmark_tuple(deltas: BenchmarkDeltas) -> tuple[float, float]:
    return float(deltas.bid_delta), float(deltas.ask_delta)


def _finite_delta(value: float, cap: float) -> float:
    if cap <= 0:
        raise ValueError("cap must be positive")
    if math.isfinite(value):
        return float(value)
    return float(cap)


def _funding_state_samples(funding: pd.DataFrame, price_scale: float, mode: str) -> np.ndarray:
    rates = pd.to_numeric(funding["funding_rate"], errors="coerce").dropna().to_numpy(dtype=float)
    scale = price_scale if mode == "cash" else 1.0
    return rates * scale


def _funding_state_bounds(samples: np.ndarray, theta_bar: float, sigma_f: float) -> tuple[float, float]:
    finite = samples[np.isfinite(samples)]
    if len(finite):
        lower = float(np.quantile(finite, 0.001))
        upper = float(np.quantile(finite, 0.999))
    else:
        lower = theta_bar - 4.0 * sigma_f
        upper = theta_bar + 4.0 * sigma_f

    lower = min(lower, theta_bar - 4.0 * sigma_f, 0.0)
    upper = max(upper, theta_bar + 4.0 * sigma_f, 0.0)
    min_span = max(abs(sigma_f) * 8.0, abs(theta_bar) * 0.5, 1e-6)
    if upper - lower < min_span:
        midpoint = 0.5 * (upper + lower)
        lower = midpoint - 0.5 * min_span
        upper = midpoint + 0.5 * min_span
    padding = max(0.1 * (upper - lower), abs(sigma_f) * 2.0, min_span * 0.1)
    return float(lower - padding), float(upper + padding)


@app.command()
def main(
    config: Path = typer.Option(Path("configs/backtest_eth.yaml"), help="YAML backtest config."),
    out_json: Path = typer.Option(Path("results/backtest-summary.json")),
) -> None:
    cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
    price = pd.read_parquet(cfg["price_path"])
    funding = pd.read_parquet(cfg["funding_path"])
    coin = cfg.get("coin")
    start_time = cfg.get("start_time")
    end_time = cfg.get("end_time")
    price = _filter_inputs(price, coin=coin, start_time=start_time, end_time=end_time)
    funding = _filter_inputs(funding, coin=coin, start_time=start_time, end_time=end_time)
    if price.empty:
        raise typer.BadParameter("No price rows remain after config filters")
    if funding.empty:
        raise typer.BadParameter("No funding rows remain after config filters")
    calibration = {}
    calibration_path = cfg.get("calibration_path")
    if calibration_path and Path(calibration_path).exists():
        calibration = json.loads(Path(calibration_path).read_text(encoding="utf-8")).get("ou", {})
    fill_intensity = {}
    fill_intensity_path = cfg.get("fill_intensity_path")
    if fill_intensity_path and Path(fill_intensity_path).exists():
        fill_intensity = json.loads(Path(fill_intensity_path).read_text(encoding="utf-8"))
    price_times = pd.to_datetime(price[_time_column(price)], utc=True)
    backtest_horizon = max((price_times.max() - price_times.min()).total_seconds() / 3600.0, 1.0)
    control_horizon = float(cfg.get("control_horizon_hours", backtest_horizon))
    if control_horizon <= 0:
        raise typer.BadParameter("control_horizon_hours must be positive")
    policy_time_mode = str(cfg.get("policy_time_mode", "elapsed")).lower()
    if policy_time_mode not in {"elapsed", "rolling"}:
        raise typer.BadParameter("policy_time_mode must be `elapsed` or `rolling`")
    funding_signal_mode = str(cfg.get("funding_signal_mode", "fractional")).lower()
    if funding_signal_mode not in {"fractional", "cash"}:
        raise typer.BadParameter("funding_signal_mode must be `fractional` or `cash`")
    cash_funding_state_price_scale = _funding_scale(price, cfg)
    funding_state_price_scale = cash_funding_state_price_scale if funding_signal_mode == "cash" else 1.0
    raw_theta_bar = float(cfg.get("theta_bar", calibration.get("theta", 0.0)))
    raw_sigma_f = float(cfg.get("sigma_f", calibration.get("sigma", 0.0001)))
    theta_bar = raw_theta_bar
    sigma_f = raw_sigma_f
    if funding_signal_mode == "cash":
        theta_bar *= funding_state_price_scale
        sigma_f *= funding_state_price_scale
    kappa = float(cfg.get("kappa", calibration.get("kappa", 0.05)))
    terminal_penalty = float(cfg.get("terminal_penalty", 0.001))
    running_penalty = float(cfg.get("running_penalty", 0.0001))
    riccati = solve_lq_funding_coefficients(
        RiccatiParams(
            horizon_hours=control_horizon,
            kappa=kappa,
            theta_bar=theta_bar,
            sigma_f=sigma_f,
            terminal_penalty=terminal_penalty,
            running_penalty=running_penalty,
        )
    )
    pure_as_riccati = solve_lq_funding_coefficients(
        RiccatiParams(
            horizon_hours=control_horizon,
            kappa=kappa,
            theta_bar=0.0,
            sigma_f=0.0,
            terminal_penalty=terminal_penalty,
            running_penalty=running_penalty,
        )
    )
    bt_config = BacktestConfig(
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
        funding_accrual_mode=str(cfg.get("funding_accrual_mode", "hourly_boundary")),
    )
    intensity_k = bt_config.intensity_k
    tick = bt_config.tick_size

    policies = {
        "funding_aware": (
            lambda t, q, f, mid: funding_aware(
                riccati,
                _policy_time(t, policy_time_mode),
                q,
                _funding_signal(f, mid, funding_signal_mode),
                intensity_k,
                tick,
            ),
            bt_config,
        ),
        "funding_aware_spot_hedged": (
            lambda t, q, f, mid: funding_aware(
                riccati,
                _policy_time(t, policy_time_mode),
                q,
                _funding_signal(f, mid, funding_signal_mode),
                intensity_k,
                tick,
            ),
            replace(bt_config, hedge_spot=True),
        ),
        "pure_as": (
            lambda t, q, f, mid: pure_as(pure_as_riccati, _policy_time(t, policy_time_mode), q, intensity_k, tick),
            bt_config,
        ),
        "pure_as_spot_hedged": (
            lambda t, q, f, mid: pure_as(pure_as_riccati, _policy_time(t, policy_time_mode), q, intensity_k, tick),
            replace(bt_config, hedge_spot=True),
        ),
        "symmetric_1bps": (
            lambda t, q, f, mid: symmetric_constant(t, q, f, 1.0, mid),
            bt_config,
        ),
    }
    summary = {}
    metadata = {
        "config": str(config),
        "coin": coin,
        "start_time": start_time,
        "end_time": end_time,
        "horizon_hours": control_horizon,
        "backtest_horizon_hours": backtest_horizon,
        "control_horizon_hours": control_horizon,
        "policy_time_mode": policy_time_mode,
        "funding_signal_mode": funding_signal_mode,
        "funding_state_price_scale": funding_state_price_scale,
        "cash_funding_state_price_scale": cash_funding_state_price_scale,
        "raw_riccati_theta_bar": raw_theta_bar,
        "raw_riccati_sigma_f": raw_sigma_f,
        "riccati_theta_bar": theta_bar,
        "riccati_sigma_f": sigma_f,
        "pure_as_theta_bar": 0.0,
        "pure_as_sigma_f": 0.0,
        "lambda_base": bt_config.lambda_base,
        "intensity_k": bt_config.intensity_k,
        "quote_size": bt_config.quote_size,
        "seed": bt_config.seed,
    }

    if bool(cfg.get("enable_model_variants", False)):
        fractional_riccati = solve_lq_funding_coefficients(
            RiccatiParams(
                horizon_hours=control_horizon,
                kappa=kappa,
                theta_bar=raw_theta_bar,
                sigma_f=raw_sigma_f,
                terminal_penalty=terminal_penalty,
                running_penalty=running_penalty,
            )
        )
        explicit_s_config = FractionalFundingQuoteConfig(
            control_horizon_hours=float(cfg.get("explicit_s_control_horizon_hours", control_horizon)),
            max_funding_skew=float(cfg.get("explicit_s_max_funding_skew", 0.5)),
            min_delta=tick,
        )
        carry_params = CarryOverlayParams(
            target_inventory_per_cash_funding=float(cfg.get("carry_target_inventory_per_cash_funding", 25.0)),
            max_target_inventory=float(cfg.get("carry_max_target_inventory", bt_config.inventory_limit)),
            skew_per_inventory=float(cfg.get("carry_skew_per_inventory", 0.05)),
            max_skew=float(cfg.get("carry_max_skew", 0.5)),
        )
        regime_gate_signal_mode = str(cfg.get("regime_gate_signal_mode", "fractional")).lower()
        if regime_gate_signal_mode not in {"fractional", "cash"}:
            raise typer.BadParameter("regime_gate_signal_mode must be `fractional` or `cash`")
        regime_gate_samples = _funding_state_samples(funding, cash_funding_state_price_scale, regime_gate_signal_mode)
        default_gate_threshold = float(np.quantile(np.abs(regime_gate_samples), 0.75)) if len(regime_gate_samples) else 0.0
        regime_gate_threshold = float(cfg.get("regime_gate_threshold", default_gate_threshold))
        regime_gate_mode = str(cfg.get("regime_gate_mode", "absolute")).lower()

        hjb_fd_mode = str(cfg.get("hjb_fd_funding_signal_mode", funding_signal_mode)).lower()
        if hjb_fd_mode not in {"fractional", "cash"}:
            raise typer.BadParameter("hjb_fd_funding_signal_mode must be `fractional` or `cash`")
        hjb_state_scale = cash_funding_state_price_scale if hjb_fd_mode == "cash" else 1.0
        hjb_theta_bar = raw_theta_bar * hjb_state_scale
        hjb_sigma_f = raw_sigma_f * hjb_state_scale
        hjb_price_scale = cash_funding_state_price_scale if hjb_fd_mode == "cash" else 1.0
        hjb_samples = _funding_state_samples(funding, hjb_price_scale, hjb_fd_mode)
        default_f_min, default_f_max = _funding_state_bounds(hjb_samples, hjb_theta_bar, hjb_sigma_f)
        q_bound = float(bt_config.inventory_limit)
        hjb_fd_solution = solve_hjb_fd(
            HJBFDSolverParams(
                horizon_hours=float(cfg.get("hjb_fd_horizon_hours", control_horizon)),
                q_min=float(cfg.get("hjb_fd_q_min", -q_bound)),
                q_max=float(cfg.get("hjb_fd_q_max", q_bound)),
                f_min=float(cfg.get("hjb_fd_f_min", default_f_min)),
                f_max=float(cfg.get("hjb_fd_f_max", default_f_max)),
                n_f=int(cfg.get("hjb_fd_n_f", 31)),
                n_t=int(cfg.get("hjb_fd_n_t", 64)),
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
        hjb_fd_boundary_delta = float(cfg.get("hjb_fd_boundary_delta", 1_000_000.0))
        risk_soft_limit_fraction = float(cfg.get("risk_soft_limit_fraction", 0.5))
        risk_widening = float(cfg.get("risk_widening", 1.0))
        risk_skew_cap_cfg = cfg.get("risk_skew_cap", 0.5)
        risk_skew_cap = None if risk_skew_cap_cfg is None else float(risk_skew_cap_cfg)

        def explicit_s_fractional_policy(t: float, q: float, f: float, mid: float) -> BenchmarkDeltas:
            return _as_benchmark_deltas(
                explicit_s_fractional_funding_deltas(
                    fractional_riccati,
                    _policy_time(t, policy_time_mode),
                    q,
                    f,
                    mid,
                    intensity_k,
                    explicit_s_config,
                )
            )

        def hjb_fd_policy(t: float, q: float, f: float, mid: float) -> BenchmarkDeltas:
            bid_delta, ask_delta = hjb_fd_solution.optimal_deltas(
                _policy_time(t, policy_time_mode),
                q,
                _funding_signal(f, mid, hjb_fd_mode),
            )
            return _as_benchmark_deltas(
                (
                    _finite_delta(bid_delta, hjb_fd_boundary_delta),
                    _finite_delta(ask_delta, hjb_fd_boundary_delta),
                )
            )

        def regime_gated_policy(t: float, q: float, f: float, mid: float) -> BenchmarkDeltas:
            t_policy = _policy_time(t, policy_time_mode)
            pure_deltas = pure_as(pure_as_riccati, t_policy, q, intensity_k, tick)
            aware_deltas = funding_aware(
                riccati,
                t_policy,
                q,
                _funding_signal(f, mid, funding_signal_mode),
                intensity_k,
                tick,
            )
            return _as_benchmark_deltas(
                regime_gated_funding_aware_deltas(
                    _benchmark_tuple(pure_deltas),
                    _benchmark_tuple(aware_deltas),
                    _funding_signal(f, mid, regime_gate_signal_mode),
                    regime_gate_threshold,
                    mode=regime_gate_mode,
                )
            )

        def carry_overlay_policy(t: float, q: float, f: float, mid: float):
            return carry_overlay_deltas(
                pure_as_riccati,
                _policy_time(t, policy_time_mode),
                q,
                _funding_signal(f, mid, "cash"),
                intensity_k,
                carry_params,
                min_delta=tick,
            )

        def risk_calibrated_policy(t: float, q: float, f: float, mid: float) -> BenchmarkDeltas:
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
                    soft_limit_fraction=risk_soft_limit_fraction,
                    risk_widening=risk_widening,
                    skew_cap=risk_skew_cap,
                )
            )

        policies.update(
            {
                "explicit_s_fractional": (explicit_s_fractional_policy, bt_config),
                "hjb_fd": (hjb_fd_policy, bt_config),
                "regime_gated": (regime_gated_policy, bt_config),
                "carry_overlay": (carry_overlay_policy, bt_config),
                "risk_calibrated": (risk_calibrated_policy, bt_config),
            }
        )
        metadata["model_variants"] = {
            "explicit_s_fractional": {
                "control_horizon_hours": explicit_s_config.control_horizon_hours,
                "max_funding_skew": explicit_s_config.max_funding_skew,
            },
            "hjb_fd": {
                "funding_signal_mode": hjb_fd_mode,
                "q_min": float(hjb_fd_solution.q_grid[0]),
                "q_max": float(hjb_fd_solution.q_grid[-1]),
                "q_step": float(hjb_fd_solution.q_grid[1] - hjb_fd_solution.q_grid[0]),
                "f_min": float(hjb_fd_solution.f_grid[0]),
                "f_max": float(hjb_fd_solution.f_grid[-1]),
                "n_f": int(len(hjb_fd_solution.f_grid)),
                "n_t": int(len(hjb_fd_solution.t_grid)),
                "boundary_delta": hjb_fd_boundary_delta,
            },
            "regime_gated": {
                "funding_signal_mode": regime_gate_signal_mode,
                "threshold": regime_gate_threshold,
                "mode": regime_gate_mode,
            },
            "carry_overlay": {
                "target_inventory_per_cash_funding": carry_params.target_inventory_per_cash_funding,
                "max_target_inventory": carry_params.max_target_inventory,
                "skew_per_inventory": carry_params.skew_per_inventory,
                "max_skew": carry_params.max_skew,
            },
            "risk_calibrated": {
                "soft_limit_fraction": risk_soft_limit_fraction,
                "risk_widening": risk_widening,
                "skew_cap": risk_skew_cap,
            },
        }

    events_dir = Path(cfg.get("events_dir", "results"))
    run_name = str(cfg.get("run_name", ""))
    for name, (policy, run_config) in policies.items():
        events = run_event_backtest(price, funding, policy, run_config)
        events_name = f"{run_name}-{name}-events.parquet" if run_name else f"{name}-events.parquet"
        events_path = events_dir / events_name
        ensure_parent(events_path)
        events.to_parquet(events_path, index=False)
        summary[name] = summarize_backtest(events)
        summary[name]["events_path"] = str(events_path)
    summary["_metadata"] = metadata

    ensure_parent(out_json).write_text(json.dumps(_json_clean(summary), indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    typer.echo(f"Wrote backtest summary to {out_json}")


if __name__ == "__main__":
    app()
