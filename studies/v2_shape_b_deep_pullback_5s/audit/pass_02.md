# Look-Ahead & Timestamp Audit — Pass 02 (delta)

**Date** 2026-09-02 · **Scope** `compiled_plan.json` (streams/availability_table delta), `research_workflow/grammar/compiler.py`
(role-assignment change), `research_workflow/host/mux.py` (mechanism re-verification, unchanged file)
**Scope hash (audited composite)** `0db52eeff6bbe048a4bf6adb8652df4aa94b14915e1f311a851a2b5ebd7fcca0`
**Lint** preflight CLEAR; readiness overall PASS (34/34 tests, up from 33) · **Verdict** CLEAR

## Summary
Critical: 0 · Warning: 1 · Note: 1

## Prior findings adjudicated
| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | [pass_01 Warning, B9] `features/trackers/host_bindings.py:690-691` — `FrozenExternalScoreBinding.derive` stamps every Model-C input's `availability_ts` as `epoch.T`, so `FrozenExternalModelScorer.score()`'s `future = [... > checkpoint_ts]` guard is vacuous | **NOT FIXED (unrelated to this delta)** | This platform change (compiler.py role assignment) does not touch `host_bindings.py` or `external_model_scoring.py`; `research_workflow/external_model_scoring.py` hash is unchanged (`7c7095c7...`) between the two closures. Re-read `derive()`: the call site still passes `availability_ts={n: ts for n in surf}`. Carried forward as open, not re-itemized further per the bounded re-audit rule. |

(Shape B pass_01 did not separately file the `nq_1m`-role/mux-visibility finding as its own item — it was raised only under Shape A's report and referenced generically; treated here as the same underlying mechanism, addressed below rather than as a formal adjudication row.)

## Checks performed (delta-scoped)
- **1m context enforcement, now in-code.** `compiled_plan.json:streams` shows `nq_1m: {"role": "context", "visibility": "strictly_before"}` (previously `execution`/`at_epoch`); `availability_table` shows `regime_1m` now `"visibility": "strictly_before"`. `research_workflow/host/mux.py` unchanged (hash `63f4b6...`): `ingest()` now queues `nq_1m` bars via `_context_queue`, releasing them only when a later execution-stream bar (`ts_init < before_ts`) arrives; `assert_epoch_visibility` now enforces `visible_through[nq_1m] < T` for real. Same mechanism verified for Shape A now applies here identically.
- **Derived 5s/5m unaffected, verified still correct under the new regime.** `nq_5s` (`derived_from: nq_1s`) and `nq_5m` (`derived_from: nq_1s`) both remain `role: "execution"` (unchanged — they are `source: "derived"`, not `external`, so the fix's scope — "every EXTERNAL timeframe coarser than the finest external" — does not touch them). The derived-bucket-before-source-bar delivery order inside `StreamMux._apply` (recursion before `self._deliver(bar)`) is untouched, so the trigger graph's `regime_5s.turned(...)` / `pullback` sub-epoch mechanism (pass_01's traced-clean finding) is unaffected by this change.
- **`pullback` tracker's `regime` input (`regime_1m`) is now itself delayed.** Since `pullback.on_event("regime", "changed")` and `pullback.on_bar` (which reads `regime_1m` state each 1s bar) now see `regime_1m` updates released only strictly-before the current `nq_1s` epoch, this only tightens (never loosens) the causal bound already assumed correct in pass_01's trace of `arm_ts`/`triggering_event_close_ts`/`counter_close_ts_at` — no new risk introduced.
- Day parity (B: 2021-01-01..05, 162 rows/46 cols) stated exact vs. the prior composite — consistent with this being a defense-in-depth fix rather than a value change, matching the same reasoning applied for Shape A.

## Notes
- (carried forward, open) `FrozenExternalScoreBinding`'s vacuous `availability_ts` — see adjudication row above; unaffected by this delta, remains a WARNING, smallest fix unchanged (thread each feature's true availability timestamp instead of a uniform `ts`).
- (carried forward) Asymmetric absolute-direction flip label (`target_direction=-1`) and `SplitSessionTable` (ALL/RTH) — unaffected, no new evidence, not re-itemized.

## Referred to contract-checker
- None new.

## Clean checks
A1-A5, B1-B7, B9, B10, C1-C3, F1-F4, G1-G4 clean. H1-H4 not applicable (label-only contract, no arms).

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "study": "v2_shape_b_deep_pullback_5s", "auditor": "lookahead-auditor", "audited_execution_composite_sha256": "0db52eeff6bbe048a4bf6adb8652df4aa94b14915e1f311a851a2b5ebd7fcca0", "critical": 0, "warning": 1, "note": 1}
<!-- AUDIT_SUMMARY_V2_END -->
