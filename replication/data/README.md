# Replication data

The tracked Parquet files under `data/clean/` are the compact public inputs
for the principal evaluation and venue-native validation. The validation files contain official Hyperliquid
`candleSnapshot` observations at 15-minute frequency and `fundingHistory`
observations at hourly frequency for ETH, BTC, and SOL for the requested window
2026-06-18 00:00 UTC through 2026-07-31 23:59 UTC.

The candle files contain 4,217 rows for ETH and BTC (starting 01:45 UTC) and
4,216 for SOL (starting 02:00 UTC); all end at 23:45 UTC on 31 July. Each
funding file contains the full 1,056 hourly rows. Exact schemas, timestamp
bounds, byte sizes, and SHA-256 checksums are recorded in
`data/replication/manifest.json`.

The API inputs can be downloaded again with start timestamp `1781740800000`
and end timestamp `1785542399999`. For example:

```powershell
python -m perp_mm_funding.fetch_data candles `
  --coin ETH --interval 15m `
  --start-ms 1781740800000 --end-ms 1785542399999 `
  --out data/clean/eth-hyperliquid-candles-15m-final-20260618-20260731.parquet

python -m perp_mm_funding.fetch_data funding `
  --coin ETH `
  --start-ms 1781740800000 --end-ms 1785542399999 `
  --out data/clean/eth-funding-1h-final-20260618-20260731.parquet
```

Replace `ETH` and the output stem with `BTC` or `SOL` for the other assets.
Minor differences are possible if the venue later revises historical API
records; the tracked files and manifest define the study inputs.

The public Hyperliquid endpoint did not return venue-native one-minute candles
for this retrospective window. The intrabar sensitivity therefore also tracks
63,360 public Binance USD-M one-minute mark-price candles per asset and causal
bridge files built from them. Each bridge block starts from the observable
Hyperliquid open, follows concurrent Binance returns, and inserts the official
Hyperliquid close only at the boundary minute. It is an intrabar path
sensitivity, not Hyperliquid execution data. Rebuild one asset with:

```powershell
python -m perp_mm_funding.fetch_data binance-mark-candles `
  --symbol ETHUSDT --interval 1m `
  --start-ms 1781740800000 --end-ms 1785542399999 `
  --out data/clean/eth-binance-mark-candles-1m-final-20260618-20260731.parquet

python -m perp_mm_funding.build_intrabar_bridge `
  --hyperliquid-path data/clean/eth-hyperliquid-candles-15m-final-20260618-20260731.parquet `
  --reference-path data/clean/eth-binance-mark-candles-1m-final-20260618-20260731.parquet `
  --out data/clean/eth-causal-intrabar-bridge-1m-final-20260618-20260731.parquet
```

Replace `ETH`/`ETHUSDT` with the corresponding BTC or SOL symbols for the other
assets.

## Principal 198-day evaluation

The principal expanded-sample evaluation covers 15 January--31 July 2026 (198 complete
days). For each asset it combines 4,752 official Hyperliquid hourly candles,
4,752 official hourly funding observations, and 285,120 Binance USD-M
one-minute mark-price candles. The causal bridge follows within-hour Binance
returns from each observable Hyperliquid open and is anchored exactly to the
completed Hyperliquid close at every hourly boundary. All 4,752 anchors per
asset have zero close-price discrepancy. The hourly anchors are used because
the public endpoint no longer returns older 15-minute candles.

The horizon was expanded after the venue-native validation was inspected. All
policies and AS risk matches remain fixed from development-only selection, so
this is the paper's main expanded-sample evidence rather than a prospective
confirmatory holdout.

The much larger pre-2026 L2 archive is not duplicated here. It is used only to
construct the tracked fill-intensity curves and requires requester-pays archive
credentials. Reconstruction instructions are in the repository root README.
