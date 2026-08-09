from __future__ import annotations

from dataclasses import asdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import product
import json
import math
from pathlib import Path
from typing import Any

import typer
import yaml

from perp_mm_funding.io import ensure_parent
from perp_mm_funding.run_variant_sweep import (
    VariantTrial,
    _load_config,
    _load_frames,
    _run_trial_for_seeds,
    _windowed_config,
)


app = typer.Typer(help="Run the frozen development-only HJB and risk-matched AS selection.")


def _grid_trials(variant: str, grid: dict[str, list[float]]) -> list[VariantTrial]:
    keys = list(grid)
    trials: list[VariantTrial] = []
    for values in product(*(grid[key] for key in keys)):
        params = dict(zip(keys, values, strict=True))
        suffix = "__".join(f"{key}={value:g}" for key, value in params.items())
        trials.append(VariantTrial(name=f"{variant}__{suffix}", variant=variant, params=params))
    return trials


def _explicit_trials(variant: str, candidates: list[dict[str, float]]) -> list[VariantTrial]:
    trials: list[VariantTrial] = []
    for index, params in enumerate(candidates, start=1):
        trials.append(
            VariantTrial(
                name=f"{variant}__additional_{index:02d}",
                variant=variant,
                params={key: float(value) for key, value in params.items()},
            )
        )
    return trials


def _select_hjb(candidates: list[dict[str, Any]], baseline_rms: float) -> tuple[dict[str, Any], bool]:
    feasible = [result for result in candidates if float(result["inventory_rms"]) <= baseline_rms]
    if feasible:
        return max(feasible, key=lambda result: float(result["final_equity"])), True
    return min(candidates, key=lambda result: (float(result["inventory_rms"]), -float(result["final_equity"]))), False


def _select_risk_matched_as(candidates: list[dict[str, Any]], target_rms: float) -> dict[str, Any]:
    return min(
        candidates,
        key=lambda result: (
            abs(float(result["inventory_rms"]) - target_rms),
            -float(result["final_equity"]),
        ),
    )


def _compact(result: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "trial",
        "variant",
        "params",
        "final_equity",
        "final_equity_std",
        "inventory_rms",
        "inventory_rms_std",
        "turnover",
        "realized_trading_fees",
        "net_pnl_bps_turnover",
        "fill_rate",
    ]
    return {key: result.get(key) for key in keys}


def _run_candidate(cfg: dict[str, Any], trial: VariantTrial, seeds: list[int]) -> dict[str, Any]:
    price, funding = _load_frames(cfg)
    return _run_trial_for_seeds(cfg, price, funding, trial, seeds)


