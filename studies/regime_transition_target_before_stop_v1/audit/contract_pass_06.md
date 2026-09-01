<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"BLOCKED","audit_type":"contract","auditor":"Codex-PhaseD-Contract-20260901","critical":3,"warning":0,"note":0,"study":"regime_transition_target_before_stop_v1","audited_execution_composite_sha256":"8065d438b4e24f84a51e827d27171c04de5feb7dd58e615d77aaa8bf6b87091c"}
<!-- AUDIT_SUMMARY_V2_END -->

# Contract Audit — Pass 06

## Prior-finding adjudication

Passes 01–05 were `CLEAR` and contained no blocking findings to re-adjudicate. Their composite `4dcdc030…` is superseded by this pass's independently resolved `8065d438…` composite.

## Compliance

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen composite current | PASS | `scripts/resolve_execution_manifest.py --json` independently resolves `8065d438b4e24f84a51e827d27171c04de5feb7dd58e615d77aaa8bf6b87091c`; `audit/frozen_execution_manifest.json:2-4` binds the same value. | `audit/preflight.json:4-45` is `CLEAR`, lists every required check, and reports none missing. | None. |
| TRAIN/OOS chronology (C4) | PASS | `research_decision.yaml:12-15,38-49`; `study.yaml:141-179`; driver folds are fixed at `phase_d_modeling.py:28-44`, rejects observed 2024–2026 at `:117-120`, and checks regime-group disjointness at `:146-151,268-273`. | `test_phase_d_modeling_driver.py:59-86` covers six cells, fixed folds, deterministic selection, persistence, and rejection of a synthetic 2024 row. | None. |
| Withdrawn target hash reconciliation | PASS | `artifacts/train_target_authority_reconciliation.json` records `785d95…` only as `superseded_reported_hash`/`UNSUPPORTED`, binds byte SHA `21d598…`, target logical SHA `552690…`, exact zero mismatch counts, and `oos_2024_accessed:false`. | Reconciliation evidence reproduces 1,387,411 identities and Phase C accounting; no Phase D fit output exists. | None. |
| Exact 13-feature order / identity preprocessing (D4) | PASS | `phase_d_modeling.py:104-109,245-249` reads the frozen ordered feature contract, requires 13 unique columns, and records its identity; `:280-282,312-314` declares identity preprocessing. | Synthetic acceptance uses exactly 13 ordered features (`test_phase_d_modeling_driver.py:31-32,59-75`). | None. |
| Backtest/fill/serve controls (E) | NOT APPLICABLE | Phase D is TRAIN modeling only; `research_decision.yaml:38-49` authorizes no backtest, entry rule, or OOS execution. | No backtest was run. | None. |

### CRITICAL: Phase D can fit without authenticating the authoritative target

`phase_d_modeling.py:247-249` hashes caller-supplied files only after loading them and never compares the target path, byte SHA `21d598…`, or logical SHA `552690…` with the reconciliation authority. The public CLI accepts arbitrary `--targets` (`:325-335`); the synthetic test intentionally supplies a non-authoritative fixture and succeeds (`test_phase_d_modeling_driver.py:54-75`). Thus a different TRAIN target can be fitted and persisted under its own newly observed hash, contrary to the resolved authority.

Smallest remediation: before any output directory or estimator construction, fail closed unless the canonical target path and byte SHA match the reconciliation record; add a negative wrong-target-hash test.

### CRITICAL: The driver bypasses governed fit-time hard gates

The driver imports and calls low-level `research.analysis.modeling.fit_model` (`phase_d_modeling.py:21-24,221-225`). It therefore bypasses `research_workflow.modeling.fit_models` checks for study-open state, TRAIN partition provenance, forward-outcome exclusion, and required `pre_fit` gates (`research_workflow/modeling.py:48-91`). Selecting 13 columns reduces exposure but is not execution of the declared hard gates.

Smallest remediation: route each cell through the governed fit surface, or invoke the same fail-closed open/partition/outcome/pre-fit checks before every estimator construction, with focused failure tests.

### CRITICAL: The Phase D executable and output contract is incomplete

`SPEC.md:15,34-52` still declares only `implementation/target_before_stop_diagnostics.py` and collect-mode deliverables. In contrast, `study.yaml:141-169,196-197` declares Phase D modeling and its driver. The literal `config/deliverables_contract.json:3-14` authorizes only `collect`, leaving no declared completion contract for Phase D reports/models. Independently, the approved per-fold metric set requires log loss, but the driver emits ROC AUC, PR AUC, and Brier only (`phase_d_modeling.py:276-277,302-308`).

Smallest remediation: regenerate the derived SPEC with the Phase D driver, declare Phase D outputs in the authoritative deliverables contract, and add log loss plus a schema test for the declared report.

## Seal and execution status

The existing `preexec_audit_seal.json:2-5` binds obsolete composite `4dcdc030…`; this is expected before current reviews and must not authorize fitting. No TRAIN freeze/OOS opening is claimed, and 2024 remains locked.

## Blocking verdict

BLOCKED. The composite and TRAIN/OOS declaration are current, but target authority is not enforced at the executable boundary, governed fit hard gates are bypassed, and Phase D lacks a literal complete deliverables/report contract. Do not seal or start modeling until these three findings are fixed and re-audited.
