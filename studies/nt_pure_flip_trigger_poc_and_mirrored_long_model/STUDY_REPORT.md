# NT Event-Driven Pure Flip Proof-of-Concept and Mirrored Long-Entry Study — Report

## Decision

**Phase 2: `NT_POC_PROMISING_LONG_MODEL_NOT_RUN`.**
**Phase 3: descoped** — deferred to a separately-briefed future study (user
decision, 2026-07-20). See `results/final_decision.json` for the full
structured decision record and `SPEC.md`'s "Post-Phase-2 status" section
for the scope-gap finding that drove the descope.

## What this study answered

Whether the frozen bearish-flip model (`F3_volume_delta_plus_price_levels`
+ GBT, trained in `short_rth_pure_flip_prediction_enriched`) plus a
simplified fixed-stop/regime-flip management scheme is **causally
reproducible and economically promising under a real NautilusTrader
event-driven `BacktestEngine`** (not a pandas replay), for the busiest
2025 month, across three trigger variants inherited from
`short_rth_pure_flip_score_entry_policy`.

## Phase 0 — Frozen inputs

Recorded in `results/phase0_frozen_inputs_manifest.json`. Key facts,
verified rather than assumed:
- Frozen cutoffs match the brief exactly to 16 significant figures:
  `top5 = 0.45049368433122905`, `top2.5 = 0.5064939282727833`.
- The fitted GBT model was never persisted to disk anywhere in
  `short_rth_pure_flip_prediction_enriched` (confirmed by direct grep for
  `pickle`/`joblib` — none found). Determinism rests on `random_state=42`
  plus an earlier empirical proof this session (a crash-recovery rerun of
  the 8-combo training pipeline reproduced byte-identical diagnostics).
  The generator script and output score column are hashed instead
  (`score_column_sha256` in the manifest).
- No `.git` directory exists at the repo root — `git_commit` is recorded
  as `null`, not fabricated.
- All three trigger schedules (`trig_B_top2.5`, `trig_C30_top5`,
  `trig_B_top5`) reused directly from `short_rth_pure_flip_score_entry_policy`.

## Phase 1 — Month selection

Computed from calendar-month grouping of the three existing schedule
files' `entry_ts`, ranked by trigger-count sum (profitability not
consulted, per the brief). **March 2025 selected**: T1=55, T2=75, T3=75,
sum=205, unique_regimes=75 — see `phase2/month_selection.csv` for the
full 12-month table (March was the clear maximum on every tie-break
criterion).

## Phase 2 — NT event-driven backtest

### Architecture

`SimpleFlipTriggerStrategy`, adapted from the already-audited
`fable5_nt_short_rth_policy_a/strategy.py`, with two simplifications per
the brief: no confirmation-timeout exit, and a single fixed
`entry_px ± 1.25×ATR` stop placed once at entry and never swapped. Entries
dispatch from a frozen precomputed schedule (the SPEC's own explicitly-
permitted fallback, since no NT strategy anywhere in this repo scores an
ML model live — verified by a dedicated research pass reading every
`Strategy` subclass and every `features.engine` importer). Regime state
for the exit logic (bearish-flip confirmation, then bullish-flip exit) is
genuinely recomputed live via the reused, already-audited `RegimeEngine`
— not looked up.

All decision-relevant logic (entry-direction thesis/opposing tracking,
stop-touch classification, PnL/excursion math) was extracted into a
plain-Python, NT-independent `trade_state.py` and hand-tested (21 pytest
cases, all passing) before being wired into the `Strategy`.

### Pre-execution audit (before the real run)

Caught **1 CRITICAL**: the original stop mechanism manually polled
`bar.high`/`bar.low` and submitted a FOK market order on touch, which
would fill at the bar's **close** rather than the stop's actual trigger
price — systematically understating every stop-loss. Fixed by placing a
genuine resting `stop_market` order (GTC, reduce_only) once at entry
fill. A follow-up targeted audit confirmed the fix and found 0 CRITICAL
remaining before the real `BacktestEngine` run was launched.

### Real run results (March 2025, full year of 1s+1m bars loaded, 3
independent strategy instances)

| Variant | Trades | Net PnL | PF | % reach bearish flip before stop | Gate |
|---|---|---|---|---|---|
| T1 (trig_B_top2.5) | 55 | $1,545 | 1.106 | 72.7% | **fails** (not-outlier-driven check: net PnL $1,545 < largest single winner $5,295) |
| T2 (trig_C30_top5) | 75 | $10,600 | 1.612 | 73.3% | **passes** |
| T3 (trig_B_top5) | 75 | $10,530 | 1.605 | 72.0% | **passes** |

All three variants: 0 skips (every scheduled entry filled). Exit-reason
breakdown (`phase2/exit_reason_summary.csv`): the `opposing_flip_exit`
bucket is the dominant, aggregate-positive contributor for all three
variants (e.g. T2: 48/75 trades, net $23,470), consistently outweighing
losses from both stop-exit buckets (`fixed_stop_before_bearish_flip`,
`fixed_stop_after_bearish_flip`).

Giveback diagnostics (`phase2/winner_giveback_counts.csv`, descriptive
only — no exit optimization performed per the brief's guardrail): a
meaningful fraction of trades that reach ≥1.0 ATR favorable excursion
still close as losers (e.g. T2: 18 of 50 such trades) — expected under a
fixed-stop/opposing-flip-exit scheme with no trailing protection, and
consistent with the already-closed `postalign_stop_helps` finding from
prior work.

### Parity checks — all three EXACT (required by SPEC, `SystemExit` on any
mismatch)

