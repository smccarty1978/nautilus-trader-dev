---
audit_type: "contract"
study: v2_shape_c_barrier_race_fade
auditor: contract-checker
---

# Contract & Governance Audit — v2_shape_c_barrier_race_fade — pass 02

Re-audit trigger: new composite `ecfb18141c0ac4cde99b38ad59c2457cb4e833f51af2e4a14994d5bed976a57f`
(`audit/frozen_execution_manifest.json`, generated `2026-09-02T20:21:18Z`), following (1) the
declared `outcome.horizon_end_rule: first_bar_at_or_after` and (2) the `model.models[*].subset`
correction (LONG cells → `regime_direction: 1`, SHORT cells → `regime_direction: -1`). Packet
(`_work/controller/audit_packet_contract.json`) is current — its `identity.execution_composite_sha256`
matches the manifest and its `worktree_dirty_paths` includes `audit/pass_03.md`, confirming it
was regenerated after the causal pass 03 ingest.

Model store re-verified at the corrected path `.nt_research\models\models\<id>\manifest.json`
(the `registry\<id>\` path named in an earlier task does not exist).

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Plan bound to current spec | PASS | `compiled_plan.json:883` plan_sha256=`5655c7fbf30180566076fb433bc615ae1846c9b3ecdb25da6b40a1b43d866831`, `:996` spec_sha256=`6af88d1207b9c60f3f81bfa3a97aa772df4430c76d3c12fea20194dd3f3cd069`; both changed from pass 01 (spec edited to add `horizon_end_rule` and correct `subset`), and both match the packet and `frozen_execution_manifest.json` exactly | `readiness.json` `PLAN_BOUND_TO_SPEC`=PASSED | none |
| `horizon_end_rule: first_bar_at_or_after` declared and compiled | PASS | `study.yaml:65` (with authority citation comment); `compiled_plan.json:846` `"horizon_end_rule": "first_bar_at_or_after"` | Causal pass 03 (`audit/status.json`) reviewed this as a declared temporal semantic of the sealed target authority and returned `verdict: CLEAR`, `critical: 0` | none |
| `model.models[*].subset` correction: LONG→+1, SHORT→-1 | PASS | `study.yaml:83-88`: all three LONG cells now `regime_direction: 1`, all three SHORT cells `regime_direction: -1` (inverted from pass 01). `compiled_plan.json:759-803` mirrors this exactly for all six model entries in the same id order | — | none |
| Six model ids, labels unchanged from pass 01 | PASS | Same six ids as pass 01 (`a9878a03...`, `98ab6190...`, `546e1a09...`, `1b285fe3...`, `45c2c622...`, `36ba0ed6...`) each still mapped to `target_tp1_sl0_5_label` / `target_tp1_sl1_0_label` / `target_tp1_sl1_5_label` per SL tier, matching the corresponding entries in `.nt_research\models\models\<id>\manifest.json` (`tier: registry`, `selection_status: selected`, `lineage.train_years: [2021]` only) verified in pass 01 — no id, hash, or label changed | — | none |
| Primary arm and expiry unchanged | PASS | `compiled_plan.json:877` `primary_arm: "barrier_tp_1_0_sl_1_0"`; all three arms still `"expiry": "censor"` (lines 815, 823, 831) | — | none |
| `model.mode: score` unchanged | PASS | `study.yaml:80` `mode: score`; `compiled_plan.json:756` `"mode": "score"`; packet top-level `model` block still `{"arms": [], "family": null, "params": {}, "validation": null}` | — | none |
| Chronology unchanged | PASS | `study.yaml:74-78` train=[2021], dev=[2022], prohibited=[2023-2026]; `artifacts/experiment_authorization.json` regenerated at `2026-09-02T20:21:18Z` with identical years | `readiness.json` `CHRONOLOGY_ROLE_TABLE`=PASSED | none |
| Readiness PASS bound to new composite | PASS | `overall_status: PASS`, composite matches; R9 `current=ecfb18141c0a frozen=ecfb18141c0a`; R5 "16 primitives bound; unbound=[]" | R1/R3/R5/R8/R9 all `passed: true` | none |
| Preflight CLEAR bound to new composite | PASS | `status: CLEAR`, composite matches; all 7 required checks PASSED | — | none |
| Tests PASS bound to new composite | PASS | 36 passed / 0 failed (up from 34 in pass 01, consistent with new coverage for the horizon-end-rule and subset-correction changes), composite matches | 3 test files | none |
| Causal status CLEAR, distinct auditor, bound to new composite | PASS | `audit/status.json`: `audit_report_path: pass_03.md`, `verdict: CLEAR`, `auditor: lookahead-auditor`, composite matches, `critical: 0` (correctly re-audited, not a stale pass_02 carryover) | — | none |
| No study Python | PASS | Unchanged from pass 01; no new files introduced by this delta | — | none |

## Referred to lookahead-auditor
None — causal pass 03 already reviewed and cleared the `horizon_end_rule` temporal semantic under distinct identity `lookahead-auditor`.

## Blocking verdict
CLEAR

All lifecycle artifacts (readiness, preflight, causal status pass 03, tests, authorization) reconcile to the new audited composite `ecfb18141c0a...`. The plan is bound to the current (edited) spec, with both hashes changed together consistently. The two declared deltas — `horizon_end_rule: first_bar_at_or_after` and the LONG/SHORT `subset.regime_direction` correction — are both compiled into `compiled_plan.json` exactly as declared in `study.yaml`, and causal review has already cleared the horizon-end-rule semantic. The six model ids, their labels, the primary arm, and censor expiry are unchanged and re-verified against the live model store. Chronology is unchanged and disjoint. No governance violation found.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "study": "v2_shape_c_barrier_race_fade", "auditor": "contract-checker", "audited_execution_composite_sha256": "ecfb18141c0ac4cde99b38ad59c2457cb4e833f51af2e4a14994d5bed976a57f", "critical": 0, "warning": 0, "note": 1}
<!-- AUDIT_SUMMARY_V2_END -->
