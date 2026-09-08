# Tiered merge gates — design proof

    packet:      artifacts/platform_v2/tiered_gates/PACKET.md
    branch:      chore/tiered_gates (from main 68e0722a, 2026-09-08)
    status:      DESIGN PROVEN WITH FINDINGS — implementation not started (packet §4: stop at the design)
    evidence:    artifacts/platform_v2/tiered_gates/evidence/ (replay tool, replay table, synthetic fixtures,
                 mojibake proof; §5 durations UNMEASURED by owner decision)

## 0. Verdict first

1. **No historical defect escapes the tiering.** Every branch-introduced defect the broad gate has ever
   caught (Wave 1 F3 encoding; the four real `NEW_FAILURE`s on chore/collection_latency) sits in a merge
   that classifies **CORE_SURFACE** under the mechanical rules, so it still runs broad. Wave 1 classifies
   CORE on five paths (`grammar/compiler.py`, `grammar/plan.py`, `grammar/spec.py`, `grammar/deliverables.py`,
   `lifecycle_v2.py`), exactly as the packet requires.
2. **The proof for ADDITIVE_CAPABILITY is vacuous against history.** Of the 30 platform merges and direct
   platform commits since Platform V2, **zero** classify ADDITIVE and **one** classifies MODIFIED. Every
   "feature" chore in the record also edited a host or lifecycle file. The class is therefore proven only by
   construction (an AST insertion invariant) and by synthetic fixtures, never by a real merge. That is stated
   as the weakest point, not hidden.
3. **The owner's headline example is not cheap by import reachability.** A new feature definition
   (`_add(...)` in `features/registry.py`) is reachable from 139 of 178 test files because
   `features/__init__.py` imports the registry. Its derived surface is 81 % of the suite by count. Whether that
   is minutes or an hour is a measured question, left open in §5 by owner decision. Tracker, provider-adapter and analysis-op
   additions derive to 35 / 34 files (15 – 16 % of tests) and are the cases where the tiering pays.
4. **The one real defect (F3) is caught in seconds by a mechanical diff-hygiene check** (UTF-8 decode plus a
   mojibake detector): 4 of 4 corrupted lines flagged at the gate commit `5d3aad6a`, **0 false positives**
   across 12,774 tracked text files on main. That check belongs in every tier, including broad.
5. **Three platform facts block a green cheap gate today**, independent of this design: the committed
   test-failure baseline is schema 1 and `test_delta --check-baseline` reports `BASELINE_INCOMPATIBLE` on
   main 68e0722a; `cap scaffold` does not register a tracker in `TRACKER_BINDINGS` and the hand insertion is a
   circular import when the new module is imported first; generated `registry.json` conflicts in every
   batch merge. These are §7 escalations.

Recommendation: implement the tiering for **ADDITIVE tracker / provider-adapter / analysis-op** changes and
for **MODIFIED_CAPABILITY**, with the batch queue and the diff-hygiene check, after the baseline migration and
the `TRACKER_BINDINGS` fix. Do **not** promise "minutes" for feature-definition additions until the
`features/__init__.py` coupling is removed or the first real additive merge under the tiering shows the reachable set is fast (§5).

## 1. Change classes — mechanical rules

Classification is a pure function of `git diff --name-status -M <merge-base> <head>` plus the AST of the
touched registration files. The session declares nothing. Everything not matched by an allowlist is CORE.

| class | mechanical definition |
|---|---|
| **CORE_SURFACE** | any path not matched below: `research_workflow/**` (grammar, host, lifecycle, controller, closure, manifest, partitioning, policy, supervisor, workspace, …), `backtests/**`, `utils/**`, `scripts/*.py`, `config/**`, `conftest.py`, `pytest.ini`, `.gitattributes`, `studies/**` (pinned scientific evidence), agent definition files, any **deletion**, any registration file whose edit is not insertion-only |
| **MODIFIED_CAPABILITY** | every path is on the capability allowlist, tests, inert or generated, **and** at least one existing capability module is modified (M) in a way that is not insertion-only: `features/trackers/<x>.py` (not `host_bindings.py`), `research/analysis/diagnostic_ops.py` |
| **ADDITIVE_CAPABILITY** | every path is one of: **A** `features/trackers/<x>.py`; **A** test file under a test scope; **A** `research_workflow/capabilities/proposals/*.yaml`; **M** of a *registration file* passing the insertion-only AST rule; **M** `research_workflow/capabilities_index.yaml` passing the semantic seed rule; **M** of a *generated* file (`research_workflow/capabilities/registry.json`, `docs/RESEARCH_YAML_REFERENCE.md`), which the gate regenerates and compares rather than trusts; docs / artifacts |
| **INERT_OR_TESTS_ONLY** | only docs, artifacts, proposals or test files changed; runs the changed tests plus the readers of the changed data files plus the governance floor |

