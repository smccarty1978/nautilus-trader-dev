# ALL_FLIPS Train/Serve (Old vs Corrected) Skew Audit

Built: 2026-07-11 16:35:21.633658+00:00


## entry_price_minus_flip_close_atr (property of the corrected atlas's own entries, no old-atlas dependency)

count    39531.000000
mean        -0.005030
std          0.198259
min         -8.076509
25%         -0.104510
50%          0.000000
75%          0.089340
max          8.511852



## match_mode=backward

- trades matched: 39,524 / 39,608 (99.8%)

- n_matched: 157789

- current_pnl_old_minus_corrected_atr_median: 2.238015855970943e-09

- current_pnl_old_minus_corrected_atr_p90: 0.41021330711543874

- current_pnl_old_minus_corrected_atr_max: 44.93217231099709

- mfe_old_minus_corrected_atr_median: -0.2066643823733558

- mfe_old_minus_corrected_atr_p90: 5.6892778968197515

- mfe_old_minus_corrected_atr_max: 96.48400596296402

- giveback_old_minus_corrected_atr_median: -0.2798187936431027

- giveback_old_minus_corrected_atr_p90: 5.670499142324116

- giveback_old_minus_corrected_atr_max: 87.07707688793147


(backward-only match is causally conservative but biases MFE/giveback comparisons downward by construction -- see nearest-match figures above for an unbiased skew estimate; see studies/_shared_exit_mgmt/skew_audit.py docstring)


## match_mode=nearest

- trades matched: 39,524 / 39,608 (99.8%)

- n_matched: 197620

- current_pnl_old_minus_corrected_atr_median: -1.3100728002424233e-09

- current_pnl_old_minus_corrected_atr_p90: 0.4618616934952245

- current_pnl_old_minus_corrected_atr_max: 44.93217231099709

- mfe_old_minus_corrected_atr_median: -0.14133958015543674

- mfe_old_minus_corrected_atr_p90: 4.795636407760826

- mfe_old_minus_corrected_atr_max: 96.48400596296402

- giveback_old_minus_corrected_atr_median: -0.12399954222655707

- giveback_old_minus_corrected_atr_p90: 4.792382668741154

- giveback_old_minus_corrected_atr_max: 87.07707688793147
