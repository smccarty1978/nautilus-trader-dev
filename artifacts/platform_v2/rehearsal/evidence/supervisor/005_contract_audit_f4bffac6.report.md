# CONTRACT AUDIT pass 01 — `rehearsal_checkpoint_norm`

auditor `contract-checker:005_contract_audit_f4bffac6` · composite `73db2ed0f21316e4c0a5b04790a37910824f37dc67d964a30d020c39dc6b75f7` · plan `50c8e6667a90` · spec `3af9393f69cc` · packet_version 2

Gate facts cited from the brief, not re-derived: preflight CLEAR (8/8, `leaked_outcome_columns=[]`), readiness PASS (R1/R3/R5/R8/R9/R10), tests PASS 137/0, controller `NEEDS_CONTRACT_AUDIT` with `execution_composite == current == 73db2ed0f213`, causal audit CLEAR under a distinct identity (`lookahead-auditor:004_causal_audit_300a825d`). Closure files changed by the study branch against `main`: none. Pass 01 — no prior findings to adjudicate.

## Findings

### CRITICAL-1 — The treatment variable of the declared research question is absent from the compiled contract

`research_decision.yaml:3-9` (the authoritative decision contract) asks whether `structural_max_expansion_checkpoint_atr` adds OOS tail lift **over** `structural_max_expansion_atr`. `SPEC.md:82-88` makes the four-instance feature set a contract term verbatim: *"Do NOT drop, rename, substitute, re-parameterize... A spec that compiles because a declared feature was removed is a research-contract violation."* `research_decision.yaml:20` predeclares `on_capability_gap: stop_and_handoff`.

`study.yaml:25-29` drops `structural_max_expansion_checkpoint_atr` under an `OWNER INTERVENTION` comment. The compiled contract confirms the drop: `packet.columns.features` carries four columns of which only the frozen-ATR variant `structural_max_expansion_atr` is present, `packet.binding_proof` has one `feature.structural_max_expansion_atr` entry, and `packet.model.arms` / `packet.outcome.arms` are both `[]`.

Failure path: the declared analysis (`study.yaml:51-62`) fits one model on the baseline feature set and computes `analysis.metric.tail_lift` on `score__primary` for the OOS frame against a TRAIN reference. There is no treatment fit and no comparator frame, so the quantity the question names — lift *over* the frozen-ATR normalization — does not exist anywhere in the deliverable set. A phase-D report of `tail_lift.json` would describe the baseline classifier while the study, its SPEC and its decision contract all state it answers a normalization contrast.

The owner's decision to proceed is recorded, but it was recorded at the **lowest** precedence level. The stated order is `research_decision.yaml > SPEC.md > study.yaml`; a comment in `study.yaml` cannot amend the two documents above it, and both still declare the contrast (`research_decision.yaml` `status: DRAFT`, question unchanged; `SPEC.md:44` still lists the fourth instance).

Smallest remediation: ratify the deviation where it binds — amend `research_decision.yaml.research_question` and `SPEC.md` to the single-arm rehearsal question and re-freeze. This is a contract edit, not a re-run. Restoring the fourth instance and resuming the CapabilityGap handoff is the alternative.

### WARNING-2 — The terminal-decision vocabulary cannot detect CRITICAL-1

`REHEARSAL_COMPLETE` (`research_decision.yaml:15`) is satisfied by "the lifecycle ran to closure ... and `tail_lift.json` exists for the study's own fitted-model scores with TRAIN-frozen thresholds". It contains no clause about the declared feature surface or the contrast. The study therefore reaches its success label with the treatment variable absent, and `REHEARSAL_INCOMPLETE` (`:16`) fires only on a missing stage/gate/deliverable — which is not what happened. A closure gate that does not cover the deliverable it vouches for cannot detect the scope loss that has already occurred. Remediation: add the four-instance feature surface to the `REHEARSAL_COMPLETE` clause, or route this deviation explicitly to `REHEARSAL_INCOMPLETE`.

### WARNING-3 — Declared selection protocol has no candidate set, metric, bound or seed (C4)

`study.yaml:50` declares `validation: {protocol: model_selection.random, tuning_years: [2023], final_train_validation_years: []}`. The compiled `packet.model.validation` resolves it with `max_trials: null`, `primary_metric: null`, `random_seed: null`, and `packet.model.arms: []`. Nothing is selected, no metric ranks a selection, no trial bound limits it and no seed reproduces it — so C4's "selection seals authenticate their own selected result" has no selected result to authenticate. The overlap clause of C4 is clean (tuning 2023 ⊆ TRAIN; test window 2024 disjoint). Today the protocol is inert rather than wrong; it becomes a reproducibility defect the moment a second arm is restored under CRITICAL-1. Remediation: drop the selection protocol for a single-fit study, or supply `primary_metric`, `max_trials` and `random_seed`.

