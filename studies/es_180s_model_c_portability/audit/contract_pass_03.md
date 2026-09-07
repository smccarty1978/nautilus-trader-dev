# CONTRACT AUDIT pass 03 — `es_180s_model_c_portability`

- auditor: `contract-checker:009_contract_audit_9d99d5bb`
- audited execution composite: `6d44da61d0649a99f3491ee413ae449c71de8dd1aaf793b64aa8ddadc0bf0222`
- phase B, pre-execution at this composite. Prior audit was at `4f766f57`; since then one closure file changed
  (`research_workflow/lifecycle_v2.py` d107c8aed9cd -> 4afdce38d4fc) via `8cf5576e`, merged `a7f932b0`, merged `85a7724d`.
- surface: brief gate facts + `audit_packet_contract.json` + `git diff fd943207e35a..HEAD -- research_workflow/lifecycle_v2.py`;
  targeted reads cited below. No other closure file reopened.

## Adjudication of pass 02 findings

- **WARNING-1 (TRAIN freeze declares `new_models_trained: false` / `metrics: null` for a multi-cell fit)** — **FIXED.**
  `lifecycle_v2.py:1186` is now `bool(models.get("new_models_trained") or models.get("model_id"))` and the fit body
  writes `"new_models_trained": True` at `:1001`; `:1187` reads `_model_record_metrics(models)` (`:143-153`), which
  falls back to the per-cell `metrics` recorded at `:989`. Asserted by
  `research_workflow/tests/test_multi_arm_modeling.py:432-434` (`new_models_trained is True`, metrics keyed
  `{primary:LONG, primary:SHORT}`, non-null fold/final-validation metric).
- **NOTE-1 (missing `subset` defaults to "no filter")** — **FIXED**, beyond a note's requirement.
  `_model_record_subset` (`:127-140`) raises `MODEL_RECORD_SUBSET_MISSING` when a record carries `arm`/`cell` but no
  `subset`; both `analyze` call sites now use it (`:1342`, `:1346`), so `_score_models`'s permissive
  `m.get("subset") or {}` (`:1095`) can no longer be reached with an unslicing record. Test:
  `test_multi_arm_modeling.py:479-492`.
- **NOTE-2 (on-disk execution artifacts bound to the superseded composite)** — **NOT FIXED, carried, still expected.**
  `receipts/fit.json:2` is `da3d3ab4`, `packet.identity.seal.execution_manifest_composite_sha256` is `da3d3ab4`,
  `status.json:21 train_freeze: null`. Re-carried below as NOTE-4.
