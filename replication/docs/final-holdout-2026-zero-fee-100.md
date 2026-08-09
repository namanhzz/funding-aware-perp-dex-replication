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
| pure_as_default | 90789.62 | 0.00 | +/-0.00 | -1838.86 | +/-433.39 | 0.17 | 5.7331 | 96255340.22 | 0.00 | 9.432 |
| pure_as_risk_matched | 92628.48 | 1838.86 | +/-433.39 | 0.00 | +/-0.00 | 0.00 | 3.7390 | 97642830.50 | 0.00 | 9.486 |
| hjb_fd_selected | 92290.46 | 1500.84 | +/-480.96 | -338.02 | +/-284.35 | 0.35 | 3.6400 | 97574308.07 | 0.00 | 9.458 |

### BTC

| Policy | Net PnL | Delta vs default AS | 95% paired CI | Delta vs nearest-risk AS | 95% paired CI | Win vs named baseline | Inv. RMS | Turnover | Fees | Net bps/turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pure_as_default | 56684.97 | 0.00 | +/-0.00 | -2842.04 | +/-570.57 | 0.19 | 0.2972 | 160804071.18 | 0.00 | 3.525 |
| pure_as_risk_matched | 59527.01 | 2842.04 | +/-570.57 | 0.00 | +/-0.00 | 0.00 | 0.1694 | 124965438.44 | 0.00 | 4.763 |
| hjb_fd_selected | 58119.65 | 1434.67 | +/-517.84 | -1407.37 | +/-355.49 | 0.18 | 0.1842 | 163739696.38 | 0.00 | 3.549 |

### SOL

| Policy | Net PnL | Delta vs default AS | 95% paired CI | Delta vs nearest-risk AS | 95% paired CI | Win vs named baseline | Inv. RMS | Turnover | Fees | Net bps/turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pure_as_default | 105075.18 | 0.00 | +/-0.00 | -23027.53 | +/-235.25 | 0.00 | 20.0184 | 101363789.35 | 0.00 | 10.366 |
| pure_as_risk_matched | 128102.71 | 23027.53 | +/-235.25 | 0.00 | +/-0.00 | 0.00 | 77.7669 | 98192520.78 | 0.00 | 13.046 |
| hjb_fd_selected | 128842.84 | 23767.66 | +/-210.24 | 740.14 | +/-273.29 | 0.69 | 74.8985 | 96671979.54 | 0.00 | 13.328 |

## Interpretation

Use the paired deltas and inventory RMS jointly. The nearest-risk
AS comparison is the primary economic contrast; default AS remains
a transparent reference. Weekly non-overlapping block statistics
are stored in the JSON for time-clustered inference.
