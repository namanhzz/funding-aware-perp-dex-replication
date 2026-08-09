from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import typer

from perp_mm_funding.calibration.cir import fit_shifted_cir_moments
from perp_mm_funding.calibration.diagnostics import residual_summary
from perp_mm_funding.calibration.jump_ou import fit_ou_jump_mle, threshold_ou_jump_diagnostic
from perp_mm_funding.calibration.ou import fit_ou_mle, ou_log_likelihood
from perp_mm_funding.io import ensure_parent

app = typer.Typer(help="Run funding-rate calibration diagnostics.")


def _split_train_test(frame: pd.DataFrame, train_fraction: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    split = int(len(frame) * train_fraction)
    split = min(max(split, 10), len(frame) - 3)
    return frame.iloc[:split].copy(), frame.iloc[split:].copy()


def _price_series(frame: pd.DataFrame, coin: str) -> pd.DataFrame:
    price_frame = frame.copy()
    if "coin" in price_frame.columns:
        price_frame = price_frame[price_frame["coin"].astype(str).str.upper() == coin.upper()].copy()
    if {"open_time", "close"}.issubset(price_frame.columns):
        return price_frame[["open_time", "close"]].rename(columns={"open_time": "time", "close": "price"})
    if {"time", "mid"}.issubset(price_frame.columns):
        return price_frame[["time", "mid"]].rename(columns={"mid": "price"})
    raise ValueError("Price frame must contain open_time/close or time/mid columns")


def _mark_return_funding_corr(funding: pd.DataFrame, prices: pd.DataFrame | None, fit: object, price_coin: str) -> tuple[float | None, int]:
    if prices is None or prices.empty:
        return None, 0
    price = _price_series(prices, price_coin)
    if price.empty:
        return None, 0
    price["time"] = pd.to_datetime(price["time"], utc=True)
    hourly_price = price.set_index("time")["price"].sort_index().resample("1h").last()
    hourly_return = np.log(hourly_price).diff().rename("log_return")

    funding_frame = funding.sort_values("time").copy()
    funding_frame["time"] = pd.to_datetime(funding_frame["time"], utc=True)
    values = funding_frame["funding_rate"].to_numpy(dtype=float)
    times = funding_frame["time"]
    if len(values) < 3:
        return None, 0
    dt = times.diff().dt.total_seconds().to_numpy()[1:] / 3600.0
    previous = values[:-1]
    current = values[1:]
    phi = np.exp(-fit.kappa * dt)
    expected = fit.theta + phi * (previous - fit.theta)
    innovations = pd.Series(current - expected, index=times.iloc[1:].dt.floor("1h"), name="funding_innovation")
    merged = pd.concat([innovations, hourly_return], axis=1, join="inner").dropna()
    if len(merged) < 20:
        return None, int(len(merged))
    return float(np.corrcoef(merged["funding_innovation"], merged["log_return"])[0, 1]), int(len(merged))


@app.command()
def main(
    funding: Path = typer.Option(Path("data/clean/eth-funding-1h.parquet"), help="Clean funding parquet."),
    candles: Path | None = typer.Option(None, help="Optional clean candle parquet."),
    price_coin: str = typer.Option("ETH", help="Coin to use when the price/L2 file contains multiple assets."),
    train_fraction: float = typer.Option(0.7, min=0.1, max=0.95),
    out_json: Path = typer.Option(Path("results/calibration-eth.json")),
    out_md: Path = typer.Option(Path("docs/calibration-results.md")),
) -> None:
    frame = pd.read_parquet(funding).sort_values("time")
    if "funding_rate" not in frame.columns:
        raise typer.BadParameter("Funding parquet must contain funding_rate")
    train, test = _split_train_test(frame, train_fraction)
    fit = fit_ou_mle(train["funding_rate"], train["time"])
    test_ll = ou_log_likelihood(test["funding_rate"], fit.kappa, fit.theta, fit.sigma, test["time"])
    cir = fit_shifted_cir_moments(train["funding_rate"])
    resid = residual_summary(fit.standardized_residuals)
    jump_diag = threshold_ou_jump_diagnostic(fit)
    jump_fit = fit_ou_jump_mle(train["funding_rate"], train["time"], base_fit=fit)
    heavy_tail_flag = resid["jarque_bera_pvalue"] < 0.05 and resid["excess_kurtosis"] > 3.0
    candle_frame = pd.read_parquet(candles) if candles is not None and candles.exists() else None
    rho, rho_observations = _mark_return_funding_corr(frame, candle_frame, fit, price_coin)
    summary = {
        "ou": fit.as_dict(),
        "test_log_likelihood": float(test_ll),
        "standardized_residuals": resid,
        "ou_jump_diagnostic": jump_diag.as_dict(),
        "ou_jump_mle": jump_fit.as_dict(),
        "calibration_gate": "pivot_to_ou_jumps" if heavy_tail_flag else "pure_ou_acceptable",
        "shifted_cir": cir.as_dict(),
        "rho_funding_price": rho,
        "rho_observations": rho_observations,
        "price_coin": price_coin.upper(),
        "price_file": str(candles) if candles is not None else None,
        "train_rows": len(train),
        "test_rows": len(test),
    }

    ensure_parent(out_json).write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# Calibration Results",
        "",
        f"- Funding file: `{funding}`",
        f"- Train rows: {len(train)}",
        f"- Test rows: {len(test)}",
        f"- OU kappa: {fit.kappa:.8g} per hour",
        f"- OU theta: {fit.theta:.8g}",
        f"- OU sigma_f: {fit.sigma:.8g} per sqrt hour",
        f"- OU half-life: {fit.half_life_hours:.3f} hours",
        f"- Train log-likelihood: {fit.log_likelihood:.3f}",
        f"- Test log-likelihood: {test_ll:.3f}",
        f"- Funding-price innovation correlation rho: {rho}",
        f"- Rho observations: {rho_observations}",
        f"- Price file: `{candles}`",
        f"- Price coin: {price_coin.upper()}",
        f"- Calibration gate: {summary['calibration_gate']}",
        "",
        "## Residual Diagnostics",
        "",
    ]
    for key, value in summary["standardized_residuals"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Shifted CIR Robustness", ""])
    for key, value in cir.as_dict().items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## OU Jump Diagnostic", ""])
    for key, value in jump_diag.as_dict().items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## OU Jump MLE",
            "",
            "- transition_model: Bernoulli-normal jump approximation on OU transitions",
            "- note: one-jump small-dt approximation, not a full multi-jump compound-Poisson expansion",
        ]
    )
    for key, value in jump_fit.as_dict().items():
        lines.append(f"- {key}: {value}")
    if heavy_tail_flag:
        lines.extend(
            [
                "",
                "## Decision",
                "",
                "Residuals are heavy-tailed under Gaussian OU. Treat pure OU as the baseline mean-reversion state, but move the next modeling pass to OU+jumps before making paper-level claims.",
            ]
        )
    ensure_parent(out_md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    typer.echo(f"Wrote calibration outputs to {out_json} and {out_md}")


if __name__ == "__main__":
    app()
