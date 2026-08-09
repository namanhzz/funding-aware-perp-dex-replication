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
| pure_as_default | 76351.32 | 0.00 | +/-0.00 | -1630.73 | +/-432.84 | 0.19 | 5.7331 | 96255340.22 | 14438.30 | 7.932 |
| pure_as_risk_matched | 77982.05 | 1630.73 | +/-432.84 | 0.00 | +/-0.00 | 0.00 | 3.7390 | 97642830.50 | 14646.42 | 7.986 |
| hjb_fd_selected | 77654.31 | 1302.99 | +/-481.02 | -327.74 | +/-284.10 | 0.37 | 3.6400 | 97574308.07 | 14636.15 | 7.958 |

### BTC

| Policy | Net PnL | Delta vs default AS | 95% paired CI | Delta vs nearest-risk AS | 95% paired CI | Win vs named baseline | Inv. RMS | Turnover | Fees | Net bps/turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pure_as_default | 32564.36 | 0.00 | +/-0.00 | -8217.83 | +/-572.61 | 0.00 | 0.2972 | 160804071.18 | 24120.61 | 2.025 |
| pure_as_risk_matched | 40782.20 | 8217.83 | +/-572.61 | 0.00 | +/-0.00 | 0.00 | 0.1694 | 124965438.44 | 18744.82 | 3.263 |
| hjb_fd_selected | 33558.69 | 994.33 | +/-518.94 | -7223.50 | +/-355.80 | 0.00 | 0.1842 | 163739696.38 | 24560.95 | 2.049 |

### SOL

| Policy | Net PnL | Delta vs default AS | 95% paired CI | Delta vs nearest-risk AS | 95% paired CI | Win vs named baseline | Inv. RMS | Turnover | Fees | Net bps/turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pure_as_default | 89870.61 | 0.00 | +/-0.00 | -23503.22 | +/-233.58 | 0.00 | 20.0184 | 101363789.35 | 15204.57 | 8.866 |
| pure_as_risk_matched | 113373.83 | 23503.22 | +/-233.58 | 0.00 | +/-0.00 | 0.00 | 77.7669 | 98192520.78 | 14728.88 | 11.546 |
| hjb_fd_selected | 114342.05 | 24471.44 | +/-208.54 | 968.22 | +/-272.95 | 0.75 | 74.8985 | 96671979.54 | 14500.80 | 11.828 |

## Interpretation

Use the paired deltas and inventory RMS jointly. The nearest-risk
AS comparison is the primary economic contrast; default AS remains
a transparent reference. Weekly non-overlapping block statistics
are stored in the JSON for time-clustered inference.
