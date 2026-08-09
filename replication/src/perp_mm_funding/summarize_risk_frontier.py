from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import typer

from perp_mm_funding.io import ensure_parent
from perp_mm_funding.run_final_robustness import (
    _hac_mean_ci,
    _mean_std_ci,
    _mean_std_t_ci,
    _moving_block_bootstrap_mean_interval,
)


app = typer.Typer(help="Summarize paired SOL HJB/AS risk-frontier evidence.")


def summarize_frontier(payload: dict[str, Any]) -> dict[str, Any]:
    results = {item["trial"]: item for item in payload["assets"][0]["results"]}
    rows: list[dict[str, Any]] = []
    for pair in payload["frontier_pairs"]:
        hjb = results[pair["hjb_trial"]]
        baseline = results[pair["as_trial"]]
        baseline_by_seed = {
            int(item["seed"]): item for item in baseline["per_seed_results"]
        }
        seed_deltas = [
            float(item["final_equity"])
            - float(baseline_by_seed[int(item["seed"])]["final_equity"])
            for item in hjb["per_seed_results"]
        ]
        paired_mean, paired_std, paired_ci95 = _mean_std_ci(seed_deltas)

        weekly_means = []
        week_keys = sorted(
            hjb["per_seed_results"][0].get("complete_week_pnl", {}),
            key=int,
        )
        for key in week_keys:
            weekly_means.append(
                float(
                    np.mean(
                        [
                            float(item["complete_week_pnl"][key])
                            - float(baseline_by_seed[int(item["seed"])]["complete_week_pnl"][key])
                            for item in hjb["per_seed_results"]
                        ]
                    )
                )
            )
        weekly_mean, weekly_std, weekly_ci95 = _mean_std_t_ci(weekly_means)

        daily_means = []
        day_keys = sorted(
            hjb["per_seed_results"][0].get("complete_day_pnl", {}),
            key=int,
        )
        for key in day_keys:
            daily_means.append(
                float(
                    np.mean(
                        [
                            float(item["complete_day_pnl"][key])
                            - float(baseline_by_seed[int(item["seed"])]["complete_day_pnl"][key])
                            for item in hjb["per_seed_results"]
                        ]
                    )
                )
            )
        daily_mean, daily_hac_se, daily_hac_ci95 = _hac_mean_ci(daily_means, max_lag=7)
        bootstrap_lower, bootstrap_upper = _moving_block_bootstrap_mean_interval(
            daily_means,
            block_length=7,
        )

        hjb_rms = float(hjb["inventory_rms"])
        as_rms = float(baseline["inventory_rms"])
        rms_ratio = hjb_rms / as_rms if as_rms else float("nan")
        rows.append(
            {
                **pair,
                "hjb_net_pnl": float(hjb["final_equity"]),
                "as_net_pnl": float(baseline["final_equity"]),
                "hjb_inventory_rms": hjb_rms,
                "as_inventory_rms": as_rms,
                "rms_ratio": rms_ratio,
                "risk_gap_within_10pct": bool(abs(rms_ratio - 1.0) <= 0.10),
                "paired_delta": paired_mean,
                "paired_delta_std": paired_std,
                "paired_delta_ci95": paired_ci95,
                "paired_win_rate": float(np.mean(np.asarray(seed_deltas) > 0.0)),
                "weekly_delta_means": weekly_means,
                "weekly_delta_mean": weekly_mean,
                "weekly_delta_std": weekly_std,
                "weekly_delta_ci95": weekly_ci95,
                "weekly_win_rate": float(np.mean(np.asarray(weekly_means) > 0.0)),
                "daily_delta_means": daily_means,
                "daily_delta_mean": daily_mean,
                "daily_delta_hac_se": daily_hac_se,
                "daily_delta_hac_ci95": daily_hac_ci95,
                "daily_block_bootstrap_lower": bootstrap_lower,
                "daily_block_bootstrap_upper": bootstrap_upper,
            }
        )

    comparable = [row for row in rows if row["risk_gap_within_10pct"]]
    return {
        "source": payload["config"],
        "analysis_label": payload.get("analysis_label"),
        "selection_basis": payload.get("selection_basis"),
        "rows": rows,
        "comparable_risk_points": len(comparable),
        "positive_comparable_risk_points": sum(row["paired_delta"] > 0.0 for row in comparable),
    }


def _markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# SOL risk-frontier summary",
        "",
        str(summary.get("selection_basis", "")),
        "",
        "| HJB RMS | AS RMS | RMS ratio | HJB-AS PnL | MC 95% half-width | Weekly mean | Weekly 95% half-width | Daily HAC 95% half-width |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["rows"]:
        lines.append(
            f"| {row['hjb_inventory_rms']:.2f} | {row['as_inventory_rms']:.2f} | "
            f"{row['rms_ratio']:.3f} | {row['paired_delta']:.2f} | "
            f"{row['paired_delta_ci95']:.2f} | {row['weekly_delta_mean']:.2f} | "
            f"{row['weekly_delta_ci95']:.2f} | {row['daily_delta_hac_ci95']:.2f} |"
        )
    lines.extend(
        [
            "",
            f"Comparable-risk points (absolute RMS gap no greater than 10%): {summary['comparable_risk_points']}.",
            f"Positive paired differences among them: {summary['positive_comparable_risk_points']}.",
            "",
        ]
    )
    return "\n".join(lines)


@app.command()
def main(
    results_path: Path = typer.Option(
        Path("results/final-holdout-2026-sol-risk-frontier-100.json"),
        exists=True,
        dir_okay=False,
    ),
    out_json: Path = typer.Option(Path("results/sol-risk-frontier-summary.json")),
    out_md: Path = typer.Option(Path("docs/sol-risk-frontier-summary.md")),
) -> None:
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    summary = summarize_frontier(payload)
    ensure_parent(out_json).write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    ensure_parent(out_md).write_text(_markdown(summary), encoding="utf-8")
    typer.echo(f"Wrote {out_json}")
    typer.echo(f"Wrote {out_md}")


if __name__ == "__main__":
    app()
