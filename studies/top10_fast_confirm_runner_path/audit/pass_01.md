# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-10
**Scope:** SPEC.md §2/§4/§8; implementation/engine.py, build.py, validate.py;
analysis/phases.py, policies.py. Shared upstream (`model_driven_entry_exit_discovery/
implementation/engine.py`) reviewed only for interface causality (MarketData,
RegimeIndex, index_*, next_start_after) — not re-audited in full, per predecessor
audit note.
**Scope hash:** e451d8f3bd5bf04c0ab8d165de5b2ac2b1b2208deb5986d50244145d6770ec0
**Lint:** 0 critical / 0 warning (`causal_lint.py`, 9 files scanned)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 0
- Note: 3

## Method
No `audit_packet.json` / prior git history exists for this study (new untracked
directory), so full files were read rather than diffed. Ran `causal_lint.py`
(clean) and cross-checked the seven "key claims" against `engine.py`,
`policies.py`, and the already-materialized `results/validation_report.json`
(all 14 non-audit gates pass; reconciliation matches accepted baseline
`-0.0765` vs `-0.0742` and pool `0.898` vs `0.899`, both within the 0.005
tolerance) to confirm static analysis against the actual run.

## Critical findings
None.

## Verification of the seven key claims

1. **Landmark bound `[0..j]` (§4).** Verified by code trace. `run_mfe`,
   `run_mae`, `last_ext` are `np.maximum.accumulate` outputs — cumulative-max
   arrays are causal by construction: the value at index `j` depends only on
   entries `≤ j` regardless of how much of the array was materialized. `new_ext`
   (`engine.py:286` / `:159`) is `bar_hi[k] > run_mfe[k-1]`, a per-index
   comparison against the *prior* cummax value, likewise causal at every index
   independent of array extent. All landmark fields (`engine.py:305–327`) index
   or slice only through `j`; `prog_mfe/mark_*` bound `j_W ≥ ci` by construction
   of the null condition (`ts[j]-confirm_ns < W·NS`). Clean.

2. **`eventual_max_mfe_atr` label-only.** `STATE_VARS` (`engine.py:54–60`)
   excludes it; it appears only in output dicts, Phase 6/7/8/9/11 stratification
   and descriptive fields (`gb*_remaining_mfe`, `stall_additional_mfe`), and in
   `policies.py` only in `evaluate()`'s output dict and `runner_destruction()`
   diagnostics — never in `trig_progress`/`trig_stall_dd`. Clean.

3. **Causal fill for triggers.** `Window.realise(i, fill_next=True)`
   (`engine.py:101–112`) fills at `market.open_[start+i+1]`; both Phase-12
   triggers and the placebo call with `fill_next=True`. Clean. **Disclosure**
   (not a defect — see Notes): the OPPOSING_FLIP/SESSION terminal (`nat_i`/
   `unc_i` when not stopped) fills at that bar's own close (`fill_next=False`),
   not the next bar's open, because the regime-flip decision is dispatched
   concurrently with that bar's close (same convention as the already-audited
   predecessor `simulate()`, `model_driven_entry_exit_discovery/.../engine.py:313–329`).
   Reconciliation against the previously-accepted baseline (`-0.0742`/`0.899`)
   confirms this is the same convention used to produce those accepted numbers,
   not a new divergence.

4. **Session containment.** `prepare()`/`walk()` clamp `end` to
   `sess_end = searchsorted(day_close_ns, ..., side='right')` and to
   `market.n`; `MarketData` loads RTH-only rows. Gate `session_containment_
   no_overnight` passed (0 violations, `validation_report.json`). Clean.

5. **Phase-12 triggers + placebo.** `trig_progress`/`trig_stall_dd`
   (`policies.py:62–88`) read only `w.mark`, `w.run_mfe`, `w.last_ext` up to
   the scanned index — each is causal at every index by the same cummax
   argument as #1. Placebo draws `rng.integers(w.ci, w.nat_i)` (half-open,
   matches `[ci, nat_i)`) and fills with `fill_next=True`. Clean.

6. **1.00 ATR stop always live for policies.** `acted = ti>=0 and ti<w.nat_i`
   (`policies.py:114`); `nat_i` already equals `stop_i` when the stop is hit
   first. A policy cannot act past `nat_i`. Clean.

7. **Phase 10 model score.** `build.py:model_context` filters
   `checkpoint_decision_ns >= confirm_ns` and joins on `new_regime_id` before
   the `join_asof(..., strategy="backward")`, so only within-new-regime,
   at-or-before-landmark dispatches are read. `score_at_confirm` uses
   `group_by(...).agg(pl.col("score").first())` on a frame pre-sorted by
   `checkpoint_decision_ns` — verified empirically (`polars 1.34`) that
   `.first()` respects pre-sort order within a group, not an arbitrary row.
   Clean.

## Warnings
None.

## Notes
- **N1 — fill-convention disclosure.** SPEC §2's fill rule text ("a trigger...
  fills at the FOLLOWING bar's open") reads as universal, but the
  OPPOSING_FLIP/SESSION terminal fills at that bar's own close (see claim 3).
  This is inherited, reconciles exactly against the accepted baseline, and is
  conceptually distinct from a "trigger" (the regime decision and that bar's
  close are dispatched at the same instant, not observed-then-reacted-to).
  Worth a one-line SPEC clarification; does not change any result.
- **N2 — dead code in the independent-replay gate.** `validate.py:146`
  computes `seg_hi` inside the gate-9/12 replay loop but never uses or asserts
  against it; the replay only checks `mark` (`ret_from_entry`), not the other
  landmark state variables. The causal-bound argument was independently
  re-verified here by direct code trace (claim 1), so the underlying
  computation is not in doubt, but the empirical replay is narrower than its
  "landmark state" claim suggests.
- **N3 — no-op filter.** `phases.py:401`
  `sd.filter(pl.col("landmark_s") == pl.col("landmark_s"))` is a tautology
  (self-comparison), evidently a leftover/typo; harmless (no rows dropped) but
  worth cleaning.

## Referred to contract-checker
- Gate `no_future_extreme_in_causal_state` (`validate.py:161`) is hardcoded
  `"passed": True` rather than computed — a test-quality gap (see N2), not a
  causal defect given independent manual verification above.
- `studies/top10_fast_confirm_runner_path/tests/` contains only `__init__.py`
  — no test files despite the study having a `tests/` directory.

## Clean checks
- A1–A5, B1–B10, C1–C3, F1–F4, G1–G4, H1–H4 verified clean.
- `causal_lint.py`: 0 critical / 0 warning.
- Reconciliation against accepted baseline/pool passed within tolerance
  (`validation_report.json`, gates 1–13 all `passed: true`).
