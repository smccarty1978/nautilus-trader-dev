# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-11
**Scope:** `SPEC.md`, `run_study.py`, `implementation/{common,candidates,features,labels_a,observations_b,train,validate}.py`, `analysis/gates.py` (full-file review; no prior commit exists for this study, so no diff was available — `audit_packet.json` absent)
**Scope hash:** `858ddc3fc493506dfe61e64edec0fc26f924a71b4fcf9d73b88c36cc0e4c20d2`
**Lint:** 0 critical / 0 warning (`causal_lint.py`, 13 files scanned)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 1
- Note: 1

## Prior fix verification (not a new finding — confirming the disclosed fix)
`p80_to_p90_seconds` cross-prime leak: confirmed fixed. `candidates.py` still computes the
raw `p80_ns`/`p90_ns` join on every candidate row, but `run_study.py:_causal_cross_prime`
(line 43-53) gates exposure to `max(p80_ns, p90_ns) <= candidate_ns`, and
`assert_no_future_reference` (line 56-71, gate V14) hard-asserts zero future references
against the underlying `cand` table before Stage 1 completes. Checked no other field has
the same shape: `n_recent_prime_crossings`, `seconds_since_P80/P90` in `features.py:130-143`
are computed from `p[:i+1]` — strictly bounded by the causal index `i`, within-regime, at or
before `t0` only. No other cross-prime/cross-regime field reads a value keyed to a second
population's later event without the same `<= candidate_ns` bound. Clean.

## Critical findings
None.

## Warnings

### [V7-scope] `implementation/validate.py:32-68` — Gate V7's hard-truncated replay does not cover FAM_STATE, only FAM_PATH
**Claim under test:** SPEC §13 V7 states the availability check is "Verified by HARD-TRUNCATED
replay ... ≥6 quantities each" for *both* `FAM_PATH` (`path_init_ns <= decision_ns`) and
`FAM_STATE` (`score_decision_ns <= decision_ns`). `replay_features` truncates `market` at
`hi_ns=t0` (`_truncated_market`, line 20-29) before rebuilding `PathContext` features — this
is a genuine independent replay for FAM_PATH. But the `ScoreHistory` object (`hist`) passed
into `replay_features` is never truncated; `score_state(hist, ..., t0, ...)` at line 50 is
called with the exact same untruncated `hist` and the exact same `t0` used at production
feature-build time (`run_study.py` Stage 1). Because `score_state`'s own windowing logic
(`np.searchsorted(ns, t0, side="right") - 1`, `features.py:99`) is the only thing being
exercised twice, the check is a self-consistency tautology for the STATE side, not an
independent hard-truncation proof — it would report `mismatches: 0, passed: True` even if
`score_state`'s boundary logic silently regressed to admit a future dispatch, because the
recomputation has access to the identical future rows the first computation did.
**Current results:** not affected — `score_state`'s boundary logic was verified causal by
direct inspection (`ns[i] <= t0` for the row actually used). No wrong number is currently
produced.
**Why it matters:** V7 is a frozen validation gate this SPEC (and V13/gate-passing) relies on
to catch a *future* regression in FAM_STATE causality; as written it cannot catch one.
**Smallest fix:** build a truncated `ScoreHistory` from `scores.filter(pl.col("score_decision_ns") <= hi_ns)` inside `replay_features`, mirroring `_truncated_market`, and pass that into `score_state` instead of the full-year `hist`.

## Notes

### [naming] `observations_b.py:212` reuses `PathContext.features`' `regime_start_ns` parameter as `entry_ns` for Model B
Cosmetically produces a feature still named `excursion_from_regime_start_atr` in the Model-B
matrix that is actually excursion-from-trade-entry. Not a causality defect (still `<= t0`,
still same-session-clamped) — the anchor is simply mis-named for Model B. No action required
for causality; flagged for the author's own hygiene pass.

## Referred to contract-checker
- `entry_atr` appears in both `bfeat` (feature frame) and `blab` (label frame) with a
  join suffix collision handled ad hoc (`run_study.py:606-610`) rather than declared once in
  the SPEC's feature/identity contract — deliverable-schema hygiene, not causality.

