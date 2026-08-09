# Final 2026 holdout

Date: 2026-08-09

Seeds: `[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100]`

This run freezes the development-selected parameters and evaluates:
`['pure_as', 'pure_as', 'hjb_fd']`.

No parameter search is performed on the final holdout.

## Results

### ETH

| Policy | Net PnL | Delta vs default AS | 95% paired CI | Delta vs nearest-risk AS | 95% paired CI | Win vs named baseline | Inv. RMS | Turnover | Fees | Net bps/turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pure_as_default | 80753.06 | 0.00 | +/-0.00 | -1711.22 | +/-386.38 | 0.22 | 5.6792 | 110810640.31 | 16621.60 | 7.287 |
| pure_as_risk_matched | 82464.27 | 1711.22 | +/-386.38 | 0.00 | +/-0.00 | 0.00 | 3.5643 | 112013049.53 | 16801.96 | 7.362 |
| hjb_fd_selected | 82695.21 | 1942.16 | +/-386.50 | 230.94 | +/-305.50 | 0.58 | 3.5728 | 111978384.14 | 16796.76 | 7.385 |

### BTC

| Policy | Net PnL | Delta vs default AS | 95% paired CI | Delta vs nearest-risk AS | 95% paired CI | Win vs named baseline | Inv. RMS | Turnover | Fees | Net bps/turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pure_as_default | 31548.52 | 0.00 | +/-0.00 | -10623.23 | +/-533.00 | 0.00 | 0.2960 | 191030455.98 | 28654.57 | 1.651 |
| pure_as_risk_matched | 42171.75 | 10623.23 | +/-533.00 | 0.00 | +/-0.00 | 0.00 | 0.1585 | 145695815.29 | 21854.37 | 2.894 |
| hjb_fd_selected | 32628.09 | 1079.57 | +/-532.54 | -9543.67 | +/-323.02 | 0.00 | 0.1801 | 193905419.34 | 29085.81 | 1.683 |

### SOL

| Policy | Net PnL | Delta vs default AS | 95% paired CI | Delta vs nearest-risk AS | 95% paired CI | Win vs named baseline | Inv. RMS | Turnover | Fees | Net bps/turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pure_as_default | 102420.28 | 0.00 | +/-0.00 | -28105.53 | +/-209.23 | 0.00 | 18.6681 | 124391000.93 | 18658.65 | 8.234 |
| pure_as_risk_matched | 130525.81 | 28105.53 | +/-209.23 | 0.00 | +/-0.00 | 0.00 | 71.9374 | 123272403.60 | 18490.86 | 10.588 |
| hjb_fd_selected | 131803.69 | 29383.42 | +/-228.67 | 1277.89 | +/-246.80 | 0.83 | 74.7983 | 121624004.25 | 18243.60 | 10.837 |

## Interpretation

Use the paired deltas and inventory RMS jointly. The nearest-risk
AS comparison is the primary economic contrast; default AS remains
a transparent reference. Weekly non-overlapping block statistics
are stored in the JSON for time-clustered inference.
