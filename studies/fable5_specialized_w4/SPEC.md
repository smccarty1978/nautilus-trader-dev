# FABLE5 — CODEX 5.X W4 Specialized Model Study (Long/Short and Session-Aware Retraining)

## Objective

Test whether specialized W4-style candidate-selection models — side-specific,
and optionally side×session-specific — produce materially better executable
trade economics than the current pooled/frozen W4 candidate stream under
unchanged Policy A management. The unit of modeling is the **candidate**
(a strict W4 threshold crossing inside an established-regime opportunity),
and the target is **candidate-level Policy A economics**, not the upstream
checkpoint weakness label.

This is a **1-second OHLC research simulation**. No NT-native validation is
claimed. Descriptive model diagnostics, causal candidate-selection replay,
and one-position portfolio replay are reported separately.

## Frozen inputs (sha256-recorded in `input_freeze.json` before execution)

- Candidate population: `studies/codex_5_w4_multi_candidate_reentry/_work/candidates_{2025,2026}.parquet`
  — the audited generated strict-crossing population (11,812 candidates,
  4,767 opportunities; 8,682/3,530 in 2025, 3,130/1,237 in 2026).
- Feature source: repaired per-year atlases
  `studies/CODEX_5_X_weakness_atlas_repair/_work/CODEX_5_X_repaired_years/CODEX_5_X_weakness_atlas_repaired_{2025,2026}.parquet`.
- Frozen W4 scores: `CODEX_5_X_repaired_w4_scores_{2025,2026}.parquet`
  (comparator + Model D input only).
- Raw 1-second bars: `data/raw/NQ_v0_1s_2025.parquet`, `data/raw/NQ_v0_1s_2026_ytd.parquet`.
- Prior comparators: frozen Policy A trades
  (`CODEX_5_X_established_fade_{year}_trades.parquet`,
  `codex_5_w4_fade_confirmation_clock_isolation/results/isolation_trade_diffs.parquet`),
  multi-candidate R10/R30 results, streaming S1/S4 results, prior PR10/PR30
  first-crossing results.

W4 is **not** retrained or rescored. Thresholds, candidate generation, and
Policy A management are unchanged.

## Split discipline (decided with user, 2026-07-17)

Only 2025/2026 candidate data exists. Generating 2021–2024 candidates was
rejected because (a) the frozen W4 bundle was trained on 2021–2024, so scores
there are in-sample and the crossing population is optimistically selected,
and (b) those atlases are at 30s checkpoint cadence vs 5s for 2025/2026.

- Development training: 2025-H1 — candidates with `candidate_time <`
  2025-07-01 UTC (`1751328000000000000` ns).
- Development validation / all selection: 2025-H2 — candidates with
  `candidate_time >=` that boundary.
- Boundary purge: candidates in H1 whose replayed exit (`exit_fill_ts`) or
  opportunity end reaches `>=` the boundary are **purged from training**
  (counted and reported). H2 keeps all its candidates.
- Final holdout: 2026, opened exactly once after a frozen model manifest and a
  passing pre-execution audit exist. **Sample depth is limited; 2026 is a
  selection-isolated descriptive test, not deployment approval.**
- Known caveat (flagged, accepted): 2025-H2 was the frozen W4's isotonic
  calibration window. Isotonic is monotone, so candidate membership (a rank
  event at the frozen threshold) is mildly in-sample for H2; the specialized
  models' raw features are unaffected.

Nothing — model family, segmentation, thresholds, retention, calibration,
features, hyperparameters — is chosen using 2026.

## Candidate rows and features

Each candidate row carries: candidate/opportunity ids, sequence number, year,
timestamps, direction (`long_fade`/`short_fade`), session (`ETH`/`RTH`, from
`is_rth` at the immediate fill), frozen `w4_score`/`threshold`/`score_margin`,
immediate fill time/price, `atr_at_checkpoint`, and the causal feature vector.

Causal feature vector (Models A/B/C) = the 152 repaired atlas features that
feed W4 (47 center + 100 sequence + 5 local: `regime_age`, `current_pnl`,
`current_mfe`, `current_mae`, `giveback`) joined 1:1 from the atlas row at
(`regime_start_ns`, `observation_time == candidate_time`), plus candidate
fields `candidate_seq`, `new_progress_windows`, `retained_mfe_ratio`,
`atr_at_checkpoint`. Model A (pooled) additionally receives `direction_flag`
(+1 long_fade / −1 short_fade) and `session_flag` (1 RTH / 0 ETH); Model B
receives `session_flag`. **The frozen `w4_score`/`score_margin` are excluded
from A/B/C features** (user decision: cleanest attribution); they appear only
in the baseline comparator and Model D.

All features are values already computed at the candidate checkpoint. No
field derived from trade outcome, future MFE/MAE, future stop state, future
flip timing, or realized PnL is an input.

## Labels (per-candidate independent Policy A replay)

Every candidate is replayed **independently** from its immediate causal fill
(`candidate_fill_time` open) using the byte-identical Policy A management
contract from the multi-candidate study (`simulate_trade`): 1.25×ATR
fill-anchored pre-alignment stop active on the entry bar, 300s confirmation
timeout anchored at entry, aligning flip within timeout continues, 1.50×ATR
post-alignment stop, opposing-flip next-open scheduled exit, adverse-first
stop semantics within 1s bars, stop gap fills at open when the bar opens
beyond the trigger, $20/point, $10 round-trip cost.

Labels:

- `net_pnl_usd` (primary economic quantity), `net_pnl_atr`
  (= gross points / `atr_at_checkpoint`).
