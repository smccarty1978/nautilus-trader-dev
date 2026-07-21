# Short-RTH Enriched Volume/Level Retrain

## Status

**COMPLETE. Final decision: `ENRICHED_RETRAIN_OVERFITS_2025`.** See
`STUDY_REPORT.md` for the full write-up. The best combo (F3 combined
features, logistic regression, 20% retention) beat Baseline A decisively on
2025 dev (+$36.29/tr vs +$23.64/tr, PF 1.241 vs 1.129, lower max DD) but
flipped negative on sealed 2026 (−$3.11/tr, PF 0.983) — every one of the 8
(feature_set, model) combos' best 2025 band also went negative on 2026, so
this is not an isolated failure of one combo. Audit: `audit/audit.md`, 0
CRITICAL, confirms this is a genuine overfit finding, not a look-ahead
artifact. Keep the current W4 short-RTH Policy A baseline; do not promote
any enriched variant to NT validation.

## Decision to inform

Whether the newly accepted OHLCV volume/delta and price-level context
features (`[[ohlcv_volume_delta_price_level_features_accepted]]`, 461
features, `ACCEPT_FEATURE_FOUNDATION`) improve short-RTH entry selection
enough to beat the current original W4 short-RTH Policy A baseline and
justify NT schedule-driven validation. One-shot retrain using the completed
feature foundation — not a new feature-engineering pass.

## Primary hypothesis

Adding causal OHLCV-estimated volume/delta features and causal price-level
context features improves short-RTH entry selection by helping the model
distinguish:

```text
1. real short-RTH reversal/fade opportunities that become opposing-flip winners
2. false early shorts that hit the 1.25A pre-alignment stop
3. dead/neutral candidates that time out
```

Null hypothesis: the new features do not improve OOS selection; the current
original W4 short-RTH Policy A baseline (`[[short_rth_retrain_baseline_still_best]]`)
remains best.

## Scout-pass findings (grounds this SPEC in verified fact, not assumption)

Verified directly against the actual parquet files before freezing this SPEC:

1. **Canonical input is `studies/ohlcv_volume_delta_price_level_features/_work/full_{year}.parquet`**,
   not the older `short_rth_w4_retrain_entry_strength/_work/labeled_featured_{year}.parquet`.
   Confirmed by direct diff (2025 file): `full_2025.parquet` is an exact
   superset — same 198,255 rows, all 187 original columns present unchanged,
   plus 465 added columns (461 registered features + 4 provenance columns).
   Do not join these two files together; `full_{year}.parquet` already
   contains everything `labeled_featured_{year}.parquet` has.
2. **Provenance columns to exclude from every model input** (confirmed
   present, exact names): `observation_ts`, `latest_source_ts_used`,
   `latest_1s_bar_close_ts_used`, `latest_1m_bar_close_ts_used`.
3. **Existing (F0) feature set is `FEATURE_COLS = CENTER_FEATS + SEQUENCE_FEATS`**
   (149 columns), importable unchanged from
   `studies/regime_sequence_chop_context/train_weakness_model.py`. Do
   not re-derive this list.
4. **New feature families, exact counts**: `ohlcv_est_delta` = 214 columns,
   `price_level_context` = 247 columns (`features/registry.py`, family
   field). F1 = F0 + `ohlcv_est_delta`. F2 = F0 + `price_level_context`. F3 =
   F0 + both.
5. **31 non-numeric columns exist inside `price_level_context`**, found by
   direct dtype inspection of `full_2025.parquet`:
   - 2 free-form identity columns: `nearest_level_above_name`,
     `nearest_level_below_name`. **Exclude from all feature sets** (per
     brief: "prefer excluding names in this first pass" — these are
     effectively high-cardinality level labels, not a bounded categorical).
   - 29 bounded categorical columns following the pattern `*_position`
     (e.g. `prior_day_open_position`, `rolling_5m_close_position`), each
     taking exactly one of `{ABOVE, BELOW, TOUCH, UNAVAILABLE}`. **One-hot
     encode these 29 columns** (4 dummy columns each, `UNAVAILABLE` kept as
     its own explicit category — never silently dropped or zero-filled) for
     F2/F3 only. This is a safe, non-leaky, bounded categorical encoding,
     consistent with the brief's "unless safely encoded" exception.
