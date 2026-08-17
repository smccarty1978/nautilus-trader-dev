# Contract Audit — Pass 01

**Study:** `es_wick_imbalance_acceptance_v2`
**Scope:** SPEC/deliverables manifest fidelity, terminal-label reachability, Research
Decision Contract adherence, C4/D/E. Causality (A, B, C1-C3, F, G, H) is out of scope —
already audited independently in `audit/pass_02.md` (auditor `causal-audit-scottm-pass01`,
CLEAR).
**Mode:** PRE-EXECUTION. No run has occurred; findings judge reachability and contract
consistency in the frozen study assets, not produced artifacts.
**Authoritative deliverable source:** `config/deliverables_contract.json`
(`authorized_modes: ["collect"]`). Consumed as-is; no independent deliverable list was
assembled.

---

## Findings

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Collect-mode deliverables reachable at declared paths | PASS | `backtests/nt_runtime/output_manager.py::persist_collection` (lines 288-357) writes `candidates.parquet`/`observations.parquet`/`collection_manifest.json` under `run_dir/collection`, and `status.json` under `run_dir`; `__init__` (lines 145-146) writes `run_manifest.json` under `run_dir` — all 5 paths match `deliverables_contract.json`'s `relative_to` fields exactly. | `tests/test_study_contracts.py::test_deliverables_are_declared_per_mode_and_all_reachable` cross-checks against `research/engines/deliverables_engine.py::KNOWN_ARTIFACT_PRODUCERS`; `::test_spec_md_renders_the_deliverables_contract` checks SPEC.md prose contains every declared artifact name. | None. |
| Terminal label reachability (LABELED_POSITIVE / LABELED_NEGATIVE / CENSORED) | PASS | `strategies/flip_prediction_collector.py`: `DISPOSITION_POSITIVE` reached at line 484 (`_on_regime_flip`, opposing flip inside horizon); `DISPOSITION_NEGATIVE` reached at line 427 (`_sweep_elapsed_horizons`, horizon elapsed with no flip) and line 487 (defensive path, flip after horizon already elapsed); `DISPOSITION_CENSORED` reached at lines 423 (sweep, session-end censored), 463 (`on_stop`, residual pending at run end), 480 (`_on_regime_flip`, flip inside a session-end-censored horizon). `_emit_observation` (line 353) is the single writer, called exactly once per candidate resolution path — matches `target_censoring.rule` in `research_decision.yaml` ("every emitted candidate reaches exactly one terminal disposition"). | No standalone unit test iterates all three disposition branches directly, but `reconcile_candidate_dispositions` in `output_manager.py` (lines 26-102) structurally enforces `candidates == labeled_positive + labeled_negative + censored` at persist time and fails the run (`status: FAILED_VALIDATION`) if any candidate is undisposed, orphaned, or duplicated. | None. |
| `session_end_censoring: true` implemented per `target_contract.json` | PASS | `_is_censored_by_session` (line 430) gates on `session_close_ts > horizon_end_ts is False`... i.e. correctly returns `True` only when `horizon_end_ts > session_close_ts`; wired into all three `DISPOSITION_CENSORED` call sites. | Reconciliation check above provides run-time proof; no isolated unit test found for `_is_censored_by_session` alone (NOT VERIFIED in isolation, but behavior is exercised transitively by the reconciliation gate). | None — pre-execution; would surface as `FAILED_VALIDATION` if wrong. |
| `feature_contract.json` agrees with `study.yaml features.source` and discloses provisional status | PASS | `feature_contract.json`: `feature_statuses.latest_1m_wick_imbalance = "provisional"`, `source_key: null`. `study.yaml`: `features.source: explicit_feature_list`. `research/engines/feature_binding_engine.py` (lines 37, 51, 133) treats `source_key` as pass-through from `features_spec.source_key`, which is unset (→ `None`/`null`) for `explicit_feature_list` mode — `source_key: null` is the expected value for this mode, not a defect. `research_decision.yaml`'s `feature_status_caveat` (lines 59-64) explicitly discloses the provisional status and its `null_policy: allow` rationale. | `tests/test_study_contracts.py::test_feature_hash_equals_hash_recomputed_from_the_ordered_list` and `::test_declared_features_resolve_in_the_central_registry` bind the single feature to `features/registry.py` and `features/trackers/wick.py`. | None. |
| `research_decision.yaml` chronology / `authorized_dates` fidelity vs `study.yaml` / `SPEC.md` | PASS | `research_decision.yaml` (`train: [2024]`, `dev: []`, `prohibited: [2025, 2026]`, `authorized_dates: [2024-09-03, -04, -05]`) matches `study.yaml chronology` and `execution.data_requirements.authorized_dates` verbatim; also matches `config/execution_contract.json`. | `tests/test_study_contracts.py::test_execution_chronology_equals_the_source_decision` recomputes disjointness of train/dev/prohibited from `execution_contract.json` against `study.yaml`. `scripts/check_research_decision_fidelity.py` chronology check (lines 184-197) compares `study.yaml` directly to `research_decision.yaml`. | None. |
| Warmup (E5) respected without crossing into prohibited years | PASS | `backtests/nt_runtime/data_plan.py` defaults `warmup_days=5` (line 138/208) and computes `warmup_start_dt = start_dt - 5d` (line 183); lines 283-302 raise `UNAUTHORIZED_WARMUP_DOMAIN` if the warmup window falls into a prohibited year. For `authorized_dates` starting 2024-09-03, the 5-day warmup stays entirely inside 2024 (a `train` year), so no prohibited-year overlap is possible. | Not independently unit-tested for this study's specific dates (NOT VERIFIED for this exact window), but the guard is unconditional and generic. | None. |
| C4 (walk-forward discipline, selection seals, promotion gates) | NOT APPLICABLE | This study performs no model selection, no walk-forward split, and `model_arms` declares exactly one arm (`A`). `operation: train_evaluate` / `model.family: HistGradientBoostingClassifier` in `study.yaml` are inherited canonical-`flip_prediction`-template fields; no training or promotion code path is reachable under `authorized_modes: ["collect"]` (`backtests/nt_runtime/strategy_binding.py:145` only recognizes `collect`/`backtest` as `supported_modes`, and this study's compiled contracts never invoke either beyond collect). | — | — |
| D (train/serve skew) | NOT APPLICABLE | No model is trained or served in a collect-only, single-feature descriptive run; `D1-D4` presuppose an offline/live pair that does not exist here. | — | — |

---

### NOTE: `operation.kind: train_evaluate` / `model.family` boilerplate is inert but undisclosed at the study.yaml layer

`study.yaml` carries `operation.kind: train_evaluate` and `model.family:
HistGradientBoostingClassifier`, inherited from the canonical `flip_prediction` factory
template. `research_decision.yaml`'s `scope_caveats` explicitly states "No model fitting,
threshold tuning, or trading backtest," which correctly disclaims these fields at the
decision-contract layer — but `study.yaml` itself, and `SPEC.md`, carry no equivalent
annotation next to the inert fields. `scripts/check_research_decision_fidelity.py` does not
check `operation.kind` or `model.family` against `research_decision.yaml` at all (its
`ResearchDecisionContract` schema has no field for either). Concretely: nothing under this
study's own compiled contracts or `strategy_binding.py` currently offers a `train` mode to
invoke, so there is no reachable failure path today. This is disclosure debt, not a
reachable defect — recorded as a NOTE, not counted as a blocking or warning finding.

### WARNING: `baseline_feature_selection.mode: "train_only"` is not cross-checked by the fidelity gate

`research_decision.yaml` declares `baseline_feature_selection.mode: "train_only"`.
`scripts/check_research_decision_fidelity.py` (lines 100-118) only validates
`study.yaml`'s `features.selection.mode` against the decision contract when
`baseline_feature_selection.mode == "none"`; for `"train_only"` (this study's value) no
check exists at all — the branch is silently skipped. For this specific study there is no
concrete failure path today, because `study.yaml features.source: explicit_feature_list`
declares a single named feature and no selection mechanism exists to police. This is a real
gate gap (an enforced-in-practice-but-not-in-code invariant per the checklist's WARNING
definition) rather than a defect in this study's own configuration — flagged once here so
it isn't silently re-invented as a per-study finding on a future pass of a different study
that actually uses `train_only` selection with a multi-feature list.

---

## Referred to lookahead-auditor

None — no novel causal theory identified; `audit/pass_02.md` already covers C1-C3/F/G/H for
this composite and is CLEAR.

---

## Blocking verdict

<!-- AUDIT_SUMMARY_V2_START -->
{
  "verdict": "CLEAR",
  "audit_type": "contract",
  "study": "es_wick_imbalance_acceptance_v2",
  "auditor": "contract-audit-mccarty-2026-08-17-p01",
  "audited_execution_composite_sha256": "3cacbb80eb5bb093353e554c3a5cf6cb0318731d76cff68970fdcdf8a2bf982c",
  "blocking": 0,
  "warning": 1,
  "not_verified": 0
}
<!-- AUDIT_SUMMARY_V2_END -->

**CLEAR.** All five collect-mode deliverables in `config/deliverables_contract.json` map
to a real, reachable producer at the declared path in `backtests/nt_runtime/output_manager.py`.
All three declared terminal dispositions (`LABELED_POSITIVE`, `LABELED_NEGATIVE`,
`CENSORED`) are independently reachable in `strategies/flip_prediction_collector.py` and are
structurally reconciled against the emitted candidate population before a run is filed as
`SUCCESS`. `research_decision.yaml` chronology, `authorized_dates`, and the provisional
feature-status disclosure are all consistent with `study.yaml`/`SPEC.md`/the config
contracts, and are machine-checked by `tests/test_study_contracts.py` and
`check_research_decision_fidelity.py`. C4 and D are not applicable — this is a single-arm,
collect-only descriptive run with no model training or serving. One WARNING is recorded: the
Research Decision Contract fidelity gate has no check for `baseline_feature_selection.mode:
"train_only"`, though it has no reachable consequence in this specific study's
configuration. Nothing here blocks execution.
