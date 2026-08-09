from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
import yaml

from perp_mm_funding.io import ensure_parent


app = typer.Typer(help="Compile selected development parameters into frozen final-holdout configs.")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _scenario_config(
    design: dict[str, Any],
    selections: dict[str, dict[str, Any]],
    *,
    maker_fee_rate: float,
    adverse_selection_bps: float = 0.0,
    fill_probability_scale: float = 1.0,
    alternative_fill: bool = False,
    funding_accrual_mode: str = "hourly_boundary",
    price_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    assets = []
    for asset in design["assets"]:
        selected = selections[asset]
        overrides = {
            **design["holdout_files"][asset],
            "simulation_frequency": design.get("simulation_frequency"),
            "maker_fee_rate": maker_fee_rate,
            "adverse_selection_bps": adverse_selection_bps,
            "fill_probability_scale": fill_probability_scale,
            "funding_accrual_mode": funding_accrual_mode,
        }
        if price_paths is not None:
            overrides["price_path"] = price_paths[asset]
        if alternative_fill:
            overrides["fill_intensity_path"] = f"results/fill-intensity-{asset.lower()}-minute-hit-train.json"
        assets.append(
            {
                "asset": asset,
                "base_config": design["asset_base_configs"][asset],
                "base_overrides": overrides,
                "trials": [
                    {"name": "pure_as_default", "variant": "pure_as", "params": {}},
                    {
                        "name": "pure_as_risk_matched",
                        "variant": "pure_as",
                        "params": selected["risk_matched_as"]["params"],
                    },
                    {
                        "name": "hjb_fd_selected",
                        "variant": "hjb_fd",
                        "params": selected["selected_hjb"]["params"],
                    },
                ],
            }
        )
    return {
        "start_time": design["final_holdout_start_time"],
        "end_time": design["final_holdout_end_time"],
        "seeds": list(range(1, 101)),
        "jobs": 20,
        "paired_baselines": [
            {"trial": "pure_as_risk_matched", "field_suffix": "risk_matched_as"}
        ],
        "assets": assets,
    }


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    ensure_parent(path).write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


@app.command()
def main(
    design_path: Path = typer.Option(Path("configs/final_holdout_2026_design.yaml")),
    selection_dir: Path = typer.Option(Path("results")),
) -> None:
    design = yaml.safe_load(design_path.read_text(encoding="utf-8"))
    selections: dict[str, dict[str, Any]] = {}
    combined_assets = []
    for asset in design["assets"]:
        path = selection_dir / f"predeclared-development-selection-2026-{asset.lower()}.json"
        payload = _load_json(path)
        selection = payload["assets"][0]
        selections[asset] = selection
        combined_assets.append(selection)

    combined = {
        "design": str(design_path),
        "development_start_time": design["development_start_time"],
        "development_end_time": design["development_end_time"],
        "seeds": design["selection"]["seeds"],
        "assets": combined_assets,
    }
    ensure_parent(selection_dir / "predeclared-development-selection-2026.json").write_text(
        json.dumps(combined, indent=2, sort_keys=True), encoding="utf-8"
    )

    primary_fee = float(design["final_evaluation"]["primary_maker_fee_rate"])
    scenarios = {
        "final_holdout_2026_100.yaml": _scenario_config(
            design, selections, maker_fee_rate=primary_fee
        ),
        "final_holdout_2026_minute_hit_100.yaml": _scenario_config(
            design, selections, maker_fee_rate=primary_fee, alternative_fill=True
        ),
        "final_holdout_2026_conservative_execution_100.yaml": _scenario_config(
            design,
            selections,
            maker_fee_rate=primary_fee,
            adverse_selection_bps=float(design["robustness"]["conservative_execution"]["adverse_selection_bps"]),
            fill_probability_scale=float(design["robustness"]["conservative_execution"]["fill_probability_scale"]),
        ),
        "final_holdout_2026_zero_fee_100.yaml": _scenario_config(
            design, selections, maker_fee_rate=0.0
        ),
        "final_holdout_2026_rebate_100.yaml": _scenario_config(
            design, selections, maker_fee_rate=-0.00001
        ),
        "final_holdout_2026_continuous_funding_100.yaml": _scenario_config(
            design,
            selections,
            maker_fee_rate=primary_fee,
            funding_accrual_mode="continuous",
        ),
        "final_holdout_2026_intrabar_bridge_100.yaml": _scenario_config(
            design,
            selections,
            maker_fee_rate=primary_fee,
            price_paths={
                asset: (
                    "data/clean/"
                    f"{asset.lower()}-causal-intrabar-bridge-1m-final-20260618-20260731.parquet"
                )
                for asset in design["assets"]
            },
        ),
    }
    for name, payload in scenarios.items():
        _write_yaml(Path("configs") / name, payload)
        typer.echo(f"Wrote configs/{name}")
    typer.echo("Wrote results/predeclared-development-selection-2026.json")


if __name__ == "__main__":
    app()
