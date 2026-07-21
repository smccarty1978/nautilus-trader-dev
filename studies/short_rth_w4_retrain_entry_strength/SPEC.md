# Short-RTH W4 Retrain Entry Strength

## Status

**COMPLETE. Final decision: `SHORT_RTH_BASELINE_STILL_BEST`.** See
`STUDY_REPORT.md` for the full write-up. Phase 0 (data readiness) passed
cleanly (`results/phase0_summary.md`); Phase 1 (train/select/seal) ran to
completion and found no model/retention-band combination that beats the
current pooled W4 threshold — the single best 2025-selected candidate (GBT
@ 35% retention) reaches only +$4.75/trade (vs Baseline A's +$23.64/trade)
and fails outright on sealed 2026 (−$32.36/trade). Keep the current
0.688350 threshold; proceed to Phase 2 live-W4 NT validation instead of any
retrained variant. Audit: `audit/audit.md`, PASS, 0 CRITICAL.

The original blocker (2021-2024 candidate data required in-sample W4
scoring) was resolved by `[[short_rth_entry_surface_backfill]]`, which
delivered `BACKFILL_RECONCILIATION_PASS`, `BACKFILL_2021_SMOKE_PASS`,
`BACKFILL_TRAINING_SURFACE_READY`, and `FULL_SURFACE_LABELING_PASS` — a
813,972-row, causally-clean, exactly-reconciled 2021-2024 labeled surface at
`studies/short_rth_entry_surface_backfill/results/training_surface_2021_2024_labeled.parquet`.

A scout pass before freezing this SPEC found **two remaining gaps**, neither
of which repeats the original circularity/cadence blocker — both are
mechanical data-assembly steps using code that already exists and is already
audited:

1. **The labeled 2021-2024 surface has no feature columns.** It carries
   identity fields (`regime_start_ns`, `observation_time`, `entry_ts`,
   `entry_px`, `atr_at_entry`, `entry_direction`) and label outputs (38
   columns total), but none of the 149 causal `CENTER_FEATS`/`SEQUENCE_FEATS`
   a model needs as inputs. Those live in
   `studies/short_rth_entry_surface_backfill/_work/atlas_5s_backfill_{year}.parquet`
   (2021-2024) and must be joined onto the labeled surface 1:1 on
   (`regime_start_ns`, `observation_time`) before any training.
2. **2025-2026 have no full-surface labels yet.** `entry_surface.build_surface`
   was run for 2025-2026 (`results/reconciliation_2025_2026_surface.parquet`),
   but `label_full_surface.py` has only ever been run for `--years 2021 2022
   2023 2024`. Development selection (2025) and sealed test (2026) both
   require the same full-surface Policy A labels 2021-2024 already has,
   generated with **exactly the same code, unmodified** (`label_row`,
   `simulate_trade_arrays`) — not a re-derivation, not an approximation.

**Phase 0 gate (must pass before Phase 1):**

- Join the 149-feature causal vector onto all four label parquets
  (`full_surface_labels_{2021,2022,2023,2024}.parquet`) and the combined
  `training_surface_2021_2024_labeled.parquet`, keyed on
  (`regime_start_ns`, `observation_time`); assert 100% join rate (every
  labeled row has a matching atlas feature row) and re-assert the 149-column
  schema hash already computed in `[[short_rth_entry_surface_backfill]]`.
- Run `entry_surface.build_surface` + `label_full_surface.py` for 2025 and
  2026 against the existing `CODEX_5_X_weakness_atlas_repair` atlas (already
  built, already used for the reconciliation smoke) — same functions, same
  established/RTH/valid-fill gate, same Policy A contract, same MAE/MFE
  post-hoc scan. Join the same 149 features for these two years.
- Re-verify, on the 2025-2026 feature-joined labeled output, the two known
  controls this study must still be able to reproduce:
  - candidate basis: 650 (2025) / 222 (2026), combined 872;
  - fixed-807 overlay: 604 (2025) / 203 (2026).
  These are the same reconciliation checks `[[short_rth_entry_surface_backfill]]`
  already passed against the crossing-only comparator; re-running them here
  after the feature join and the 2025/2026 labeling pass is a cheap
  regression check, not new logic.

If Phase 0 does not close cleanly (join rate <100%, schema mismatch, or the
650/222/604/203 controls fail to reproduce), stop and report
`SHORT_RTH_PARITY_FAIL` rather than proceeding to Phase 1 on a silently
incomplete dataset.

## Decision to inform

Whether a short-RTH-only entry model trained on the newly labeled
score-independent surface can improve the confirmed short-RTH Policy A
pocket versus the current original pooled W4 threshold, and whether any such
model should be promoted to NT schedule-driven validation.

## Primary hypothesis

A short-RTH-only model trained on 2021-2024 can reduce pre-alignment
stop-outs while preserving the opposing-flip winner cohort, improving
risk-adjusted expectancy versus the current original pooled W4 short-RTH
baseline.

Null: the current original pooled W4 threshold remains the best
risk-adjusted entry selector; retrained models either overfit 2025, clip too
many winners, or fail on sealed 2026.

## Target polarity (read before writing any code)

The labeled surface's `avoid_pre_alignment_stop` column (both in the
2021-2024 parquet and whatever this study computes fresh for 2025-2026) is
**bad-outcome polarity**: `1` = hit the pre-alignment stop, `0` = did not.
Do not treat `1` as favorable. This study's own primary target uses the
literal, unambiguous name instead:

```text
hit_pre_alignment_stop = 1  ->  bad (stopped out before alignment)
stop_survival_score = 1 - P(hit_pre_alignment_stop)
```

Rank and retain candidates by **highest** `stop_survival_score`. This is the
opposite sense from the seq-1 feasibility check's own (differently-defined)
`avoid_pre_alignment_stop` field computed earlier in
`[[short_rth_entry_surface_backfill]]` — the two are not interchangeable.

## Population

* Instrument: `NQ`. Direction: `short only` (fade a prevailing bullish 1m
  regime). Session: `RTH only`, `08:30:00-15:00:00 America/Chicago`, entry
  filter using the remediated **fill-time** RTH convention (not decision-time
  — see `[[short_rth_entry_surface_backfill]]` audit remediation).
* Population definition: **all eligible established bullish-regime RTH
  short-fade checkpoints** from the score-independent entry surface
  (`entry_surface.build_surface`) — the same established-regime gate as the
  audited threshold-ladder population (`regime_age_s_min=120`,
  `running_mfe_atr_min=1.0`, `new_progress_windows_min=2`,
  `retained_mfe_ratio_min=0.5`). The frozen W4 score is **not** used to
  define 2021-2024 candidates. It is used only as the Baseline-A/B/C
  comparator and, for 2025-2026 only, as an optional per-row comparison
  column (never a training input).
* Training years: `2021-2024`. Development/selection year: `2025`. Sealed
  OOS test year: `2026`.
* Exclusions: warmup periods, prior-repaired-study bad/missing intervals, no
  future-conditioned filtering, no resolved-only substitution, no long
  fades, no ETH entries.

## Mechanics under test (frozen, unchanged from `[[short_rth_entry_surface_backfill]]`)

Policy A management, unchanged, applied identically to every hypothetical
row:

```text
pre_alignment_stop = entry_price + 1.25 * atr_at_checkpoint
confirmation_deadline = entry_time + 300 seconds

If bearish alignment occurs before or exactly at the deadline:
    aligned = true
    post_alignment_stop = entry_price + 1.50 * atr_at_checkpoint

After alignment, exit on first of:
    1. post-alignment 1.50A stop
    2. opposing bullish regime flip

If no bearish alignment by deadline:
    exit by confirmation timeout
```

1 contract, `$20/pt`, `$10/trade` round-turn cost, no extra slippage model.
1-second OHLC research simulation; not NT-native. This is an
**entry-selection study**: Policy A, the RTH definition, and checkpoint
cadence are frozen and out of scope for modification.

## Baselines