def _run_candidates(
    cfg: dict[str, Any],
    trials: list[VariantTrial],
    seeds: list[int],
    jobs: int,
    label: str,
) -> list[dict[str, Any]]:
    if jobs <= 1:
        return [_run_candidate(cfg, trial, seeds) for trial in trials]
    results_by_name: dict[str, dict[str, Any]] = {}
    with ProcessPoolExecutor(max_workers=min(jobs, len(trials))) as executor:
        futures = {executor.submit(_run_candidate, cfg, trial, seeds): trial for trial in trials}
        for index, future in enumerate(as_completed(futures), start=1):
            trial = futures[future]
            results_by_name[trial.name] = future.result()
            typer.echo(f"[{label} {index}/{len(trials)}] {trial.name}")
    return [results_by_name[trial.name] for trial in trials]


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    label = str(payload.get("record_label", "Frozen development-only selection"))
    lines = [f"# {label}", ""]
    if label.lower().startswith("post-result"):
        lines.extend(
            [
                "This diagnostic was recorded after the initial final-window analysis.",
                "Candidate policies and risk matches use development data only; final-window",
                "PnL is not used to select a grid point or its AS match.",
            ]
        )
    else:
        lines.extend(
            [
                "The final design and grids were frozen before the 2026 holdout was evaluated.",
                "The AS grid was expanded using development results only because its initial",
                "range did not bracket the selected HJB inventory RMS; the design file records",
                "this amendment.",
            ]
        )
    lines.extend([
        "All selection results use data ending on 2025-12-31.", "",
        "| Asset | Policy | Final equity | Inventory RMS | Turnover | Trading fees |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ])
    for asset in payload["assets"]:
        for label in ["baseline_as", "selected_hjb", "risk_matched_as"]:
            result = asset[label]
            lines.append(
                f"| {asset['asset']} | {label} | {result['final_equity']:.2f} | "
                f"{result['inventory_rms']:.4f} | {result['turnover']:.2f} | "
                f"{result['realized_trading_fees']:.2f} |"
            )
        lines.append("")
        lines.append(f"- {asset['asset']} HJB inventory constraint feasible: `{asset['hjb_constraint_feasible']}`")
    ensure_parent(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


@app.command()
def main(
    design: Path = typer.Option(Path("configs/final_holdout_2026_design.yaml")),
    out_json: Path = typer.Option(Path("results/predeclared-development-selection-2026.json")),
    out_md: Path = typer.Option(Path("docs/predeclared-development-selection-2026.md")),
    assets: str = typer.Option("", help="Optional comma-separated asset subset."),
    jobs: int = typer.Option(8, min=1, help="Parallel parameter candidates per asset."),
) -> None:
    design_cfg = _load_config(design)
    seeds = [int(seed) for seed in design_cfg["selection"]["seeds"]]
    fee_rate = float(design_cfg["final_evaluation"]["primary_maker_fee_rate"])
    hjb_trials = _grid_trials("hjb_fd", design_cfg["selection"]["hjb_grid"])
    as_trials = _grid_trials("pure_as", design_cfg["selection"]["as_grid"])
    as_trials.extend(
        _explicit_trials(
            "pure_as",
            list(design_cfg["selection"].get("as_additional_candidates", [])),
        )
    )

    selected_assets = [item.strip().upper() for item in assets.split(",") if item.strip()]
    if not selected_assets:
        selected_assets = [str(item).upper() for item in design_cfg["assets"]]
    unknown = sorted(set(selected_assets).difference(design_cfg["assets"]))
    if unknown:
        raise typer.BadParameter(f"Unknown assets: {unknown}")

    asset_payloads: list[dict[str, Any]] = []
    for asset in selected_assets:
        typer.echo(f"[asset] {asset}")
        base_path = Path(design_cfg["asset_base_configs"][asset])
        cfg = _windowed_config(
            _load_config(base_path),
            str(design_cfg["development_start_time"]),
            str(design_cfg["development_end_time"]),
        )
        cfg["maker_fee_rate"] = fee_rate
        cfg["adverse_selection_bps"] = 0.0
        cfg["fill_probability_scale"] = 1.0
        price, funding = _load_frames(cfg)
        baseline = _run_trial_for_seeds(cfg, price, funding, VariantTrial("pure_as_default", "pure_as", {}), seeds)

        hjb_results = _run_candidates(cfg, hjb_trials, seeds, jobs, f"{asset} HJB")
        selected_hjb, feasible = _select_hjb(hjb_results, float(baseline["inventory_rms"]))

        as_results = _run_candidates(cfg, as_trials, seeds, jobs, f"{asset} AS")
        matched_as = _select_risk_matched_as(as_results, float(selected_hjb["inventory_rms"]))

        asset_payloads.append(
            {
                "asset": asset,
                "base_config": str(base_path),
                "hjb_constraint_feasible": feasible,
                "baseline_as": _compact(baseline),
                "selected_hjb": _compact(selected_hjb),
                "risk_matched_as": _compact(matched_as),
                "hjb_candidates": [_compact(result) for result in hjb_results],
                "as_candidates": [_compact(result) for result in as_results],
            }
        )

    payload = {
        "record_label": design_cfg.get("record_label", "Frozen development-only selection"),
        "design": str(design),
        "development_start_time": design_cfg["development_start_time"],
        "development_end_time": design_cfg["development_end_time"],
        "maker_fee_rate": fee_rate,
        "seeds": seeds,
        "assets": asset_payloads,
    }
    ensure_parent(out_json).write_text(json.dumps(_clean(payload), indent=2, sort_keys=True), encoding="utf-8")
    _write_markdown(out_md, payload)
    typer.echo(f"Wrote {out_json}")
    typer.echo(f"Wrote {out_md}")


if __name__ == "__main__":
    app()