6. **Outcome-class mapping resolved from existing columns — no new
   derivation logic needed.** Cross-tabulating `exit_reason` against
   `hit_pre_alignment_stop` / `hit_timeout` / `hit_post_alignment_stop` /
   `hit_opposing_flip` / `net_pnl` sign on `full_2025.parquet` shows the four
   `exit_reason` values are already mutually exclusive and exhaustive, and
   splitting `original_opposing_flip_exit` by `net_pnl` sign yields exactly
   the 5 classes the brief specifies:

   | outcome_class | condition | 2025 rows | share |
   |---|---|---|---|
   | `pre_alignment_stop` | `exit_reason == 'preflip_policy_stop'` | 64,874 | 32.7% |
   | `confirmation_timeout` | `exit_reason == 'confirmation_timeout_exit'` | 85,876 | 43.3% |
   | `post_alignment_stop` | `exit_reason == 'original_stop_after_aligned_flip'` | 1,611 | 0.8% |
   | `opposing_flip_winner` | `exit_reason == 'original_opposing_flip_exit' & net_pnl > 0` | 32,552 | 16.4% |
   | `opposing_flip_loser` | `exit_reason == 'original_opposing_flip_exit' & net_pnl <= 0` | 13,342 | 6.7% |

   `opposing_flip_exit_positive` (existing column) was verified to already
   equal `hit_opposing_flip==1 & net_pnl>0` exactly (100% match on
   `full_2025.parquet`) — use it directly rather than recomputing.
   `pre_alignment_stop`/`post_alignment_stop`/`confirmation_timeout` map
   1:1 onto the existing `hit_*` boolean columns. Because this mapping is
   exhaustive and mutually exclusive, a genuine 5-class multiclass
   classifier is feasible with the same `sklearn` toolchain the prior
   retrain study already used (`HistGradientBoostingClassifier` and
   `LogisticRegression` both support multiclass natively) — **the brief's
   fallback two-binary-model path is not needed and is not used.**

## Target polarity (read before writing any code)

Primary target: 5-class `outcome_class` (table above), computed once in
Phase 0 directly from existing `exit_reason`/`net_pnl` columns and cached
into the working parquet. Do not re-derive per feature set or per model run.

```text
entry_quality_score =
    + P(opposing_flip_winner)
    - P(pre_alignment_stop)
    - 0.25 * P(confirmation_timeout)
    - 0.50 * P(post_alignment_stop)
```

`P(opposing_flip_loser)` is not weighted in the score (the brief's formula
omits it) but is retained as a diagnostic class so the multiclass model
isn't forced to conflate it with `opposing_flip_winner`. Rank and retain
candidates by **highest** `entry_quality_score`. This is a different
quantity from the prior retrain study's `stop_survival_score`
(`[[short_rth_retrain_baseline_still_best]]`) — do not conflate the two.

## Population

* Instrument: `NQ`. Direction: `short only`. Session: `RTH only`, existing
  remediated fill-time RTH convention (unchanged).
* Population: the same score-independent short-RTH entry surface used by
  the prior retrain study and the feature-foundation study — established
  bullish-regime RTH short-fade checkpoints, frozen gate
  (`regime_age_s_min=120`, `running_mfe_atr_min=1.0`,
  `new_progress_windows_min=2`, `retained_mfe_ratio_min=0.5`). Not
  re-derived; loaded from `full_{year}.parquet`.
* Train: `2021-2024`. Dev/model selection: `2025`. Sealed final test: `2026`.
* No feature-foundation rebuild unless files are missing (verified present
  for all 6 years, see Scout-pass §1). No feature-semantics changes. No
  interaction features.

## Mechanics (frozen, unchanged from Policy A)

```text
pre_alignment_stop = entry_price + 1.25 * atr_at_checkpoint
confirmation_deadline = entry_time + 300 seconds

If bearish alignment occurs before or exactly at deadline:
    aligned = true
    post_alignment_stop = entry_price + 1.50 * atr_at_checkpoint

After alignment, exit on first of:
    1. post-alignment 1.50A stop
    2. opposing bullish regime flip

If no bearish alignment by deadline:
    exit by confirmation timeout
```

1 contract, `$20/pt` multiplier, `$10/trade` round-turn cost. No changes to
stops, timeout, exits, RTH, or direction — this is an entry-selection study
only.

## Baselines