**A — current original W4 candidate basis** (2025-2026, from
`[[short_rth_threshold_ladder]]`): 872 candidates (650/222), net +$22,250,
$/tr +$25.52, PF 1.129, max DD $18,686.

**B — confirmed fixed-807 pocket** (offline): 807 trades (604/203), net
+$27,013, $/tr +$33.47, PF 1.174, max DD $14,331; 2025 +$20,304, 2026
+$6,709.

**C — NT Phase 1 schedule-driven benchmark** (`[[nt_short_rth_policy_a_confirmed]]`):
807 trades, net +$23,270, $/tr +$28.84, PF 1.149, max DD $15,000.

This study stays offline/1-second-OHLC unless a model earns promotion under
the selection gate below.

## Variables to test

Only entry selection varies. Stops, exits, RTH, thresholds, session, and
checkpoint cadence are frozen.

### Model target

Primary: `hit_pre_alignment_stop` (1 = hit the 1.25A pre-alignment stop
before bearish alignment, 0 = did not). Score: `stop_survival_score = 1 -
P(hit_pre_alignment_stop)`; rank by highest.

Secondary diagnostics only (never used to select the production model
unless explicitly separated as such): `aligned_before_stop_or_timeout`,
`opposing_flip_exit_positive`, `net_pnl_positive`, `realized_policy_a_net_pnl`.

### Model families (small, predeclared)

1. Regularized logistic regression (median-impute + standardize train-only
   statistics; L2, documented `C`).
2. Shallow gradient-boosted / shallow tree classifier, capped depth,
   documented regularization.
3. Current pooled W4 score/rank, 2025-2026 only, as a non-retrained
   comparator (never trained on 2021-2024).

No broader model search.

### Retention bands (fixed, no free-threshold optimization)

```text
100% / 85% / 70% / 50% / 35% / 20%
```

by highest `stop_survival_score`, computed within the split being reported
(train-only percentiles for train, frozen dev cutoffs applied unchanged to
2026).

## Training discipline

```text
Train: 2021-2024
Select model family + retention band: 2025 only
Final sealed evaluation: 2026 only
```

Forbidden: 2026 model selection, 2026 threshold tuning, 2026-informed
feature selection, reweighting after seeing 2026 economics. If 2025 and 2026
disagree, report instability explicitly rather than picking whichever looks
better.

## Candidate-to-trade policy — three layers

**Layer 1 — row-level diagnostics.** All eligible rows, every retention
band, reported by score decile. Question: does the model identify
lower-stop-risk checkpoints? Aggregate all-row PnL is **not** deployable
strategy PnL (rows overlap heavily within a regime by construction — see
`[[short_rth_entry_surface_backfill]]`).

**Layer 2 — one-entry-per-regime policy.** For each bullish regime, select
the first eligible RTH checkpoint whose `stop_survival_score` passes the
split's fixed retention cutoff. This produces a deployable candidate-entry
schedule, comparable to the current W4 candidate basis (Baseline A). Use
this layer for the primary economic comparison.

**Layer 3 — fixed-807 overlay.** Apply the selected model to the known
fixed-807 opportunity set (the globally one-position-executed confirmed
pocket) and report keep/drop/move-entry counts, for continuity with
Baseline B. If this overlay is not semantically clean against the model's
own selection logic (e.g. the 807 pocket's regime set was itself selected
by the one-position rule, not by this model), state why and skip rather than
forcing a comparison that would misattribute the effect.

## Required outputs

**Data checks:** row count by year/split, candidate/regime count by year,
feature schema hash, label distribution by year, missing feature columns,
NaN rate, target polarity check (explicit assertion that `hit_pre_alignment_stop`
means what this SPEC says it means), class balance for the primary target.

**Model diagnostics** (per family): train AUC, 2025 AUC, 2026 sealed AUC,
precision/recall for avoiding pre-alignment stops, calibration by decile,
score distribution by year, feature importance/coefficients, evidence of
year drift.

**Economic diagnostics** (per retention band × split, Layer 2 primary,
Layer 1/3 as noted): trades, retention, net PnL, $/trade, gross profit/loss,
PF, win rate, avg winner/loser, max closed-trade-sequence DD, monthly
PnL/count, exit-reason counts/PnL, pre-alignment-stop/timeout/post-align-stop/
opposing-flip rates, opposing-flip PnL.