## Notes

- **NOTE-1** `analysis.metric.tail_lift` excludes rows whose label is non-binary and counts them in the payload (`research/analysis/diagnostic_ops.py:954-959`), so censoring is handled and disclosed *provided* `target_flip_within_horizon` is null — not 0 — for session-end-censored rows (`packet.outcome.semantics.session_end_censoring: true`, `same_bar_rule: ambiguous_censor`). The packet cannot prove the null encoding. Phase D must report `excluded.rows_non_binary_label` alongside the tail table.
- **NOTE-2** `packet.outcome.semantics.resolution_precedence` includes `GAP` while `max_gap_ns` is `null`, so `censor_reason == GAP` is unreachable. Benign for a `flip` kernel; disclosure only.
- **NOTE-3** `packet.deliverables_by_stage.analyze` lists only `artifacts/experiment_analysis_v2.json`; the two artifacts the study declares (`study.yaml:60-62`) and on which `REHEARSAL_COMPLETE` depends by name (`tail_lift.json`) are not in the stage deliverable list. Analyze has not run, so this is coverage, not an existence failure.

## Clean checks

Composite current (controller fingerprints match) · preflight ran and passed every required check · readiness `overall_status` PASS · causal and contract identities distinct · TRAIN 2023 / OOS 2024 / prohibited {2020,2021,2022,2025,2026} disjoint, `authorized_dates ['2023-03-01']` inside TRAIN · no forward-outcome column in `packet.columns.features` (all label columns confined to `columns.observation`; preflight `leaked_outcome_columns=[]`) · `study_python.python_files: []` with no exception needed (tier-2 invariant) · partitions: one, `train-2023`, reuse `off` · dirty paths confined to `studies/rehearsal_checkpoint_norm/{artifacts,audit}/`, no closure file dirty · every declared primitive maps to exactly one runtime implementation (7/7 `bound: true`) · the two `regime_efficiency` instances are timeframe expansions of one canonical identity (`study.yaml:23`, `over: {timeframe: [1m, 5m]}`), not a duplicated provider · **D2** the model is fit on the post-`qualify` population by construction · **D4** determinism declared (`deterministic: true`, `n_jobs: 1`, `random_state: 42`); all four features numeric with `features.structural_snapshot_ready` gating the snapshot · **E1/E2** every tracker timeframe (1s, 1m, 5m-from-1m) is declared in `streams` and covered by R1_NQ + R5_binding_proof · **E5** warmup 5 days before partition with `candidate_emission: false`, `target_generation: false`.

## Not applicable

**D1** (no live serve path; collection-only study) · **D3** (no ONNX export) · **E3/E4** (no orders, no fills — the outcome is a label from a regime-flip event) · seal freshness, TRAIN-freeze-before-OOS, `derivation_population`, `forward_outcome_manifest.json` (all post-date this pre-execution audit; `packet.identity.seal` is `{}`) · a per-study `config/deliverables_contract.json` (V1 artifact; `packet.deliverables_by_stage` is the V2 contract).

## Referred to lookahead-auditor

Nothing. No causal defect outside the SPEC surfaced.

## Blocking verdict

**BLOCKED.** The study cannot produce the result its decision contract declares: the treatment feature that defines the question was removed from `study.yaml`, in direct contradiction of a SPEC clause that names that exact removal as a research-contract violation and of a predeclared `stop_and_handoff` fork policy. The owner's intervention is recorded, but only in `study.yaml` — the two higher-precedence documents still declare the contrast, and the study's own terminal-decision vocabulary would return `REHEARSAL_COMPLETE` regardless (WARNING-2). The remediation is cheap and is a contract edit, not a re-run: amend `research_decision.yaml` and `SPEC.md` to the single-arm question the compiled plan actually asks, tighten `REHEARSAL_COMPLETE`, and re-freeze. The executable surface itself is clean — every lifecycle gate, the authorization grid, the binding proof and the outcome/feature separation all pass at composite `73db2ed0f213`.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "contract", "study": "rehearsal_checkpoint_norm", "auditor": "contract-checker:005_contract_audit_f4bffac6", "audited_execution_composite_sha256": "73db2ed0f21316e4c0a5b04790a37910824f37dc67d964a30d020c39dc6b75f7", "critical": 1, "warning": 2, "note": 3}
<!-- AUDIT_SUMMARY_V2_END -->
