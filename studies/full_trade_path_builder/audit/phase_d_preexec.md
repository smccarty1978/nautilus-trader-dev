# Phase D Pre-Execution Look-Ahead & Timestamp Audit

**Date:** 2026-07-25  
**Scope:** Estimate, frozen Phase D task packet/configuration, endpoint construction, NT path strategy, monthly runner, core test, accepted Phase B/C inputs, and final specification §§9, 12–17  
**Auditor:** lookahead-auditor v1  
**Scope hash:** `65c3a3e1c48cde58b51b6a7cdc71390a78921bf90352bb941aa2b981d245eef9`

## Summary

- Critical: 0
- Warning: 0
- Note: 0
- Verdict: **PASS — Phase D production execution is authorized**

## Findings

None.

## Clean checks

### Phase B flip and score provenance

- Every consumed `confirmed_flips.parquet` is checked against a complete monthly Phase B manifest.
- Each flip artifact must match its manifest hash.
- The deduplicated global flip ledger is hashed deterministically.
- Its digest must equal the accepted Phase B `global_label_manifest.json` ledger hash.
- Every Phase B score artifact is verified before path collection.
- Monthly manifests record all carried-score input hashes.
- Resume validation rehashes each recorded score artifact and fails on any mismatch.
- The canonical accepted Phase B root is enforced.

### Phase C input provenance

- The canonical accepted Phase C root is enforced.
- The global Phase C manifest must be complete with exactly 5,836 selections.
- Accepted independent parity must remain `PASS` with 5,836 selections.
- Each monthly Phase C manifest must be complete.
- Each monthly execution identity must equal the accepted global Phase C identity.
- Every selection parquet must match its monthly manifest hash.

### Threshold binding

- Phase D YAML carries all available frozen opposite-model thresholds.
- Bullish Top-10, Top-5, and Top-2.5 values are parsed from the frozen Bullish source.
- Bearish Top-5 and Top-2.5 values are parsed from the frozen Bearish source.
- Bearish Top-10 remains explicitly unavailable.
- YAML values must exactly equal frozen source values.
- Top-2.5 values must also equal the authorized overlap waiver.
- Waiver authorization is required.
- Inclusive `>=` membership is enforced.
- Validated thresholds are passed explicitly into the NT strategy.
- Phase D identity binds source hashes and the executed threshold contract.
- No threshold is recomputed from Phase B output.

### Endpoint construction and release

- Confirmation is the accepted flip attached by Phase C.
- Fallback is the first accepted opposite-direction flip strictly after confirmation.
- `bisect_right` excludes same-time fallback candidates.
- Trades without observable fallback are planned as right-censored at the seal.
- Future endpoint facts remain descriptive and do not affect selection or model values.
- The fallback boundary changes path state only when replay reaches its timestamp.

### NT timestamp semantics

- All path rows and running-state updates occur in one-second NT callbacks.
- Source bars require `ts_event < ts_init`.
- The first path bar has `ts_event >= checkpoint_decision_ns`.
- `timestamp_open_ns` uses `bar.ts_event`.
- `timestamp_close_ns` uses `bar.ts_init`.
- The fallback bar with `ts_init == fallback_exit_flip_ns` is included.
- The first bar after fallback is excluded and its open is stored separately.
- Regime state on a row ending at `T` includes only flips strictly before `T`.
- Scores available at `T` may attach to the completed row ending at `T`.
- Older valid scores carry their source timestamp, age, and carry flag.
- No catalog read crosses the sealed boundary.

### Economics and extrema

- Long and short movement formulas use the correct high/low direction normalization.
- Running MFE begins at zero and remains nonnegative.
- Path adverse extrema and running MAE retain signed, normally nonpositive values.
- Summary MAE is the positive magnitude of the most adverse path value.
- New MFE and MAE timestamps use the completed one-second bar close.
- Entry revisits use intrabar high/low.
- Entry revisit plus a new favorable extreme is labeled `ordering_ambiguous_same_bar`.
- Fallback economics are named and computed as descriptive marks, not fills or realized PnL.

### Censoring and terminal state

- Missing fallback produces sealed-boundary censoring.
- A missing expected fallback boundary bar fails completed-path status and censors at the last observed bar.
- Censored trades store terminal mark price and timestamp.
- Completed fallback economics remain null for censored paths.
- The last observed row is marked final for censored paths.
- December entries remain in their entry-month partition.

### Resume, atomicity, and scale

- Runner, core, strategy, configuration, task packet, waiver, threshold sources, accepted parity, and completion audit are identity-bound.
- Existing output manifests must match current identity, selection input, flip ledger, carried-score inputs, plans, paths, and summaries.
- Plans and parquet outputs use atomic replacement.
- A manifest is written only after output artifacts and hashes exist.
- Incomplete manifests are rebuilt.
- Processing is bounded to one entry month at a time.
- The estimated row volume and maximum overlap remain compatible with the stated memory and disk plan.

## Compliance matrix

| Rule | Status |
|---|---|
| A1 | PASS |
| A2 | N/A |
| A3 | PASS |
| A4 | N/A |
| A5 | PASS |
| B1–B7 | N/A |
| C1–C2 | PASS |
| C3–C4 | N/A |
| D1 | PASS |
| D2 | N/A |
| D3–D4 | PASS |
| E1–E2 | PASS |
| E3–E4 | N/A |
| E5 | N/A |
| F1–F4 | PASS |
| G1 | N/A |
| G2 | PASS |
| G3–G4 | N/A |
| H1–H4 | N/A |

---

*Read-only static audit complete. The mandatory zero-critical/zero-warning pre-execution gate is satisfied.*
