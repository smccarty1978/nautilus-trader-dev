# Framework reconciliation — clean_maturity_flip_model_180s_horizon

Date: 2026-08-29
Branch: `study/clean_maturity_flip_180s_reconcile` (forked off `bec2354`)
Scope executed: deterministic reconciliation only (lifecycle stages 1–6). **STOP before re-collection / re-fit.**

---

## 1. Verdict

The study previously reached a sealed pre-TRAIN state **and a full TRAIN freeze** under the
old framework (sealed composite `85efdcc4…`, audit pass 12). That state is **invalidated** by
framework change. It has been re-prepared, re-audited and re-sealed under the current
framework. All downstream TRAIN artifacts (collection, Phase‑1/2 selection, 2023 gate,
freeze, thresholds) are **stale and must be regenerated** — they are left on disk, not
deleted, and will be overwritten at lifecycle stages 10–13.

Seal: **LOCKED** — composite `bd2e9cf145a7408cff84613fec65149a94c296eeafad6194b42d427df4203e0e`.

---

## 2. What changed and why the old seal died

### 2a. Parameterized‑feature identity repair (the known issue) — CONFIRMED, now fixed here

Old frozen `compiled_study.json` / `config/feature_contract.json` collapsed the three
`timeframe: 1m` structural instances onto `5m`:

| slot | study.yaml declares | old frozen contract resolved to | physical_alias (old) |
|---|---|---|---|
| 0 | `regime_efficiency` @ **1m** prior completed | `timeframe: 5m` | `regime_efficiency` |
| 1 | `regime_mfe_atr` @ **1m** | `timeframe: 5m` | `regime_mfe_atr` |
| 2 | `regime_range_atr` @ **1m** | `timeframe: 5m` | `regime_range_atr` |
| 3–5 | same three @ **5m** | `timeframe: 5m` | (identical aliases → collapsed) |

Recompiling with the current compiler resolves them correctly and distinctly:

```
prior_1m_regime_efficiency  prior_1m_regime_mfe_atr  prior_1m_regime_range_atr
prior_5m_regime_efficiency  prior_5m_regime_mfe_atr  prior_5m_regime_range_atr
rolling_300s_retention_ratio  rolling_300s_current_progress_atr
rolling_300s_max_progress_atr  rolling_300s_giveback_atr
arrival_velocity  arrival_acceleration  ema_slope
```

- feature_list_sha256: `4e46c0b3…` (old, collapsed) → `38c0201f…` (new, disambiguated)
- spec_sha256: `e6a3fd9e…` → `e363badf…` (one‑time migration event, expected)

Canonical **semantic** identity is preserved (same 13 `FeatureInstance`s, same parameters);
only the compiled aliases changed. Per BLUEPRINT §7 this is deterministic framework
reconciliation, **not** a semantic decision. **The collected feature columns nevertheless
change**, so the existing TRAIN collection and every downstream fit are invalid.

### 2b. Execution‑closure churn (collector + target runtime)

Five commits after the study's freeze touch its execution closure:

| commit | closure files touched |
|---|---|
| `f9e4f99` | `research_workflow/workflow_engine.py`, `study_closure.py` (new) |
| `f0bdadf` | `generic_collector.py`, `compiler.py`, `collection.py`, `modeling.py`, `experiment.py`, `research_workflow/__init__.py`, `research/engines/target_engine.py`, `research/schemas/study_spec.py`; new `target_runtime.py`, `runtime_bindings.py`, `model_artifacts.py`, `target_replay_oracle.py` |
| `c4ae619` | `scripts/create_study.py` |
| `b0eabc3` | `generic_collector.py`, `target_runtime.py`, `target_replay_oracle.py` |
| `bec2354` | `generic_collector.py` (+128), `target_engine.py`, `target_runtime.py` (+312), `target_replay_oracle.py`, `runtime_bindings.py`; new `target_expression.py` |

Consequence: the collector now obtains dispositions/labels from a resolved
`TargetContract → TargetRuntime` dispatcher. The recompiled contract now carries
`target_contract.primitive: "flip_within_horizon"` (was absent). TRAIN freeze now binds
stage‑scoped lineage (`COLLECTION_PRODUCER` / `TARGET_RUNTIME` / `MODELING_EXECUTION`).

### 2c. Secondary framework gap found (worked around, not fixed)