- **NOTE-3 / NOTE-4 / NOTE-5 (pass 01's three: packet omits `model.cells`; `GAP` inert; `year_role_table` null)** —
  **NOT FIXED, carried.** `packet.model` still has no `cells` key and `arms: []`; `packet.outcome.semantics` still has
  `max_gap_ns: null` on a `flip` kernel with `GAP` in `resolution_precedence`; `packet.year_role_table` is still `null`.
  All three are unchanged platform-side disclosures. Re-carried as NOTE-1..3.

No prior finding is re-raised under new framing.

## Requirements

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Deliverables declared for every stage that ran exist | PASS | brief §1: 6/6 present, non-zero bytes; `packet.deliverables_by_stage` is the V2 contract (no V1 `config/deliverables_contract.json` expected) | tests PASS 132/0 @ `6d44da61` | — |
| Audited composite is current; gates ran at it | PASS | `status.json:12-15` `execution_composite = current = plan_closure = 6d44da61`; preflight 8/8, readiness R1/R3/R5/R8/R9/R10 pass, all stamped `6d44da61` | — | — |
| Causal and contract identities distinct | PASS | causal `lookahead-auditor:008_causal_audit_0e982346` CLEAR @ `6d44da61` vs. this report | — | — |
| TRAIN/OOS/prohibited disjoint; authorization not stale; OOS untouched | PASS | `packet.chronology` == `experiment_authorization.json` (train 2020–23, dev 2024, prohibited 2025–26); no `_work/controller/partitions/oos` exists; `status.json:21 train_freeze: null` | — | — |
| **Changed surface** — freeze provenance is a fact of the fit, not of top-level mirroring | PASS | `lifecycle_v2.py:1186-1187`, `:143-153`, `:1001`, `:989` | `test_multi_arm_modeling.py:432-434` | — |
| **Changed surface** — a record without its population slice is refused, not silently unsliced | PASS | `lifecycle_v2.py:127-140`, used at `:1342,1346` | `test_multi_arm_modeling.py:479-492` | — |
| **Changed surface** — reuse/score path still declares provenance truthfully | PASS | score body writes `new_models_trained: False` (`:1126`); the no-protected-OOS freeze writes `False` (`:1145`); `:1186` propagates it | — | — |
| Freeze keys every (arm, cell) and binds the model store's real canonical bytes | PASS (unchanged) | `lifecycle_v2.py:1162-1174,1178-1180`; raises `FREEZE_CANONICAL_SHA_MISSING` rather than a null sha | `test_multi_arm_modeling.py:410-429` | — |
| A stale fit artifact cannot be frozen | PASS | `receipts/fit.json:2` is `da3d3ab4` ≠ current `6d44da61`, so smoke/collection/reconcile/merge/fit re-run before freeze; the pre-fix subset-less `experiment_models.json` is therefore unreachable *and* would now raise | — | — |
| **C4** no refit on the test window; selection seals authenticate their own result | PASS | unchanged plan: fit is TRAIN 2020–2023, `model.validation` empty, no search space; `analyze` only *scores* frozen models on 2024 and refits nothing (`:1339-1347`) | — | — |
| **D1** offline/live parity · **D2** post-filter cascade · **D3** ONNX export | NOT APPLICABLE | unchanged: observational collection, no live strategy, no cascade, no export | R8 host_boundary_lint=pass | — |
| **D4** deterministic encodings, imputation, feature ordering | PASS | 13 numeric features, order fixed by `packet.columns.features`; `random_state: 42`; scoring re-derives order from `manifest["lineage"]["ordered_inputs"]` and raises `MODEL_INPUTS_UNBOUND` (`:1090-1093`) | — | — |
| **E1/E2** bar subscriptions and `BarType` match the data loaded | PASS (gate-derived) | single instrument/dataset `ES_1S_V2_GLOBEX` digest `9f38a41e`; packet carries no `BarType` strings | R1_ES=pass, R5_binding_proof=pass | — |
| **E3** fill model / `LIMIT` auto-fill | NOT APPLICABLE | no orders, no venue simulation | — | — |
| **E4** entry not on the just-closed bar · **E5** warmup respected | PASS | unchanged: `entry_reference: next_bar_open`; warmup 5 days with `candidate_emission:false`, `target_generation:false` | — | — |
| Thresholds/deciles `derivation_population`, partition reconciliation, outcome-manifest self-description | NOT APPLICABLE (this pass) | freeze/oos have not run at this composite; the plan declares no thresholds (freeze writes `thresholds: {} / deciles: {}`) | — | re-audit post-execution |

## Findings

**NOTE-1 — packet `model` block omits `cells`** (`packet.model.arms: []`, no `cells` key). Carried from pass 01;
content verified good there and byte-identical since. Platform-side packet-rendering gap, not this study.

**NOTE-2 — `GAP` is inert in `resolution_precedence`** (`packet.outcome.semantics.max_gap_ns: null` on a `flip`
kernel). Disclosure only; unchanged.

**NOTE-3 — `packet.year_role_table` is `null`.** Structural (`model.validation` is empty); harmless with two year
roles and nothing selecting on 2024. Chronology is verified directly against `experiment_authorization.json`.

**NOTE-4 — every on-disk execution artifact is bound to the superseded composite.** `preexec_audit_seal.json`
(`execution_manifest_composite_sha256: da3d3ab4`), `audit/contract_status.json` (pass 02, `4f766f57`) and all five
receipts predate `6d44da61`. Expected shape of a re-audit before re-seal (controller `NEEDS_CONTRACT_AUDIT`);
recorded so no reader mistakes the on-disk seal for authentication of the current composite.

**NOTE-5 — the same `model_id` assumption survives in the platform card writer.**
`scripts/platform_v2_cards.py:62` still computes `"new_models_trained": bool(models.get("model_id"))` from
`experiment_models.json`, so the card at `:116` will report `NEW_MODELS_TRAINED: false` for this multi-cell study even
though the freeze now says `true`. Not a gate, not in any stage closure, not a declared deliverable, and it changes no
result — but it is the last reader named in pass 02's WARNING-1 and the same category. Remediation: mirror the
freeze's expression there.

**NOTE-6 — `_model_record_metrics` returns `{name: None}` rather than `None` in `mode: score`.** Scored records carry
`metrics_by_year`, not `metrics` (`:1107-1109`), so a reuse-mode freeze now records a metric map of nulls where it
previously recorded a single null. Cosmetic; not applicable to this study (`packet.model.mode: train`).

## Referred to lookahead-auditor

None. Causality at this composite was cleared by `lookahead-auditor:008_causal_audit_0e982346` (critical 0 / warning 0 / note 7).

## Blocking verdict

**CLEAR.** The one warning that blocked pass 02 is repaired at the site it named and with the assertion it asked for:
the TRAIN freeze this study is about to write will declare `new_models_trained: true` and carry per-cell TRAIN metrics
for `primary:LONG` and `primary:SHORT`. The same commit closed pass 02's NOTE-1 harder than noted — a cell record
without its `subset` now raises instead of scoring both directions over one undirected population. Composite, plan,
spec, preflight, readiness and tests all agree at `6d44da61`; chronology matches the authorization, the year roles are
disjoint, and 2024 is untouched (no OOS partition, no train freeze). Six notes remain, all disclosure-only: three
inherited packet-rendering/semantics gaps, the expected pre-re-seal staleness of on-disk artifacts, one residual
`model_id` assumption in a non-closure reporting script, and one cosmetic shape change on a branch this study does not
take. Requirements depending on stages not yet run at this composite are recorded NOT APPLICABLE; this verdict does
not vouch for them.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "study": "es_180s_model_c_portability", "auditor": "contract-checker:009_contract_audit_9d99d5bb", "audited_execution_composite_sha256": "6d44da61d0649a99f3491ee413ae449c71de8dd1aaf793b64aa8ddadc0bf0222", "critical": 0, "warning": 0, "note": 6}
<!-- AUDIT_SUMMARY_V2_END -->
