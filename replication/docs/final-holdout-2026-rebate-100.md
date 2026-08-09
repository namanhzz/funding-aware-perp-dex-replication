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
| pure_as_default | 91752.17 | 0.00 | +/-0.00 | -1852.73 | +/-433.42 | 0.17 | 5.7331 | 96255340.22 | -962.55 | 9.532 |
| pure_as_risk_matched | 93604.90 | 1852.73 | +/-433.42 | 0.00 | +/-0.00 | 0.00 | 3.7390 | 97642830.50 | -976.43 | 9.586 |
| hjb_fd_selected | 93266.20 | 1514.03 | +/-480.96 | -338.70 | +/-284.37 | 0.35 | 3.6400 | 97574308.07 | -975.74 | 9.558 |

### BTC

| Policy | Net PnL | Delta vs default AS | 95% paired CI | Delta vs nearest-risk AS | 95% paired CI | Win vs named baseline | Inv. RMS | Turnover | Fees | Net bps/turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pure_as_default | 58293.01 | 0.00 | +/-0.00 | -2483.65 | +/-570.45 | 0.23 | 0.2972 | 160804071.18 | -1608.04 | 3.625 |
| pure_as_risk_matched | 60776.67 | 2483.65 | +/-570.45 | 0.00 | +/-0.00 | 0.00 | 0.1694 | 124965438.44 | -1249.65 | 4.863 |
| hjb_fd_selected | 59757.04 | 1464.03 | +/-517.77 | -1019.62 | +/-355.48 | 0.25 | 0.1842 | 163739696.38 | -1637.40 | 3.649 |

### SOL

| Policy | Net PnL | Delta vs default AS | 95% paired CI | Delta vs nearest-risk AS | 95% paired CI | Win vs named baseline | Inv. RMS | Turnover | Fees | Net bps/turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pure_as_default | 106088.82 | 0.00 | +/-0.00 | -22995.81 | +/-235.36 | 0.00 | 20.0184 | 101363789.35 | -1013.64 | 10.466 |
| pure_as_risk_matched | 129084.63 | 22995.81 | +/-235.36 | 0.00 | +/-0.00 | 0.00 | 77.7669 | 98192520.78 | -981.93 | 13.146 |
| hjb_fd_selected | 129809.56 | 23720.75 | +/-210.35 | 724.93 | +/-273.31 | 0.69 | 74.8985 | 96671979.54 | -966.72 | 13.428 |

## Interpretation

Use the paired deltas and inventory RMS jointly. The nearest-risk
AS comparison is the primary economic contrast; default AS remains
a transparent reference. Weekly non-overlapping block statistics
are stored in the JSON for time-clustered inference.
