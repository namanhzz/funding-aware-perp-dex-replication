# Calibration Results

- Funding file: `data\clean\btc-funding-1h.parquet`
- Train rows: 9072
- Test rows: 3888
- OU kappa: 0.17026175 per hour
- OU theta: 1.6094146e-05
- OU sigma_f: 1.1392421e-05 per sqrt hour
- OU half-life: 4.071 hours
- Train log-likelihood: 91130.393
- Test log-likelihood: 40540.216
- Funding-price innovation correlation rho: 0.027761162107067756
- Rho observations: 9687
- Price file: `data\clean\hyperliquid_l2_panel_1m.parquet`
- Price coin: BTC
- Calibration gate: pivot_to_ou_jumps

## Residual Diagnostics

- mean: 9.811558964518107e-08
- std: 1.0000551223919194
- skew: 3.964622223447647
- excess_kurtosis: 105.47740200491684
- jarque_bera_stat: 4224037.915955997
- jarque_bera_pvalue: 0.0

## Shifted CIR Robustness

- shift: 9.099600000000001e-05
- kappa: 0.17026235852358051
- theta: 0.00010709014626125329
- sigma: 0.0029815870959747012
- warning: Funding can be negative; this is a shifted-CIR robustness diagnostic, not a literal CIR fit.

## OU Jump Diagnostic

- threshold_z: 3.0
- jump_count: 147
- total_transitions: 9071
- jump_fraction: 0.0162054900231507
- jump_intensity_per_hour: 0.0162054900995739
- jump_mean: 1.8970503856806703e-05
- jump_std: 6.284345475804055e-05
- non_jump_residual_std: 6.416921605401953e-06

## OU Jump MLE

- transition_model: Bernoulli-normal jump approximation on OU transitions
- note: one-jump small-dt approximation, not a full multi-jump compound-Poisson expansion
- kappa: 0.22536699408228844
- theta: 1.2270632859925183e-05
- sigma: 4.380003322571833e-06
- jump_intensity_per_hour: 0.012354930166891383
- jump_mean: 9.369486720696361e-06
- jump_sigma: 3.5931707248715056e-05
- log_likelihood: 95547.4235465426
- ou_log_likelihood: 91130.39263964805
- likelihood_improvement: 4417.03090689455
- aic: -191082.8470930852
- bic: -191040.17006634152
- posterior_jump_count: 746.4880279931359
- n_obs: 9072
- dt_mean_hours: 0.9999999952841166
- converged: True

## Decision

Residuals are heavy-tailed under Gaussian OU. Treat pure OU as the baseline mean-reversion state, but move the next modeling pass to OU+jumps before making paper-level claims.