1. **Regime-transition parity**: NT's live `RegimeEngine` flip stream vs.
   the offline canonical 2025 timeline — 27,166/27,166 matched for every
   variant, 0 mismatches.
2. **Trigger-condition parity**: re-deriving the trigger flags fresh from
   the stored score column via the already-tested
   `trigger_logic.build_trigger_flags`, filtered to March 2025 — exact set
   match against each schedule's `(regime_start_ns, signal_decision_ts)`
   pairs (55/55, 75/75, 75/75).
3. **ATR/score parity**: join-and-compare against the source schedule —
   exact, by construction (no live rescoring occurs; the completion audit
   confirmed this is disclosed as construction-based, not hidden, and
   that the other two checks are genuine independent re-derivations that
   compensate).

### Completion-gate audit (full pipeline, post-execution)

**0 CRITICAL, 0 new WARNING, 4 NOTEs.** Independently re-verified rather
than trusted: re-ran `test_trade_state.py` fresh (21/21 pass), re-ran the
sibling precedent's full-`BacktestEngine` stop-fill fixture in isolation
to re-confirm a resting `stop_market` order fills at trigger price (not
bar close) under this study's exact dual-bar-feed engine config, traced
`reconcile.py`'s re-derivation functions to confirm they are genuine
independent re-derivations rather than tautologies, and hand-verified
`apply_gate.py`'s "not-one-outlier-driven" formula against T1's actual
numbers to confirm the fail is a real output of the stated rule, not a
sign-flip bug.

Notes recorded (none block the decision): (1) the ATR/score parity check
is self-disclosed as construction-tautological; (2) `max_mtm_dd` uses bar
close rather than high/low for intratrade mark-outs, understating true
intrabar drawdown — doesn't affect the gate since `apply_gate.py` never
reads it; (3) an inert month-bucketing column inconsistency between
`build_schedules.py` and `reconcile.py`, harmless for RTH hours but not
verified safe for a future ETH-inclusive reuse; (4) the SPEC's
"qualitative path evidence" gate criterion has no coded check and remains
a human-judgment step. One WARNING carried forward, unresolved, from the
original pre-execution audit: `build_schedules.py` discards the upstream
`entry_ts` column with no entry-timing parity check against actual NT
fill times (confirmed drift up to ~7s in 1-2% of rows) — immaterial to
this run's decision, should be closed before treating entry-timing
fidelity as fully proven in any future reuse.

## Phase 2 gate outcome

**Infrastructure gate: PASS** (0 CRITICAL, exact parity on all three
checks). **Economic gate: PASS** (T2 and T3 both clear net-positive, PF,
≥30 trades, ≥55% reach-bearish-flip, opposing-flip-bucket-positive, and
not-one-outlier-driven; at least one variant passing is sufficient per
SPEC). **Decision: `NT_POC_PROMISING_LONG_MODEL_NOT_RUN`** — per the
brief's own gate logic, this cleared the study to proceed to Phase 3.

## Phase 3 — descoped (not executed)

Before writing any Phase 3 code, scouting the actual implementation
(rather than trusting SPEC.md's own scout-pass finding) surfaced that the
assumption "reuse `short_rth_pure_flip_prediction_enriched`'s machinery
verbatim, mirrored" does not hold: that study's population traces through
`ohlcv_volume_delta_price_level_features` back to
`short_rth_entry_surface_backfill/entry_surface.py:69-71`, which drops
every bearish-regime (`direction == -1`) row at the very first funnel
stage, for all 6 years. `features/trackers/price_levels.py` already
supports a `direction=+1` parameter mechanically, but there is no
bearish-regime checkpoint population anywhere in the repo to attach it
to — confirmed via a repo-wide search of all 410 `studies/*/_work/*.parquet`
files.

Correctly mirroring Phase 3 requires: a new `entry_surface.py`-style
funnel inverted to keep `direction == -1` (with its `favorable` excursion
sign convention also inverted), a full 695-feature re-attachment run
across 2021-2026, fresh pure-arithmetic labeling
(`bullish_regime_flip_within_300s`), and a fresh GBT retrain — i.e.
rebuilding the equivalent of three prior full studies' pipelines
mirrored, not the scoped-down reuse this SPEC originally assumed.

Given that gap between frozen scope and actual required effort, the user
decided (2026-07-20) to **stop after Phase 2** and defer Phase 3 to a
separately-briefed future study rather than fold a multi-study-sized
rebuild into this session. No Phase 3 code, data, or results exist; this
is recorded explicitly rather than left ambiguous
(`phase3_status: "descoped_scope_gap_deferred"` in `final_decision.json`).

## Key takeaways for future work

1. The frozen-score architecture (dispatch from precomputed schedule +
   live regime recomputation for exits) is now proven, end-to-end, under
   a real NT `BacktestEngine`, with exact parity on all three independent
   checks — this pattern is reusable for any future frozen-score NT PoC
   without re-litigating the "live ML scoring vs. frozen scores" question.
2. `trig_C30_top5` (T2) and `trig_B_top5` (T3) both show comparable,
   real, economically positive results (PF ~1.6, ~$10.5-10.6K net over 75
   trades) that are causally reproducible in a genuine event-driven
   engine — a materially stronger form of evidence than any prior
   pandas-replay result in this line of studies. `trig_B_top2.5` (T1) is
   directionally positive but not gate-clean (outlier-driven).
3. The mirrored long-model idea is sound in principle but requires
   substantially more infrastructure than assumed — any future attempt
   should be scoped and briefed as its own multi-phase study, not treated
   as a same-session extension of a POC.
