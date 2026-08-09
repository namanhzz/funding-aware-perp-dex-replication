from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import typer

from perp_mm_funding.io import ensure_parent


app = typer.Typer(help="Build a causal one-minute intrabar price-path sensitivity.")


def build_causal_intrabar_bridge(
    hyperliquid_candles: pd.DataFrame,
    reference_candles: pd.DataFrame,
) -> pd.DataFrame:
    """Rebase one-minute reference returns inside completed venue candles.

    Each 15-minute block starts from the contemporaneously observable
    Hyperliquid open and follows the one-minute reference-market return path.
    The final minute is replaced by the completed Hyperliquid close when that
    close becomes observable. Earlier minutes never use the future venue close.
    """

    required = {"open_time", "close_time", "open", "close"}
    for name, frame in {
        "hyperliquid_candles": hyperliquid_candles,
        "reference_candles": reference_candles,
    }.items():
        missing = sorted(required.difference(frame.columns))
        if missing:
            raise ValueError(f"{name} is missing columns: {missing}")

    venue = hyperliquid_candles.copy()
    reference = reference_candles.copy()
    for frame in (venue, reference):
        frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
        frame["close_time"] = pd.to_datetime(frame["close_time"], utc=True)
        frame.sort_values("open_time", inplace=True)

    reference_times_ns = reference["open_time"].astype("datetime64[ns, UTC]").array.asi8

    rows: list[dict[str, object]] = []
    for candle in venue.itertuples(index=False):
        block_start = pd.Timestamp(candle.open_time).floor("1min")
        block_end = pd.Timestamp(candle.close_time).ceil("1min")
        left = int(np.searchsorted(reference_times_ns, block_start.value, side="left"))
        right = int(np.searchsorted(reference_times_ns, block_end.value, side="left"))
        block = reference.iloc[left:right]
        expected = int((block_end - block_start).total_seconds() // 60)
        if len(block) != expected or expected <= 0:
            raise ValueError(
                f"Reference path has {len(block)}/{expected} rows for "
                f"{block_start.isoformat()}--{block_end.isoformat()}"
            )

        venue_open = float(candle.open)
        reference_open = float(block.iloc[0]["open"])
        if venue_open <= 0.0 or reference_open <= 0.0:
            raise ValueError("Bridge prices must be positive")

        previous_close = venue_open
        for minute_index, reference_row in enumerate(block.itertuples(index=False), start=1):
            proxy_close = venue_open * float(reference_row.close) / reference_open
            bridge_close = float(candle.close) if minute_index == expected else proxy_close
            bridge_open = previous_close
            rows.append(
                {
                    "open_time": pd.Timestamp(reference_row.open_time),
                    "close_time": pd.Timestamp(reference_row.close_time),
                    "coin": str(candle.coin),
                    "interval": "1m_bridge",
                    "open": bridge_open,
                    "high": max(bridge_open, bridge_close),
                    "low": min(bridge_open, bridge_close),
                    "close": bridge_close,
                    "volume": 0.0,
                    "n_trades": 0,
                }
            )
            previous_close = bridge_close

    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("No bridge rows were produced")
    return result.drop_duplicates(subset=["open_time", "coin"], keep="last").reset_index(drop=True)


@app.command()
def main(
    hyperliquid_path: Path = typer.Option(..., exists=True, dir_okay=False),
    reference_path: Path = typer.Option(..., exists=True, dir_okay=False),
    out: Path = typer.Option(..., dir_okay=False),
) -> None:
    bridge = build_causal_intrabar_bridge(
        pd.read_parquet(hyperliquid_path),
        pd.read_parquet(reference_path),
    )
    ensure_parent(out)
    bridge.to_parquet(out, index=False)
    typer.echo(f"Wrote {len(bridge)} causal one-minute bridge rows to {out}")


if __name__ == "__main__":
    app()
