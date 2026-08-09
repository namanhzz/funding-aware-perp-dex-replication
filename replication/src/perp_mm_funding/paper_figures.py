from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import typer

from perp_mm_funding.io import ensure_parent

app = typer.Typer(help="Generate paper figures from cached calibration/backtest results.")

ASSET_ORDER = ["ETH", "BTC", "SOL"]
COLORS = {
    "pure_as": "#4C566A",
    "hjb_fd": "#1F9D8A",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(fig: plt.Figure, output_stem: Path) -> list[Path]:
    paths = [output_stem.with_suffix(".pdf"), output_stem.with_suffix(".png")]
    for path in paths:
        ensure_parent(path)
        fig.savefig(path, bbox_inches="tight", dpi=220)
    plt.close(fig)
    return paths


def _asset_payload(payload: dict[str, Any], asset: str) -> dict[str, Any]:
    for item in payload["assets"]:
        if item["asset"] == asset:
            return item
    raise KeyError(f"missing asset in final robustness payload: {asset}")


def _result_by_trial(asset_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["trial"]: item for item in asset_payload["results"]}


def _bar_labels(ax: plt.Axes, xs: np.ndarray, ys: list[float], labels: list[str], dy: float) -> None:
    for x, y, label in zip(xs, ys, labels, strict=True):
        ax.text(x, y + dy, label, ha="center", va="bottom", fontsize=8)


def calibration_figure(calibration_paths: list[Path], out_stem: Path) -> list[Path]:
    rows = []
    for path in calibration_paths:
        payload = _load_json(path)
        asset = str(payload["price_coin"]).upper()
        rows.append(
            {
                "asset": asset,
                "half_life": float(payload["ou"]["half_life_hours"]),
                "ll_gain": float(payload["ou_jump_mle"]["likelihood_improvement"]),
                "rho": float(payload["rho_funding_price"]),
            }
        )
    rows = sorted(rows, key=lambda item: ASSET_ORDER.index(item["asset"]))

    assets = [row["asset"] for row in rows]
    x = np.arange(len(assets))
    fig, axes = plt.subplots(1, 3, figsize=(11.8, 3.1), constrained_layout=True)

    axes[0].bar(x, [row["half_life"] for row in rows], color="#3B6EA8")
    axes[0].set_title("OU half-life")
    axes[0].set_ylabel("hours")
    axes[0].set_xticks(x, assets)

    axes[1].bar(x, [row["ll_gain"] for row in rows], color="#8F5AA6")
    axes[1].set_title("OU+jump LL gain")
    axes[1].set_ylabel("LL gain")
    axes[1].set_xticks(x, assets)

    rho = [row["rho"] for row in rows]
    axes[2].bar(x, rho, color="#D18F3F")
    axes[2].axhline(0.0, color="#333333", linewidth=0.8)
    axes[2].set_title("Funding-price correlation")
    axes[2].set_ylabel(r"$\rho$")
    axes[2].set_xticks(x, assets)

    for ax in axes:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="y", alpha=0.2)

    return _save(fig, out_stem)


def backtest_summary_figure(final_results_path: Path, out_stem: Path) -> list[Path]:
    payload = _load_json(final_results_path)
    assets = ASSET_ORDER
    x = np.arange(len(assets))

    fig, axes = plt.subplots(1, 2, figsize=(10.8, 3.4), constrained_layout=True)

    deltas = []
    delta_ci = []
    inv_ratios = []
    win_labels = []
    for asset in assets:
        results = _result_by_trial(_asset_payload(payload, asset))
        baseline = results["pure_as_risk_matched"]
        result = results["hjb_fd_selected"]
        deltas.append(float(result["delta_final_equity_vs_risk_matched_as"]))
        delta_ci.append(float(result["delta_final_equity_vs_risk_matched_as_ci95"]))
        inv_ratios.append(float(result["inventory_rms"]) / float(baseline["inventory_rms"]))
        win_labels.append(f"{float(result['win_rate_vs_risk_matched_as']):.2f}")
    axes[0].bar(x, deltas, width=0.55, yerr=delta_ci, capsize=3, color=COLORS["hjb_fd"])
    axes[1].bar(x, inv_ratios, width=0.55, color=COLORS["hjb_fd"])
    label_offset = max(max(abs(value) for value in deltas) * 0.03, 1e-9)
    _bar_labels(axes[0], x, deltas, win_labels, dy=label_offset)

    axes[0].axhline(0.0, color="#333333", linewidth=0.8)
    axes[0].set_title("Net PnL delta vs nearest-risk AS")
    axes[0].set_ylabel("quote-currency units")
    axes[0].set_xticks(x, assets)
    axes[0].text(0.02, 0.95, "labels: paired win rate", transform=axes[0].transAxes, va="top", fontsize=8)

    axes[1].axhline(1.0, color="#333333", linewidth=0.8)
    axes[1].set_title("Inventory RMS relative to nearest-risk AS")
    axes[1].set_ylabel("ratio")
    axes[1].set_xticks(x, assets)

    for ax in axes:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="y", alpha=0.2)

    return _save(fig, out_stem)


