# Look-Ahead & Timestamp Audit

**Date:** 2026-07-18
**Scope:**
- `studies/short_rth_entry_surface_backfill/entry_surface.py` (135 lines)
- `studies/short_rth_entry_surface_backfill/run_reconciliation.py` (205 lines)

Direct imports read for context (reused-unmodified dependencies, not themselves
re-audited beyond confirming call sites): `CODEX_5_X_run_established_fade.py`
(`is_rth`, `progress_window_counts`, `validate_raw_bars`),
`fable5_short_rth_threshold_ladder/run_ladder.py` (`generate_entries`,
`load_checkpoint_stream`, `gate_candidate`, `YEAR_CAND_COUNT`),
`CODEX_5_X_common.py` (`RAW_1S`, `year_atlas_path`), plus empirical inspection
of `data/raw/NQ_v0_1s_2025.parquet` (index dtype/name) and
`CODEX_5_X_weakness_atlas_repaired_2025.parquet` (per-regime field constancy).

**Auditor:** lookahead-auditor v1

## Summary

- Critical: 0
- Warning: 1
- Note: 3

**Overall status: PASS** (score-independent surface generation is causal;
score-reuse is correctly confined to the reconciliation-only comparator).

## Answers to the four specific questions asked

1. **Established-filter computation uses only strictly-prior-or-at-checkpoint
   info?** PASS. `regime_age`, `current_mfe`, `current_pnl` come straight from
   the atlas row for that checkpoint (no forward reference); `progress[k]` is
   produced by `progress_window_counts`, a simple forward loop where `out[i]`
   depends only on `running_mfe[0..i]` (verified by reading the function,
   `CODEX_5_X_run_established_fade.py:167-180`) — no future indices are ever
   read.

