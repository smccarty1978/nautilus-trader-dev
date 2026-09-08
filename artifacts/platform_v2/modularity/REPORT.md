# Session 2 — the three blockers (chore/capability-modularity)

    packet:   RESTORE THE GATE, THEN UNBLOCK MODULARITY — Session 2
    branch:   chore/capability-modularity from main 68e0722a; three commits, one per blocker
    status:   B1 DONE · B2 DONE WITH ESCALATION (surface stays large — structural coupling named) · B3 DONE
    gate:     CORE_SURFACE (host_bindings.py, compiler.py, capabilities.py) → one broad run against the
              Session 1 baseline before merge; result appended in §5 when it lands

## B1 — `cap scaffold` registers trackers, without the circular import  (`9b724dbf`)

**Answer to the open question — does a tracker need the host to be told about it?** No. The host never
read the table: `research_workflow/host/strategy.py` instantiates every tracker from the compiled plan's
`implementation` dotted path (`_load(t["implementation"])`). Only two readers existed: the compiler
(`_binding_table`, capability id → class) and the registry generator (`_host_bindings`). Both read the
hand-maintained `TRACKER_BINDINGS` dict at the bottom of the module that also defines `BaseBinding`,
which is why a new binding module (which subclasses `BaseBinding`) and the registration module (which
would import the new binding) imported each other.

Fix, cycle removed rather than hidden:

- `BaseBinding` moves to `features/trackers/base.py`; `host_bindings.py` re-exports it.
- `TRACKER_BINDINGS` is now a lazy mapping over `BUILTIN_BINDINGS` (the six bindings declared in
  `host_bindings.py`) plus every binding **seeded in `research_workflow/capabilities_index.yaml`**
  whose `host_binding` / `implementation` resolves by import path to a `BaseBinding` subclass with the
  matching `CAPABILITY`. Resolution happens on access, after every module is initialised. The seed entry
  `cap scaffold` already wrote is the registration; no hand edit anywhere.
- The scaffold template imports from `features.trackers.base`.
- The compiler refuses a seeded tracker whose registry status is `candidate` or `broken` with a
  `MISSING_CAPABILITY` gap naming `cap promote`, so an unpromoted scaffold is bindable by its own
  tests but never silently by a governed study.

Coupling converted from ACCIDENTAL to gone for trackers, feature hosts and derived inputs (the three
seeded hosted kinds). Provider adapters (`ADAPTER_REGISTRY` in `provider_host.py`) and analysis ops
(`OPS` in `diagnostic_ops.py`) keep their hand-maintained dict for now; the same registry-driven
resolution applies to them and is the pattern to follow.

Tests: `research_workflow/tests/test_capability_modularity.py` (seed resolution through the index and the
compiler table; unresolvable / foreign / built-in-shadowing seeds skipped; binding module imported
**before** the registration module in a subprocess; scaffold template exec-s to a `BaseBinding`
subclass; compiler status refusal).

## B2 — `features/__init__.py` stops importing the registry  (`9d90f037`)  — **GATE NOT MET, ESCALATED**

The package init re-exported `FeatureLibrary`, `FeatureEngine`, three trackers and two registry
functions. Nothing imported them by name; the only `import features` uses are path anchors
(`Path(features.__file__)`). The init is now docstring-only.

**Gate:** re-derived surfaces on the fixed tree with the tiered-gates replay tool
(`artifacts/platform_v2/tiered_gates/evidence/tier_replay.py`, `TIER_ROOT` = this worktree):

| module | test files reaching it, main 68e0722a | after B2 |
|---|---:|---:|
| `features/engine.py` | 139 | **4** |
| any `features/trackers/<x>.py` via the package init | 139 | 0 (a tracker import no longer loads the registry: subprocess test) |
| `features/registry.py` | 139 / 178 | **132 / 181** |
| fixture B (one `_add(...)` feature definition) | 139 files / 1,922 tests | 133 files / 1,848 tests |
| fixture C (analysis op) | 34 / 384 | 35 / 384 |

The package-init artifact is gone, but the feature-definition surface stays at 73 % because
`features/registry.py` is a **genuine runtime dependency of core modules**, reached through them:

| importer (reach) | form | what it uses |
|---|---|---|
| `research_workflow/provider_host.py` (110) | in-function | `resolve_feature_instances` & co. — the host binds feature instances |
| `research_workflow/forward_outcomes/guard.py` (109) | in-function | `resolve_feature_request` — the outcome-leak guard checks names against the registry |
| `research_workflow/output_manager.py` (97) | in-function | `resolve_feature_instances`, `resolve_source_universe` |
| `backtests/nt_runtime/modes/collect.py` (56) | in-function | `derive_study_feature_requirements` |
| `research_workflow/generic_collector.py` (54) | module-level | `resolve_runtime_feature_aliases` |
| `research_workflow/grammar/compiler.py` (30) | in-function | canonical bundle lookups |
| `research_workflow/phase0.py` (29) | module-level | `resolve_feature_instances` |

