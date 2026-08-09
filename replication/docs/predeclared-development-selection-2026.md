# Frozen development-only selection

The final design and grids were frozen before the 2026 holdout was evaluated.
The AS grid was expanded using development results only because its initial
range did not bracket the selected HJB inventory RMS; the design file records
this amendment.
All selection results use data ending on 2025-12-31.

| Asset | Policy | Final equity | Inventory RMS | Turnover | Trading fees |
| --- | --- | ---: | ---: | ---: | ---: |
| ETH | baseline_as | 84102.71 | 5.7169 | 242899989.03 | 36435.00 |
| ETH | selected_hjb | 91108.74 | 3.6143 | 245946577.60 | 36891.99 |
| ETH | risk_matched_as | 92142.13 | 3.7028 | 246162800.53 | 36924.42 |

- ETH HJB inventory constraint feasible: `True`
| BTC | baseline_as | 28868.42 | 0.2968 | 335235290.41 | 50285.29 |
| BTC | selected_hjb | 29536.43 | 0.1846 | 341118843.84 | 51167.83 |
| BTC | risk_matched_as | 42902.81 | 0.1682 | 261815467.39 | 39272.32 |

- BTC HJB inventory constraint feasible: `True`
| SOL | baseline_as | 103175.64 | 19.9122 | 271371637.89 | 40705.75 |
| SOL | selected_hjb | 137549.17 | 74.6288 | 259830304.74 | 38974.55 |
| SOL | risk_matched_as | 134460.93 | 77.2739 | 263865196.42 | 39579.78 |

- SOL HJB inventory constraint feasible: `False`
