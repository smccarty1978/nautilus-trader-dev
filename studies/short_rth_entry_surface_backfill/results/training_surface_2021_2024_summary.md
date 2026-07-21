# 2021-2024 Short-RTH Score-Independent Training Surface — Assembly

## Decision: `BACKFILL_TRAINING_SURFACE_READY`

Assembled from four independently validated per-year backfills. 2025 and 2026 are explicitly excluded from this dataset (reserved for development/sealed-OOS in the retrain study).

## Acceptance gate

| Check | Result |
|--|--|
| atlas_rebuilds_complete | PASS |
| zero_causal_critical_violations | PASS |
| all_expected_feature_columns_present | PASS |
| policy_a_labels_zero_errors | PASS |
| fill_time_rth_convention_preserved | PASS |
| schema_stable_across_years | PASS |
| no_unexplained_intraday_gaps_reviewed | PASS |

- Combined training-surface row count (established/RTH/valid-fill checkpoints, 2021-2024): **813,972**
- Feature schema hash (149 CENTER_FEATS+SEQUENCE_FEATS columns, sorted): `846ead21e7bc8d78...`
- Schema stable across all 4 years: True

## By-year summary

| Year | Surface rows | Seq-1 candidates | Labeled | Label errors | Causal violations | RTH-boundary divergence (ckpts) | Gaps >300s |
|--:|--:|--:|--:|--:|--:|--:|--:|
| 2021 | 212,241 | 1,762 | 1,762 | 0 | 0 | 121 | 379 |
| 2022 | 192,378 | 1,711 | 1,711 | 0 | 0 | 0 | 257 |
| 2023 | 204,742 | 1,732 | 1,732 | 0 | 0 | 0 | 257 |
| 2024 | 204,611 | 1,672 | 1,672 | 0 | 0 | 62 | 258 |

## Exit-reason distribution by year

- 2021: {'confirmation_timeout_exit': 872, 'preflip_policy_stop': 606, 'original_opposing_flip_exit': 279, 'original_stop_after_aligned_flip': 5}
- 2022: {'confirmation_timeout_exit': 798, 'preflip_policy_stop': 645, 'original_opposing_flip_exit': 261, 'original_stop_after_aligned_flip': 7}
- 2023: {'confirmation_timeout_exit': 822, 'preflip_policy_stop': 610, 'original_opposing_flip_exit': 292, 'original_stop_after_aligned_flip': 8}
- 2024: {'confirmation_timeout_exit': 848, 'preflip_policy_stop': 566, 'original_opposing_flip_exit': 251, 'original_stop_after_aligned_flip': 7}

## Exit-reason PnL by year (sanity check only, NOT a claimed result)

- 2021: {'confirmation_timeout_exit': 25385.0, 'original_opposing_flip_exit': 92730.0, 'original_stop_after_aligned_flip': -1015.3373589719558, 'preflip_policy_stop': -123718.50020586094}
- 2022: {'confirmation_timeout_exit': 75510.0, 'original_opposing_flip_exit': 126110.0, 'original_stop_after_aligned_flip': -2816.6498976882212, 'preflip_policy_stop': -225845.09454196197}
- 2023: {'confirmation_timeout_exit': 34310.0, 'original_opposing_flip_exit': 101975.0, 'original_stop_after_aligned_flip': -1609.603350173602, 'preflip_policy_stop': -139439.46410009067}
- 2024: {'confirmation_timeout_exit': 33740.0, 'original_opposing_flip_exit': 114630.0, 'original_stop_after_aligned_flip': -1390.4069806843472, 'preflip_policy_stop': -157065.9139860837}

## Suspicious-intraday-gap review (manual cross-check, not automated)

All `SUSPICIOUS_INTRADAY`-flagged gaps in 2022-2024 (7/8/8 respectively; 2021 predates the classifier and was reviewed via its own top-10 list, which showed none) were manually cross-checked against the US market holiday calendar: every one falls on or immediately before a recognized CME/Nasdaq holiday (MLK Day, Presidents Day, Memorial Day, Juneteenth, July 4th, Labor Day, Thanksgiving) with a ~5-hour midday-to-evening duration consistent with the known CME early-close holiday session convention. None were within-RTH data holes on an ordinary trading day. Classified as reviewed-and-explained, not unexplained.

## Not done

No model has been trained. No feature has been selected. No threshold has been tuned. 2025 and 2026 are not part of this dataset. Policy A labeling here is still the seq-1-per-regime feasibility check, not full-population labeling of every established/RTH/valid-fill checkpoint -- that full labeling pass is the next step before the retrain study can actually train anything.