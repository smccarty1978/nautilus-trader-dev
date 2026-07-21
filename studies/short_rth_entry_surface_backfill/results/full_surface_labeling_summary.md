# Full-Surface Policy A Labeling — 2021-2024

## Decision: `FULL_SURFACE_LABELING_PASS`

Every row of the 2021-2024 established/RTH/valid-fill surface is labeled as an INDEPENDENT hypothetical short entry under unchanged Policy A. Rows overlap heavily within a regime by design -- this is a labeling surface, not a one-position strategy replay, and aggregate PnL below is NOT deployable strategy PnL.

## Acceptance gate

| Check | Result |
|--|--|
| seq1_parity_exact | PASS |
| all_rows_labeled_or_coded | PASS |
| label_errors_zero_or_explained | PASS |
| data_quality_all_clean | PASS |

- Total surface rows: 813,972
- Labeled: 813,972
- Censored (end-of-data): 0
- Label errors: 0

## seq-1 parity + aggregate reconciliation (acceptance gate)

| Year | seq-1 rows | Checked | Matches | Mismatches | Aggregate exact match |
|--:|--:|--:|--:|--:|--|
| 2021 | 1762 | 1762 | 1762 | 0 | True |
| 2022 | 1711 | 1711 | 1711 | 0 | True |
| 2023 | 1732 | 1732 | 1732 | 0 | True |
| 2024 | 1672 | 1672 | 1672 | 0 | True |

## Per-year detail

### 2021

- Surface rows: 212,241, labeled: 212,241, censored: 0, errors: 0
- Runtime: 34.4s
- Exit-reason counts: {'confirmation_timeout_exit': 92419, 'preflip_policy_stop': 67324, 'original_opposing_flip_exit': 49623, 'original_stop_after_aligned_flip': 2875}
- Exit-reason %: {'confirmation_timeout_exit': 43.54, 'preflip_policy_stop': 31.72, 'original_opposing_flip_exit': 23.38, 'original_stop_after_aligned_flip': 1.35}
- Exit-reason net PnL: {'confirmation_timeout_exit': 1502605.0, 'original_opposing_flip_exit': 10710870.0, 'original_stop_after_aligned_flip': -684313.5516079731, 'preflip_policy_stop': -13894736.772079915}
- pre_alignment_stop_rate: 0.3172, timeout_rate: 0.4354, post_alignment_stop_rate: 0.0135, opposing_flip_rate: 0.2338, alignment_rate: 0.2474
- Median time-to-alignment: 165.0s, median hold time: 301.0s
- Gross PnL sum: $-243,165, Net PnL sum: $-2,365,575 (mean $-11.15, std $296.30) -- **sanity/descriptive only, NOT deployable strategy PnL**
- MAE/MFE (ATR): median 0.891/0.818, p90 1.373/3.274
- Label-column NaN rates: {'exit_ts': 0.0, 'exit_px': 0.0, 'net_pnl': 0.0, 'mae_atr': 0.0, 'mfe_atr': 0.0}
- Data-quality checks: {'negative_hold_time': 0, 'exit_before_entry': 0, 'alignment_after_exit': 0, 'stop_px_wrong_side_for_short': 0, 'post_stop_px_wrong_side_for_short': 0, 'all_clean': True}
- Label-error reasons: {}
- Censor reasons: {}

### 2022

- Surface rows: 192,378, labeled: 192,378, censored: 0, errors: 0
- Runtime: 32.9s
- Exit-reason counts: {'confirmation_timeout_exit': 78214, 'preflip_policy_stop': 65804, 'original_opposing_flip_exit': 45984, 'original_stop_after_aligned_flip': 2376}
- Exit-reason %: {'confirmation_timeout_exit': 40.66, 'preflip_policy_stop': 34.21, 'original_opposing_flip_exit': 23.9, 'original_stop_after_aligned_flip': 1.24}
- Exit-reason net PnL: {'confirmation_timeout_exit': 4781165.0, 'original_opposing_flip_exit': 17628245.0, 'original_stop_after_aligned_flip': -1005306.7497575544, 'preflip_policy_stop': -22842169.462207586}
- pre_alignment_stop_rate: 0.3421, timeout_rate: 0.4066, post_alignment_stop_rate: 0.0124, opposing_flip_rate: 0.2390, alignment_rate: 0.2514
- Median time-to-alignment: 165.0s, median hold time: 301.0s
- Gross PnL sum: $485,714, Net PnL sum: $-1,438,066 (mean $-7.48, std $500.04) -- **sanity/descriptive only, NOT deployable strategy PnL**
- MAE/MFE (ATR): median 0.934/0.868, p90 1.371/3.307
- Label-column NaN rates: {'exit_ts': 0.0, 'exit_px': 0.0, 'net_pnl': 0.0, 'mae_atr': 0.0, 'mfe_atr': 0.0}
- Data-quality checks: {'negative_hold_time': 0, 'exit_before_entry': 0, 'alignment_after_exit': 0, 'stop_px_wrong_side_for_short': 0, 'post_stop_px_wrong_side_for_short': 0, 'all_clean': True}
- Label-error reasons: {}
- Censor reasons: {}

