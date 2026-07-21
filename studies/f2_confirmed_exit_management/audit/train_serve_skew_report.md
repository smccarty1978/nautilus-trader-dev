# F2_CONFIRMED Train/Serve (Old vs Corrected) Skew Audit

Built: 2026-07-11 16:34:47.015128+00:00


## entry_price_minus_flip_close_atr (property of the corrected atlas's own entries, no old-atlas dependency; NOTE for F2_CONFIRMED this measures entry_px against the ORIGINAL flip bar's close, one bar before the bar+1 confirmation that actually triggered entry -- expect a larger, systematic gap than ALL_FLIPS since a full confirmation bar's worth of price movement has occurred between flip and entry)

count    18145.000000
mean         0.540849
std          0.475308
min         -2.140465
25%          0.214945
50%          0.443772
75%          0.764552
max          5.735954



## match_mode=backward

- trades matched: 18,141 / 18,177 (99.8%)

- n_matched: 90705

- current_pnl_old_minus_corrected_atr_median: 0.4505929583407138

- current_pnl_old_minus_corrected_atr_p90: 1.2679113048274342

- current_pnl_old_minus_corrected_atr_max: 44.57474280660256

- mfe_old_minus_corrected_atr_median: -0.18630632861486562

- mfe_old_minus_corrected_atr_p90: 5.549566296809477

- mfe_old_minus_corrected_atr_max: 97.74052528059097

- giveback_old_minus_corrected_atr_median: -0.42382777272754363

- giveback_old_minus_corrected_atr_p90: 6.225441700188104

- giveback_old_minus_corrected_atr_max: 87.30473897441829


(backward-only match is causally conservative but biases MFE/giveback comparisons downward by construction -- see nearest-match figures above for an unbiased skew estimate; see studies/_shared_exit_mgmt/skew_audit.py docstring)


## match_mode=nearest

- trades matched: 18,141 / 18,177 (99.8%)

- n_matched: 90705

- current_pnl_old_minus_corrected_atr_median: 0.4436183559021937

- current_pnl_old_minus_corrected_atr_p90: 1.251127828562864

- current_pnl_old_minus_corrected_atr_max: 44.57474280660256

- mfe_old_minus_corrected_atr_median: -0.16346324693411218

- mfe_old_minus_corrected_atr_p90: 5.570804850544441

- mfe_old_minus_corrected_atr_max: 97.74052528059097

- giveback_old_minus_corrected_atr_median: -0.33761199306284984

- giveback_old_minus_corrected_atr_p90: 6.247089183078103

- giveback_old_minus_corrected_atr_max: 87.30473897441829
