# Look-Ahead & Timestamp Audit — PRE-EXECUTION GATE

**Date:** 2026-07-09
**Scope:** `studies/adaptive_rank_filter_walkforward/awf_common.py`, `build_folds.py`,
`train_adaptive_models.py`, `run_nt_adaptive.py`, plus direct imports/reuse targets:
`studies/rank_filter_oos_validation/common.py` (`repair_f2_window`, `audit_delayed_entry`,
`get_session`), `studies/regime_sequence_chop_context/train_flip_filter.py` (`FEATURES_LIST`
+ fit recipe), `collectors/collector_v2/strategy.py` (`CollectorV2Strategy`, skip-gate
wiring only — internals previously audited elsewhere), `studies/rank_filter_oos_validation/run_nt_validation.py`
(comparison baseline for wiring parity).
**Trigger:** Mandatory pre-execution audit per CLAUDE.md (rolling-retrain / walk-forward
logic, not yet executed for real — `train_adaptive_models.py` and `run_nt_adaptive.py`
have not been run).
**Auditor:** lookahead-auditor v1

## Summary

- Critical: 0
- Warning: 3
- Note: 4

**Verdict: PASS_WITH_WARNINGS** — no look-ahead, train/serve-skew, or timestamp-misuse
defect found that would corrupt results. Three WARNINGs are procedural/robustness gaps
that should be checked (cheap, no code change strictly required) before trusting output;
none block a first execution, but #2 should be checked immediately after
`train_adaptive_models.py` completes and before `run_nt_adaptive.py` is trusted.

## Warnings

### [D4-adjacent] `train_adaptive_models.py:79-81` — insufficient-data folds silently degrade to unfiltered (R0-equivalent) for that deploy month/window, with no propagated flag in the artifact consumed downstream

When `n_train_purged < 50 or n_val_purged < 10`, `run_fold()` returns an **empty**
`deploy_scores` DataFrame for that `(window_name, deploy_month)` combination. Nothing is
written to `adaptive_skip_decisions.parquet` for that fold. Downstream,
`run_nt_adaptive.py::adaptive_skip_set()` (lines 80-87) builds its skip set purely from
whatever rows exist in that parquet — if a fold contributed zero rows, its deploy-month
episodes simply never appear in the skip set for that policy/window, which is
behaviorally indistinguishable from "the model scored everything as safe to trade" (i.e.
that month silently reverts to R0 for that adaptive policy). The only place this is
visible is `model_training_audit.parquet`'s `status` column (which the code does populate
correctly — confirmed at lines 68-81, 89 — so this is fully diagnosable, just not
enforced).

Given F2 population size (~62,769 rows over the full atlas, ~980 signals/month on
average, confirmed by direct read of `flip_context_atlas.parquet`), this guard is very
unlikely to trip for any of the 48 folds (16 deploy months x 3 windows) — but "unlikely"
is not "impossible," and a single silently-degraded fold would understate the adaptive
policy's differentiation from R0 for that month without any error or warning at
backtest time.

**Recommended fix (do not apply):** after running `train_adaptive_models.py`, explicitly
check `model_training_audit.parquet['status'].value_counts()` before running
`run_nt_adaptive.py`. If any fold shows `insufficient_data`, either accept it explicitly
(document which deploy months are R0-contaminated for which window) or hard-fail the
pipeline until data is available.

### [A5/F3] `awf_common.py:71-84` — fold month boundaries are UTC calendar months; the atlas's own `month` tag (carried into `deploy_scores`) is Chicago-local calendar months

`month_bounds()` takes `pd.Period.start_time`/`end_time` (naive) and labels them UTC via
`tz_localize("UTC")` — i.e., "2025-06" as a fold boundary means 2025-06-01T00:00 UTC to
2025-06-30T23:59:59.999999999 UTC. But `repair_f2_window()` in
`studies/rank_filter_oos_validation/common.py:185` tags each episode's own `month` column
using `ts_ct.dt.strftime("%Y-%m")` — i.e., Chicago-local calendar month. `train_adaptive_models.py`
carries this atlas `month` column straight through into `deploy_scores` (line 126 `keep_cols`
includes `"month"`) without ever recomputing it against the fold's own (UTC) `deploy_month`.

