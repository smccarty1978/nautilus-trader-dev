# Feature promotion, and the migration residue

Branch `chore/feature_promotion` from main `8bf26857`. Implementation commit `3e90a73e` (this report
and its evidence follow in a second commit). Human-attended session; the report is the deliverable.

## 0. The decision (§1 of the packet)

**Adopted as proposed, no deviation in the evidence bar.** A feature definition is verified by
evidence about itself, executed by `features/promotion.py` (`research feature verify|promote|check`):

| requirement | what is executed | refusal code |
|---|---|---|
| Golden values | `features/definitions/golden/<name>.json`: an event tape + snapshots with expected values the author derived independently (`derivation` text mandatory), replayed through `ProviderHost.from_instance_specs` -- the adapters a study binds, never the provider class | `GOLDEN_FIXTURE_MISSING`, `GOLDEN_FIXTURE_INVALID`, `GOLDEN_VALUE_MISMATCH` |
| Causal availability | existing machinery only: declared `source_timeframe` contract must cover every stream the adapter consumes; each value is produced with only events available at or before its epoch dispatched; the fixture must carry an event after its last snapshot and the host's `SNAPSHOT_BEFORE_LATEST_RUNTIME_EVENT` guard must fire | `FEATURE_AVAILABILITY_CONTRACT_UNDERDECLARED`, `GOLDEN_FIXTURE_NO_POST_SNAPSHOT_EVENT`, `CAUSAL_GUARD_NOT_ENFORCED` |
| Determinism | two replays on fresh hosts, rows byte-identical | `FEATURE_NONDETERMINISTIC` |