## Clean checks
- A1-A5 (timestamp conventions): `ts`/`path_init_ns` used throughout for PATH indexing; no
  `ts_event` used for gating; named `America/Chicago` zone everywhere; no fixed UTC offsets.
- B1-B7, B9 (feature look-ahead): no `center=True`, no `.shift(-N)`, no `bfill`; all rolling
  windows (`score_state`, `PathContext.features`) bounded above by `t0` via `searchsorted(...,
  side="right") - 1`/`side="left"` on the correct boundary; nulls never forward-filled.
- C1-C3 (labels): forward windows begin at `market.index_strictly_after(t0)` for Model A
  (`labels_a.py:57`) and at `r+1` (bar strictly after the causally-located rung index) for
  Model B (`observations_b.py:66`); primary/optimistic collision handling matches SPEC;
  fold assignment is a pure calendar function of `candidate_ns` (Model A) and `entry_ns`
  (Model B, gate V6 gates trade containment) — no random split found anywhere in
  `train.py`/`run_study.py` except bootstrap CI resampling, which is post-model evaluation,
  not fold assignment.
- F1-F4 (session handling): all windows clamped via `day_close_ns`/`sess_lo`/`sess_end`;
  no overnight stitching; RTH-only market load; named timezone; 15:00 CT forced flat
  respected in both Model A (`labels_a.py:62-68`) and Model B (inherited `prepare()`,
  `top10_fast_confirm_runner_path/implementation/engine.py:128-130`).
- G1-G4 (data integrity): loads from `regime_complete_v1` canonical store only (already
  `*.v.0`-sourced upstream); `assert_2024_only` checks actual timestamps, not partition
  columns, on every produced frame; no bar dropping/ffill logic present in this study's own
  code (relies on canonical store's own resampling, out of this study's scope).
- H1-H4 (bracket price resolution): Model A/B barrier detection uses `high`/`low` throughout
  (`labels_a.py:74-99`, `observations_b.py:58-101`); no `exit_pnl = (sl_px - entry_px)`
  pattern found; reference price is disclosed inherited `checkpoint_reference_price` with a
  `REF_NEXT_OPEN` sensitivity reported alongside (`labels_a.py:128-140`), matching SPEC §4.3's
  explicit disclosure — not a fresh finding.

---

## Remediation (study author, same day, after pass 01)

**WARNING 1 — V7 STATE-side replay was a tautology. FIXED.**
`implementation/validate.py::replay_features` now physically truncates BOTH time
bases. The dispatch rows are filtered to `score_decision_ns <= t0` and a fresh
`ScoreHistory` is constructed from what survives, mirroring `_truncated_market`
on the path side. The production `ScoreHistory` is no longer reachable from the
gate. Re-run result: **300 observations / 13,800 quantities / 0 mismatches**, so
the gate now earns the claim SPEC §13 V7 makes for it.

**NOTE 1 — `excursion_from_regime_start_atr` misnamed for Model B. FIXED.**
`PathContext.features` now takes `anchor_ns` plus an explicit `anchor_label`, and
`observations_b.py` passes `anchor_label="entry"`. Model B emits
`excursion_from_entry_atr`; Model A is unchanged. Naming only, no value changed.

**Referred item — `entry_atr` in both Model-B frames.** Handled in gate V4 rather
than deferred: `entry_atr` is `arm_atr`, frozen at entry and therefore known at
every rung, so it is declared as a decision-time identity field and excluded by
name — and, to stop the exclusion becoming a loophole, the two frames are asserted
to carry bit-identical values. If they ever diverged, one would be a re-derived
forward quantity and V4 would fail.

**Independent defect found by the author before this audit, recorded for lineage:**
`p80_to_p90_seconds` was exposed at P80 candidates, where it references a FUTURE
P90 crossing. It carried +0.267 permutation AUC and was the entire apparent P80
result (ABL_STATE 0.734 -> 0.531 once removed). Fixed at the source
(`_causal_cross_prime`), hard-asserted by new gate V14, all Model-A results
recomputed. Confirmed complete by this audit.
