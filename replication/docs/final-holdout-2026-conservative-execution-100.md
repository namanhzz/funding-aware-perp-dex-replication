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
| pure_as_default | 40634.17 | 0.00 | +/-0.00 | -726.92 | +/-353.57 | 0.38 | 5.7970 | 54620283.32 | 8193.04 | 7.439 |
| pure_as_risk_matched | 41361.10 | 726.92 | +/-353.57 | 0.00 | +/-0.00 | 0.00 | 3.9398 | 55770618.81 | 8365.59 | 7.416 |
| hjb_fd_selected | 41672.55 | 1038.38 | +/-364.03 | 311.46 | +/-315.99 | 0.62 | 3.8024 | 55783990.41 | 8367.60 | 7.470 |

### BTC

| Policy | Net PnL | Delta vs default AS | 95% paired CI | Delta vs nearest-risk AS | 95% paired CI | Win vs named baseline | Inv. RMS | Turnover | Fees | Net bps/turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pure_as_default | 13785.73 | 0.00 | +/-0.00 | -5079.92 | +/-481.31 | 0.01 | 0.2984 | 90378772.71 | 13556.82 | 1.525 |
| pure_as_risk_matched | 18865.65 | 5079.92 | +/-481.31 | 0.00 | +/-0.00 | 0.00 | 0.1759 | 68391033.11 | 10258.65 | 2.758 |
| hjb_fd_selected | 14355.10 | 569.37 | +/-547.40 | -4510.55 | +/-372.68 | 0.00 | 0.1914 | 92747267.97 | 13912.09 | 1.548 |

### SOL

| Policy | Net PnL | Delta vs default AS | 95% paired CI | Delta vs nearest-risk AS | 95% paired CI | Win vs named baseline | Inv. RMS | Turnover | Fees | Net bps/turnover |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pure_as_default | 46402.16 | 0.00 | +/-0.00 | -14811.61 | +/-250.28 | 0.00 | 21.1545 | 60106881.43 | 9016.03 | 7.720 |
| pure_as_risk_matched | 61213.77 | 14811.61 | +/-250.28 | 0.00 | +/-0.00 | 0.00 | 82.0889 | 55711338.96 | 8356.70 | 10.987 |
| hjb_fd_selected | 61685.43 | 15283.27 | +/-220.67 | 471.66 | +/-306.41 | 0.64 | 78.7011 | 54734384.09 | 8210.16 | 11.270 |

## Interpretation

Use the paired deltas and inventory RMS jointly. The nearest-risk
AS comparison is the primary economic contrast; default AS remains
a transparent reference. Weekly non-overlapping block statistics
are stored in the JSON for time-clustered inference.
