# NT Event-Driven Pure Flip Proof-of-Concept and Mirrored Long-Entry Study

## Status

**SPEC frozen, not yet implemented.** Scout pass complete (including a
dedicated research pass over the existing NT infrastructure) — see
"Scout-pass findings" below. One finding materially shapes Phase 2's
architecture and is stated up front because it resolves the brief's own
explicit either/or choice ("scored causally during replay... or frozen
scores... proven against runtime recomputation").

## Decision to inform

Whether the frozen bearish-flip model + simplified fixed-stop/regime-flip
management is causally reproducible and economically promising under a
real NautilusTrader event-driven backtest (not a pandas replay), for the
busiest 2025 month, across three trigger variants — and, if promising,
whether a mirrored bullish-flip (long) model shows comparable signal
quality.

## Scout-pass findings (grounds this SPEC in verified fact, not assumption)

1. **No existing NT strategy in this repo scores an ML model live in
   `on_bar`, and `FeatureEngine` (the 461-feature enriched library) has
   never been wired into a running NT `Strategy`.** Verified by reading
   every `Strategy` subclass in the repo and every importer of
   `features.engine`: zero matches for either. Both existing NT studies
   (`fable5_nt_short_rth_policy_a`, `fable5_pre_flip_d10_reversal_entry`)
   load a **precomputed score/schedule parquet** at `on_start` and dispatch
   via a sorted pointer-sweep over `observation_time` — regime state
   (bullish/bearish) is the only thing recomputed live, via a reused
   `RegimeEngine` class, not `FeatureEngine`. Building genuine live 695-
   feature GBT scoring inside NT would require reconciling `FeatureEngine`'s
   richer regime-object interface (`regime.regime_id`, `regime.atr.value`,
   etc.) against the plain-int `RegimeEngine.update()` interface the NT
   studies actually use — a from-scratch integration project larger in
   scope than `fable5_nt_short_rth_policy_a` itself (~1,100 lines + a
   4-pass audit for a much simpler, non-ML-scored strategy).
2. **Resolution: Phase 2 uses the brief's explicitly-permitted second path
   — frozen (precomputed) scores, with parity proven against runtime
   recomputation, not live in-loop scoring.** Concretely: (a) entries are
   dispatched from a frozen schedule (reusing the exact pointer-sweep
   pattern already audited in `fable5_nt_short_rth_policy_a/strategy.py`);
   (b) regime state for the EXIT logic (bearish-flip confirmation, then
   bullish-flip exit) is genuinely recomputed live via the same audited
   `RegimeEngine`, not looked up; (c) score/trigger parity is proven by
   (i) an exact-timestamp re-derivation check (re-running the
   already-tested `trigger_logic.py` against the stored score column for
   the selected month and confirming byte-identical trigger rows) and
   (ii) a regime-transition parity gate identical in kind to
   `fable5_nt_short_rth_policy_a/reconcile.py`'s `flip_parity()` (NT's live
   regime timeline vs. the canonical offline timeline the frozen scores'
   `confirm_flip_ns` values were built from). This is NOT "scored causally
   during replay" in the strongest sense (a live 695-feature-vector
   forward pass every bar) — it is the SPEC's own stated fallback, and is
   the only one of the two tractable inside a single-session build,
   consistent with the effort ratio observed in finding 1.
3. **The fitted F3+GBT bearish-flip model object was never persisted to
   disk.** `short_rth_pure_flip_prediction_enriched/train_and_evaluate.py`
   computes scores in-memory and writes them to
   `_work/scored_{split}.parquet`, then discards the fitted model — no
   `pickle`/`joblib` save call anywhere in that script (confirmed by
   direct grep). There is therefore no single artifact to SHA256 as "the
   model." Determinism is instead established by: (a) `random_state=42`
   fixed throughout, and (b) an empirical proof already on record from
   earlier this session — after a mid-run crash, the entire 8-combo
   training pipeline was re-run from scratch and reproduced byte-identical
   diagnostics for every already-completed combo. This SPEC records the
   **generator script hash** (`train_and_evaluate.py`) and the **output
   score hash** (the specific score column in `scored_dev_2025.parquet`)
   as the frozen artifacts, per the "record model SHA256" requirement,
   with this caveat stated explicitly rather than fabricating a model
   artifact hash that doesn't exist.
4. **Frozen threshold values confirmed exactly** against
   `studies/short_rth_pure_flip_score_entry_policy/_work/cutoffs.json`:
   `top5 = 0.45049368433122905`, `top2.5 = 0.5064939282727833` — match the
   brief's expected values exactly (16 significant figures).
