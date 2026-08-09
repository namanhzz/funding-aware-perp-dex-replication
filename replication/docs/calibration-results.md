# Calibration Results

- Funding file: `data\clean\eth-funding-18m.parquet`
- Train rows: 9072
- Test rows: 3888
- OU kappa: 0.12465694 per hour
- OU theta: 1.4271687e-05
- OU sigma_f: 1.1125287e-05 per sqrt hour
- OU half-life: 5.560 hours
- Train log-likelihood: 91148.938
- Test log-likelihood: 40567.490
- Funding-price innovation correlation rho: 0.0025861925237435244
- Rho observations: 9725
- Price file: `data\clean\hyperliquid_l2_panel_1m.parquet`
- Price coin: ETH
- Calibration gate: pivot_to_ou_jumps

## Residual Diagnostics

- mean: -2.373060639413481e-06
- std: 1.0000551138044507
- skew: -3.5473061052483894
- excess_kurtosis: 164.19965647362864
- jarque_bera_stat: 10198040.375974879
- jarque_bera_pvalue: 0.0

## Shifted CIR Robustness

- shift: 0.0003855854
- kappa: 0.12465816410704451
- theta: 0.00039985712237838807
- sigma: 0.03624113906391472
- warning: Funding can be negative; this is a shifted-CIR robustness diagnostic, not a literal CIR fit.

## OU Jump Diagnostic

- threshold_z: 3.0
- jump_count: 152
- total_transitions: 9071
- jump_fraction: 0.016756697166795283
- jump_intensity_per_hour: 0.016756697238120902
- jump_mean: 1.3935273727663375e-05
- jump_std: 5.68780864811484e-05
- non_jump_residual_std: 7.299745392571002e-06

## OU Jump MLE

- transition_model: Bernoulli-normal jump approximation on OU transitions
- note: one-jump small-dt approximation, not a full multi-jump compound-Poisson expansion
- kappa: 0.15470724629009558
- theta: 1.0657272556469107e-05
- sigma: 5.579875427235042e-06
- jump_intensity_per_hour: 0.02053612921841941
- jump_mean: 6.561977256474081e-06
- jump_sigma: 2.661456391904844e-05
- log_likelihood: 93965.27487744328
- ou_log_likelihood: 91148.93758114455
- likelihood_improvement: 2816.337296298734
- aic: -187918.54975488657
- bic: -187875.8727281429
- posterior_jump_count: 716.4677821302179
- n_obs: 9072
- dt_mean_hours: 0.9999999957434559
- converged: True

## Decision

Residuals are heavy-tailed under Gaussian OU. Treat pure OU as the baseline mean-reversion state, but move the next modeling pass to OU+jumps before making paper-level claims.
