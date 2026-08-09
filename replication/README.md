# Replication materials

This folder is the self-contained public replication package for
“Funding-aware optimal market making on a perpetual DEX.” It contains the
tracked empirical inputs needed for the reported evaluation, the model and
simulation code, frozen configurations, tests, and complete seed-level output
files.

## Environment

Python 3.10 or later is recommended. From this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Run the test suite before replication:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Principal 198-day evaluation

The principal sample spans 15 January–31 July 2026. Policies and nearest-risk
Avellaneda–Stoikov matches were fixed from pre-2026 development selection. The
100-seed cross-asset run is:

```powershell
.\.venv\Scripts\python.exe -m perp_mm_funding.run_final_robustness `
  --config configs\extended_window_2026_100.yaml `
  --out-json results\extended-window-2026-100.json `
  --out-md docs\extended-window-2026-100.md --jobs 8
```

The disclosed post-result SOL risk-frontier diagnostic is:

```powershell
.\.venv\Scripts\python.exe -m perp_mm_funding.run_final_robustness `
  --config configs\extended_window_2026_sol_risk_frontier_100.yaml `
  --out-json results\extended-window-2026-sol-risk-frontier-100.json `
  --out-md docs\extended-window-2026-sol-risk-frontier-100.md --jobs 8

.\.venv\Scripts\python.exe -m perp_mm_funding.summarize_risk_frontier `
  --results-path results\extended-window-2026-sol-risk-frontier-100.json `
  --out-json results\extended-window-2026-sol-risk-frontier-summary.json `
  --out-md docs\extended-window-2026-sol-risk-frontier-summary.md
```

## Venue-native validation and sensitivities

The main venue-native validation uses 100 paired seeds and official
Hyperliquid 15-minute candles and hourly funding over 18 June–31 July 2026:

```powershell
.\.venv\Scripts\python.exe -m perp_mm_funding.run_final_robustness `
  --config configs\final_holdout_2026_100.yaml `
  --out-json results\final-holdout-2026-100.json `
  --out-md docs\final-holdout-2026-100.md --jobs 8
```

The other `final_holdout_2026_*_100.yaml` files run the reported fee,
fill-calibration, conservative-execution, intrabar-path, continuous-funding,
and SOL-frontier sensitivities with the same command pattern.

## Data provenance

- Official Hyperliquid candles and funding:
  `https://api.hyperliquid.xyz/info`.
- Hyperliquid historical-data documentation:
  `https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data`.
- Binance USD-M mark-price candles used for causal intrabar bridges:
  `https://fapi.binance.com/fapi/v1/markPriceKlines`.

Principal one-minute paths follow concurrent Binance mark-price returns within
each hour and are anchored exactly to the completed official Hyperliquid hourly
close. The venue-native validation instead uses official Hyperliquid 15-minute
candles directly. The tracked Parquet files define the empirical inputs used in
the study.

The larger pre-2026 requester-pays Hyperliquid L2 archive is not duplicated.
It is needed only to reconstruct the already-tracked fill-intensity calibration
products, not to rerun the frozen evaluation configurations.

## Integrity manifest

`data/replication/manifest.json` records SHA-256 hashes, byte sizes, schemas,
row counts, and time ranges for every canonical data, configuration, and result
file. Rebuild and verify it with:

```powershell
.\.venv\Scripts\python.exe -m perp_mm_funding.build_replication_manifest
```

The manifest source list is `configs/replication_manifest.yaml`.