Resolution: CORE if any file votes CORE; else MODIFIED if any file votes MODIFIED; else ADDITIVE; else inert.
A mixed diff is therefore always its most expensive member. An unmapped path is CORE.

**Registration files and the insertion-only AST rule.** The platform registers primitives in four
hand-maintained literals inside modules that otherwise are core:

| file | registration literal(s) |
|---|---|
| `features/trackers/host_bindings.py` | `TRACKER_BINDINGS` dict, `__all__` |
| `research_workflow/provider_host.py` | `ADAPTER_REGISTRY` dict, `__all__` |
| `features/registry.py` | module-level `_add(...)` calls |
| `research/analysis/diagnostic_ops.py` | `OPS`, `OP_INPUTS` dicts |

A modification of one of these files is ADDITIVE **iff**, comparing the module-level AST before and after:
(a) every pre-existing top-level statement is present and AST-identical (`ast.dump` equality, so a comment or
whitespace change is invisible and an edit of any existing statement is not); (b) every pre-existing entry of
every module-level dict/list literal is present and unchanged; (c) the only additions are new entries in the
*declared* registration literals, new top-level `def`/`class` whose names did not exist before, new imports,
and (for `features/registry.py`) new module-level `_add(...)` calls; (d) no new module-level literal, no
decorated definitions, nothing else. Because every old statement is byte-identical at the AST level, no
existing code path can reference a new name; the change is invisible to every consumer that reads the literal
by key and visible only to consumers that enumerate it, which is exactly what the surface in §2 covers.

**Semantic seed rule.** `cap scaffold` re-serialises the whole `capabilities_index.yaml` (799 changed lines for
one appended entry, fixture A), so a textual insertion rule fails on the sanctioned flow itself. The rule is
semantic: parse both files; every old entry (by `id`) exists in the new file with an identical body; only new
ids were added.

**Generated files** are never merged on trust: the gate runs `cap generate --check` (and
`gen_yaml_reference`) on the candidate tree and compares content hashes; a stale or hand-edited generated file
is a gate failure, not a class vote.

**Diff hygiene (every tier).** Every changed text file must decode as strict UTF-8, and no added line may
match the mojibake detector `[ÂÃâ][cp1252 upper-half char]`. Proof: §4, F3.

## 2. Test surface per class — derivation

The surface is *derived* from a reverse coverage map, not asserted:

1. For each of the 178 test files under `research_workflow/tests`, `scripts/tests`, `features/tests`,
   `tests`, `research/analysis/tests`, compute the transitive repo-local import closure using the compiler's own
   walker (`research_workflow.grammar.compiler._static_imports`, function-level imports included, package
   `__init__` modules included, exactly as the frozen manifest is derived), seeded by the test file, its
   `conftest.py` chain, and **string literals** in the test that name a repo file or dotted module (this is how
   subprocess-driven tests — `sys.executable, "scripts/research.py"`, `-m research_workflow.lifecycle_v2` — enter
   the map; 45 of 178 test files spawn subprocesses).
2. Invert: `file → {tests whose closure contains file}`. Median closure per test is 96 files; 431 repo files
   are covered by at least one test.
