from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
import typer
import yaml

from perp_mm_funding.io import ensure_parent


app = typer.Typer(help="Build checksummed replication-data manifests.")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parquet_metadata(path: Path) -> dict[str, Any]:
    parquet = pq.ParquetFile(path)
    columns = parquet.schema.names
    metadata: dict[str, Any] = {"rows": parquet.metadata.num_rows, "columns": columns}
    time_column = next((column for column in ["time", "open_time"] if column in columns), None)
    if time_column is not None:
        values = pd.read_parquet(path, columns=[time_column])[time_column]
        metadata["time_min"] = str(pd.to_datetime(values, utc=True).min())
        metadata["time_max"] = str(pd.to_datetime(values, utc=True).max())
    return metadata


def describe_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": path.as_posix(), "status": "missing"}
    record: dict[str, Any] = {
        "path": path.as_posix(),
        "status": "available",
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }
    if path.suffix.lower() == ".parquet":
        record.update(_parquet_metadata(path))
    return record


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Replication data manifest",
        "",
        "Final holdout candles and funding were downloaded from the official Hyperliquid info API.",
        "Training fill curves were produced from pre-2026 official fills joined to the local L2 panel.",
        "The manifest records exact file hashes; source reconstruction commands are in the repository documentation.",
        "",
        "| File | Status | Rows | Size (bytes) | SHA-256 |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for item in payload["files"]:
        lines.append(
            f"| `{item['path']}` | {item['status']} | {item.get('rows', '')} | "
            f"{item.get('size_bytes', '')} | `{item.get('sha256', '')}` |"
        )
    lines.extend(["", "## Source URLs", ""])
    for name, url in payload["source_urls"].items():
        lines.append(f"- {name}: {url}")
    ensure_parent(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


@app.command()
def main(
    config: Path = typer.Option(Path("configs/replication_manifest.yaml")),
    out_json: Path = typer.Option(Path("data/replication/manifest.json")),
    out_md: Path = typer.Option(Path("docs/replication-data-manifest.md")),
) -> None:
    cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
    payload = {
        "source_urls": cfg.get("source_urls", {}),
        "files": [describe_file(Path(value)) for value in cfg.get("files", [])],
    }
    ensure_parent(out_json).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_markdown(out_md, payload)
    typer.echo(f"Wrote {out_json}")
    typer.echo(f"Wrote {out_md}")


if __name__ == "__main__":
    app()
