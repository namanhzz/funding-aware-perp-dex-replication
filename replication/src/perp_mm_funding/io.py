from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping, Any

import pandas as pd


def ensure_parent(path: str | Path) -> Path:
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def write_jsonl(rows: Iterable[Mapping[str, Any]], path: str | Path) -> Path:
    output = ensure_parent(path)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), sort_keys=True) + "\n")
    return output


def write_parquet(frame: pd.DataFrame, path: str | Path) -> Path:
    output = ensure_parent(path)
    frame.to_parquet(output, index=False)
    return output


def read_parquet(path: str | Path) -> pd.DataFrame:
    return pd.read_parquet(path)