**Failure attribution** (best 2025-selected model/retention): pre-alignment
stops avoided, opposing-flip winners removed, net PnL saved from avoided
stops, net PnL lost from removed winners, timeout change, post-alignment
stop change, month-level concentration, whether 2026 agrees or contradicts
2025.

## Selection gate

A model is promising only if, selected on 2025, it also satisfies sealed
2026: 2025 improves over baseline on $/trade, PF, and/or DD; 2026 remains
positive; 2026 does not materially degrade versus the current W4 baseline;
pre-alignment stop reduction is not offset by removing too many
opposing-flip winners; monthly shape is not obviously worse; the result is
not driven by one month.

- Improves 2025, fails 2026 -> `SHORT_RTH_RETRAIN_OVERFITS_2025`.
- Reduces stops but removes too many winners -> `SHORT_RTH_RETRAIN_CLIPS_WINNERS`.
- No model beats baseline risk-adjusted -> `SHORT_RTH_BASELINE_STILL_BEST`.

## Constraints

No V2 collector; no microstructure/order-flow features; no broad long/short
W4 retrain; no long fades; no ETH; no Policy A change; no RTH-definition
change; no checkpoint-cadence change; no W4 threshold tuning; no BE/EMA
stops, runners, re-entry; no 2026 for selection; no frozen-W4 scoring on
2021-2024; no interpreting overlapping full-surface aggregate PnL (Layer 1)
as a strategy result.

## Required artifacts

```text
studies/short_rth_w4_retrain_entry_strength/
  SPEC.md
  results/model_diagnostics.csv
  results/economic_results.csv
  results/retention_band_results.csv
  results/exit_reason_attribution.csv
  results/monthly_results.csv
  results/best_model_trade_schedule.parquet
  results/best_model_oos_2026_trades.parquet
  results/feature_importance.csv
  results/manifest.json
  audit/audit.md
  STUDY_REPORT.md
  REPRODUCE.md
```

## Final decision labels

```text
SHORT_RTH_RETRAIN_REJECT
SHORT_RTH_RETRAIN_PROMISING
SHORT_RTH_RETRAIN_OVERFITS_2025
SHORT_RTH_RETRAIN_CLIPS_WINNERS
SHORT_RTH_BASELINE_STILL_BEST          <-- SELECTED
SHORT_RTH_BACKFILL_REQUIRED
SHORT_RTH_PARITY_FAIL
```

## Final report — answers (see STUDY_REPORT.md for full detail)

1. Does a short-RTH-only model improve over the current W4 threshold
   baseline? **No.** Best 2025 candidate (GBT @ 35% retention) reaches only
   +$4.75/trade vs Baseline A's +$23.64/trade.
2. Does it reduce pre-alignment stop-outs? **Yes, modestly** (187/57 stops
   avoided in 2025/2026) — the only positive finding.
3. Does it preserve the opposing-flip winner cohort? **No** — removes
   163/33 opposing-flip winners, costing 2.3-2.5x more than the stops saved.
4. Does the improvement survive sealed 2026? **N/A** — there was no real
   2025 improvement to begin with; the selected candidate fails 2026
   outright (−$32.36/trade).
5. Is monthly stability better or worse? **Worse** — 2026's single best
   month accounts for 48% of the selected schedule's PnL magnitude vs 24%
   in 2025.
6. Is any model strong enough to promote to NT schedule-driven validation?
   **No.**
7. If not, should we keep the current W4 short-RTH Policy A baseline?
   **Yes** — proceed to Phase 2 live-W4 NT validation instead.

## Guardrails

No training runs until Phase 0 (feature join + 2025/2026 full-surface
labeling + control reconciliation) passes and is recorded in
`audit/audit.md`. Mandatory `lookahead-auditor` pass, 0 CRITICAL findings,
before any model is fit. No silent substitution of a different population
or a different target polarity to route around the Phase 0 gap.