5. **The three required trigger-variant schedules already exist**, fully
   computed and audited, at
   `studies/short_rth_pure_flip_score_entry_policy/_work/schedule_trig_{B_top2.5,C30_top5,B_top5}_2025.parquet`
   — each carries `regime_start_ns`, `observation_time`, `entry_ts`,
   `atr_at_entry`, `confirm_flip_ns`, and the frozen score. Phase 1's month
   selection and Phase 2's schedule construction both read directly from
   these files (filtered to the chosen month) — no re-derivation of the
   trigger logic itself, only re-verification that it reproduces these
   rows (finding 2c).
6. **No git repository exists at the repo root** (`git rev-parse HEAD`
   fails: "not a git repository") — the "Git commit" field in the frozen-
   inputs manifest is recorded as `null`/"not available", not fabricated.
7. **Existing NT catalog and instrument config reused verbatim**: 1s/1m NQ
   bars at `data/catalog/NQ_v0_2020_2026`, `NQ.XCME` `FuturesContract`
   (multiplier 20, price_increment 0.25) via `TestInstrumentProvider`,
   `Venue("XCME")` NETTING/MARGIN — identical to both existing NT studies,
   not reconfigured.
8. **The simplified exit logic is a strict subset of
   `fable5_nt_short_rth_policy_a/strategy.py`'s already-audited state
   machine**, with two specific removals: (a) no confirmation-timeout path
   (delete the `timeout_ts` check and `confirmation_timeout` exit reason
   entirely — per this brief, "if bearish alignment takes longer than five
   minutes, remain in the trade, there is no timeout"), (b) no
   pre/post-alignment stop distinction (delete `_swap_to_post_stop`; a
   single stop-market order at `entry_px + 1.25*atr`, placed once at entry
   fill, never cancelled/replaced, remains resting until either it fills
   or the position closes via the opposing-flip exit). The alignment
   ("bearish flip confirms the thesis") → opposing-flip-exit structure is
   otherwise unchanged and reused directly.

## Phase 0 — Frozen inputs (recorded, not re-derived)

```text
Bearish-flip model: F3_volume_delta_plus_price_levels + GBT
  (trained in studies/short_rth_pure_flip_prediction_enriched/train_and_evaluate.py,
   NOT persisted as a model artifact -- see finding 3)
Feature set: F3, 695 columns (studies/short_rth_enriched_volume_level_retrain/_work/feature_sets.json)
Frozen thresholds: top5=0.45049368433122905, top2.5=0.5064939282727833
Training years: 2021-2024 (confirmed: train_and_evaluate_manifest.json train_rows=813,972)
Score source: studies/short_rth_pure_flip_prediction_enriched/_work/scored_dev_2025.parquet
Trigger schedules: studies/short_rth_pure_flip_score_entry_policy/_work/schedule_trig_{key}_2025.parquet
Underlying data: data/raw/NQ_v0_1s_2025.parquet; data/catalog/NQ_v0_2020_2026 (NT catalog)
Git commit: not available (no .git at repo root)
```

Recorded in `phase2/month_selection_manifest.json` and `results/final_decision.json`
with exact SHA256 for every script/data file listed above.

## Phase 1 — Month selection

Computed directly from the three existing schedule files (finding 5),
grouped by calendar month of `entry_ts`. Selection is by trigger-count sum
only, per the brief — profitability is not consulted before freezing the
month.

## Phase 2 — NT event-driven backtest

Strategy: `SimpleFlipTriggerStrategy`, adapted from
`fable5_nt_short_rth_policy_a/strategy.py` per finding 8 (single fixed
stop, no timeout). Three independent runs (T1/T2/T3), separate strategy
instances, no pooling before all three complete.

Parity checks (finding 2c): trigger-condition re-derivation (exact),
regime-transition parity vs. canonical timeline (exact, reusing
`flip_parity()`'s pattern), ATR-at-entry parity (exact — `atr_at_checkpoint`
is a stored value, not recomputed), score identity (the frozen score used
to build the schedule, checked against the stored `scored_dev_2025.parquet`
column — exact, since no live rescoring occurs).

## Phase 2 gate

Per the brief's stated criteria verbatim (infrastructure: 0 CRITICAL, exact
parity; economics: net PnL>0 OR PF>1.05 for at least one variant, ≥30
trades, ≥55% reach bearish flip before stop, opposing-flip bucket
aggregate-positive, not one-outlier-driven, plus qualitative path evidence).

## Phase 3 — Mirrored long model (conditional on Phase 2 gate passing)