3. For a diff: a changed `.py` contributes `reverse[file]`; a changed test contributes itself; a changed data
   file (yaml/json/md) contributes `reverse[m]` for every module `m` that names it (word-bounded `git grep`,
   so `registry.json` does not match `canonical_registry.json`); a generated file contributes
   `reverse[generator module]`; plus a fixed **governance floor** that runs regardless of reachability:
   `test_closure_transitive_imports`, `test_redteam_v2_closure`, `test_replay_closure`,
   `scripts/tests/test_execution_closure`, `scripts/tests/test_capabilities`, `test_grammar_v2`,
   `test_golden_fixture`, `test_runtime_bindings`, `test_docs_v2`.
4. Plus the non-pytest checks: `cap generate --check`, `python scripts/lint_host.py`, diff hygiene.

**What each class could break, and what covers it.**

*ADDITIVE_CAPABILITY.*

| plausible breakage | covered by | status |
|---|---|---|
| new id duplicates / collides with an existing capability id | `cap generate` raises `CAPABILITY_ID_DUPLICATE`; `cap generate --check` in the gate | covered |
| new module fails to import or has import-time side effects | `cap generate` imports every `TRACKER_BINDINGS` class and every registry `implementation`; the new module's own test | covered for import failure; **side effects beyond import success are not asserted** (finding F-7a) |
| compiler cannot bind the new id / declarations untruthful | `test_grammar_v2`, `test_golden_fixture` (floor) and the new test; `test_runtime_bindings` (floor) | covered for existing fixtures; the new id is exercised only by its own test until a study binds it |
| registry-wide enumerations change (canonical reference, alias rendering, feature universes of historical V1 studies with `source: all`) | `reverse[features/registry.py]` includes `test_registry_universe_output_contract`, `test_feature_system_v2`, `test_feature_surface_validation`, `test_candidate_authority` | covered — and this is why the feature-definition surface is large |
| a new tracker `FIELDS` / `EVENTS` name shadows a predicate name of an existing study | no test enumerates field-name collisions across bindings | **not covered** (F-7c) |
| frozen manifest / closure membership changes for sealed studies | new modules are outside every sealed closure by construction; `test_closure_transitive_imports`, `test_redteam_v2_closure` (floor) | covered |
| host boundary violated by a new adapter in `provider_host.py` | `lint_host` covers `research_workflow/host/` only; `provider_host.py` is outside its scope | **not covered by lint_host**; covered only by the adapter's own test (F-7d) |
| encoding corruption in a new or touched file | diff hygiene (proven on F3) | covered |

*MODIFIED_CAPABILITY.* The changed module's `reverse[...]` set plus the floor. Validation of the derivation
itself: on the only two merges with recorded broad-run defects, every failing test file lies inside the
derived surface — Wave 1: `test_redteam_v2_model_authority.py` ✔; collection_latency: `test_lifecycle_v2.py`,
`test_redteam_v2_closure.py` ✔ (plus `test_runtime_bindings.py`, `test_stage3_integration.py` ✔ for the two
provisioning failures). 5 of 5. Small sample; stated as such. A modified capability also stales every sealed
study that binds it — that is the study's freeze semantics, not the merge gate's job, and is unchanged.

*CORE_SURFACE.* Broad, unchanged: `research_workflow/tests scripts/tests` (+ `features/tests tests
research/analysis/tests`, which the baseline already scopes), `cap generate --check`, `lint_host`, diff hygiene.

## 3. Batched merge

**Batch.** An ordered set of chore branches, each with a live chore claim, each with a DONE result card whose
targeted tests passed, each classified individually from `merge-base(main, branch)..branch`. The batch class
is the maximum of its members; **one CORE member promotes the whole batch to broad** (constraint kept).

**Assembly (tested as a merged whole, never per branch).** The coordinator builds an integration ref
`batch/<id>` = current `main` + sequential `git merge --no-ff <branch>` in claim order. Per-branch surfaces do
not cover interactions between members (two insertions into the same registration table; two adapters for one
provider path), and the merged tree is what lands on main, so the union surface runs **once on the integration
commit**. Generated files are excluded from the merge and regenerated after the last member
(`cap generate`, `gen_yaml_reference`), then `cap generate --check` must be clean. Evidence from fixture
`tmp/synthBatch`: `registry.json` conflicted on all three merges, and two adjacent `_add(...)` insertions in
`features/registry.py` conflicted textually although they are semantically disjoint (F-5).

