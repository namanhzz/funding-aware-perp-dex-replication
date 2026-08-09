# Principal 198-day expanded-sample evaluation

Date: 2026-08-09

Seeds: `[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100]`

This run freezes the development-selected parameters and evaluates:
`['pure_as', 'pure_as', 'hjb_fd']`.

No parameter search is performed in this evaluation.

## Results

### ETH

| Policy | Net PnL | Delta vs default AS | 95% paired CI | Delta vs nearest-risk AS | 95% paired CI | Win vs named baseline | Inv. RMS | Turnover | Fees | Net bps/turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pure_as_default | 333166.46 | 0.00 | +/-0.00 | -6144.37 | +/-1101.15 | 0.11 | 5.7364 | 513469808.16 | 77020.47 | 6.489 |
| pure_as_risk_matched | 339310.83 | 6144.37 | +/-1101.15 | 0.00 | +/-0.00 | 0.00 | 3.7365 | 520836661.92 | 78125.50 | 6.515 |
| hjb_fd_selected | 339736.22 | 6569.76 | +/-1066.13 | 425.39 | +/-963.26 | 0.58 | 3.6321 | 520557441.07 | 78083.62 | 6.526 |

### BTC

| Policy | Net PnL | Delta vs default AS | 95% paired CI | Delta vs nearest-risk AS | 95% paired CI | Win vs named baseline | Inv. RMS | Turnover | Fees | Net bps/turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pure_as_default | 133666.95 | 0.00 | +/-0.00 | -39576.03 | +/-1608.68 | 0.00 | 0.2972 | 818782330.13 | 122817.35 | 1.633 |
| pure_as_risk_matched | 173242.98 | 39576.03 | +/-1608.68 | 0.00 | +/-0.00 | 0.00 | 0.1692 | 636463526.27 | 95469.53 | 2.722 |
| hjb_fd_selected | 139290.47 | 5623.52 | +/-1411.32 | -33952.51 | +/-1153.37 | 0.00 | 0.1840 | 833977477.63 | 125096.62 | 1.670 |

### SOL

| Policy | Net PnL | Delta vs default AS | 95% paired CI | Delta vs nearest-risk AS | 95% paired CI | Win vs named baseline | Inv. RMS | Turnover | Fees | Net bps/turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pure_as_default | 395830.25 | 0.00 | +/-0.00 | -106777.58 | +/-595.49 | 0.00 | 20.0173 | 522403019.20 | 78360.45 | 7.577 |
| pure_as_risk_matched | 502607.82 | 106777.58 | +/-595.49 | 0.00 | +/-0.00 | 0.00 | 77.5813 | 506180615.95 | 75927.09 | 9.929 |
| hjb_fd_selected | 506469.08 | 110638.84 | +/-655.10 | 3861.26 | +/-897.67 | 0.77 | 74.7455 | 498310829.07 | 74746.62 | 10.164 |

## Interpretation

Use the paired deltas and inventory RMS jointly. The nearest-risk
AS comparison is the primary economic contrast; default AS remains
a transparent reference. Weekly non-overlapping block statistics
are stored in the JSON for time-clustered inference.