This is **not a leak** — fold membership itself is always computed from the UTC-ns
`observation_time` masks (lines 54-56), consistently on both sides (train/val/deploy all
use the same UTC-Period convention), so no episode is mis-assigned to the wrong fold and
no future information crosses a boundary. It is, however, a labeling inconsistency: an
episode confirmed in the ~5-6 hour window around UTC midnight can carry a `month` value
that disagrees with the `deploy_month`/fold it was actually scored/traded under (e.g. an
episode at 2025-05-31 20:30 America/Chicago = 2025-06-01 01:30 UTC would be tagged
`month="2025-05"` but assigned to the `deploy_month="2025-06"` fold). Anyone doing
per-month analysis by grouping on the carried-through `month` column (rather than the
fold's own `deploy_month` column, which IS present and correct) would get a handful of
boundary episodes bucketed inconsistently with what was actually traded that fold.

**Recommended fix (do not apply):** in any downstream analysis, group by `deploy_month`
(fold-assigned, UTC, authoritative), never by the carried-through `month` column
(Chicago-local, descriptive only). Consider dropping or renaming the `month` column in
`deploy_scores` to make this unambiguous.

### [C3-adjacent] `build_folds.py:9` — docstring worked example is off by one month from the code's actual (correct) output

The module docstring's example states: *"Example (12m): deploy=2025-06 -> validate=2025-05
-> train=2024-06..2025-04."* That is only an 11-month train window. I independently
recomputed the arithmetic (`train_end_month - (n_months-1)` with `n_months=12`) and
cross-checked against the actual `fold_definitions.parquet` already on disk: for
`window_name="12m", deploy_month="2025-06"`, the code produces `train_start_month="2024-05"`,
`train_end_month="2025-04"` — a correct, full 12-calendar-month window (May 2024 through
April 2025 inclusive). **The code is correct; only the comment is wrong.** Flagging
because a future reader (including a future audit) trusting the comment over the code
could wrongly conclude the window is short by a month.

**Recommended fix (do not apply):** correct the docstring's worked example to
`train=2024-05..2025-04`.

## Notes

### `run_nt_adaptive.py:66-67, 103-104, 160-161` — sub-second truncation at period/catalog boundaries (`"...23:59:59"` not `"...23:59:59.999999999"`)

Inherited unchanged from `studies/rank_filter_oos_validation/run_nt_validation.py`
(verified identical pattern at that file's lines 113-114, 174-175). Truncates the last
sub-second of the last day of each period/catalog load window. Immaterial in practice
(NQ 1s bars won't straddle that gap in a way that matters) and not a new defect
introduced by this study — noting only for completeness since CLAUDE.md's pre-execution
gate asks that reused-verbatim mechanics be re-examined, not assumed clean.

### `awf_common.py:29` (`FEATURES_LIST` import) — feature-causality semantics not re-derived in this pass

Confirmed mechanically: `FEATURES_LIST` imported directly from
`studies/regime_sequence_chop_context/train_flip_filter.py` (not redefined/copied),
149 entries, all unique (verified by direct execution of the import). The fit recipe in
`fit_ridge_logistic`/`score_with` (`awf_common.py:103-124`) is a byte-for-byte match of
`train_flip_filter.py`'s median-impute + `StandardScaler` + `LogisticRegression(C=0.1,
max_iter=500, penalty='l2')` recipe (verified against `train_flip_filter.py:61-90`).
This audit did **not** re-derive the causal correctness of each of the 149 features
themselves (several sequence-based names like `seq_5r_mean_retracement_mfe` reference
past-completed regime runs, which is plausible as causal look-back but was not
independently re-verified feature-by-feature here) — that scope was covered by the prior
audit of `studies/regime_sequence_chop_context`. If that prior audit is not on record,
it should be, since this study now depends on it more heavily (149 features feeding a
newly-retrained model, rather than a single frozen score).

### `train_adaptive_models.py:120-121` — R2/R4 exemption columns have ~0.02% NaN rate; NaN defaults to "not exempt" (fail-closed)

`seq_5r_center_migration_slope_atr` / `seq_5r_asym_duration` are NaN for ~0.019% of the
atlas (verified by direct read). `deploy[col] > threshold` evaluates `False` for NaN,
so `~r2_exempt` / `~r4_exempt` is `True` for those rows — meaning a NaN exemption feature
does not exempt the episode from a score-based skip. This is a benign fail-closed default
(consistent with the frozen static-policy behavior in `run_nt_adaptive.py:70-73`, which
uses the identical elementwise comparison), not a leak, and the rate is negligible.
Noting only so it isn't mistaken for a bug if someone spot-checks a NaN row's skip flag.

### `train_adaptive_models.py:109` — ATR tercile edges computed from as few as 10 validation samples (the guard floor)

`n_val_purged < 10` is the hard floor before a fold is even attempted; `np.quantile(...,
[1/3, 2/3])` on exactly 10-20 samples would be a noisy bucket-edge estimate. Given actual
F2 volume (~980 signals/month average), this floor is very unlikely to bind in practice —
this is a defensive-coding note about the theoretical floor, not an observed problem.

## Structural finding (not a bug — answers the user's explicit question)

**Confirmed: retained-trade identity across policies (R0 vs static R2/R4 vs adaptive
A1/A2/A4) is an empirical claim, not a structural guarantee, and the code contains
nothing that would make it a guarantee.**

Direct reading of `collectors/collector_v2/strategy.py` confirms:
- The strategy holds **at most one open trade at a time** — entry is gated on
  `self._trade is None` (`strategy.py:349-350`), and the pending-entry object itself is
  singular (`self._pending_entry: dict | None`, `strategy.py:159`).
- The policy skip check (`_is_policy_skip`, `strategy.py:1234-1249`) is evaluated and
  applied **before** the pending-entry dict is constructed (`strategy.py:667` gate,
  `strategy.py:717` construction) — i.e., a skipped signal never occupies the single
  position slot at all.
- Therefore: if R0 takes a trade that a filtered policy skips, the filtered policy is
  flat for that trade's entire duration while R0 is in position. Any subsequent signal
  that arrives during that window will be **accepted** by the filtered policy (flat,
  free to enter) and **rejected/ignored** by R0 (already in position, gate fails). This
  necessarily means the *set*, *timestamps*, and *fill prices* of "retained" trades can
  diverge between policies even for episodes neither policy's filter touched directly —
  a second-order consequence of shared single-position occupancy, not a first-order
  filter effect.
- Nothing in `CollectorV2Strategy`, `CollectorV2Config`, or this study's wiring
  (`run_nt_adaptive.py`) changes or bypasses this single-position mechanic per policy —
  all six static policies and all nine adaptive policies (3 window sizes x 3 variants)
  run as fully independent `BacktestEngine` instances (`run_nt_adaptive.py:116-152`,
  one `engine.run()` per `(policy, period_key)` pair), each with its own independent
  position state.
- Confirmed: the `_is_policy_skip` timestamp match (`strategy.py:1240-1249`) is
  backward-only (`np.searchsorted(..., side="right") - 1`, then `0 <= gap <= tolerance`),
  per a comment dated 2026-07-07 documenting a prior lookahead-audit fix for this exact
  class. Re-verified directly in this pass (not merely trusted from the comment) — no
  forward-looking match is possible regardless of how the skip set was built upstream.

**Conclusion: your planned `nt_parity_audit` is necessary and correct, and cannot be
replaced by code reading.** The code guarantees causal, single-timestamp-consistent skip
application; it does not and structurally cannot guarantee that R0's retained trades are
a strict superset match to any filtered policy's retained trades beyond the directly
skipped episodes themselves. Treat any assumption of "filtered policy = R0 minus skipped
trades, trade-for-trade" as false until the parity audit empirically confirms the scope
of divergence (which should be small in expectation, since skip rates are 5-15% and
average trade duration presumably << inter-signal spacing, but "should be small" is
exactly the kind of claim that needs the empirical check, not an assumption).

## Clean checks

- **Fold sequencing (build_folds.py, train_adaptive_models.py):** independently
  recomputed month arithmetic for representative folds (3m/6m/12m x multiple deploy
  months) and cross-checked against the actual `fold_definitions.parquet` on disk.
  Confirmed zero folds where `deploy_month <= val_month`; confirmed each window size
  produces exactly N calendar months (12m verified as 2024-05..2025-04 for
  deploy=2025-06, i.e. genuinely 12 months, not 11 or 13); confirmed the worked example
  in the task brief ("train through April 2025 / validate May 2025 / deploy June 2025")
  matches the code's output exactly.
- **`purge_straddling` unit consistency (`awf_common.py:96-100`):** confirmed
  `ep_end_time` (atlas) and `.value` on a `pd.Timestamp(int64_ns, tz="UTC")` are both
  int64 UTC nanoseconds; round-tripped a `pd.Timestamp` through `.value` and back to
  confirm no precision loss or unit mismatch.
- **Training/scoring isolation (`train_adaptive_models.py::run_fold`):** confirmed by
  direct code reading that `fit_ridge_logistic` is called on `train` (purged) only;
  `val_score` uses that same fitted `pipe`/`medians`; threshold candidates (5/10/15%)
  and `ev_lift()` are computed entirely from `val` and `val_score` — zero references to
  `deploy` anywhere in the threshold-selection loop (lines 92-109).
- **"Best" threshold selection direction:** confirmed the comparison
  (`stats["ev_lift"] > best["ev_lift"]`) correctly maximizes lift (higher retained-EV
  advantage wins); no off-by-one, no inverted comparison.
- **ATR bucket edges:** confirmed frozen on `val["atr"]` (line 109) and applied via
  `np.digitize` to `deploy["atr"]` (line 117) — never recomputed on deploy.
- **Deployment scoring:** confirmed `deploy_score = c.score_with(pipe, medians, deploy)`
  reuses the train-fit pipeline; confirmed `frozen_threshold` is a scalar carried from
  the validation-only threshold search with zero data-dependency on `deploy`.
- **Exemption logic (A2/A4):** confirmed purely elementwise (`deploy[col] > thr`), no
  rolling/window operation that could leak across different episodes' deploy-month
  positions.
- **Insufficient-data guard distinguishability:** confirmed `status` field is populated
  (`"ok"` vs `"insufficient_data"`) and written to `model_training_audit.parquet` for
  every fold, including ones that return early — this table is available for
  post-run auditing even though (see Warning above) it isn't automatically
  cross-checked before the NT run.
- **`repair_f2_window` widening to 2021-2026-04-29:** confirmed all six required raw
  1s year files (`NQ_v0_1s_2021.parquet` .. `NQ_v0_1s_2025.parquet`,
  `NQ_v0_1s_2026_ytd.parquet`) exist on disk, so the widened call will not silently
  degrade to `missing_replay_bar` status for any in-range year purely due to a missing
  file. `audit_delayed_entry`'s fill-price lookup (`common.py:91-158`) is causal by
  construction (`method="backfill"` — next 1s-open at/after the target, never before).
- **`run_nt_adaptive.py` wiring parity vs. `run_nt_validation.py`:** confirmed identical
  `entry_delay_ns` (30_000_000_000), `enable_hhll_exit=False`, `force_flat_at_min_ct=0`,
  `no_entry_after_min_ct=0`, `rth_only=False`, `require_5m_aligned=False`,
  `position_size=1`; confirmed the 5-day warmup-buffer load + trim-back-to-window logic
  (lines 103-104, 160-169) is a verbatim structural match to the original
  (`run_nt_validation.py:113-114, 174-183`), same column name (`decision_ts`), same
  inclusive `>=`/`<=` boundary operators.
- **`adaptive_skip_set()` (`run_nt_adaptive.py:80-87`):** confirmed pure pass-through —
  reads precomputed `a{n}_skip` columns from `adaptive_skip_decisions.parquet`, no
  scoring, no threshold logic, no recomputation of any kind performed in this
  NT-facing file.
- **`static_skip_set()` (`run_nt_adaptive.py:63-77`):** confirmed same frozen threshold
  key (`"R1"`) and same exemption columns/thresholds as
  `rank_filter_oos_validation/run_nt_validation.py::load_skip_set`; the wider date range
  is applied via a simple UTC timestamp range filter over the already-repaired `f2`
  frame (no independent re-repair call, no behavior change vs. narrower per-period
  usage other than population size).
- **`FEATURES_LIST` fidelity:** imported directly (not copy-pasted/redefined);
  independently executed the import and confirmed 149 entries, all unique, matching the
  brief's stated count.
- **Fit recipe fidelity:** confirmed `LogisticRegression(C=0.1, max_iter=500,
  penalty='l2')` and the median-impute-then-scale order exactly match
  `train_flip_filter.py:61-90`.
- **CollectorV2Strategy reuse — skip-gate wiring only (per scope instruction):**
  confirmed the backward-only timestamp-matching tolerance logic
  (`strategy.py:1234-1249`) and the skip-before-pending-entry ordering
  (`strategy.py:667` vs `717`) by direct code reading in this pass, not merely by
  trusting the prior audit's comment.

---

*Audit complete. Findings reflect read-only static analysis plus small isolated
arithmetic/data-shape verification scripts (pandas month-boundary recomputation, feature
list/dtype/NaN-rate checks, raw-file existence checks). No component of
`train_adaptive_models.py` or `run_nt_adaptive.py` was executed as part of this audit —
`fold_definitions.parquet` pre-existed on disk (pure date-arithmetic, no atlas/model
dependency) and was read, not regenerated. Dynamic/runtime behavior (actual retained-trade
divergence magnitude between policies) is explicitly out of scope here and is the subject
of the user's planned `nt_parity_audit`, which this audit confirms is necessary rather
than optional.*
