from __future__ import annotations

from pathlib import Path

import pandas as pd
import typer

from perp_mm_funding.io import ensure_parent

app = typer.Typer(help="Generate data quality reports for clean parquet files.")


def _expected_count(time: pd.Series, freq: str) -> int:
    if time.empty:
        return 0
    index = pd.to_datetime(time, utc=True).sort_values()
    expected = pd.date_range(index.iloc[0].floor(freq), index.iloc[-1].floor(freq), freq=freq, tz="UTC")
    return len(expected)


def _duplicate_count(frame: pd.DataFrame, columns: list[str]) -> int:
    existing = [column for column in columns if column in frame.columns]
    if not existing:
        return 0
    return int(frame.duplicated(subset=existing).sum())


def funding_quality(frame: pd.DataFrame) -> dict[str, object]:
    expected = _expected_count(frame["time"], "1h")
    rows = len(frame)
    missing_ratio = 0.0 if expected == 0 else max(expected - rows, 0) / expected
    abs_funding = frame["funding_rate"].abs()
    return {
        "rows": rows,
        "start": str(frame["time"].min()),
        "end": str(frame["time"].max()),
        "expected_hourly_rows": expected,
        "missing_ratio": missing_ratio,
        "duplicate_timestamps": _duplicate_count(frame, ["time", "coin"]),
        "abs_gt_1pct_per_hour": int((abs_funding > 0.01).sum()),
        "abs_gt_4pct_per_hour": int((abs_funding > 0.04).sum()),
    }


def candle_quality(frame: pd.DataFrame) -> dict[str, object]:
    expected = _expected_count(frame["open_time"], "1min")
    rows = len(frame)
    missing_ratio = 0.0 if expected == 0 else max(expected - rows, 0) / expected
    return {
        "rows": rows,
        "start": str(frame["open_time"].min()),
        "end": str(frame["open_time"].max()),
        "expected_minute_rows": expected,
        "missing_ratio": missing_ratio,
        "duplicate_timestamps": _duplicate_count(frame, ["open_time", "coin", "interval"]),
        "non_positive_close": int((frame["close"] <= 0).sum()),
    }


@app.command()
def main(
    funding: Path = typer.Option(Path("data/clean/eth-funding-1h.parquet")),
    candles: Path | None = typer.Option(Path("data/clean/eth-perp-1m.parquet")),
    out: Path = typer.Option(Path("docs/data-quality.md")),
) -> None:
    lines = ["# Data Quality", ""]
    if funding.exists():
        report = funding_quality(pd.read_parquet(funding))
        lines.extend(["## Funding", ""])
        lines.extend([f"- {key}: {value}" for key, value in report.items()])
        lines.append("")
    else:
        lines.extend(["## Funding", "", f"- Missing file: `{funding}`", ""])

    if candles is not None and candles.exists():
        report = candle_quality(pd.read_parquet(candles))
        lines.extend(["## Candles", ""])
        lines.extend([f"- {key}: {value}" for key, value in report.items()])
        lines.append("")
    elif candles is not None:
        lines.extend(["## Candles", "", f"- Missing file: `{candles}`", ""])

    ensure_parent(out).write_text("\n".join(lines), encoding="utf-8")
    typer.echo(f"Wrote data quality report to {out}")


if __name__ == "__main__":
    app()

