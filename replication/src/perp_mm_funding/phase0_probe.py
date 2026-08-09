from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import typer

from perp_mm_funding.calibration.diagnostics import acf_pacf_table, ar1_half_life_hours, rolling_adf, run_adf
from perp_mm_funding.fetch_data import _window
from perp_mm_funding.hyperliquid_client import HyperliquidClient
from perp_mm_funding.io import ensure_parent, write_jsonl, write_parquet
from perp_mm_funding.schemas import normalize_funding_rows

app = typer.Typer(help="Run Phase 0 funding-rate kill-or-go probe.")


def _load_or_fetch(coin: str, days: int, input_path: Path | None, out_path: Path) -> pd.DataFrame:
    if input_path is not None and input_path.exists():
        return pd.read_parquet(input_path).sort_values("time").reset_index(drop=True)
    start, end = _window(days, None, None)
    client = HyperliquidClient()
    rows = client.paginate_funding_history(coin, start, end)
    write_jsonl(rows, Path(f"data/raw/{coin.lower()}-phase0-funding-{start}-{end}.jsonl"))
    frame = normalize_funding_rows(rows)
    write_parquet(frame, out_path)
    return frame


def _plot_funding(frame: pd.DataFrame, output: Path) -> None:
    ensure_parent(output)
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(frame["time"], frame["funding_rate"], linewidth=1)
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_title("Hyperliquid Funding Rate")
    ax.set_xlabel("Time")
    ax.set_ylabel("Funding rate")
    fig.tight_layout()
    fig.savefig(output, dpi=160)
    plt.close(fig)


def _plot_acf_pacf(table: pd.DataFrame, output: Path) -> None:
    ensure_parent(output)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].bar(table["lag"], table["acf"])
    axes[0].set_title("ACF")
    axes[0].set_xlabel("Lag")
    axes[1].bar(table["lag"], table["pacf"])
    axes[1].set_title("PACF")
    axes[1].set_xlabel("Lag")
    fig.tight_layout()
    fig.savefig(output, dpi=160)
    plt.close(fig)


@app.command()
def main(
    coin: str = typer.Option("ETH", help="Hyperliquid coin symbol."),
    days: int = typer.Option(90, min=14, help="Lookback window."),
    input_path: Path | None = typer.Option(None, help="Use existing funding parquet instead of fetching."),
    clean_out: Path = typer.Option(Path("data/clean/eth-funding-1h.parquet")),
    report_out: Path = typer.Option(Path("docs/go-no-go.md")),
) -> None:
    frame = _load_or_fetch(coin, days, input_path, clean_out)
    if frame.empty:
        raise typer.BadParameter("No funding rows available")

    funding = frame["funding_rate"]
    adf = run_adf(funding)
    window = min(len(frame), 90 * 24)
    rolling = rolling_adf(funding, window=window)
    acfpacf = acf_pacf_table(funding, nlags=72)
    half_life = ar1_half_life_hours(funding)

    _plot_funding(frame, Path("results/figures/phase0-funding.png"))
    _plot_acf_pacf(acfpacf, Path("results/figures/phase0-acf-pacf.png"))

    min_pvalue = float(rolling["pvalue"].min()) if not rolling.empty else adf.pvalue
    adf_pass = min_pvalue < 0.05
    half_life_pass = 1.0 <= half_life <= 24.0 * 7.0
    verdict = "GO" if adf_pass and half_life_pass else "NO-GO / PIVOT"

    lines = [
        "# Phase 0 Go/No-Go",
        "",
        f"- Coin: {coin.upper()}",
        f"- Rows: {len(frame)}",
        f"- Start: {frame['time'].min()}",
        f"- End: {frame['time'].max()}",
        f"- ADF statistic: {adf.statistic:.6g}",
        f"- ADF p-value full window: {adf.pvalue:.6g}",
        f"- Minimum rolling ADF p-value: {min_pvalue:.6g}",
        f"- AR(1) half-life hours: {half_life:.6g}",
        f"- ADF gate passed: {adf_pass}",
        f"- Half-life gate passed: {half_life_pass}",
        f"- Verdict: **{verdict}**",
        "",
        "## Artifacts",
        "",
        "- `results/figures/phase0-funding.png`",
        "- `results/figures/phase0-acf-pacf.png`",
        "",
        "## Notes",
        "",
        "Inspect the ACF/PACF plot manually for long memory, periodicity, or regime-switching before entering Phase 1.",
    ]
    ensure_parent(report_out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    typer.echo(f"Phase 0 verdict: {verdict}. Report: {report_out}")


if __name__ == "__main__":
    app()

