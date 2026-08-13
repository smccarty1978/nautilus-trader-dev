# Contract-Checker — Pass 01

**Date:** 2026-08-12
**Scope:** SPEC §6–10 — C4, D, E, Deliverables Manifest, terminal labels, domain/completeness.
Causality (A, B, C1–C3, F, G, H) belongs to `lookahead-auditor`, which passed at pass 2
(0 critical / 0 warning / 1 note) and is not re-litigated here.
**Verdict:** BLOCKED — 1 blocking, 1 warning, 1 note, 1 not-verified.

Transcribed from the agent's report by the calling session; the contract-checker
toolset is read-only and cannot write its own status file.

## Adjudication of the referred finding

**N1 — gate V11 tautology (referred by `lookahead-auditor` passes 1 and 2). FIXED.**
`validate.py:256-292` was rewritten between passes. V11 no longer reads the
already-deduplicated `price_only_diagnostics.csv`; it re-derives triggers from
`recovery_state_panel.parquet` via `_triggers()`, independently computes the
earliest qualifying `decision_ts` per trade per `(D, lvl, T)`, and asserts the
retained row matches. Same standard as the V3 fix.

## Blocking

### [B1] `results/recovery_state_panel.parquet` missing `path='UNCONSTRAINED'` — manifest item 9
`arms.py:340-348` built the `key` dict without a `path` field and `build.py`
wrote the panel unchanged; only `phases.py` ever assigned `path`, and only on
derived CSV tables. Gate V8 (`validate.py:221-232`) listed seven CSVs and never
opened either panel, so the missing column was invisible to a 14/14-passing gate
suite.

**Resolved.** `arms.py::horizon_states` now sets `key["path"] = PATH_UNC`. V8 was
widened to cover `recovery_state_panel.parquet` and to assert the panel carries
no label other than `UNCONSTRAINED` — a `STOP_LIVE` row there would mean
stop-truncated data had reached a descriptive table. `tests/test_v8_path_labelling.py`
pins the gate in both directions, including the exact defect that shipped.
Re-ran `--stage all`: 14/14 gates, 356,988 panel rows all `UNCONSTRAINED`,
0 nulls, terminal label unchanged.

## Warning

### [W1] Manifest column-name drift
Several tables emit manifest quantities under different literals. No quantity is
missing. Recorded in **SPEC Amendment A1** rather than renamed, because the
emitted names are load-bearing for `validate.py`, the tests, and the artifacts.
`exit_now_hwm_atr_CONTRAST_ONLY` is a deliberate §7.4 safety name, not drift —
the suffix is what makes gate V3 enforceable.

## Note

### [N2] Terminal-label thresholds are not §5 grid members
`MATERIAL_ATR = 0.05`, control-win-rate `< 0.25`, monotone-cell count `>= 2`,
inversion `< 0.5`, loser:winner `>= 2.0`. §5 governs thresholds appearing in
results; these appear only in the label decision. Disclosed in **SPEC Amendment
A2** and `REPORT.md` §9. Six of seven clauses fail by wide margins (0.0023 vs
0.05; 0.833 vs 0.5), so the R4 label is not threshold-sensitive.

## Not verified

**E — warmup fidelity.** The window is the accepted
`top10_fast_confirm_runner_path.prepare()`, inherited per SPEC §3 rather than
re-derived. Its warmup correctness was validated in the predecessor study and is
cited, not re-audited.

## Pass

| Requirement | Verdict |
|---|---|
| Terminal-label reachability R1–R4 | PASS — all four branches reachable; R4 is the residual `else` |
| Domain & completeness (SPEC §9) | PASS — V9 checks partitions per cell **and** per year; underpowered NULLs with counts visible; `EMPTY_CELL` emitted, never dropped |
| Seal integrity (SPEC §3, V1) | PASS — CT-converted timestamps, enforced at source scan, re-derived in `validate.py` |
| C4 — walk-forward / promotion gates | NOT APPLICABLE — no model trained; V3 confirms 0 forbidden imports |
| D — train/serve skew | NOT APPLICABLE — no model, no serving path, no artifact |
| E — fill model | PASS — bar j+1 OPEN, cross-checked bar-for-bar against the accepted `Window.realise` (V10) |
