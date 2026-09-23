# Bucket ↔ score reconciliation (validation block)

**Bucket rule (frozen before any fit):** taken from the atlas's 2023 nomination tests
(`t2023_E_nomination_tests.parquet`, sha pinned in the contract):
- `tested`, estimate > 0;
- n_child ≥ 150 and n_rest ≥ 150;
- metric `is_win` or `reach_fav_2p00`;
- top 10 per metric by p-value, then deduplicated → **15 buckets**.

**Why the n_rest gate exists:** the first draft picked 7 degenerate `rest_mean = 0` contrasts. These are the
atlas's own documented spurious p ≈ 0 cases, where the rest-of-parent is nearly empty. The gate was added
before any model was fit.

**Disclosure:** the atlas selected these buckets on full-year 2023, which includes the dark final 20%. All
numbers below are from the validation block only.

| id | parent | bucket | atlas 2023 lift | val N | val +2A (parent) | val win (parent) | val +3A | val 5m-align | L3 score − parent |
|---|---|---|---|---|---|---|---|---|---|
| B00 | all | mtf_state = L/S/S/S | win +5.1 pp | 222 | 36.0 (36.3) | 35.6 (33.2) | 22.5 | 32.2 | −0.008 |
| B01 | S/L/L/L | sd_cur_mfe_5m_A ≥ 2 | win +9.3 | 33 | 42.4 (34.0) | 36.4 (28.6) | 33.3 | 42.4 | +0.010 |
| B02 | S/L/L/L | sd_cur_mfe_15m_A ≥ 2 | win +9.9 | 29 | 41.4 (34.0) | 34.5 (28.6) | 27.6 | 37.9 | +0.015 |
| B03 | S/L/S/S | pos_15m ∈ [0.6, 0.8) | win +11.9 | 49 | 36.7 (29.2) | 30.6 (27.5) | 22.4 | 38.8 | −0.002 |
| B04 | L/S/L/L | sd_cur_mfe_5m_A ∈ [1, 2) | win +10.0 | 42 | 26.2 (28.9) | 33.3 (33.7) | 19.0 | 39.5 | +0.003 |
| B05 | S/S/S/S | pos_5m ∈ [0.8, 1.0] | win +8.6 | 99 | 49.5 (44.4) | 41.4 (37.7) | 33.3 | 0.0 | +0.004 |
| B06 | S/L/L/L | pos_1h ∈ [0.6, 0.8) | win +6.1 | 55 | 47.3 (34.0) | 40.0 (28.6) | 34.5 | 37.0 | −0.001 |
| B07 | S/S/S/S | sd_pri_end_5m_A ≥ 2 | win +7.8 | 97 | 48.5 (44.4) | 41.2 (37.7) | 35.1 | 0.0 | +0.003 |
| B08 | S/S/S/S | sd_cur_mae_5m_A ≥ 2 | win +8.1 | 119 | 47.9 (44.4) | 42.0 (37.7) | 32.8 | 0.0 | +0.004 |
| B09 | S/L/L/S | sd_pri_start_15m_B ≥ 2 | win +8.4 | 77 | 36.4 (37.8) | 32.5 (34.2) | 23.4 | 30.3 | +0.009 |
| B10 | S/S/S/S | sd_pri_mae_5m_B ≥ 2 | +2A +9.8 | 98 | 50.0 (44.4) | 44.9 (37.7) | 36.7 | 0.0 | +0.007 |
| B11 | S/S/S/S | sd_cur_start_5m_A ≥ 2 | +2A +10.3 | 117 | 47.9 (44.4) | 41.9 (37.7) | 33.3 | 0.0 | +0.004 |
| B12 | L/S/S/S | sd_cur_mfe_1h_B ≥ 2 | +2A +8.7 | 176 | 35.2 (36.0) | 34.1 (35.6) | 22.2 | 36.7 | +0.000 |
| B13 | L/S/S/S | sd_pri_mae_1h_B < −2 | +2A +6.6 | 112 | 40.2 (36.0) | 40.2 (35.6) | 24.1 | 35.2 | +0.007 |
| B14 | S/L/S/S | sd_cur_mfe_5m_A ∈ [1, 2) | +2A +9.2 | 49 | 44.9 (29.2) | 44.9 (27.5) | 24.5 | 43.8 | +0.004 |

(The 5m-alignment rate is 0.0 in S/S/S/S buckets by construction: the 5m is already aligned at T0.)

## Do the old bucket effects become ordered by the new T0 score? No.

- **The score barely separates a bucket from its parent.** Mean-score differences are −0.008 to +0.015 on
  a probability scale whose pooled mean is 0.37. The model does not treat bucket members as different trades.
- **Rank correlations across the 15 buckets are near zero:**
  - bucket mean score vs validation +2A: ρ = 0.03 / −0.02 / 0.10 (L1 / L2 / L3);
  - bucket mean score vs validation win rate: ρ = −0.11 / −0.06 / 0.10;
  - atlas 2023 lift vs validation lift over parent: ρ = 0.08.

  The atlas ranking does not predict which buckets keep their lift on validation, and the model does not
  recover the buckets either.
- **11 of 15 buckets are still above their parent on validation +2A**, several by 4–16 pp. With child
  N of 29–222 these are within noise, and the four S/S/S/S buckets overlap each other heavily.

**Conclusion:** there is no evidence that the ML combines weak structural subsets into a shared latent
"development" signal. The bucket lifts behave as unstable, local effects. No mechanism is claimed, and
feature importance was not used.

Machine-readable, all three configs: `artifacts/BUCKET_RECONCILIATION.{csv,parquet}`.