Reuses `short_rth_pure_flip_prediction_enriched`'s `phase0_prepare_data.py`/
`train_and_evaluate.py` machinery verbatim, mirrored: population = qualified
bearish RTH regime, target = `bullish_regime_flip_within_300s`
(pure `confirm_flip_ns`/`observation_time` arithmetic, same finding-1
correction discipline as `[[age_gate_120_vs_240_inconclusive]]`'s fix — not
re-derived from any Policy-A-style simulation flag). Direction-normalized
features (`price_level_context`'s `*_ahead_of_trade`/`*_behind_trade`,
direction-normalized distances) already take `entry_direction` as a
parameter in `features/trackers/price_levels.py` — mirroring means
re-running the SAME causal feature-attachment code with `entry_direction=+1`
for bearish-regime checkpoints, not hand-flipping any feature's sign. Exact
mirrored feature counts will be confirmed and reported, not assumed equal
to the bearish model's 149/363/481/695.

## Process note (per standing project feedback)

`[[feedback_preexecution_audit_gate]]`: the new Phase 2 strategy logic
(fixed single stop, no-timeout exit state machine) and any new mirrored-
population label logic in Phase 3 are new derivation code, not verbatim
reuse — hand-computed tests will be written and passed, and a
pre-execution audit run, before each is applied at scale, matching this
session's established discipline.

## Guardrails

Mandatory `lookahead-auditor` pass for both phases, 0 CRITICAL required.
Phase 3 does not proceed unless Phase 2's gate passes. No exit optimization
in either phase (path diagnostics are descriptive only).

## Post-Phase-2 status: Phase 3 descoped, not executed

Phase 2's gate passed (`NT_POC_PROMISING_LONG_MODEL_NOT_RUN` — see
`results/final_decision.json`; T2/T3 both clear the full economic gate,
T1 clears everything except "not one-outlier-driven"; infra gate exact on
all three parity checks; completion-gate audit 0 CRITICAL). Per SPEC's own
guardrail this cleared Phase 3 to proceed.

However, scouting Phase 3's actual implementation (before writing any
code) surfaced a scope error in this SPEC's finding above: "Reuses
`short_rth_pure_flip_prediction_enriched`'s machinery verbatim, mirrored"
assumed a bearish-regime (established-downtrend) checkpoint population
already existed or could be produced by a parameter flip. It does not.
Traced via a dedicated Explore pass: `short_rth_pure_flip_prediction_enriched
/phase0_prepare_data.py` reads `ohlcv_volume_delta_price_level_features
/_work/full_{year}.parquet`, which reads
`short_rth_w4_retrain_entry_strength/_work/labeled_featured_{year}.parquet`,
which traces to `short_rth_entry_surface_backfill/entry_surface.py:69-71`:

```python
direction = int(first.direction)
if direction != 1:          # prevailing long -> short-fade candidate only
    continue
```

Every bearish-regime (`direction == -1`) regime is dropped at the very
first funnel stage, for all 6 years, before any RTH/established/valid-fill
filtering runs (`entry_surface.py:57,63-73`; confirmed in
`short_rth_entry_surface_backfill/SPEC.md:301`: "Direction is short (-1)
for every row in this surface"). `features/trackers/price_levels.py`'s
`direction` parameter (confirmed at lines 178-179, 392-425) DOES correctly
implement the ahead/behind mirror mechanically — but there is no bearish-
regime population anywhere in the repo to attach it to. Confirmed via a
repo-wide search of all `studies/*/_work/*.parquet` (410 files) and grep
for `bearish_regime`/`direction != -1`/`established_long` — no such
surface exists.

Building Phase 3 correctly therefore requires a NEW `entry_surface.py`-
style build (funnel inverted to keep `direction == -1`, with the
`favorable` excursion sign convention at `entry_surface.py:86` also
inverted) across all 6 years, followed by a full 695-feature
re-attachment run, fresh labeling, and a fresh GBT retrain — i.e.
rebuilding the equivalent of three prior full studies'
(`short_rth_entry_surface_backfill`, `ohlcv_volume_delta_price_level_features`,
`short_rth_pure_flip_prediction_enriched`) pipelines mirrored, not the
"reuse machinery verbatim" scope this SPEC originally assumed.

**Decision (user, 2026-07-20): stop after Phase 2.** Given the scope gap
between what was frozen and what Phase 3 actually requires, Phase 3 is
descoped from this study and deferred to a separately-briefed future
study rather than folded in here. This document, `STUDY_REPORT.md`, and
`results/final_decision.json` report Phase 2 only;
`phase3_status = "descoped_scope_gap_deferred"`.