def seed_delta_figure(final_results_path: Path, out_stem: Path) -> list[Path]:
    payload = _load_json(final_results_path)
    fig, ax = plt.subplots(figsize=(7.0, 3.4), constrained_layout=True)
    data = []
    for asset in ASSET_ORDER:
        results = _result_by_trial(_asset_payload(payload, asset))
        baseline = {
            int(row["seed"]): float(row["final_equity"])
            for row in results["pure_as_risk_matched"]["per_seed_results"]
        }
        deltas = [
            float(row["final_equity"]) - baseline[int(row["seed"])]
            for row in results["hjb_fd_selected"]["per_seed_results"]
        ]
        data.append(deltas)

    try:
        ax.boxplot(data, tick_labels=ASSET_ORDER, showmeans=True)
    except TypeError:
        ax.boxplot(data, labels=ASSET_ORDER, showmeans=True)
    for asset_idx, deltas in enumerate(data, start=1):
        jitter = np.linspace(-0.08, 0.08, len(deltas))
        ax.scatter(asset_idx + jitter, deltas, s=18, color=COLORS["hjb_fd"], alpha=0.75, zorder=3)
    ax.axhline(0.0, color="#333333", linewidth=0.8)
    ax.set_title("Seed-level net PnL delta: FD HJB minus nearest-risk AS")
    ax.set_ylabel("quote-currency units")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.2)
    return _save(fig, out_stem)


def risk_frontier_figure(frontier_summary_path: Path, out_stem: Path) -> list[Path]:
    payload = _load_json(frontier_summary_path)
    rows = payload["rows"]
    analysis_label = str(payload.get("analysis_label", "")).lower()
    window_label = "198-day" if "198-day" in analysis_label else "final-window"
    hjb_points = sorted(
        {(float(row["hjb_inventory_rms"]), float(row["hjb_net_pnl"])) for row in rows}
    )
    as_points = sorted(
        {(float(row["as_inventory_rms"]), float(row["as_net_pnl"])) for row in rows}
    )

    fig, axes = plt.subplots(1, 2, figsize=(10.8, 3.4), constrained_layout=True)
    axes[0].plot(
        [point[0] for point in as_points],
        [point[1] for point in as_points],
        color=COLORS["pure_as"],
        marker="s",
        markersize=4,
        label="AS",
    )
    axes[0].plot(
        [point[0] for point in hjb_points],
        [point[1] for point in hjb_points],
        color=COLORS["hjb_fd"],
        marker="o",
        markersize=4,
        label="Funding-aware HJB",
    )
    axes[0].set_title(f"SOL {window_label} risk frontier")
    axes[0].set_xlabel("inventory RMS")
    axes[0].set_ylabel("net PnL")
    axes[0].legend(frameon=False, fontsize=8)

    comparable = [row for row in rows if row["risk_gap_within_10pct"]]
    xs = [
        0.5 * (float(row["hjb_inventory_rms"]) + float(row["as_inventory_rms"]))
        for row in comparable
    ]
    ys = [float(row["paired_delta"]) for row in comparable]
    errors = [float(row["paired_delta_ci95"]) for row in comparable]
    colors = [COLORS["hjb_fd"] if value > 0.0 else "#B24C4C" for value in ys]
    axes[1].errorbar(xs, ys, yerr=errors, fmt="none", ecolor="#555555", capsize=2, linewidth=0.8)
    axes[1].scatter(xs, ys, c=colors, s=28, zorder=3)
    axes[1].axhline(0.0, color="#333333", linewidth=0.8)
    axes[1].set_title("HJB minus risk-matched AS")
    axes[1].set_xlabel("average inventory RMS")
    axes[1].set_ylabel("paired net-PnL difference")
    axes[1].text(
        0.97,
        0.95,
        f"{payload['positive_comparable_risk_points']}/{payload['comparable_risk_points']} comparable points positive",
        transform=axes[1].transAxes,
        va="top",
        ha="right",
        fontsize=8,
    )

    for ax in axes:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(alpha=0.2)
    return _save(fig, out_stem)


@app.command()
def main(
    final_results: Path = typer.Option(Path("results/final-hjb-robustness.json")),
    frontier_summary: Path = typer.Option(Path("results/sol-risk-frontier-summary.json")),
    extended_frontier_summary: Path = typer.Option(
        Path("results/extended-window-2026-sol-risk-frontier-summary.json")
    ),
    out_dir: Path = typer.Option(Path("results/figures")),
) -> None:
    written: list[Path] = []
    written.extend(
        calibration_figure(
            [
                Path("results/calibration-eth.json"),
                Path("results/calibration-btc.json"),
                Path("results/calibration-sol.json"),
            ],
            out_dir / "calibration-ou-jump-summary",
        )
    )
    written.extend(backtest_summary_figure(final_results, out_dir / "final-backtest-summary"))
    written.extend(seed_delta_figure(final_results, out_dir / "final-backtest-seed-deltas"))
    if frontier_summary.exists():
        written.extend(risk_frontier_figure(frontier_summary, out_dir / "sol-risk-frontier"))
    if extended_frontier_summary.exists():
        written.extend(
            risk_frontier_figure(
                extended_frontier_summary,
                out_dir / "sol-risk-frontier-extended",
            )
        )
    for path in written:
        typer.echo(f"Wrote {path}")


if __name__ == "__main__":
    app()