**Conflict.** A non-generated conflict ejects the later branch from this batch (its owner rebases on the
merged result and re-queues); the batch is re-assembled without it. A conflict never gets resolved inside the
batch.

**One member fails.** The union-surface run is the gate. On `NEW_FAILURE`, the failing node ids only
(seconds, not minutes) are re-run on each integration prefix `main+b1`, `main+b1+b2`, …; the first prefix at
which a node fails names the branch to eject. Re-assemble, run the union surface once more. Bound: two surface
runs per batch, then escalate. Baseline exemptions are consumed under the Wave 2 semantics (exact node, exact
message, exact scope, exact reference commit, exact environment); nothing is loosened.

**Lease and claim.** Claims are per branch and stay live until that branch is on main; the batch adds no
claim. Two live claims cannot overlap (`PLATFORM_SURFACE_OWNED_BY_ANOTHER_AGENT` at claim time), so members are
disjoint by construction; the coordinator additionally requires every member's diff ⊆ its own claim ∪ its own
test files ∪ generated files (the current `_merge_gate` write-surface check, extended to exempt generated
files, which no claim names today). The `MainMergeLock` is **not** held during the surface run (its max age is
1,800 s; a broad batch exceeds it). It is taken only for the final step: verify `main == batch base`,
fast-forward `main` to the tested integration head (history keeps one `--no-ff` merge per member), release.
If `main` moved during the run, the batch is stale and re-assembles; a batch never merges a tree it did not
test. Owners release their chore claims after `CAPABILITY_MERGED`; a study waiting on any member merges main
**once** per batch, which is the pace win the packet asks for.

## 4. Historical replay

Universe: every chore merge and direct platform commit on `main` since Platform V2 (`dc2ae0fe`), 30 commits.
Class and derived surface are computed by `evidence/tier_replay.py replay` (`evidence/replay.json`). "Broad
found" is what is persisted: only three merges have a recorded broad-run card; the rest ran targeted or
pre-baseline suites and recorded nothing.