- `candidate_policy_net_positive` = `net_pnl_usd > 0` (primary classifier label).
- `reaches_alignment_within_5m` (= `reached_aligning_flip`).
- `avoids_pre_alignment_stop` (= exit_reason ≠ `preflip_policy_stop`).
- `top_quintile_pnl` / `bottom_quintile_pnl` — quintile edges computed on the
  H1 training set only, then applied everywhere.
- Non-replayable candidates (missing fill, or fill at/after the aligning
  flip) get null labels, are excluded from training/evaluation, and are
  counted in the dataset audit.

**Reconciliation gate (must pass before any training):** the seq-1 candidates
restricted to the frozen 4,383-trade executable regime set must reproduce the
frozen Policy A trades exactly — entry ts/px, exit ts/px, exit reason, net
PnL (atol 1e-8) — against `isolation_trade_diffs` and the frozen trade files.
Any mismatch aborts the study.

## Model structures

- **A — pooled retrained**: one model, direction/session as features.
- **B — side-specific**: `long_fade_model`, `short_fade_model`; session as a
  feature.
- **C — side×session**: 4 models, each trained only if its H1 cell has
  ≥150 positive and ≥150 negative labeled candidates; otherwise that cell is
  reported `INSUFFICIENT_SAMPLE` and Model C is not promoted.
- **D — hierarchical calibration**: frozen pooled `w4_score` recalibrated by
  isotonic regression per side (and per side×session where the C gate
  passes), fit on H1 only.
- **Baseline comparator**: the frozen W4 ranked by `score_margin`
  (= `w4_score − direction_threshold`, making sides comparable under a global
  retention percentile; no retraining), plus the original take-everything W4
  candidate stream and the frozen Policy A first-candidate arm.

Model families per structure (predeclared, no search beyond this):

- Regularized logistic regression: median-impute (train medians) +
  standardize; `C ∈ {0.1, 1.0}`, L2, `max_iter=2000`.
- `HistGradientBoostingClassifier`: `max_depth=3`, `learning_rate=0.05`,
  `max_iter ∈ {100, 200}`, `random_state=42`, native NaN handling.

Family/config selection per structure: highest 2025-H2 **independent-candidate
net PnL at the top-30% retention band**; ties → logistic over GBT, lower C,
fewer iterations. Selection uses H2 only.

## Retention policy

For each model, retention bands top 10/20/30/40/50% are defined as score
cutoffs at the corresponding percentiles of the model's H2 development scores
**within its scoring segment** (pooled → global percentiles; side models →
per-side; side×session → per-cell). Cutoffs are frozen in the manifest and
applied unchanged to 2026. The original W4 threshold baseline (accept all
candidates) is always reported alongside.

## Policy replay

At each candidate, in time order: score with the frozen specialized model;
accept iff score ≥ frozen cutoff; enter at the candidate's immediate causal
fill; manage with Policy A. No PR10/PR30 delay. No re-entry logic beyond what
the candidate stream already contains.

Two accountings, reported separately and reconciled:

1. **Independent candidate economics** — every accepted candidate booked
   (upper-bound diagnostic; concurrent positions possible).
2. **One-position streaming economics** — chronological global single
   position; a candidate arriving while a position is open is skipped
   (skip does not consume the opportunity); after a stop exit the position
   frees at exit+1s, else at exit ts (identical to the streaming study's
   busy rule).

If the two disagree materially, the report explains why.

## Reporting

For every model×retention policy and the baselines, report by: combined,
2025 (H2 development), 2026, long/short, ETH/RTH, and the four
direction×session cells — candidate count, executed, skipped, total net PnL,
mean PnL/candidate, mean PnL/trade, PF, win rate, stop rate, timeout rate,
avg winner/loser, max closed-trade drawdown, retention rate, total costs.
2025-H1 (training) economics are reported separately and labeled in-sample.

Diagnostics per model: ROC-AUC, PR-AUC, Brier, calibration curve (10 bins),
lift/PnL/WR/stop-rate/alignment-rate by score decile, feature importance
(native + permutation top-20 on H2), monthly feature-importance stability
across H1, and side/session importance differences. Classification metrics
never override economic metrics; divergences are stated explicitly.

## Deliverables

`results/`: specialized_w4_dataset_audit.parquet,
specialized_w4_model_metrics.parquet, specialized_w4_decile_lift.parquet,
specialized_w4_policy_results.parquet, specialized_w4_trade_diffs.parquet,
specialized_w4_feature_importance.parquet,
specialized_w4_calibration_report.md, final_report.md, run_manifest.json.
`audit/`: pre_execution_audit.md, completion_audit.md.

## Final decision labels (one selected)

NO_SPECIALIZED_W4_EDGE · SIDE_SPECIFIC_W4_PROMISING ·
SIDE_SESSION_W4_PROMISING · LONG_ETH_FILTER_PROMISING ·
SHORT_RTH_EDGE_PRESERVED · MODEL_METRICS_IMPROVE_BUT_PNL_FAILS ·
SPECIALIZATION_OVERFITS_2025 · INSUFFICIENT_SAMPLE_FOR_SPECIALIZATION ·
FULL_COLLECTOR_V2_REQUIRED

## Guardrails

No 2026-driven selection of any kind; Policy A unchanged; no delay gates; no
re-entry-after-stop beyond the one-position streaming layer; results labeled
1-second OHLC research simulation; pre-execution lookahead audit required
before any replay or training run; completion audit before reporting.