**A — current original W4 candidate basis** (2025-2026): 872 candidates
(650/222), net +$22,250, $/tr +$25.52, PF 1.129, max DD $18,686.

**B — confirmed fixed-807 pocket** (offline): 807 trades (604/203), net
+$27,013, $/tr +$33.47, PF 1.174, max DD $14,331.

**C — NT Phase 1 schedule-driven benchmark**
(`[[nt_short_rth_policy_a_confirmed]]`): 807 trades, net +$23,270, $/tr
+$28.84, PF 1.149, max DD $15,000.

**D — prior 149-feature retrain** (`[[short_rth_retrain_baseline_still_best]]`):
`SHORT_RTH_BASELINE_STILL_BEST`, GBT @ 35% retention, 2025 +$4.75/tr (PF
1.029), 2026 −$32.36/tr (PF 0.825). The enriched model must beat D and,
more importantly, must beat or materially improve on A/B to be worth
promoting.

## Feature sets to compare

```text
F0_existing_only                    149 cols (CENTER_FEATS + SEQUENCE_FEATS)
F1_volume_delta_only                F0 + 214 ohlcv_est_delta cols
F2_price_levels_only                F0 + 247 price_level_context cols (29 one-hot encoded)
F3_volume_delta_plus_price_levels   F0 + both new families
```

Exclude from all model inputs: the 4 provenance columns (§2), the 2
`*_name` identity columns (§5), any future-derived label columns. Keep
availability flags (`*_available`, `window_available_*`, `rth_available`,
etc.) — they are part of the feature definitions, not leakage.

## Model objective

5-class multiclass `outcome_class` target (see mapping table above).
`entry_quality_score` computed from the model's `predict_proba` per the
weighted formula. Do not select directly on realized net PnL — report it as
a diagnostic-only comparator (Layer 2/3 economic tables), consistent with
this project's standing rule that high AUC/separation is not the same as
PnL discrimination (`[[rl_expanded_dynamic_closed]]`).

## Model families (small, predeclared — extend, don't rewrite, the prior study's code)

```text
1. Regularized multinomial logistic regression (median-impute + standardize
   train-only statistics; L2, documented C) — same preprocessing pattern as
   studies/short_rth_w4_retrain_entry_strength/train_and_evaluate.py.
2. HistGradientBoostingClassifier, capped depth (native multiclass, native
   NaN handling) — same class already used in that file; extend to
   multiclass by fitting on `outcome_class` directly.
```

