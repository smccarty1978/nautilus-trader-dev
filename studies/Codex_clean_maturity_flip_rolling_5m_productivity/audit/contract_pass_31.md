<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"BLOCKED","audit_type":"contract","auditor":"contract-reviewer-cleanflip-final-pass31","blocking":1,"warning":0,"note":0,"study":"Codex_clean_maturity_flip_rolling_5m_productivity","audited_execution_composite_sha256":"5b45381851765e4deda7d82f85b2d535a99e88411a0eb7d2dd59595c099a39ef"}
<!-- AUDIT_SUMMARY_V2_END -->

# Contract Audit - Pass 31

Reviewer identity: `contract-reviewer-cleanflip-final-pass31`.

## Prior findings adjudicated

| Prior finding | Status | Evidence |
|---|---|---|
| Pass 30: active canonical authority bytes absent from frozen closure | FIXED | `audit/frozen_execution_manifest.json` now includes `features/authority/active.json`, the selected bundle's `canonical_registry.json`, `legacy_alias_mapping.json`, and `promotion_facts.json`, plus every provider module resolved from the 532 declared instances. The current preflight authenticates these at composite `5b45381851765e4deda7d82f85b2d535a99e88411a0eb7d2dd59595c099a39ef`. |

### BLOCKING: Declared canonical FeatureInstances do not reach collection or persistence enforcement

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| The 532 explicit canonical instances compiled for this study must be the runtime collection surface and OutputManager's exact allowed/required physical-alias contract. | FAIL | `compiled_study.json` contains 532 `spec.features.instances` and compiles 532 unique physical aliases, but `backtests/nt_runtime/output_manager.py:37-42` constructs its universe only from `feature_list` (null in this StudySpec) plus the 129-definition source universe. A direct audit probe returned allowed=129, compiled aliases=532, compiled-minus-allowed=516. `persist_collection` then uses that 129-name universe and only enforces `expected_feats` when `feature_list` is populated (`output_manager.py:415-498`), so it neither admits most declared instance aliases nor detects that they are missing. The collector receives `feature_requirements` (`modes/collect.py:229-233`; collector `:109,141`) but never consumes them after assignment. `FeatureEngine.snapshot` instead enumerates canonical engine aliases and resolves bare canonical requests (`features/engine.py:297-328`). `derive_study_feature_requirements` also discards each declared `physical_alias` before resolving (`features/registry.py:1418-1440`). Thus the compiled canonical instance parameters/aliases are not the execution surface. | Frozen preflight is CLEAR, but `audit/readiness.json` predates this migration (`prepared_execution_identity` differs) and proves only 111 emitted canonical names against 129 definitions, not the frozen 532-instance contract. The direct resolver probe resolved all 532 instances and all seven provider modules are frozen, but OutputManager's shared helper returned only 129 allowed names. No test proves 532 instance aliases flow from StudySpec through collector emission and persistence. | Make the shared collection resolver resolve `features.instances` with their explicit physical aliases; propagate those resolved instances into FeatureEngine/provider execution; make OutputManager use that same resolved alias list as both allowed and required collection surface. Add an end-to-end test asserting all 532 declared aliases are emitted/accepted and a removed instance alias fails as missing. Re-run PREPARE, R1-R10, FREEZE, and preflight before re-audit. |

The literal collect deliverables contract remains present and the active authority closure is now complete, but those controls cannot authorize a runtime surface different from the compiled 532-instance contract.

## Blocking verdict

BLOCKED

The frozen compiler contract declares 532 parameterized feature instances, while collector execution and OutputManager still operate on the 129 bare canonical-definition universe. This permits missing declared instances and rejects most declared physical aliases, so the one-day smoke cannot be contract-authorized until the shared instance resolver drives both emission and persistence.
