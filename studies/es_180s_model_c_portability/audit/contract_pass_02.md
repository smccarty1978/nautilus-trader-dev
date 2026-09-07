# CONTRACT AUDIT pass 02 — `es_180s_model_c_portability`

- auditor: `contract-checker:006_contract_audit_76b6bb2b`
- audited execution composite: `4f766f57344718f1416cc8f827f67bac8ed4f560b4b86f2fc921e1a7742797a1`
- phase B, pre-execution at this composite. Prior audit was at `da3d3ab4ee9b`; since then `fit` ran and
  succeeded, `freeze` died `KeyError: 'name'` (`_work/controller/failure_packet.json:12,29`), main's fix
  landed (`67ce07d3`, merged `be66e8de`), and the plan was recompiled.
- surface: brief gate facts + `audit_packet_contract.json` + the 2 changed closure files; targeted reads cited below.

## Adjudication of pass 01 findings

- **NOTE-1 (packet `model` block omits `cells`)** — NOT FIXED, carried. `git diff -- compiled_plan.json` in this
  worktree touches only `closure.*`, `plan_sha256`, `registry_sha256`; the `model.cells` block pass 01 verified is
  byte-identical, so the omission is unchanged and its content is still known-good. Platform remediation, not this study.
- **NOTE-2 (`GAP` inert in `resolution_precedence`)** — NOT FIXED, carried. `packet.outcome.semantics` unchanged
  (`max_gap_ns: null` on a `flip` kernel). Disclosure only.
- **NOTE-3 (`year_role_table` null)** — NOT FIXED, carried. Still null; still structural (`model.validation` is null)
  and still harmless with two year roles and nothing selecting on 2024.

No prior finding is re-raised under new framing.

## Requirements

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Deliverables declared for every stage that ran exist | PASS | brief §1: 6/6 present, non-zero bytes; `packet.deliverables_by_stage` is the V2 contract | tests PASS 132/0 @ `4f766f57` | — |
| Audited composite is current; gates ran at it | PASS | controller `execution_composite = current = plan_closure = 4f766f57`; preflight 8/8, readiness R1/R3/R5/R8/R9/R10 pass, all stamped `4f766f57` | — | — |
| Causal and contract identities distinct | PASS | causal `lookahead-auditor:005_causal_audit_ea737155` (CLEAR, `4f766f57`) vs. this report | — | — |
| TRAIN/OOS/prohibited disjoint; authorization not stale; OOS untouched | PASS | `packet.chronology` == `experiment_authorization.json`; `failure_packet.json:30 oos_accessed=false`; no `partitions/oos` receipt exists | — | — |
| **Changed surface** — freeze keys every (arm, cell) and binds the model store's real canonical bytes | PASS | `lifecycle_v2.py:1133-1145,1149-1151`; raises `FREEZE_CANONICAL_SHA_MISSING` rather than writing a null sha | `test_multi_arm_modeling.py:410-429` | — |
| **Changed surface** — OOS scoring is bound to the freeze's canonical bytes and each cell scores its own slice | PASS | `lifecycle_v2.py:1296-1313` builds `expect.canonical_sha256` from the freeze; `_score_models:1058-1069` authenticates then filters | `test_multi_arm_modeling.py:432-449` (asserts the two slices partition the scored population) | — |
| **Changed surface** — freeze precedes any OOS scoring; the OOS door is the only entry | PASS | `analyze` calls `assert_oos_open` (`:1254`) before touching `partitions/oos`, then requires the TRAIN freeze (`:1268-1271`); `oos` re-checks `TRAIN_CLOSURE_STALE` (`:1172-1174`) | — | — |
| **Changed surface** — an unrecognised `experiment_models.json` fails loudly | PASS | `lifecycle_v2.py:1314-1317` `OOS_MODEL_RECORDS_UNRECOGNISED` | — | — |
| **Changed surface** — the TRAIN freeze's provenance declaration is accurate | **WARNING** | `lifecycle_v2.py:1152-1153` — see WARNING-1 | none (no test asserts either field) | one line: read `models["new_models_trained"]` / per-cell metrics instead of keying on `model_id` |
| A stale fit artifact cannot be frozen | PASS (with NOTE-1) | `governed_controller.py:299-311` binds every receipt to `execution_composite`; `receipts/fit.json:2` is `da3d3ab4` ≠ current, so smoke/collection/reconcile/merge/fit all re-run; `scripts/research.py` exposes no direct `freeze` route | — | — |
| `research/analysis/diagnostic_ops.py` change affects this study | NOT APPLICABLE | `compiled_plan.json:2 "analysis": null`; `run_op` is reachable only from `_declared_analysis` (`lifecycle_v2.py:1186`), which `analyze` skips at `:1246` | — | — |
| **C4** no refit on the test window; selection seals authenticate their own result | PASS | unchanged plan: fit is TRAIN 2020–2023, `validation` null, no `search_space`, one arm; the new analyze branch only *scores* frozen models on 2024 and refits nothing (`:1296-1313`) | — | — |
| **D1** offline/live feature parity · **D2** post-filter cascade · **D3** ONNX export | NOT APPLICABLE | unchanged since pass 01: observational collection, no live strategy, no cascade, no export | R8 host_boundary_lint=pass | — |
| **D4** deterministic encodings, imputation, feature ordering | PASS | 13 numeric features, order fixed by `columns.features`; `random_state: 42`; scoring re-derives order from `manifest["lineage"]["ordered_inputs"]` and refuses on `MODEL_INPUTS_UNBOUND` (`:1061-1064`) | — | `check_model_binding.py` re-checks at fit |
| **E1/E2** bar subscriptions and `BarType` match the data loaded | PASS (gate-derived) | single declared instrument/dataset `ES_1S_V2_GLOBEX` digest `9f38a41e`; packet carries no `BarType` strings | R1_ES=pass, R5=pass | — |
| **E3** fill model / `LIMIT` auto-fill | NOT APPLICABLE | no orders, no venue simulation | — | — |
| **E4** entry not on the just-closed bar · **E5** warmup respected | PASS | unchanged: `entry_reference: next_bar_open`; `warmup` 5 days, `candidate_emission:false`, `target_generation:false` | — | — |
| Thresholds/deciles `derivation_population`, partition reconciliation, outcome-manifest self-description | NOT APPLICABLE (this pass) | freeze/oos/collection have not run at this composite; the plan declares no thresholds (`freeze` writes `thresholds: {} / deciles: {}`) | — | re-audit post-execution |

