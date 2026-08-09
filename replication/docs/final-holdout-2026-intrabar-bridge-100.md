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
| pure_as_default | 76340.81 | 0.00 | +/-0.00 | -1660.94 | +/-419.55 | 0.21 | 5.7331 | 96275287.47 | 14441.29 | 7.929 |
| pure_as_risk_matched | 78001.75 | 1660.94 | +/-419.55 | 0.00 | +/-0.00 | 0.00 | 3.7391 | 97662744.97 | 14649.41 | 7.987 |
| hjb_fd_selected | 77717.91 | 1377.10 | +/-453.94 | -283.84 | +/-299.21 | 0.40 | 3.6404 | 97595390.30 | 14639.31 | 7.963 |

### BTC

| Policy | Net PnL | Delta vs default AS | 95% paired CI | Delta vs nearest-risk AS | 95% paired CI | Win vs named baseline | Inv. RMS | Turnover | Fees | Net bps/turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pure_as_default | 32545.12 | 0.00 | +/-0.00 | -8393.24 | +/-567.15 | 0.00 | 0.2972 | 160837090.15 | 24125.56 | 2.023 |
| pure_as_risk_matched | 40938.35 | 8393.24 | +/-567.15 | 0.00 | +/-0.00 | 0.00 | 0.1694 | 124990950.70 | 18748.64 | 3.275 |
| hjb_fd_selected | 33528.97 | 983.85 | +/-538.28 | -7409.39 | +/-348.73 | 0.00 | 0.1842 | 163775198.74 | 24566.28 | 2.047 |

### SOL

| Policy | Net PnL | Delta vs default AS | 95% paired CI | Delta vs nearest-risk AS | 95% paired CI | Win vs named baseline | Inv. RMS | Turnover | Fees | Net bps/turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pure_as_default | 89943.10 | 0.00 | +/-0.00 | -23474.79 | +/-223.40 | 0.00 | 20.0182 | 101382512.18 | 15207.38 | 8.872 |
| pure_as_risk_matched | 113417.89 | 23474.79 | +/-223.40 | 0.00 | +/-0.00 | 0.00 | 77.7652 | 98210962.32 | 14731.64 | 11.548 |
| hjb_fd_selected | 114365.53 | 24422.43 | +/-236.48 | 947.64 | +/-262.76 | 0.79 | 74.8901 | 96690188.81 | 14503.53 | 11.828 |

## Interpretation

Use the paired deltas and inventory RMS jointly. The nearest-risk
AS comparison is the primary economic contrast; default AS remains
a transparent reference. Weekly non-overlapping block statistics
are stored in the JSON for time-clustered inference.
