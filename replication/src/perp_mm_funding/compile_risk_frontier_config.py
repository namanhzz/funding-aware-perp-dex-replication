from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
import yaml

from perp_mm_funding.io import ensure_parent


app = typer.Typer(help="Compile a development-only SOL risk-frontier final diagnostic.")


def _efficient_frontier(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(candidates, key=lambda item: float(item["inventory_rms"]))
    frontier: list[dict[str, Any]] = []
    best_equity = float("-inf")
    for candidate in ordered:
        equity = float(candidate["final_equity"])
        if equity > best_equity + 1e-9:
            frontier.append(candidate)
            best_equity = equity
    return frontier


def _penalty_label(params: dict[str, Any]) -> str:
    value = f"{float(params['running_penalty']):g}"
    return value.replace(".", "p").replace("-", "m").replace("+", "")


def compile_frontier_config(
    selection: dict[str, Any],
    *,
    price_path: str,
    funding_path: str,
) -> dict[str, Any]:
    asset = selection["assets"][0]
    if str(asset["asset"]).upper() != "SOL":
        raise ValueError("The current frontier diagnostic is defined for SOL")

    hjb_candidates = [
        candidate
        for candidate in asset["hjb_candidates"]
        if float(candidate["params"]["terminal_penalty"]) == 0.00025
    ]
    hjb_frontier = _efficient_frontier(hjb_candidates)
    as_candidates = list(asset["as_candidates"])

    pairs: list[dict[str, Any]] = []
    trials_by_name: dict[str, dict[str, Any]] = {}
    for hjb in hjb_frontier:
        matched_as = min(
            as_candidates,
            key=lambda candidate: (
                abs(float(candidate["inventory_rms"]) - float(hjb["inventory_rms"])),
                -float(candidate["final_equity"]),
            ),
        )
        hjb_name = f"hjb_frontier_phi_{_penalty_label(hjb['params'])}"
        as_name = (
            "as_frontier_a_"
            f"{float(matched_as['params']['terminal_penalty']):g}_p_"
            f"{float(matched_as['params']['running_penalty']):g}"
        ).replace(".", "p").replace("-", "m").replace("+", "")
        trials_by_name[hjb_name] = {
            "name": hjb_name,
            "variant": "hjb_fd",
            "params": hjb["params"],
        }
        trials_by_name[as_name] = {
            "name": as_name,
            "variant": "pure_as",
            "params": matched_as["params"],
        }
        pairs.append(
            {
                "hjb_trial": hjb_name,
                "as_trial": as_name,
                "development_hjb_rms": hjb["inventory_rms"],
                "development_as_rms": matched_as["inventory_rms"],
            }
        )

    selected_params = asset["selected_hjb"]["params"]
    selected_hjb_name = next(
        pair["hjb_trial"]
        for pair in pairs
        if trials_by_name[pair["hjb_trial"]]["params"] == selected_params
    )
    selected_pair = next(pair for pair in pairs if pair["hjb_trial"] == selected_hjb_name)

    default_trial = {"name": "pure_as_default", "variant": "pure_as", "params": {}}
    ordered_trials = [default_trial, *trials_by_name.values()]
    return {
        "analysis_label": "Post-result SOL risk-frontier diagnostic",
        "selection_basis": (
            "Expanded development-only penalties; final-window PnL was not used "
            "to choose candidates or matches"
        ),
        "start_time": "2026-06-18T00:00:00Z",
        "end_time": "2026-07-31T23:59:00Z",
        "seeds": list(range(1, 101)),
        "jobs": 20,
        "paired_baselines": [
            {"trial": selected_pair["as_trial"], "field_suffix": "frontier_matched_as"}
        ],
        "frontier_selected_hjb_trial": selected_hjb_name,
        "frontier_selected_as_trial": selected_pair["as_trial"],
        "frontier_pairs": pairs,
        "assets": [
            {
                "asset": "SOL",
                "base_config": "configs/backtest_sol_hl_l2_holdout_model_variants.yaml",
                "base_overrides": {
                    "price_path": price_path,
                    "funding_path": funding_path,
                    "simulation_frequency": "1min",
                    "maker_fee_rate": 0.00015,
                    "adverse_selection_bps": 0.0,
                    "fill_probability_scale": 1.0,
                    "funding_accrual_mode": "hourly_boundary",
                },
                "trials": ordered_trials,
            }
        ],
    }


@app.command()
def main(
    selection_path: Path = typer.Option(
        Path("results/development-risk-frontier-2026-sol.json"),
        exists=True,
        dir_okay=False,
    ),
    out: Path = typer.Option(Path("configs/final_holdout_2026_sol_risk_frontier_100.yaml")),
) -> None:
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    payload = compile_frontier_config(
        selection,
        price_path="data/clean/sol-hyperliquid-candles-15m-final-20260618-20260731.parquet",
        funding_path="data/clean/sol-funding-1h-final-20260618-20260731.parquet",
    )
    ensure_parent(out).write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    typer.echo(f"Wrote {out}")


if __name__ == "__main__":
    app()