`python -m research_workflow.prepare` recompiles only `compiled_study.json` and
`config/deliverables_contract.json`. It does **not** regenerate the other `config/*.json`,
`SPEC.md`, `TASK_PACKET.json` or `tests/test_study_contracts.py`, so a framework‑driven
recompile leaves a sealed study internally inconsistent. Reconciled here by re‑running the
`study_factory` step‑5 write logic from the same compile pass — **`study.yaml` and
`research_decision.yaml` were not touched.** Recommend a framework fix so `prepare` syncs
all generated artifacts (mirrors the BLUEPRINT §12 migration precedent, which used the
`study_factory` directory‑writing path).

### 2d. Pre‑existing config drift, now also corrected

`config/model_selection.json` and `config/target_contract.json` on disk were already stale
against `study.yaml` **before** this reconciliation: the old `model_selection.json` still
carried `random_state: 42` in `fixed_hyperparameters` and the invalid secondary metrics
`brier_score, precision_at_p90/p95/p97_5, resolved_count` — the exact items `study.yaml`'s
own comments say would raise `UnsupportedSelectionMetric` at final validation. Now synced to
`study.yaml` (`fixed_hyperparameters: {verbosity: -1}`, `secondary_metrics: [brier]`).

---

## 3. Parent 300s benchmark — resolved, comparable

Authoritative parent: `studies/clean_maturity_flip_model_rolling_productivity/`

| field | value |
|---|---|
| frozen execution composite | `7b0994145ce702fedbf3b589a98fa869b09ef57253a17722b8de25931cbb96c8` |
| benchmark freeze artifact | `artifacts/train_experiment_freeze_repaired.json` (supersedes `train_experiment_freeze.json`) |
| train_freeze_sha256 (from OOS analysis) | `126c9b668a7f8cdc56d3f9b7d8df17a1d7e399d8b441447de3641dca8d6c48a7` |
| feature_contract_sha256 | `99f2af86aefc8ef904eed65c23be7220522d3b99d525a978cea34c104536f72a` |
| model family | `lightgbm.sklearn.LGBMClassifier`, lightgbm 4.6.0 (established by joblib deserialization; stale prose said HistGradientBoosting) |
| parent frozen HPs | n_estimators 200, learning_rate 0.05, max_depth 3, num_leaves 8, verbosity -1, seed 42 |
| A / B / C sizes | 3 / 9 / 13 |
| model_hashes | LONG_A `98fce521…` LONG_B `cea6c9ab…` LONG_C `a341ae26…` SHORT_A `1fa4ae5d…` SHORT_B `c3b7dab9…` SHORT_C `5aa9f0c8…` |
| parent OOS 2024 | already SCORED (`oos_2024_analysis_repaired.json`) — 450,973 obs; do **not** retrain |

**A/B/C surface reconciliation:** the recompiled child's 13‑feature set is **identical** to
the parent's repaired `feature_sets.C` (same canonical identities, same parameters). The
child's full contract `feature_list` is ordered structural‑first / arrival‑last; the parent
freeze and `research_decision.yaml:model_arms` are arrival‑first. Arm slicing is by column
name, so this ordering difference does not affect arm composition — but child
`feature_order_hashes` will differ from the parent's and should be sliced in the
`research_decision.yaml` order (arrival, then 1m, then 5m, then rolling_300s) for
arm‑comparable freezes.

**Parent SPEC.md drift anomaly** (parent's sealed manifest records SPEC.md sha
`734ac330…`, on‑disk is `c150bee7…`): pre‑existing in the parent's own history, already
documented in `research_decision.yaml` (`flagged_to_researcher: true`), lineage binds on the
execution composite instead. Not this study's to fix. Unchanged.

---

## 4. Gates run in this reconciliation