No broader model search, no deep learning, no unbounded hyperparameter
search. Fixed hyperparameters or a tiny predeclared grid selected on 2025
only (mirror the prior study's grid).

## Candidate-to-trade policy — three layers

**Layer 1 — row-level diagnostics.** All rows, all retention bands. Does
the model separate `pre_alignment_stop` / `opposing_flip_winner` /
`confirmation_timeout` /etc.? Report per-class AUC (one-vs-rest),
multiclass log loss, calibration by decile, outcome rates by decile, score
drift by year. Aggregate row-level PnL is diagnostic only, not deployable
(rows overlap heavily within a regime by construction).

**Layer 2 — one-entry-per-regime policy (primary economic comparison).**
For each bullish RTH regime, select the first eligible checkpoint whose
`entry_quality_score` is in the retained band. Retention bands `100% / 85% /
70% / 50% / 35% / 20%`, cutoffs computed on 2025 score distribution only, no
free threshold optimization.

**Layer 3 — fixed-807 overlay.** Apply the selected model to the known
fixed-807 opportunity set; report keep/drop/move/add attribution. If not
semantically clean (e.g. the 807 pocket's regime set was itself selected by
a different one-position rule), state why and skip rather than force a
misattributed comparison — same caveat the prior retrain study documented
for this exact overlay.

## Training discipline

```text
Train: 2021-2024
Select model family, feature set, retention band: 2025 only
Final sealed evaluation: 2026 only
```

Forbidden: 2026 model selection, 2026 threshold tuning, 2026 feature
selection, reweighting or relabeling after seeing 2026. If 2025 and 2026
disagree, report instability explicitly.

## Required outputs

**Data readiness:** row counts by year; feature count by feature set;
missing feature columns; NaN/availability rates; `outcome_class`
distribution by year; 2025/2026 W4 candidate-control reconciliation (650/222
combined 872); confirmation that rows/labels are unchanged from the
feature-foundation study's own join checks.

**Model diagnostics** (per model × feature set): train/2025/2026 metrics
(per-class AUC, log loss); calibration by decile; top features/coefficients;
score distribution by year; outcome rates by score decile; drift
diagnostics.

**Economic diagnostics** (per feature set × model × retention band): trades,
retention, net PnL, $/trade, gross profit/loss, PF, win rate, avg
winner/loser, max closed-trade-sequence DD, monthly PnL/count, exit-reason
counts and PnL, pre-alignment-stop/timeout/post-alignment-stop/opposing-flip
rates, opposing-flip PnL.

**Attribution for the 2025-selected model** (2025 and 2026): pre-alignment
stops avoided and PnL saved; opposing-flip winners removed and PnL lost;
timeout change; post-alignment-stop change; month-level concentration;
which feature family drove the effect (existing vs. volume/delta vs.
price-level).

## Selection gate

**2025 checks (required):** improves vs. Baseline A on at least two of:
$/trade, PF, max DD, pre-alignment-stop rate, opposing-flip-PnL retention.

**2026 checks (required):** net PnL stays positive; $/trade and PF not
materially worse than Baseline A; opposing-flip winners not clipped enough
to erase stop savings; monthly shape not clearly worse; result not driven
by one month.

Promotion requires **both** 2025 improvement and 2026 survival.

```text
2025 improves, 2026 fails            -> ENRICHED_RETRAIN_OVERFITS_2025
Stop savings offset by removed winners -> ENRICHED_RETRAIN_CLIPS_WINNERS
No feature set beats baseline         -> ENRICHED_RETRAIN_BASELINE_STILL_BEST
Both checks pass                      -> ENRICHED_RETRAIN_PROMISING
```

## Required comparisons

1. Feature-set comparison (F0/F1/F2/F3).
2. 2025-selected model vs. 2026 sealed result.
3. Current W4 baseline vs. best enriched model.
4. Stop-savings vs. winner-clipping attribution.
5. Feature-family contribution table (existing / volume-delta / price-level).

## Constraints

Do not: change Policy A, RTH definition, population, or labels; change
feature-foundation semantics; add delta-near-level, failed-high, or
level-rejection interaction features; add new exits, breakeven stops,
runners, or re-entry; include long fades or ETH; use 2026 for any
selection; use frozen W4 scoring to define 2021-2024 candidates; interpret
overlapping row-level PnL as deployable strategy PnL.

## Required artifacts

```text
studies/short_rth_enriched_volume_level_retrain/
  SPEC.md
  results/data_readiness.csv
  results/model_diagnostics.csv
  results/calibration_deciles.csv
  results/economic_results.csv
  results/retention_band_results.csv
  results/exit_reason_attribution.csv
  results/monthly_results.csv
  results/feature_family_contribution.csv
  results/selected_model_trade_schedule.parquet
  results/selected_model_oos_2026_trades.parquet
  results/manifest.json
  audit/audit.md
  STUDY_REPORT.md
  REPRODUCE.md
```

No `implementation/` subfolder — model/training code lives directly in this
study directory (study-local, not shared library code, per
`FEATURE_REGISTRY_CONTRACT.md`'s distinction between library code and
study-specific training scripts).

## Final decision labels

```text
ENRICHED_RETRAIN_PROMISING
ENRICHED_RETRAIN_OVERFITS_2025
ENRICHED_RETRAIN_CLIPS_WINNERS
ENRICHED_RETRAIN_BASELINE_STILL_BEST
ENRICHED_RETRAIN_PARITY_FAIL
ENRICHED_RETRAIN_REJECT
```

## Final report must answer

1. Did the enriched features improve over the old feature set?
2. Did volume/delta features add measurable signal?
3. Did price-level context features add measurable signal?
4. Did the combined model improve 2025?
5. Did the improvement survive sealed 2026?
6. Did the model avoid pre-alignment stops without clipping too many
   opposing-flip winners?
7. Is any model strong enough to promote to NT schedule-driven validation?
8. If not, should we keep the current W4 short-RTH Policy A baseline?

## Guardrails

No model training/feature selection/threshold optimization beyond the fixed
retention-band grid above; no economic conclusions beyond what Layer 2/3
support; mandatory `lookahead-auditor` pass, 0 CRITICAL required before
accepting any result.
