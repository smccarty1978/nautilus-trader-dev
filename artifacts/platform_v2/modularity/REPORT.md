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

Branch head at gate time: `22704e87` (B2, B1, B3, B2 follow-up, `main` 8971320c merged in, reports).
Command, run alone on the host, the ignored model artifact provisioned into the worktree first
(sha256 `03f602c5…`, the Wave 1 triage bytes):

```
python scripts/test_delta.py research_workflow/tests scripts/tests features/tests tests research/analysis/tests --baseline-reference ee16002e --json
```

**Operational fact, found here:** the enforced classifier's default reference is
`merge-base(HEAD, main)`, but a re-recorded baseline necessarily records the commit it *ran on*
(`ee16002e`), and the commit that *adds* the file is the next one (`8971320c`). So after any re-record,
the default `--check-baseline` on every branch reports `BASELINE_COMMIT_MISMATCH` by construction, and
every gate must name the recorded commit with `--baseline-reference` until the next re-record. The
documented flag exists for exactly this ("exact approved commit/ref"); nothing was loosened. Whether
`platform_commit` should instead be allowed to equal the parent of the baseline commit is a
one-line semantic decision for the owner; listed, not taken.

**Result (`evidence/s2_gate.card.json`, `evidence/s2_gate_assessment.json`):** 84m27s (5,067 s), 2,397 ran,
2,304 passed, 66 failed = 34 `KNOWN_BASELINE_FAILURE` + **32 `NEW_FAILURE`**, 0 fixed. **Red by the letter
of the enforced classifier; zero failures attributable to this branch.** Every one of the 32 is
explained:

| bucket | n | what it is |
|---|---:|---|
| baseline node, identical after normalising repo root / pytest tmp session dir / scratch name | 24 | the exact-message rule compares strings that embed `…\Nautilus Trader-modularity\…` vs `…\Nautilus Trader\…`, `pytest-of-…/pytest-2883` vs `pytest-2861`, `_delta_scope_<random>`; 23 of the 64 baseline entries carry such tokens and can never match from any worktree |
| baseline node, message embeds a value that changes every run or every commit | 3 | `test_acc12_canaries_green` (subprocess timing `in 1.69s`/`1.73s`), `test_rt2b2_…moves_the_composite[…]` ×2 (the tree composite hash) |
| baseline node, same finding at a shifted line | 1 | `test_no_hardcoded_feature_count_in_generic_workflow`: `compiler.py:853` → `:868`, B1 inserted 15 lines above it |
| worktree provisioning (git-ignored inputs present only in the canonical checkout) | 4 | `test_aggregate_freeze_opens_the_real_oos_gate` (180s study's bound model artifact → different failure mode), `test_materialization_required_when_catalog_absent` (`data/raw/YM_v0_1s_2024.parquet`), `test_pre_flip_reliability_contracts` ×2 (`studies/*/_work/prepared_*.parquet`) |

Cross-check against the branch: the S3 surface run on the same code (36 files, 421 passed) and every
targeted run in §4 are consistent with this; the only failures ever traced to this branch were the four
closure exemplar tests, fixed in `13529d1c` and green in this run.

**Finding for the gate design (escalated, decision needed):** Wave 2's exact-signature rule is not
reproducible for a material fraction of the baseline — 23/64 entries embed the repo root or a pytest
session directory, 3 embed run-varying values — so a broad gate from any worktree other than the one the
baseline was recorded in cannot be green on those nodes regardless of the code. Options, none taken here:
(a) normalise machine/session-local tokens only (repo root, `pytest-of-<user>/pytest-<n>`,
`_delta_scope_<hex>`, `0x…` addresses) at record and compare time — hashes, line numbers and timings stay
exact; under that rule this run has 24 fewer NEW and 8 remain (3 run-varying, 1 line shift, 4
provisioning); (b) per-entry `signature: node_only` for the handful of run-varying messages; (c) gates run
only in the canonical checkout (fixes the path class only). Merge of this branch waits on that decision.

**Decision and merge (owner, 2026-09-08):** option (a) taken. `test_delta` now compares portable signatures
(`dbb2dd3f`, merged `418202eb`). Offline re-classification of the saved card under the merged rule
(`python scripts/test_delta.py` classify over the 32 recorded messages): **24 KNOWN, 8 NEW** — the three
run-varying messages (`test_acc12_canaries_green` timing; `test_rt2b2_…moves_the_composite[…]` ×2 tree
composite), the one line shift (`test_no_hardcoded_feature_count…`, `compiler.py:853→868` from B1), and the four
worktree-provisioning nodes. None is a behaviour change of this branch. Merged into `main` on that
assessment; the run-varying/line-shift signatures are listed for a follow-up decision (per-entry
`node_only` signature or normalising `in <n>s` / composite hashes — not taken here).
