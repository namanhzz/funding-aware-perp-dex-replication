from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import typer
import yaml

from perp_mm_funding.io import ensure_parent


app = typer.Typer(help="Compile principal expanded-sample evaluation configurations.")


def extended_window_config(
    source: dict[str, Any],
    *,
    start_time: str,
    end_time: str,
    seed_count: int,
    jobs: int,
    analysis_label: str,
) -> dict[str, Any]:
    if seed_count <= 0:
        raise ValueError("seed_count must be positive")
    result = deepcopy(source)
    result["analysis_label"] = analysis_label
    result["selection_basis"] = (
        "Expanded after inspecting the venue-native validation; policies and risk "
        "matches remain fixed from development-only selection and are not retuned"
    )
    result["start_time"] = start_time
    result["end_time"] = end_time
    result["seeds"] = list(range(1, seed_count + 1))
    result["jobs"] = jobs
    for asset_cfg in result["assets"]:
        asset = str(asset_cfg["asset"]).lower()
        overrides = asset_cfg.setdefault("base_overrides", {})
        overrides["price_path"] = (
            f"data/clean/{asset}-causal-intrabar-bridge-1m-extended-20260115-20260731.parquet"
        )
        overrides["funding_path"] = (
            f"data/clean/{asset}-funding-1h-extended-20260115-20260731.parquet"
        )
        overrides["simulation_frequency"] = "1min"
    return result


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, Any]) -> None:
    ensure_parent(path).write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    typer.echo(f"Wrote {path}")


@app.command()
def main(
    primary_source: Path = typer.Option(Path("configs/final_holdout_2026_100.yaml")),
    frontier_source: Path = typer.Option(
        Path("configs/final_holdout_2026_sol_risk_frontier_100.yaml")
    ),
    primary_out: Path = typer.Option(Path("configs/extended_window_2026_100.yaml")),
    frontier_out: Path = typer.Option(
        Path("configs/extended_window_2026_sol_risk_frontier_100.yaml")
    ),
    seed_count: int = typer.Option(100, min=1),
    jobs: int = typer.Option(8, min=1),
) -> None:
    common = {
        "start_time": "2026-01-15T00:00:00Z",
        "end_time": "2026-07-31T23:59:00Z",
        "seed_count": seed_count,
        "jobs": jobs,
    }
    _write(
        primary_out,
        extended_window_config(
            _load(primary_source),
            analysis_label="Principal 198-day expanded-sample evaluation",
            **common,
        ),
    )
    _write(
        frontier_out,
        extended_window_config(
            _load(frontier_source),
            analysis_label="Principal-sample post-result 198-day SOL risk-frontier diagnostic",
            **common,
        ),
    )


if __name__ == "__main__":
    app()