### 2023

- Surface rows: 204,742, labeled: 204,742, censored: 0, errors: 0
- Runtime: 33.6s
- Exit-reason counts: {'confirmation_timeout_exit': 85752, 'preflip_policy_stop': 70070, 'original_opposing_flip_exit': 46691, 'original_stop_after_aligned_flip': 2229}
- Exit-reason %: {'confirmation_timeout_exit': 41.88, 'preflip_policy_stop': 34.22, 'original_opposing_flip_exit': 22.8, 'original_stop_after_aligned_flip': 1.09}
- Exit-reason net PnL: {'confirmation_timeout_exit': 2238890.0, 'original_opposing_flip_exit': 11742345.0, 'original_stop_after_aligned_flip': -594840.7050583346, 'preflip_policy_stop': -16178357.321145708}
- pre_alignment_stop_rate: 0.3422, timeout_rate: 0.4188, post_alignment_stop_rate: 0.0109, opposing_flip_rate: 0.2280, alignment_rate: 0.2389
- Median time-to-alignment: 165.0s, median hold time: 301.0s
- Gross PnL sum: $-744,543, Net PnL sum: $-2,791,963 (mean $-13.64, std $323.16) -- **sanity/descriptive only, NOT deployable strategy PnL**
- MAE/MFE (ATR): median 0.934/0.846, p90 1.378/3.235
- Label-column NaN rates: {'exit_ts': 0.0, 'exit_px': 0.0, 'net_pnl': 0.0, 'mae_atr': 0.0, 'mfe_atr': 0.0}
- Data-quality checks: {'negative_hold_time': 0, 'exit_before_entry': 0, 'alignment_after_exit': 0, 'stop_px_wrong_side_for_short': 0, 'post_stop_px_wrong_side_for_short': 0, 'all_clean': True}
- Label-error reasons: {}
- Censor reasons: {}

### 2024

- Surface rows: 204,611, labeled: 204,611, censored: 0, errors: 0
- Runtime: 32.9s
- Exit-reason counts: {'confirmation_timeout_exit': 91819, 'preflip_policy_stop': 68973, 'original_opposing_flip_exit': 42338, 'original_stop_after_aligned_flip': 1481}
- Exit-reason %: {'confirmation_timeout_exit': 44.87, 'preflip_policy_stop': 33.71, 'original_opposing_flip_exit': 20.69, 'original_stop_after_aligned_flip': 0.72}
- Exit-reason net PnL: {'confirmation_timeout_exit': 2373105.0, 'original_opposing_flip_exit': 12740970.0, 'original_stop_after_aligned_flip': -440892.6809429751, 'preflip_policy_stop': -19029397.264078096}
- pre_alignment_stop_rate: 0.3371, timeout_rate: 0.4487, post_alignment_stop_rate: 0.0072, opposing_flip_rate: 0.2069, alignment_rate: 0.2142
- Median time-to-alignment: 170.0s, median hold time: 301.0s
- Gross PnL sum: $-2,310,105, Net PnL sum: $-4,356,215 (mean $-21.29, std $358.12) -- **sanity/descriptive only, NOT deployable strategy PnL**
- MAE/MFE (ATR): median 0.918/0.830, p90 1.361/3.286
- Label-column NaN rates: {'exit_ts': 0.0, 'exit_px': 0.0, 'net_pnl': 0.0, 'mae_atr': 0.0, 'mfe_atr': 0.0}
- Data-quality checks: {'negative_hold_time': 0, 'exit_before_entry': 0, 'alignment_after_exit': 0, 'stop_px_wrong_side_for_short': 0, 'post_stop_px_wrong_side_for_short': 0, 'all_clean': True}
- Label-error reasons: {}
- Censor reasons: {}

## Combined 2021-2024 totals

- Total rows: 813,972, labeled: 813,972, censored: 0, errors: 0
- Combined net PnL sum (descriptive only): $-10,951,820

## Polarity note

`avoid_pre_alignment_stop` = 1 when the row DID hit the pre-alignment stop (per explicit spec), i.e. 1 = 'this is a case to avoid'. This is the OPPOSITE polarity of the earlier seq-1 feasibility check's own `avoid_pre_alignment_stop` field (1 = did NOT hit the stop). Do not mix the two.

## Not done

No model trained. No feature selected. No threshold tuned. 2025/2026 not included. Full-row aggregate PnL is not a strategy result -- rows overlap heavily and this is not a one-position replay.