| stage | tool | result |
|---|---|---|
| 1 PREPARE + FREEZE | `research_workflow.prepare` | compiled; composite `bd2e9cf1…` |
| — sibling artifact sync | `study_factory` step‑5 write logic | `config/*.json`, `SPEC.md`, `TASK_PACKET.json`, `tests/test_study_contracts.py` |
| 2 READINESS | `research_workflow.readiness` | **PASS** — R1–R10 all pass (R2 derived‑5m via `CompletedMinuteFiveMinuteAggregator`, R4 213,431 callbacks no inversion, R10 parity) |
| 3 PREFLIGHT | `research_workflow.preflight` | **CLEAR** — EXECUTION_MANIFEST, CAUSAL_LINT, ARTIFACT_SCHEMA, FEATURE_PROMOTION, RESEARCH_DECISION_FIDELITY, REQUIRED_GATES, RUNTIME_CONTRACT_BINDING, CAUSAL_INVARIANTS (14 targeted tests) |
| 4 CAUSAL REVIEW | `research_workflow.causal_audit.run_causal_review` | **CLEAR** — pass 13; causal_lint 0 critical; R10 parity clean |
| 5 CONTRACT REVIEW | `research_workflow.contract_audit.run_contract_review` | **CLEAR** — pass 13; declared surface 13 == authorized 13; generic collector binding present |
| 6 SEAL | `research_workflow.seal.generate_preexec_audit_seal` | **LOCKED** — `bd2e9cf1…`; distinct auditor identities |
| — study‑local tests | `pytest studies/…/tests/` | 27 passed |

Auditors used the deterministic library path (same auditor identity the **parent** used:
`research_workflow.causal_audit`). The collector / target‑runtime code in the closure
changed materially — see §6 decision (1).

---

## 5. Artifacts now stale (on disk, not deleted — regenerate at stages 7–13)

```
artifacts/experiment_authorization.json            (stage 9 — predates reseal)
artifacts/train_collection_manifest.json
artifacts/train_partition_merge.json
artifacts/train_candidates_merged.parquet
artifacts/train_observations_merged.parquet
artifacts/experiment_models_long.json / _short.json
artifacts/model_selection_manifest_long.json / _short.json
artifacts/model_selection_manifest_phase1_{long,short}_{prauc,brier}.json
artifacts/two_phase_selection_dispatch_summary.json
artifacts/final_train_freeze_dispatch_summary.json
artifacts/train_experiment_freeze_long.json / _short.json
runs/20260827_*                                    (4 collection run dirs)
_work/*                                            (partitioned collect scratch)
audit/pass_01..12.md, audit/contract_pass_01..12.md (superseded by pass_13)
```

---

## 6. Decisions for the researcher before the next (re‑collection) checkpoint

1. **Audit depth.** The deterministic library audit gates are CLEAR, but
   `generic_collector.py` (+~370 lines) and the new target‑runtime path are in the closure.
   Confirm whether the full `lookahead-auditor` / `contract-checker` **agent** checklist pass
   is wanted before committing compute to a 3‑year re‑collection, or whether the library gate
   + the pre‑TRAIN target‑replay parity gate is sufficient for a horizon‑only change.

2. **Parent re‑score (your "decide after label‑parity check").** The check is run against the
   NT smoke / re‑collection output: compare the new `FlipTargetRuntime` flip labels to the
   parent's committed 300s observations. Identical → hold parent as‑is; differ → re‑score the
   frozen parent models (weights unchanged) under the current collector. Reported at that
   checkpoint.

3. **`config/*.json` regeneration method.** I regenerated the sibling generated artifacts
   in place from the compile pass without touching `study.yaml`. If you prefer the sanctioned
   `study_factory --config` directory‑writing path (which re‑dumps `study.yaml`, losing its
   governance comments), say so before I proceed.

4. **Study‑local selection modules.** `implementation/two_phase_selection.py` and
   `final_train_freeze.py` still pass their tests (27). Whether the current generic
   `research_workflow.model_selection` now expresses the two‑phase protocol well enough to
   retire them (BLUEPRINT novelty ladder) will be assessed at the Phase‑1 stage — not
   blocking now.

---

## 7. Next lifecycle steps (not yet run)

7 NT SMOKE (1 day) → 8 RECONCILE → 9 AUTHORIZE → 10 TRAIN COLLECT 2021–2023 (partitioned)
→ 11 MERGE → 11b pre‑fit gates → 12 FIT (Phase 1 A/B/C, then Phase 2 tune winner, then 2023
reject‑only gate) → 13 TRAIN FREEZE + TRAIN‑only thresholds → TRAIN‑only 180s‑vs‑300s
diagnostics + 1:1 tradeability diagnostic → `180S_HORIZON_TRAIN_CARD`.

**2024 / 2025 / 2026 not touched. OOS not opened.**
