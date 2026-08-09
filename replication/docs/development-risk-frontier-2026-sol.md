# Post-result development risk-frontier diagnostic

This diagnostic was recorded after the initial final-window analysis.
Candidate policies and risk matches use development data only; final-window
PnL was not used to select a grid point or its AS match.
All selection results use data ending on 2025-12-31.

| Asset | Policy | Final equity | Inventory RMS | Turnover | Trading fees |
| --- | --- | ---: | ---: | ---: | ---: |
| SOL | baseline_as | 103175.64 | 19.9122 | 271371637.89 | 40705.75 |
| SOL | selected_hjb | 118852.40 | 17.4853 | 191891717.68 | 28783.76 |
| SOL | risk_matched_as | 95337.90 | 17.7168 | 263509230.75 | 39526.38 |

- SOL HJB inventory constraint feasible: `True`