`promote` writes `features/definitions/promotions/<name>.json`, hash-bound (LF-normalised content
hashes, the seal system's W7 rule) to the definition record, the fixture and the provider module.
`features.registry` admits the definition to the ACTIVE authority only while that record exists and
its hashes hold; the compiler re-executes the evidence for every promoted definition a study binds
(`FEATURE_PROMOTION_EVIDENCE_INVALID`, a `MISSING_CAPABILITY` gap); preflight re-executes every
record inside the existing `FEATURE_PROMOTION` gate.

**Deleted as requirements for new definitions:** the legacy-alias parity inventory, the
sealed-authorizing-study requirement, and the materializer as the only writer of `verified`. None of
them is consulted on the new path. **Kept as historical record:** `features/authority/` (143
migrated identities, 693 aliases) is byte-identical; it is hashed into every sealed manifest and the
promotion path refuses to shadow any name in it.

**Two additions to the proposed shape, both stated rather than slipped in:**

1. A *substitution guard* at promote time (packet §4/P5): refuses a name that exists in the bundle,
   a name that is already an alias of another identity, and an instance whose generated physical
   alias is owned by a different canonical name. It is not a fourth evidence requirement; it is the
   P5 property made mechanical.
2. `--allow <name>` on the additive comparator: the promotion of an already-declared record moves
   that record's *own* keys (UNVERIFIED -> bound), which the rule must permit for that name only.

## 1. What was built

| piece | path | note |
|---|---|---|
| Evidence runner + records | `features/promotion.py` | verify / promote / check_record / check_all; substitution guard |
| Catalogue as data | `features/definitions/canonical/<name>.py` (42 records) + `__init__.py` | one `DEFINITION` per file, stem = name, filename-order discovery, misnamed/duplicate record fails the catalogue closed; replaces the `for _name in (...)` loop of `canonical.py` |
| Resolver | `features/registry.py` | `_promoted_records` / `_active_definition_records`; promotions apply to the ACTIVE authority only; records + evidence are closure seeds via `definition_files()` |
| Compiler | `research_workflow/grammar/compiler.py:498` | re-executes evidence for promoted definitions; `UNVERIFIED_CANONICAL_FEATURE` and `FEATURE_PROMOTION_EVIDENCE_INVALID` are typed `MISSING_CAPABILITY` gaps |
| Host | `research_workflow/provider_host.py` | `ProviderHost.from_instance_specs`; **StructuralGeometryAdapter always requires `completed_5m`** (defect, §4) |
| Preflight gate | `scripts/check_feature_promotion.py` | `FEATURE_PROMOTION` gate re-executes every promotion record |
| Golden resolution fixture | `features/tests/golden_feature_resolution.py` | every section keyed per resolvable name; `--check`; `--additive-against <ref> [--allow <name>]` |
| CLI | `scripts/research.py feature verify|promote|check` | promote regenerates the golden and prints the commit set |
| Capability registry | `research_workflow/capabilities.py` | promoted definitions listed (`cap list features` = 144) with `verification: golden_evidence` |
| Handoff | `research_workflow/handoff.py` | `features.*` gaps now suggest `features/definitions/{canonical,golden,promotions}` (rehearsal F1) |
| Docs | `WORKFLOW.md` §E, `docs/RESEARCH_WORKFLOW.md` §21.14 table + new §21.15 | materializer docstring marked historical |
| Tests | `features/tests/test_feature_promotion_path.py` (14), boundary test updated | |
| The feature | `structural_max_expansion_checkpoint_atr` record + golden + promotion record | expected values hand-derived: null (no completed prior 5m regime), 20.0 (= 300/15), 27.5 (= 330/12); the frozen-ATR sibling reads 30.0 at the same epoch |

## 2. Gates

| # | gate | result | evidence |
|---|---|---|---|
| **P1** | the rehearsal's feature promotes and compiles | **PASS.** `research feature promote structural_max_expansion_checkpoint_atr` -> PROMOTED. The rehearsal composition with the withdrawn instance restored compiles with zero gaps: resolved `status: verified`, provider `GenericStructuralGeometryProvider`, binding proof `bound: true`, `plan_sha256 0ec9795d…`, closure (160 files) contains the record, the fixture, the promotion record and `features/promotion.py`. Same composition is `test_the_rehearsal_feature_resolves_verified_and_compiles`. | `evidence/p1_compiled_plan.json`, `evidence/promote_card.json` |
| **P2** | additive classification under the mechanical rule | **PASS for the next addition.** A synthetic next addition (record + fixture + promotion record + regenerated golden, on a throwaway branch, deleted) classifies `ADDITIVE_CAPABILITY`: 3 additive files, 1 GENERATED, 0 CORE. Requires three allowlist updates to the (unmerged, `chore/tiered_gates`) classifier, applied to a scratch copy and stated here: `features/definitions/canonical/<name>.py` and `features/definitions/{golden,promotions}/<name>.json` are capability files; `features/tests/golden/feature_resolution.json` is GENERATED (verified by `--check`); `capabilities_index.d/*.yaml` are seed files. This chore itself classifies CORE_SURFACE (61 files: 44 additive records, 11 core, 1 generated, 2 inert, 3 tests) -- correct, it is platform work. | `evidence/p2_classifier.json` |
| **P3** | golden resolution byte-identical | **PASS, two steps.** (a) Catalogue conversion: main's golden builder run on this tree against main's committed golden moves exactly one thing, `CANONICAL_FEATURE_DEFINITIONS_order` (loop order -> filename order); every per-name digest of the 693 + 41 + 36 names and every parameterised case is identical. (b) Promotion: `compare_additive(without record, with record, allow=[name])` -> `additive: true`, 0 moved, 0 removed, 8 added keys (the new name in each active universe), 3 allowed own-key moves. The universe sections grow by the one name and nothing else; candidate/legacy authorities unchanged. The golden was regenerated once (schema 2, per-name keys, 229 KB -> 810 KB) and `--check` reports `GOLDEN_CURRENT`. | `evidence/p3_conversion_old_builder_diff.txt`, `evidence/p3_promotion_additive.json` |
| **P4** | evidence enforced, adversarially | **PASS.** Live before promotion: `UNVERIFIED_CANONICAL_FEATURE`. Tests: fixture deleted -> `GOLDEN_FIXTURE_MISSING` and the definition resolves UNVERIFIED; expected value edited to the sibling's 30.0 -> `GOLDEN_VALUE_MISMATCH`, promote refused, old record stale -> UNVERIFIED; **forged record** (hashes correct, invented `observed_sha256`) -> resolution admits it, the compiler re-executes and refuses with `FEATURE_PROMOTION_EVIDENCE_INVALID: PROMOTION_RECORD_OBSERVED_SHA256_STALE`; no event after the last snapshot -> `GOLDEN_FIXTURE_NO_POST_SNAPSHOT_EVENT`; no derivation -> `GOLDEN_FIXTURE_INVALID`; provider hash drift -> demoted. Preflight (`check_feature_promotion.py`) PASS with the record replayed. | `features/tests/test_feature_promotion_path.py`, `evidence/feature_lifecycle.json` |
| **P5** | no new substitution path | **PASS.** Mechanically: `FEATURE_ALREADY_IN_AUTHORITY_BUNDLE` (a catalogue record named like a migrated identity cannot be promoted), `FEATURE_NAME_COLLIDES_WITH_ALIAS`, `PHYSICAL_ALIAS_COLLISION`, all tested. Structurally: evidence is keyed by canonical name and hash-bound to that record; the compiled instance binds `canonical_name + parameters + physical_alias + provider`; a promoted feature has to be named exactly in `features.instances`. The rehearsal's X1 substitution (a `normalizer` parameter on the sibling instead of the requested feature) is exactly the case the golden catches: the sibling's value at the same epoch is 30.0, the requested feature's is 20.0, and `GOLDEN_VALUE_MISMATCH` refuses the swap. What promotion does NOT add: a check that a study's *spec* asks for what the research decision asked for -- that remains the contract auditor's job and is unchanged. | tests above |
| **P6** | sealed studies reproduce bit-identically | **PASS.** All 16 tracked `compiled_study.json` plans (731 feature instances) re-resolved through the resolver on main and on this branch: identical per-instance resolution digest `4ee011f5…` on both. `features/authority/*` untouched (no diff). Seal verification (`policy.verify_historical_authority`) compares the committed seal to the committed manifest and is not re-resolved. The adapter's unconditional `completed_5m` requirement cannot change a sealed plan: every one of the 9 plans with structural instances predates the V2 compiler format; it only affects new compiles, where a study binding structural instances without a `completed_5m` binding now gets a typed `UNSUPPORTED_COMPOSITION` gap instead of silent nulls. | `evidence/p6_main.json`, `evidence/p6_branch.json` |

**Tests.** Targeted `test_delta` (features/tests + provider_host + grammar_v2 + capability_modularity
+ scripts test_feature_promotion, `--baseline-reference ee16002e`): 128 ran, 126 passed, 1
`KNOWN_BASELINE_FAILURE`, 1 `NEW_FAILURE` -- `test_candidate_authority::test_real_candidate_requires_
explicit_resolver_authority_and_active_does_not_use_it` asserts the active universe has 129 members;
it fails on clean main with 143 (reproduced in a main worktree) and here with 144. Pre-existing stale
count, not fixed (out of scope; it should assert membership, not a count). Consumer suites run
directly: 61 + 46 passed (capabilities, handoff, provider_host_audit, grammar, ohlcv windows).

## 3. Migration-remnant sweep (§3) -- survey only, nothing removed

Callers were verified with `git grep` over tracked non-test, non-archive, non-study files. A
read-only scout's first pass was corrected where it was wrong (it called the active bundle
"inactive by default"; `features/authority/active.json` points at `candidate/` and every compile
reads it).