| merge | branch | class | forcing paths | derived surface (files / tests) | broad found (recorded) | tier catches? |
|---|---|---|---|---|---|---|
| 474cd650 | end_cycle_wave1 | **CORE** | compiler, plan, spec, deliverables, lifecycle_v2 | 130 / 1943 | 74m41s at 5d3aad6a: F1 provider-binding (fixture), F2 missing model (fixture), **F3 encoding (real)**, 1 env | broad ✔; F3 also by diff hygiene (4/4 lines) |
| 8b3d3d2f | collection_latency | **CORE** | audit_packets_v2, governed_controller_v2, compiler, spec, lifecycle_v2, policy, provider_host | 132 / 1967 | research_workflow/tests at 30cc28c6: **4 real** (perf assertion in lifecycle end-to-end; 3 closure-perturbation tests), F1, F2, 1 env; fixed before merge; final targeted 193 OK | broad ✔; all 4 failing files inside the derived surface |
| 05656639 | docs/nt-collection-performance | INERT | docs only | 9 / 101 | none recorded | n/a |
| a7f932b0 | v2-freeze-provenance-multicell | **CORE** | lifecycle_v2 | 30 / 298 | none recorded | broad |
| be66e8de | v2-freeze-oos-multicell-model-records | **CORE** | lifecycle_v2 | 30 / 298 | none recorded | broad |
| 122c6f1a | controlled_feature_family_180s-missing_capability | **CORE** | lifecycle_v2 (context plumbing) + diagnostic_ops + registry seed | 34 / 384 | supervisor card: research_workflow/tests + test_capabilities, 0 new / 33 known | broad ✔ (nothing to catch) |
| df43989a | analysis-parity-session-exclusions | **MODIFIED** | diagnostic_ops.py (non-insertion edit) | 34 / 384 | none recorded (targeted) | derived surface; no defect on record |
| 59c53310 | supervisor-v1-efficiency-closeout | **CORE** | supervisor/*, agent files, AGENTS.md | 156 / 2236 | none recorded | broad |
| e6792ab7 | v2-closure-validate-before-write | **CORE** | lifecycle_v2 | 30 / 298 | none recorded | broad |
| 71e01ed3 | supervisor-v1-hardening-03 | **CORE** | supervisor/core, derive | 130 / 1943 | none recorded | broad |
| 933be461 | supervisor-v1-hardening-02 | **CORE** | supervisor/core, procs | 130 / 1943 | none recorded | broad |
| 66578afa | v2-closure-transitive-imports | **CORE** | compiler, PLATFORM_STATE.json | 33 / 335 | none recorded | broad |
| bb6cc9a7 | restore-historical-artifacts (2) | **CORE** | studies/** artifacts | 109 / 1607 | none recorded | broad |
| 5d1447ca | restore-historical-artifacts (1) | **CORE** | studies/** artifacts | 107 / 1568 | none recorded | broad |
| 7169c635 | supervisor-v1-hardening-01 | **CORE** | supervisor/* | 131 / 1952 | none recorded | broad |
| a33b1460 | research-supervisor | **CORE** | supervisor/*, handoff, research.py, agent files | 135 / 2018 | none recorded | broad |
| e461ea37 | v2-multi-arm-modeling | **CORE** | compiler, spec, lifecycle_v2, gen_yaml_reference | 34 / 366 | none recorded | broad |
| d8e99b4b | booster-integrity-and-test-isolation | **CORE** | scripts/parity/verify_native_booster_equivalence.py | 10 / 121 | none recorded | broad |
| fc767f2d | v2-diagnostic-window-and-analysis | **CORE** | host_bindings (non-insertion), capabilities.py, external_model_scoring, .gitattributes, … | 133 / 1991 | none recorded | broad |
| 6624a3ea | feature-window-parameterization | **CORE** | features/registry.py (4 removals), provider_host.py (23 removals: adapter rewrite) | 139 / 1922 | none recorded | broad — the one "add features" chore in the record was a host edit |
| df56be7b | platform-v2-redteam-hardening (follow-up) | **CORE** | model_migration, model_store, policy | 106 / 1559 | none recorded | broad |
| 82ff9b00 | platform-v2-redteam-hardening | **CORE** | 16 research_workflow modules, host_bindings | 132 / 1953 | none recorded | broad |
| 366cbb48 | platform-v2-do-soon | **CORE** | grammar, host, fixtures | 137 / 2027 | none recorded | broad |
| df26b124 | platform-v2-closeout | **CORE** | backtests/nt_runtime | 15 / 235 | none recorded | broad |
| dc2ae0fe | platform-v2 (DO NOW) | **CORE** | 75 files across the platform | 178 / 2373 | none recorded | broad |
| fba27a44 | direct: sessions/handoffs/test baseline | **CORE** | agent files, research.py, workspace | 154 / 2209 | none recorded | broad |
| 8338e554 | direct: writer lease identity | **CORE** | workspace, agent files | 155 / 2236 | none recorded | broad |
| bfedf510 | direct: antigravity identity | **CORE** | agent files, workspace | 29 / 270 | none recorded | broad |
| 63aecf79 | direct: Globex calendar authority | **CORE** | dataset_v2, workspace, calendars, registry | 130 / 1943 | none recorded | broad |
| 3942565c | direct: old-runtime policy + tuning | **CORE** | governed_controller_v2, compiler, spec, lifecycle_v2, policy, tuning | 107 / 1567 | none recorded | broad |

Totals: 27 CORE, 1 MODIFIED, 1 INERT, **0 ADDITIVE**.

**The named cases.**

*F3, Wave 1 encoding corruption.* `03330576` restored four lines in `grammar/compiler.py` (3) and
`lifecycle_v2.py` (1) that a cp1252 round-trip had turned into mojibake (`âˆª` for `∪`, `âŠ†` for `⊆`,
`Â§` for `§`). Wave 1 classifies **CORE_SURFACE** on the compiler, plan, spec, deliverables and lifecycle
paths; it runs broad; confirmed. Independently, the diff-hygiene detector flags all four corrupted lines,
reports 3 + 1 hits on the two files at the gate commit `5d3aad6a`, and has zero hits on any of the 12,774
tracked `.py/.md/.yaml/.json/.toml/.txt` files on main (14 legacy non-UTF-8 study reports under
`backtests/studies` and `studies/*` are outside every chore surface). Cost: seconds. So F3 would have been
caught in every tier, in seconds, before any test ran.

*The three W0-era failures.* They first appeared together on 2026-09-06 in the chore/collection_latency
run at `30cc28c6` and again in Wave 1:

| failure | node | class of cause | tier behaviour |
|---|---|---|---|
| missing model artifact | `test_stage3_integration.py::test_stage3_model_c_long_short_routing` | worktree provisioning: `studies/clean_maturity_flip_model_rolling_productivity/artifacts/train_fitted_models.joblib` is git-ignored and absent in a fresh worktree; not code | tier-independent. The node is inside the derived surface of any change reaching `features/registry.py` (fixtures B, B2) and outside the tracker/analysis-op surfaces (A, C). Under Wave 2 semantics it is `NEW_FAILURE` wherever it runs and is never auto-classified environmental; the cheap tier does not remove the provisioning requirement, it only runs the node less often |
| provider-binding assertion | `test_runtime_bindings.py::test_episode_study_is_provider_host_mode_and_all_features_bind` | the same missing artifact seen through `derived_input:model_c_score_at_candidate` unbound; not code | in the **governance floor**, so every tier runs it |
| encoding | `test_redteam_v2_model_authority.py::test_iv_compiled_availability_table_names_the_rule_and_dependencies` | real, in CORE files | CORE → broad; also diff hygiene |

**Verdict on §2 of the packet:** no historical defect is missed by the tier its merge would have been routed
to. The statement is strong for CORE (all defects live there) and empty for ADDITIVE (no instance exists).

**Synthetic fixtures (the only positive evidence for ADDITIVE).** Built on a disposable worktree
(`tmp/synth*` from 68e0722a; evidence/synth_*.json), each classified by the same tool:

| fixture | what it adds | class | surface files / tests | note |
|---|---|---|---|---|
| A `85f52c56`→`8b40dd80` | `cap propose` + `cap scaffold tracker.synth.bar_count`, `TRACKER_BINDINGS` insertion, `cap generate` | ADDITIVE | 35 / 366 | scaffold alone is unbindable (F-3); the insertion is a circular import when the binding module is imported first — the scaffolded test does exactly that (F-3) |
| B `00984fa5` | one `_add('synth_vol_sum_45s', …)` on an existing provider | ADDITIVE | 139 / 1922 | 81 % by count: `features/__init__.py` imports the registry (F-2) |
| B2 `be285969` | new provider module + adapter `class` + `ADAPTER_REGISTRY` insertion + `_add` | ADDITIVE | 140 / 1922 | the new-family case; same reachability as B |
| C `1fcc9b29` | new analysis op function + `OPS`/`OP_INPUTS` insertion | ADDITIVE | 34 / 384 | |
| batch `0f54a39b` | A + B + B2 + C merged | ADDITIVE | 141 / 1922 | `registry.json` conflicted on every merge; B and B2 conflicted in `features/registry.py` (F-5) |

## 5. Duration per class (measured)

**UNMEASURED — left open by owner decision (2026-09-08).** Two detached timed runs (the five test scopes at
68e0722a, and fixture A's derived surface, both with `evidence/plugin/timing_capture.py`) were started and
then killed at roughly two-thirds and one-half progress; their partial records are kept as
`evidence/broad_timing.partial.jsonl` and `evidence/surfaceA_timing.partial.jsonl` and must not be quoted as
durations. The broad baseline is already recorded (74m41s, `research_workflow/tests scripts/tests`, 2,088 tests,
2026-09-07), and the derived-surface durations fall out of normal use once the tiering exists: the Wave 2
`test_delta` already records `per_test_timings` and `wall_seconds` on every card. `evidence/durations.py`
aggregates any such record over the surfaces in `replay.json` and `synth_*.json`.

What is known without measurement, by count: tracker / analysis-op additions run 15 – 16 % of the tests; a
feature-definition addition runs 81 %; the historical MODIFIED_CAPABILITY merge runs 16 %; CORE stays at 100 %.
The one observation from the partial broad record worth carrying: the suite's time is concentrated in a few
end-to-end files (`test_lifecycle_v2.py`, `test_redteam_packet_f.py`, `test_declarative_analysis.py` were the
three slowest of the first 45 files), and those three are inside every derived surface above, so a
count-based percentage overstates the time saving. The first real additive merge under the tiering will
produce the number.

## 6. Where the proof is weakest

1. **ADDITIVE has no history.** 0 of 30 merges. The class is justified by the AST insertion invariant and by
   four synthetic fixtures; a real additive merge has never been gated, so its first real use is the first
   test of the rule. Mitigation: run the cheap tier *and* the broad tier in shadow for the first N additive
   merges and diff the outcomes before trusting the cheap verdict alone.
2. **Static reachability is a proxy.** Dynamic dispatch through `importlib.import_module(implementation)`
   (registry generation) and data-driven fixtures (`fixtures/golden/*.json`, authority bundles) reach the map
   only through string-literal seeds and generator modules. The two recorded defect sets (5 files) were all
   inside the derived surfaces, but that sample is tiny and entirely CORE.
3. **Feature-definition additions are near-broad by reachability** (F-2). Either §5 shows the reachable set
   is fast, or a platform change (definitions out of the package-init import path, or a registry-driven
   `TRACKER_BINDINGS`/feature table with lazy import) is a prerequisite for the owner's headline case.
4. **Insertion-only accepts new `class`/`def` bodies in `provider_host.py`.** Safe for existing code paths by
   AST identity, but the new adapter's import-time behaviour and host-boundary discipline are checked only by
   its own test; `lint_host` does not cover `provider_host.py` (F-7d).
5. **Baseline.** Since Wave 2 merged (68e0722a), `test_delta --check-baseline` reports
   `BASELINE_SCHEMA_REQUIRES_EXPLICIT_MIGRATION, BASELINE_COMMIT_MISMATCH, BASELINE_ENVIRONMENT_MISMATCH` on
   main. Every known failure inside any tier's surface is `NEW_FAILURE` until a reviewed `--update-baseline`
   is recorded on main. The cheap tier inherits this exactly as broad does (F-6).
6. **Batch conflicts are structural** (F-5): the generated registry and adjacent registrations in one file.
   The batch design regenerates and ejects; it does not resolve.

## 7. Escalations (packet §5)

- **E-1 (§5 bullet 4) Plausible ADDITIVE breakages without a covering test:** F-7a import-time side effects
  of a new module beyond import success; F-7c tracker field/event name collisions across bindings; F-7d host
  boundary of new adapters in `provider_host.py` (outside `lint_host`). Reported, class not widened.
- **E-2 Platform prerequisite:** `cap scaffold` writes the module, test and seed but not the
  `TRACKER_BINDINGS` entry the compiler binds from, and a hand insertion imports the new module from the
  registration module that defines its base class — a circular import as soon as anything imports the new
  module first (fixture A failed collection until its test imported `host_bindings` first). The sanctioned
  additive flow is not additive today. Fix belongs to the platform: base class out of the registration module,
  or a registry-driven binding table with lazy import.
- **E-3 Platform prerequisite:** baseline migration to schema 2 on main before any gate can be green.
- **E-4 Semantic decision for the owner:** whether the feature-definition case is acceptable at its measured
  reachable-surface duration (§5) or requires the decoupling in weakest-point 3 first.
- No escalation on lease or claim weakening: the batch design needs none (§3).
- No escalation on mechanical derivability: every class is a pure function of the diff and the AST.

## 8. Facts recorded for the result card

- `python scripts/research.py study result --packet artifacts/platform_v2/tiered_gates/PACKET.md --status DONE --report …`
  returns `PACKET_INVALID: PACKET_BODY_MISSING` — the packet was pasted prose, not a supervisor-written packet
  with a JSON body and `packet_sha256`, so no result card can be written for it by the CLI. This report is the
  deliverable.
- Chore claim `tiered_gates` (live, agent claude, session eeea52b1) over
  `artifacts/platform_v2/tiered_gates` and `scripts/tiered_gate.py`; nothing under `scripts/` was written
  (design only). Disposable worktree `…-tiered_synth` on `tmp/*` branches holds the synthetic fixtures; it is
  not merged and can be removed with `git worktree remove`.