## Findings

**WARNING-1 — the TRAIN freeze will declare `new_models_trained: false` and `metrics: null` for this study's
two natively-trained ES models.** `lifecycle_v2.py:1152-1153` still keys both fields on the top-level `model_id`
that a multi-cell fit never writes (`:966,974-978` set it only when `len(trained) == 1`), while the fit body itself
records `"new_models_trained": True` (`:972`) and keeps metrics per cell (`:960`). `67ce07d3` swept exactly this
`models.get("model_id")` assumption out of `model_hashes` and `model_canonical_sha256` two lines above, and left
these two fields behind. Failure path: this study fits `primary:LONG` and `primary:SHORT`; after `freeze`,
`train_experiment_freeze.json` — the artifact a reuse path and `scripts/platform_v2_cards.py:62,116` read — states
that no new models were trained and carries no TRAIN metrics, directly contradicting the study's headline claim
("trained natively on ES 2020-2023") and its own `experiment_models.json`. The OOS numbers are unaffected; the
provenance record is false. No test asserts either field (`test_multi_arm_modeling.py` covers keying and binding only).
Smallest remediation: `bool(models.get("new_models_trained") or models.get("model_id"))`, and fall back to the
per-cell metrics when `models["metrics"]` is absent; add one assertion to the existing freeze test.

**NOTE-1 — `subset` defaults silently, so a pre-fix multi-cell record would be scored undirected.**
`lifecycle_v2.py:1308,1312` and `_score_models:1066` treat a missing `subset` as "no filter", unlike the sibling
helpers `_model_record_name` / `_model_record_id`, which raise. `artifacts/experiment_models.json` on disk right now
is exactly such a record: two cells, no `subset` key, written at plan `e9faf3b0` under composite `da3d3ab4`. Fed to
the fixed analyze it would score the LONG and SHORT models over the identical undirected 2024 population and report
two per-cell metric sets that are silently wrong. Not reachable here: `receipts/fit.json:2` is bound to the
superseded composite, so `_receipt_current` (`governed_controller.py:302-311`) forces a refit under the fixed code,
and there is no CLI route to `freeze`/`analyze` outside the controller. Remediation: raise when a record carries
`arm`/`cell` but no `subset` key.

**NOTE-2 — every on-disk execution artifact is bound to the superseded composite.** `preexec_audit_seal.json`
(`execution_manifest_composite_sha256: da3d3ab4`, `registry_sha256: 0fc9abf5`), `audit/contract_status.json`
(pass 01) and all five stage receipts predate `4f766f57`. This is the expected shape of a re-audit before re-seal
(controller state `NEEDS_CONTRACT_AUDIT`), recorded so no reader mistakes the on-disk seal for authentication of
the current composite. Smoke, collection, reconcile, merge and fit all re-run.

**NOTE-3 / NOTE-4 / NOTE-5 — pass 01's three notes, carried unfixed** (packet omits `model.cells`; `GAP` inert in
`resolution_precedence`; `year_role_table` null). Adjudicated above; all disclosure-only, all platform-side.

## Referred to lookahead-auditor

None. Causality at this composite was cleared by `lookahead-auditor:005_causal_audit_ea737155` (critical 0 / warning 0 / note 6).

## Blocking verdict

**BLOCKED** on WARNING-1. Everything the fix set out to do is verified: freeze now keys and byte-binds both direction
cells, analyze authenticates each against the freeze's canonical sha and scores it on its own slice, an unrecognised
record raises instead of writing an empty deliverable, and the OOS door plus TRAIN-freeze precondition are enforced in
code with tests. Composite, plan, spec, preflight, readiness and tests all agree at `4f766f57`; chronology and
authorization are disjoint and untouched. What remains is the last two fields of the same payload the fix repaired:
the TRAIN freeze this study is about to write would assert that it trained no new models and carry no TRAIN metrics.
That is a one-line platform correction, and it is far cheaper now than after the freeze is written and sealed into the
study's permanent record. Requirements depending on stages not yet run at this composite are recorded NOT APPLICABLE;
this verdict does not vouch for them.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "contract", "study": "es_180s_model_c_portability", "auditor": "contract-checker:006_contract_audit_76b6bb2b", "audited_execution_composite_sha256": "4f766f57344718f1416cc8f827f67bac8ed4f560b4b86f2fc921e1a7742797a1", "critical": 0, "warning": 1, "note": 5}
<!-- AUDIT_SUMMARY_V2_END -->