| mechanism | what it does | migration purpose | future-facing dependents | verdict |
|---|---|---|---|---|
| `features/authority/candidate/` (`canonical_registry`, `legacy_alias_mapping` 693, `promotion_facts`) + `active.json` | the ACTIVE authority: membership and alias identity of the 143 migrated definitions | one-shot cutover bundle proven by 693-alias parity | every compile (`compiler.py:491`), `resolve_feature_request` alias path, `capabilities._features`, `workflow_engine` manifest hash, **every sealed frozen manifest hashes these four files** | **HISTORICAL RECORD, NOT A GATE** for new definitions (as of this chore); still the record of what was migrated. Do not regenerate. |
| `scripts/materialize_feature_candidate.py` (+ `scratch/feature_system_v2_*.json`, 294 tracked scratch files) | rebuilds the bundle from parity inventories; not idempotent vs the committed bundle | produced the bundle | `scripts/_legacy_reconcile_study_capabilities.py` (itself a refusing shim), docs | **REMNANT, REMOVE** (script + its scratch inputs) once the bundle is declared frozen in prose; docstring now says so |
| `features/candidate_authority.freeze_candidate / activate_frozen_candidate / activate_pipeline_candidate`, `scripts/prepare_feature_candidate.py`, `scripts/activate_feature_pipeline_v2.py`, `scripts/authorize_feature_candidate_activation.py`, `scripts/check_candidate_promotion.py` | the activation ceremony and candidate-mode preflight | cutover governance | `preflight.py` (`feature_authority == "candidate"` branch, reachable only from `preflight.py:234` candidate requests), `resolve_execution_manifest.py:610` (candidate-authority closure), one study (`deep_pullback_5s_reacceleration_model/feature_candidate.yaml`, sealed) | **REMNANT, REMOVE** the ceremony; keep `load_authority` (the reader). The sealed candidate study's closure names these files, so removal is a closure-aware chore, not a delete. |
| `research_workflow/feature_candidate_authority.py` | validates a study-level `feature_candidate.yaml` | candidate-mode studies | `causal_audit.py:127`, `contract_audit.py:122`, `resolve_execution_manifest.py:615` -- all behind `authority_type == feature_candidate` | **REMNANT, REMOVE** with the ceremony (same closure caveat) |
| `features/feature_scoped_promotions.json` (51 records, 30 named `test_idempotency_*`), `features/feature_definition_promotions.json` (26), `canonical_definition_status()` | scoped promotion via a sealed authorizing study; V1 per-definition promotion records | the only pre-chore route to `verified` for a catalogue definition | `check_feature_promotion.py` (validates records; passes), `replay_closure.REPLAY_DATA_FILES` names `feature_definition_promotions.json`, `resolve_execution_manifest.py` names the lifecycle baseline; runtime: only the `legacy_mode` branch of `resolve_feature_instances` | **HISTORICAL RECORD, NOT A GATE.** The scoped route is superseded by golden evidence; the files are closure data for sealed studies. Test-fixture records baked into a tracked file should be purged in their own chore. |
| `features/feature_lifecycle_baseline.json` (502 grandfathered) + the pinned-hash rule in `check_feature_promotion.py` | prevents mass demotion of V1 physical entries; refuses growth | Red-Team finding D | preflight gate every study; `resolve_execution_manifest.py:128` | **STILL EARNS ITS PLACE** (it is the only thing stopping a physical entry from self-granting `verified`) |
| `features/definitions/physical_catalogue.py` (693) + `legacy_instances.py` (36) + `legacy_alias_mapping` | historical output-alias spellings | parquet/model column contracts of pre-cutover studies | `resolve_feature_request` alias branch (bundle aliases), `generic_collector.py` (`legacy_mode=True`), `output_manager.py` + `check_research_decision_fidelity.py` (`verified_registry_numeric_universe`), `features/engine.py` (compat keys) -- i.e. every frozen model whose columns are legacy spellings | **STILL EARNS ITS PLACE** while any frozen model or historical parquet is replayed; the physical catalogue is read only through the boundary |
| `scripts/feature_ctl.py` (`promote` just calls `check`), `scripts/generate_canonical_feature_reference.py`, `features/CANONICAL_FEATURE_REFERENCE.yaml` | CLI checks + a YAML listing generated from the bundle | migration review surface | docs (`WORKFLOW.md`, `RESEARCH_WORKFLOW.md`, `TEMPLATES.md`, `FEATURE_REGISTRY_CONTRACT.md`), `features/tests/test_feature_ctl_request_resolution.py` | **HISTORICAL RECORD.** `feature_ctl promote` is a misnomer (it never promoted); the reference generator reads the bundle only and will not list evidence-promoted definitions -- either extend it to `_active_definition_records` or retire it for `cap list features`. |
| `scripts/run_full_legacy_feature_parity.py`, `scripts/audit_full_feature_system_v2_inventory.py`, `scripts/migrate_cleanflip_feature_instances.py`, `scripts/archive_legacy_feature_registry.py`, `scripts/restore_legacy_feature_file.py`, `features/archive/legacy_registry_2026_08_22/` | one-time parity, inventory, migration and archival tools | produced the parity evidence | docs only (`RESEARCH_WORKFLOW.md`, `DOCUMENT_MAP.md`) | **REMNANT, REMOVE** the scripts (their outputs are the bundle's `promotion_facts`); the archive directory is a frozen reference, keep or move under `archive/` |
| `scripts/_legacy_run_partitioned_train_collection.py`, `_legacy_run_research_workflow.py`, `_legacy_reconcile_study_capabilities.py` (+ the refusing shim `reconcile_study_capabilities.py`) | V1 orchestration | pre-controller workflow | no callers; the shim exists "for sealed studies whose execution closure names it" | **HISTORICAL RECORD, NOT A GATE** -- removal is closure-aware |
| `scripts/parity/*` (`compare_frames`, `compare_study_to_reference`, `run_shape`, `legacy_episode_ledger`, `verify_native_booster_equivalence`), `find_first_parity_divergence.py`, `verify_collector_parity.py` | offline-vs-NT and V2-vs-reference parity | not migration-specific | `WORKFLOW.md` §L, `platform_v2_cards.py`, `results-triager`, `test_selection.py`, CLAUDE.md hard rule | **STILL EARNS ITS PLACE** |
| `.claude/agents/research-executor.md`, `capability-router.md` (LEGACY in `AI_AGENTS.md:119-120`) | v1 lifecycle driver; pre-study routing | v1 | `scripts/route_study_capabilities.py`, `scripts/sync_agents.py`, `AGENTS.md`, `test_concurrent_research_docs.py` | **REMNANT, REMOVE** (with `route_study_capabilities.py`); the compiler's typed gaps and `cap search/describe` replaced them |
| V1 artifact names in `research_workflow/` (`experiment_analysis.json` default in `analysis.py:102`, `controller_actions.py:367`; `research_decision_stage17.json` in `model_artifacts.py:359-362`; `oos_analysis_lineage.py`) | defaults and lineage checks keyed on V1 file names | V1 lifecycle | `study_closure.py` was already fixed; these are the remaining readers | **HISTORICAL RECORD, NOT A GATE** -- verify each default is unreachable from the V2 controller before removing |
| `workflow_engine.py:144-165` `active_feature_authority` / `active_authority_bundle` hash | bundle hash in the workflow manifest | cutover provenance | `governed_controller.py:262` (manifest schema) | **STILL EARNS ITS PLACE** as provenance (it is the bundle the study compiled against) |

**Other remnants found.** `trend_normalized_est_delta_acceleration` is declared in the catalogue but
in no bundle and has no promotion record: a latent instance of the same loop (it entered on the
feature-window chore). It now fails closed as `UNVERIFIED_CANONICAL_FEATURE` and needs golden
evidence before use -- the record file says so. `test_candidate_authority` pins the active universe
to a count (129) that has been wrong since the bundle grew to 143.

## 4. Things the evidence requirement found on the way

* **StructuralGeometryAdapter subscribed to `completed_5m` only when an instance carried
  `timeframe: 5m`**, but every structural output is unavailable until the tracker holds a completed
  prior 5m regime. A study binding only `{context: current}` structural instances got silent nulls
  for every structural column. Found by the first golden replay in isolation (expected 20.0, got
  null). Fixed: the family always requires `completed_5m`. Sealed plans unaffected (P6).
* **Content hashes must be LF-normalised.** The first promotion record hashed working-tree bytes;
  with `core.autocrlf=true` the record and fixture would have re-hashed differently on every fresh
  checkout and demoted the definition. Fixed with the seal system's W7 rule before the commit landed.

## 5. What a new feature costs now

End to end for a definition on an existing provider: one record module (~30 lines), one golden
fixture (this one: a 60-line generator with three hand-derived expected values and a 742-event
synthetic tape), then `research feature verify` (0.6 s), `promote` (0.6 s plus ~10 s to regenerate
the golden), `cap generate --check` (8 s), the new test file (4 s) and the golden `--check` (10 s);
the classifier calls the resulting diff ADDITIVE. Roughly ten to twenty minutes of a human's or a
worker's time, dominated by deriving the expected values, and nothing else in the platform is
touched. During the rehearsal the same feature cost $15.05 and two failed workers (30 minutes of
worker time, 36 minutes of the owner waiting), a retry that re-scoped the science, and the feature
never landed -- because the only route to `verified` ran through a bundle that only a sealed study
could authorise and the study could not seal until the feature was verified.

## 6. Escalations (§8)

None triggered. The three requirements were sufficient to establish that this definition computes
what it claims. What they cannot establish, stated rather than patched with a fourth requirement: a
fixture whose author mis-derives the expected values *consistently with* a wrong implementation
passes. The mandatory `derivation` text exists so a reviewer can check the arithmetic against the
definition; that review is human. Nothing in §4 was weakened: closure, manifest, seal, reuse key,
registration boundaries, `test_delta` and the Wave 1 deliverable-producer gate are untouched, and
the promoted feature is bound by `plan_sha256`, the frozen manifest and the replay closure exactly
as a bundle feature (P1 closure listing). The catalogue-as-data change dragged in no consumer:
the boundary tests (`test_no_consumer_reaches_a_definition_module`, all seven consumers) pass.

## 7. Out of scope, left as found

Everything in §7 of the packet. Additionally: the stale universe count in `test_candidate_authority`,
the `CANONICAL_FEATURE_REFERENCE.yaml` generator, and every removal in §3.