Function-level imports do not help: the platform's own closure walker (and the replay tool, which
reuses it) counts imports anywhere in a file, by design. This is not an import-graph artifact. The
definitions (data: `_add(...)` calls, `FEATURE_REGISTRY`) and the resolution API (code:
`resolve_*`, `canonicalize_*`, `derive_*`) live in one module, and the resolution API is what the
host, the guard and the output manager need. Making a definition addition invisible to them requires
splitting the definitions out of the module and loading them dynamically (per-definition files or a
data file discovered at runtime), so that no static import edge exists from the resolver to any
single definition. That is a restructuring of `features/registry.py` and its authority bundle
(`features/authority/*`, `CANONICAL_FEATURE_REFERENCE.yaml`), not a one-line fix, and it is outside
this packet. **Escalated (packet ESCALATE, bullet 2).**

Consequence for the tiering: tracker, feature-host, derived-input and analysis-op additions are the
cheap additive class today (34–35 files); feature-definition additions are not, and the tiered gate
must say so rather than pretend.

**B2 follow-up finding (from the Session 3 surface run).** Four tests in
`scripts/tests/test_execution_closure.py` failed on the B2 tree: the Red Team A1.3 pin required
`features/engine.py`, `library.py`, `collector.py` and `trackers/median_center.py` to be sealed in the
legacy ES study's closure, and three mutation tests used `features/engine.py` as their exemplar. Those
four files were in the closure **only because the package init imported them**: nothing on the collect
path imports or references `FeatureEngine`, `FeatureLibrary`, `FeatureCollector` or
`MedianCenterTracker` (the legacy median-center implementation is remapped to `generic_median_center`
by the promotion inventory; the only static importer of `features.engine` in the repository is
`scripts/run_full_legacy_feature_parity.py`). They executed at collect time as a side effect and were
sealed as dead code; after B2 they no longer execute and are correctly outside the closure (ES closure
145 files, still containing `features/__init__.py`, `registry.py`, `trackers/wick.py`,
`generic_median_center.py`). The tests were re-pointed to files that do execute
(`features/trackers/wick.py`, `generic_median_center.py`, `backtests/nt_runtime/__init__.py`); the
mechanism they pin — every package `__init__` on the import path is walked and its imports followed —
is unchanged and still exercised. Sealed historical V1 studies whose frozen manifest listed those four
files will resolve a different composite from now on; they are closed and terminal, and this is the
same staleness any closure-affecting platform change causes (CLAUDE.md §3).

## B3 — `registry.json` stops conflicting on every batch merge  (`3adcb9b0`)

The generated registry is git-ignored. `load_registry()` serves the on-disk cache when its recorded
`inputs_sha256` (seed index, feature authority bundle, dataset specs, tracker and host modules,
`entry_references.py`, `capabilities.py`) matches the tree, and rebuilds it otherwise — about 10 s once
per fresh worktree, transparently inside `compile_study`. `generate(check=True)` rebuilds, fails
`CAPABILITY_REGISTRY_STALE` when an existing cache disagrees with the tree (inputs outside the digest,
such as the test files a primitive names, changed), and builds a missing cache instead of erroring.

Verifiability is unchanged: the build is a deterministic function of the tree (`generated_at_utc` and
`inputs_sha256` sit outside `content_sha256`), every compiled plan records `registry_sha256`, and
the merge gate's `cap generate --check` still runs. A branch that adds a capability never merges a
generated file again. Docs updated (`WORKFLOW.md` map row, `docs/RESEARCH_WORKFLOW.md` §21.6);
`test_docs_v2` reads through `load_registry()`; two new tests pin on-demand build, cache hit without
rebuild, and re-keying on an input change.

Not addressed, same shape: `docs/RESEARCH_YAML_REFERENCE.md` is also generated and tracked
(`scripts/gen_yaml_reference.py`, checked by `test_docs_v2`); it conflicts the same way when two
branches change the grammar. Listed, not fixed.

## 4. Targeted evidence (per commit)

| commit | targeted run | result |
|---|---|---|
| B2 `9d90f037` | `features/tests`, subprocess import test | 2 failures = baseline entries (`test_candidate_authority`, `test_feature_system_v2`), identical with the original `__init__.py` restored |
| B1 `9b724dbf` | `test_capability_modularity` (6) + `test_grammar_v2` + `test_runtime_bindings` + `test_host_core` + `scripts/tests/test_capabilities.py` + `features/tests` | 78 passed; 3 failures = the 2 baseline entries + the fresh-worktree missing model artifact (`test_episode_study_is_provider_host_mode_and_all_features_bind`) |
| B3 `3adcb9b0` | `scripts/tests/test_capabilities.py` + `test_docs_v2` + `test_capability_modularity` | 27 passed; `cap generate --check` OK; ignore rule verified |
| all three | `test_grammar_v2` + `test_golden_fixture` + `test_closure_transitive_imports` + `test_redteam_v2_closure` | 38 passed |

## 5. Merge gate (CORE_SURFACE, broad, against the Session 1 baseline)

_pending: appended when the run lands_
