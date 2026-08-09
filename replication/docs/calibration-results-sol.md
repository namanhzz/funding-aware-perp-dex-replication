# Calibration Results

- Funding file: `data\clean\sol-funding-1h.parquet`
- Train rows: 9072
- Test rows: 3888
- OU kappa: 0.30000534 per hour
- OU theta: 1.1521291e-05
- OU sigma_f: 2.9280161e-05 per sqrt hour
- OU half-life: 2.310 hours
- Train log-likelihood: 83110.226
- Test log-likelihood: 37305.912
- Funding-price innovation correlation rho: -0.015054878768563257
- Rho observations: 9687
- Price file: `data\clean\hyperliquid_l2_panel_1m.parquet`
- Price coin: SOL
- Calibration gate: pivot_to_ou_jumps

## Residual Diagnostics

- mean: 7.155418825946855e-07
- std: 1.0000551362958283
- skew: -58.812294734471614
- excess_kurtosis: 4816.642502305374
- jarque_bera_stat: 8764212932.390797
- jarque_bera_pvalue: 0.0

## Shifted CIR Robustness

- shift: 0.0020514118
- kappa: 0.3000099705767255
- theta: 0.002062933047553042
- sigma: 0.06686892042495383
- warning: Funding can be negative; this is a shifted-CIR robustness diagnostic, not a literal CIR fit.

## OU Jump Diagnostic

- threshold_z: 3.0
- jump_count: 24
- total_transitions: 9071
- jump_fraction: 0.0026457942894939916
- jump_intensity_per_hour: 0.002645794301971249
- jump_mean: -7.84439296563675e-05
- jump_std: 0.0004464835671455664
- non_jump_residual_std: 1.1102122509382753e-05

## OU Jump MLE

- transition_model: Bernoulli-normal jump approximation on OU transitions
- note: one-jump small-dt approximation, not a full multi-jump compound-Poisson expansion
- kappa: 0.3672372088080191
- theta: 1.1911799911455297e-05
- sigma: 1.279537798566174e-05
- jump_intensity_per_hour: 0.0015545001912765173
- jump_mean: -1.0162966226792173e-05
- jump_sigma: 0.0006473197117101652
- log_likelihood: 90260.01023651045
- ou_log_likelihood: 83110.22550471245
- likelihood_improvement: 7149.784731798005
- aic: -180508.0204730209
- bic: -180465.34344627723
- posterior_jump_count: 96.062164463036
- n_obs: 9072
- dt_mean_hours: 0.9999999952841166
- converged: True

## Decision

Residuals are heavy-tailed under Gaussian OU. Treat pure OU as the baseline mean-reversion state, but move the next modeling pass to OU+jumps before making paper-level claims.
