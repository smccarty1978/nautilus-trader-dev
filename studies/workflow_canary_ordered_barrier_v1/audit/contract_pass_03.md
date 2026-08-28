# Contract Audit — Pass 03 (bounded re-audit)

**Study:** `workflow_canary_ordered_barrier_v1` (disposable Tier-1 workflow canary)
**Audited execution composite:** `3af4f5e71cd9f8930fafc8b2c83a900fd0dd11ea35f73eb984a6fb3aca286336`
**Prior passes:** `contract_pass_01.md` (CLEAR, 2 WARNINGs), `contract_pass_02.md` (CLEAR, 0).
**Mode:** PRE-EXECUTION / PRE-SEAL. No collect run, no seal, no authorization, no TRAIN freeze.
**Delta reviewed this pass:** `research_workflow/target_runtime.py` only —
`OrderedBarrierTargetRuntime.ingest_bar` now retains `"open"` in each appended
`pending["events"]` entry (previously `ts`/`high`/`low`/`gap`). Purpose: let
`target_replay_oracle.replay` re-derive the `next_bar_open` entry reference from the event
tape alone. Plus 2 test additions. All other pass-02 findings carried by reference.

## Composite / lifecycle freshness

- `frozen_execution_manifest.json` `frozen_execution_composite_sha256` = `3af4f5e7…6336`
  = `preflight.json` `execution_composite_sha256` = `readiness.json`
  `prepared_execution_identity`. PREPARE re-run (`generated_at_utc` 21:16:28). **PASS.**
- `compiled_study_sha256` = `d5b0d9dc…5134` — **unchanged** since pass 01.
  `compiled_study.json` / `study.yaml` / `config/*` / `SPEC.md` untouched — only
  `target_runtime.py` (already inside the execution closure) + test files changed. No
  spec-hash restamp. **PASS.**
- preflight `status: CLEAR`, `required_checks_missing: []`, `checks_complete: true`
  (8/8 checks PASSED). readiness `overall_status: PASS` (R1–R10). **PASS.**
- No seal / `experiment_authorization.json` / `train_experiment_freeze.json` /
  `audit/status.json` exists — nothing downstream to be staled. **PASS.**

## Prior findings adjudicated

| Finding | Status | Evidence |
|---|---|---|
| Pass-01 WARNING 1 — compiled `target.condition_logic: "AND"` over a `flip` condition + an `ordered_barrier` condition; compiler sets `primitive: "ordered_barrier"` from mere presence of `conditions` and the collector dispatches to a single `TargetRuntime`, so `flip_within_60s` is never conjoined and the emitted label reflects only the barrier race. | **CARRY as NOTE** | `research/engines/target_engine.py:116-118` and `resolve_target_runtime` unchanged this pass. Known framework limitation (also affects `clean_tradable_reversal`); immaterial to this canary (acceptance C1/C2 concern only the ordered-barrier binding; every declared terminal label reachable). Non-blocking follow-up: compiler should reject / stamp an unexecutable `condition_logic`. |
| Pass-01 WARNING 2 — stale `CANARY_BLOCKER.md` | **FIXED (pass 02)** | File absent; not reintroduced. |

## New-delta verification

| Requirement | Verdict | Evidence |
|---|---|---|
| No contract change | PASS | `target_runtime.py` edit is confined to `ingest_bar`'s in-memory `pending["events"]` append. Compiled `target_contract` (`primitive`, `entry_reference`, `ordered_barriers`, `session_end_censoring`, `max_gap_seconds`) untouched; `compiled_study_sha256` unchanged. |
| No persisted candidate / observation surface change | PASS | `pending["events"]` is a runtime-internal work list consumed only by `OrderedBarrierTargetRuntime.terminal`. `_emit_observation` (`generic_collector.py:707-749`) writes a fixed observation dict that never includes `events` or any per-bar `open`. `"open"` is not in `study.yaml` `metadata_columns` or the 5 feature aliases. readiness R10 for this composite: `emitted_feature_count: 5` (same features), `metadata_count: 4`, `unexpected_columns: []`, `candidate_rows_observed: 1` — byte-identical surface to passes 01/02. |
| No barrier-math change | PASS | `terminal` reads `e.get("high")` / `e.get("low")` / `e.get("gap")` only; the added `"open"` key is inert to the first-touch race. `open` is the same 1s bar's own open, already present in the event the collector passes to `ingest_bar` — no new data source, no timing shift. |
| Oracle independence improved, not weakened | PASS | `target_replay_oracle.replay` already branches on `independent = any("open" in e for e in evs)` (`target_replay_oracle.py:57`) and, when true, derives `entry_price` / `entry_ts` from the first taped event with `ts > T` rather than any pre-populated field (`:59-66`). Retaining `open` in the runtime's own event tape lets the collector-driven `validate_target_parity` path exercise that independent branch with real runtime events. `validate_target_parity` still gates `passed` on `disposition == 0 and label == 0 and censoring_mismatches == 0`. |
| No change to freeze / seal state | PASS | see "Composite / lifecycle freshness". |
| Terminal-label reachability / deliverables / research-decision fidelity | PASS (unchanged) | `config/deliverables_contract.json` unchanged (`authorized_modes: ["collect"]`, 5 deliverables); `terminal_decisions` WORKFLOW_CANARY_PASS/FAIL reachable; preflight `RESEARCH_DECISION_FIDELITY: PASSED`. |

## C4 / D / E

- **C4**: NOT APPLICABLE — single fixed arm, no model selection.
- **D**: NOT APPLICABLE — no model trained or served.
- **E**: PASS — disposition/censoring reconciliation and the independent replay oracle are
  unchanged in behaviour; this delta only strengthens the tape-only derivation path.

## Referred to lookahead-auditor

- None new. The `entry_ts = ts - NS` / `fully_forward` entry-reference convention was
  referred in passes 01–02; `open` retention does not alter it (same bar, same instant).

## Blocking verdict

<!-- AUDIT_SUMMARY_V2_START -->
{
  "verdict": "CLEAR",
  "audit_type": "contract",
  "study": "workflow_canary_ordered_barrier_v1",
  "auditor": "contract-checker",
  "audited_execution_composite_sha256": "3af4f5e71cd9f8930fafc8b2c83a900fd0dd11ea35f73eb984a6fb3aca286336",
  "blocking": 0,
  "critical": 0,
  "warning": 0,
  "not_verified": 0
}
<!-- AUDIT_SUMMARY_V2_END -->

**CLEAR.** Retaining `"open"` in `OrderedBarrierTargetRuntime.ingest_bar`'s internal event
list is a pure additive change to a runtime work structure that never reaches a persisted
surface. No contract field, barrier calculation, timing convention, compiled-study hash,
or freeze/seal artifact is affected (readiness R10 shows a byte-identical 5-feature /
4-metadata surface with `unexpected_columns: []`; `compiled_study_sha256` unchanged; no
seal exists). It strengthens `target_replay_oracle.replay`'s genuine independence by
letting the parity harness feed it real runtime events. Pass-01 WARNING 2 remains fixed;
pass-01 WARNING 1 (unexecutable composite `AND` logic) is carried forward as a documented,
non-blocking framework limitation. No new contract or governance defect.