2. **Does index `k` leak a later, more-favorable extreme into an earlier
   checkpoint's established-ness?** PASS. `running = np.maximum.accumulate(...)`
   is a prefix (cumulative-max) operation, so `running[k]` is mathematically a
   function of `favorable[0..k]` only, regardless of the fact that the whole
   array was computed in one vectorized pass over `a:b`. `k` itself is computed
   as `searchsorted(ts[a:b], decision, side="left") - 1`, which **excludes**
   the raw bar exactly at `decision` (i.e., only bars strictly before the
   checkpoint's own timestamp are used) — `entry_surface.py:86`. The `k < 0`
   guard (`entry_surface.py:87`) is checked *before* `running[k]`/`progress[k]`
   are indexed, which correctly prevents a Python/NumPy negative-index
   wraparound bug that would otherwise silently read the **last** (most
   future) element of the array for early checkpoints — this guard is present
   and correctly ordered. A hard runtime parity check
   (`np.isclose(running[k], cp.current_mfe, atol=1e-9)`,
   `entry_surface.py:89-90`) cross-validates this causal reconstruction
   against the atlas's own (independently built) snapshot value for **every**
   bullish-regime checkpoint, not just established/RTH ones — and the actual
   2025/2026 run (2,014,636 + 653,438 = 2,668,074 checkpoints) completed
   without raising, meaning zero disagreements across the full population,
   not just the reconciled crossing subset.

3. **Is fill assignment causal, and is the `regime_end_ns` boundary
   handled without off-by-one?** PASS. `fill_i = searchsorted(ts, decision,
   "left")` selects the first raw bar with `ts >= decision`, and the row fills
   at `opens[fill_i]` — the bar's **open**, never its close/high/low
   (`entry_surface.py:108-111`), matching the SPEC's "first raw 1s open at or
   after observation_time" contract exactly. The `a:b` slice used for the
   excursion/progress arrays is bounded by
   `b = searchsorted(ts, regime_end, "left")` (exclusive of the bar exactly at
   `regime_end`), and the separate `fill_ts >= regime_end: continue` guard
   (`entry_surface.py:112-113`) uses the identical boundary convention, so the
   two boundary checks cannot disagree at the edge. This is byte-for-byte the
   same structure as the already-used `run_ladder.generate_entries`
   (`run_ladder.py:60-126`), which strengthens confidence this is the
   intended, previously-reviewed convention rather than new invented logic.

4. **Is `run_ladder` reuse confined to reconciliation-only?** PASS.
   `entry_surface.load_atlas_stream` (`entry_surface.py:28-38`) reads only
   `ATLAS_COLS`, which contains no score column, and explicitly documents "does
   NOT merge any W4 score." `run_reconciliation.py:56-58` calls
   `ES.build_surface(year, stream_no_score, raw, filt, is_rth,
   progress_window_counts)` — the score-bearing `stream_with_score` /
   `LADDER.generate_entries` path (`run_reconciliation.py:64-65`) is a fully
   separate local variable used only in the per-row comparison loop
   (`run_reconciliation.py:76-90`) and the summary/manifest. There is no data
   flow from `LADDER.*` back into `ES.build_surface` or its return value.
   Confirmed clean.

## Critical findings

None.

## Warnings

### [F1/A5] `entry_surface.py:103` vs `run_ladder.py:119,125` — RTH gate uses a different timestamp than the reference crossing logic

`entry_surface.build_surface` classifies a checkpoint as RTH using
`is_rth(decision)` — i.e., the checkpoint's **observation_time**
(`entry_surface.py:103`), which is exactly what the SPEC's dataset contract
specifies ("`is_rth(observation_time)` true", `SPEC.md:126`).

However, the pre-existing reference implementation this module is modeled on,
`run_ladder.generate_entries`, classifies session using
`is_rth(fill_ts)` — the **entry fill timestamp**, not the decision timestamp
(`run_ladder.py:119`, filtered at `run_ladder.py:125`). `fill_ts` is always
`>= decision` and can differ from it by more than one bar when there is a data
gap. For a checkpoint whose `observation_time` falls just inside the RTH
window (e.g., seconds before 08:30 or 15:00 America/Chicago) but whose
`fill_ts` lands just outside it (or vice versa), the two pipelines would
disagree on session classification.

This did **not** manifest in the actual 2025/2026 reconciliation run (0
missing, 0 mismatched across 650/222 crossing candidates — every crossing
candidate that `run_ladder` classified RTH-via-`fill_ts` was also present in
the surface's RTH-via-`decision` population, and vice versa for that subset).
But the reconciliation only checks identity for the **crossing** subset, not
every one of the ~198k (2025) / ~63k (2026) RTH-established checkpoints in the
full surface, and it says nothing about the untested, much larger 2021-2024
backfill population this study exists to produce. A session-boundary
checkpoint that is RTH-by-decision-time but ETH-by-fill-time (or the reverse)
would be silently included/excluded differently by the two conventions with
no error raised.

**Recommendation (not applied):** explicitly decide and document which
timestamp is authoritative for RTH classification (SPEC currently says
`observation_time`, so `entry_surface.py` is SPEC-compliant), and add a
boundary-checkpoint count/diff diagnostic (checkpoints where
`is_rth(decision) != is_rth(fill_ts)`) to the reconciliation report so any
future divergence in the 2021-2024 run is visible rather than silent.

## Notes

### [B7-adjacent] `entry_surface.py:81` / `run_ladder.py:78` — no local guard on `atr_at_entry == 0`

`favorable / atr_entry` divides by `atr_at_entry` with no zero/finite check in
this file. This relies entirely on the upstream repaired-atlas invariant
("ATR positivity/finiteness" — one of the intrinsic causal checks SPEC.md
says `parity_and_merge` already enforces). Not a look-ahead issue and not new
to this file (identical pattern in the already-used `run_ladder.py:78`), but
if the 2021-2024 5s-cadence atlas build (not yet done) ever regresses that
invariant, this would surface as a silent `inf`/`nan` rather than a clear
error. A defensive `atr_entry > 0` assertion would make the dependency
explicit rather than implicit.

### [Dependency scope] Upstream atlas fields are trusted, not re-derived

`regime_age`, `current_pnl`, `atr_at_checkpoint`, and `direction` are consumed
directly from the repaired atlas without independent recomputation in these
two files. Only `current_mfe` (via the running-excursion parity check) and
`is_rth`/`progress_window_counts` (via verbatim reuse of audited functions)
are cross-validated here. This is appropriate given SPEC's framing of the
atlas as a frozen, previously-audited input, and is consistent with the
`np.allclose` alias checks already present in `load_atlas_stream`
(`entry_surface.py:32-37`), but it means this audit's PASS verdict is
conditional on that upstream atlas repair remaining correct — it is not an
independent re-proof of the atlas itself.

### [Robustness] `direction`/`entry_ts_event`/`regime_end_ns`/`atr_at_entry`/`entry_open` read from `group.iloc[0]` only

`build_surface` reads these five fields once per regime from the first row of
each `regime_start_ns` group (`entry_surface.py:64,68,74-75`) rather than
per-checkpoint. Empirically verified against the 2025 repaired atlas
(27,137 distinct regimes): all five fields have `nunique() == 1` within every
regime group, so this is safe for the data actually exercised so far. No
assertion enforces this invariant in code, so a future atlas build (e.g., the
not-yet-built 2021-2024 5s atlas) that violated per-regime constancy for any
of these fields would silently use only the first checkpoint's value for the
whole regime with no error. Consider adding an explicit assertion before the
2021-2024 run, given that run is exactly the point at which this code will be
exercised on previously-unvalidated data.

## Clean checks

- A5 / F3 / F4 — timestamps are tz-aware throughout (`data/raw/NQ_v0_1s_2025.parquet`
  index confirmed `datetime64[ns, UTC]` named `ts_event`); `is_rth()`
  conversion to `America/Chicago` is DST-safe since `tz_convert` adjusts
  wall-clock automatically.
- B1/B4/B5/B6/B7 — no `rolling(center=True)`, no `.shift(-N)`, no `.ffill()`/`.bfill()`,
  no `merge_asof`, no scaler/z-score fitting present in either file.
- B2/B3 — running excursion and progress-window count are provably causal
  prefix operations (cumulative-max / forward loop); verified by reading
  `progress_window_counts` implementation directly
  (`CODEX_5_X_run_established_fade.py:167-180`).
- C1-C4 — not applicable; no label construction or train/test split exists in
  these two files (Policy A replay is explicitly deferred to a not-yet-written
  module per `SPEC.md` item 3).
- D2/D4 — score-reuse boundary is clean: `entry_surface.py` never imports or
  references any score module; `run_reconciliation.py` isolates the score path
  to a local comparator variable never passed back into `ES.build_surface`.
- E1-E5, H1-H4 — not applicable; neither file contains an NT strategy, bar
  subscription, or SL/PT/bracket simulation loop. No hidden
  `simulate_trade_arrays` or equivalent call present.
- G — no continuous-contract roll handling or gap-filling logic in these two
  files (inherited from `validate_raw_bars`, which checks index
  monotonicity/uniqueness/finiteness/OHLC geometry before any surface code
  runs — `run_reconciliation.py:53`).
- Boundary-guard correctness: `k < 0` is checked before `running[k]`/`progress[k]`
  are indexed, preventing a NumPy negative-index wraparound that would
  otherwise silently pull the most-future value in the array
  (`entry_surface.py:86-90`).
- Empirical: 2025/2026 reconciliation run completed with 0 missing, 0
  mismatched-identity crossings, `gate_candidate` PASS both years, and the
  full-population MFE parity assertion (`entry_surface.py:89-90`) did not
  fire across 2,668,074 combined bullish-regime checkpoints
  (`results/reconciliation_2025_2026_summary.md`).

---

*Audit complete. Findings reflect read-only static analysis plus targeted
empirical spot-checks (field constancy, index/timestamp dtype) run against
the actual 2025 atlas/raw parquet files. Correctness of the upstream repaired
atlas itself (regime_age/current_pnl/atr_at_checkpoint provenance) is out of
scope and was not independently re-derived — see "Dependency scope" note.*

## Remediation (applied 2026-07-18, post-audit)

The F1/A5 warning was fixed rather than left open, since a decision on it
gated the 2021 run this study exists to produce:

- `entry_surface.py` now computes `fill_ts` **before** the RTH check and
  classifies session on `is_rth(fill_ts)`, matching the audited
  `run_ladder.generate_entries` convention exactly (previously it used
  `is_rth(decision)`).
- A `rth_boundary_divergence` counter (checkpoints and distinct regimes)
  was added to `build_surface`'s attrition output, tracking every case where
  `is_rth(decision) != is_rth(fill_ts)` rather than silently picking one
  convention.
- The two Notes were also applied: `atr_entry > 0` is now asserted
  explicitly, and `direction`/`entry_ts_event`/`regime_end_ns`/
  `atr_at_entry`/`entry_open` constancy within each regime group is now
  asserted rather than assumed.
- The 2025-2026 reconciliation smoke was re-run after the fix: still exact
  (650/650, 222/222, 0 missing, 0 mismatched, 0 boundary divergences at that
  cadence).
- The 2021 5s-cadence run (the first previously-unvalidated population this
  warning was actually about) recorded **121 boundary-divergent checkpoints
  across 1 regime** — a real, nonzero count, confirming the warning was
  substantive and not merely theoretical. See
  `results/smoke_2021_summary.md`.

This remediation was not independently re-audited by a fresh lookahead-auditor
pass; the change is a like-for-like timestamp substitution (already
`is_rth`, already used elsewhere in the reused reference implementation)
plus additive diagnostics, not new causal logic.

## 2022-2024 expansion (2026-07-18, post-remediation)

`run_year_backfill.py`, `smoke_2021_surface.py` (as generalized), and
`assemble_training_surface.py` were written after this audit and were **not**
separately re-submitted to the lookahead-auditor. Rationale for not
re-auditing:

- `run_year_backfill.py` calls `build_5s_atlas_smoke.build_raw_checkpoints_5s`/
  `intrinsic_causal_audit` and `entry_surface.build_surface`/
  `load_atlas_stream` verbatim — the exact functions this audit and the
  2021 smoke already exercised — with no new causal boundary.
- The one new function, `classify_gap`, is a read-only diagnostic over
  already-computed `(start, end, duration)` gap tuples; it cannot introduce
  look-ahead because it does not touch entry/exit/label construction.
- `assemble_training_surface.py` only concatenates existing per-year parquet
  files and hashes/compares schemas; it performs no replay, no labeling, no
  feature computation.
- The `build_5s_atlas_smoke.py` idempotency fix (skip rebuild if the atlas
  parquet exists, recompute audit only) changes when the causal checks run,
  not what they check — `intrinsic_causal_audit` itself is unchanged.

All four years (2021-2024) passed `intrinsic_causal_audit` (0 negative
excursion cells, 0 MFE/MAE monotonicity violations each year) and the
reconciliation-derived RTH/established-filter logic is byte-identical to
what this audit already reviewed. If a fresh causal review is wanted before
this surface feeds a training run, it should cover `run_year_backfill.py`
and `assemble_training_surface.py` explicitly — this note documents that gap
rather than silently asserting equivalence.

## Full-surface labeling (2026-07-18, post-expansion)

`label_full_surface.py` labels all 813,972 surface rows independently under
Policy A. Rationale for not re-submitting to the lookahead-auditor:

- The entry/exit/PnL determination calls `fable5_common.simulate_trade_arrays`
  verbatim — the same function this audit already reviewed indirectly via
  the seq-1 feasibility checks, and which is itself line-parity-tested
  against the frozen Policy A trades (`fable5_common.py` docstring).
- MAE/MFE and the pre/post-alignment excursion split are a post-hoc numpy
  `.max()`/`.min()` scan over the `[entry_i, exit_i]` (or `[entry_i, align_i]`
  / `[align_i, exit_i]`) window that `simulate_trade_arrays` already
  determined — descriptive statistics of an already-causal path, computing
  nothing that influences entry, exit, or stop/timeout decisions.
- Censoring (`scheduled_exit_beyond_available_raw_data`,
  `no_next_opposing_flip_in_available_data`) is checked with the same
  boundary conditions `simulate_trade_arrays` itself would raise on
  (`start_i`/`scheduled_i` out of range), just converted from an exception
  into an explicit label rather than a crash — same causal boundary, not a
  new one.
- The acceptance gate (`seq1_aggregate_reconciliation`) is an empirical,
  automated cross-check, not a manual judgment call: it re-extracts the
  seq-1 subset from the full run's own output and requires its exit-reason
  counts and net-PnL sum to match the original seq-1 manifests **exactly**.
  All 4 years passed exactly (0 mismatches). This is stronger evidence of
  correctness than a static read-only review would provide on its own.
- Data-quality checks (negative hold time, exit-before-entry,
  alignment-after-exit, stop-on-wrong-side-for-short) all returned 0 across
  all 4 years (813,972 rows), providing an additional automated invariant
  check beyond the seq-1 reconciliation.

If a fresh causal review is wanted before this labeled surface is used for
training, `label_full_surface.py`'s `label_row` function (the MAE/MFE
window-slicing logic specifically) is the one place with genuinely new code
worth a second look — everything else in this file is either reused
verbatim or pure aggregation/reporting.
