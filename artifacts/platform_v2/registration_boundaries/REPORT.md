# Registration boundaries — one semantic idea, applied twice

    packet:   REGISTRATION BOUNDARIES
    branch:   chore/registration_boundaries, from main 6467cc41 (clean)
    commits:  f3f8db0a  feat(features)   features/registry.py is a registration boundary
              20cd3d13  feat(analysis)   research/analysis/ops.py is the analysis-op boundary
              9a4a9873  refactor(caps)   a registration boundary reads its own index file
              291feeaa  docs             RESEARCH_WORKFLOW.md §21.14
    class:    CORE_SURFACE (expected; pays the broad gate)

## 0. Verdict

| Gate | Result |
|---|---|
| **F1** golden resolution | **PASS** — the full 2.7 MB snapshot of every observable resolver output is **byte-identical**, sha256 `7055ec26…` before and after |
| **F2** surface collapse | **PASS, better than target** — 132 → **10 files / 121 tests**; the target was ~35 |
| **F3** additive classification | **PASS** — `ADDITIVE_CAPABILITY`, one file touched, no generated output in the diff |
| **F4** consumers untouched | **PASS** — `provider_host`, the outcome guard, the output manager, `collect.py`, `generic_collector`, `phase0`: zero lines changed, not even an import |
| **A1** golden resolution | **PASS** — every op resolves to the same implementation, inputs and context flag |
| **A2** surface | **REPORTED, NOT MET** — 37 files / 428 tests, ≈ the 36 it was. Structural; §3 below |
| **A3** no exclusion list | **PASS** — nothing anywhere names a test to exempt it; pinned by a test |

One escalation (§6): merging this stales the freeze of the two studies whose leases are live.

## 1. The rule, as implemented

A **registration boundary** is a module that (1) exposes a stable resolution API consumers
import, and (2) discovers registered capabilities through the declared capability index, never
by statically importing them. Recorded in `docs/RESEARCH_WORKFLOW.md` §21.14 with the two
obligations it creates (explicit closure seeding; a boundary reads its own index file).

| Boundary | Catalogue side | Index file |
|---|---|---|
| `features/trackers/host_bindings.py` (B1, already merged) | `features/trackers/*.py` | `capabilities_index.yaml` |
| `features/registry.py` — **new** | `features/definitions/*.py` | `capabilities_index.d/feature_definitions.yaml` |
| `research/analysis/ops.py` — **new** | `research/analysis/diagnostic_ops.py` | `capabilities_index.d/analysis_ops.yaml` |

## 2. Feature definitions — the primary target

`features/registry.py` was 1,714 lines holding both the catalogue (693 physical entries, 41
canonical definitions, 36 legacy instance aliases) and the resolution API that seven core
modules import. Split three ways:

* `features/feature_types.py` — `FeatureDefinition`, `FeatureInstance`, `FeatureInstanceError`,
  the name regexes, `_duration_seconds`. The vocabulary both sides share.
* `features/definitions/` — `physical_catalogue.py`, `canonical.py`, `legacy_instances.py`,
  plus `providers.py` for the two provider identities two catalogues both name. Data only.
  The package `__init__` is docstring-only, deliberately: re-exporting the submodules would put
  every definition straight back on the reachable surface.
* `features/registry.py` — the resolver. It reads
  `capabilities_index.d/feature_definitions.yaml`, imports each declared catalogue by dotted
  path on first use, and merges them in declared order. `FEATURE_REGISTRY`,
  `CANONICAL_FEATURE_DEFINITIONS`, `LEGACY_FEATURE_INSTANCE_OVERRIDES` and `_ALIAS_TO_CANONICAL`
  are served by module `__getattr__`, so every consumer and every historical test reads them
  under their existing names, unchanged.

Fail-closed on all three ways this can rot: an index declaring no catalogue
(`FEATURE_DEFINITION_INDEX_EMPTY`), an unimportable catalogue (`…_UNRESOLVED`), and a catalogue
that contributes none of the three dicts (`…_EMPTY`). Each has a test.

### F1 — golden resolution

`features/tests/golden_feature_resolution.py` snapshots **every** value a consumer can observe,
not a sample: each of the 693 physical entries and 41 canonical definitions resolved through
both authorities; each of the 36 legacy aliases validated, aliased, and turned into input
requirements; every declared parameter value, timeframe and combination of every definition;
all 40 `(source, authority, legacy_mode)` universe surfaces; family and engine alias surfaces;
provider-column canonicalisation; five study-level derivations including the full canonical
universe; and twelve fail-closed error cases with their exact messages.

Generated on main **before** any change and again on the branch **after** it:

```
full snapshot (2.7 MB, uncompressed)  sha256 7055ec2671e337922905b3b88a4106b429b77e5918d5af60cb0e47557303fb71   (pre)
full snapshot (2.7 MB, uncompressed)  sha256 7055ec2671e337922905b3b88a4106b429b77e5918d5af60cb0e47557303fb71   (post)
```

Committed as a 229 KB per-name digest manifest (`features/tests/golden/feature_resolution.json`,
composite `f7244c21…`) so a failure names the binding that moved; `--full <path>` regenerates the
whole snapshot for diffing. This is what converts the over-approximation into a proof: adding a
definition cannot change how an existing binding resolves, because nothing an existing binding
resolves to changed when the definitions moved out of the module every consumer imports.

### F2 — surface

| | main 6467cc41 | branch |
|---|---:|---:|
| test files reaching `features/registry.py` | 132 | 138 — it is the resolver, and a resolver edit *is* core |
| test files reaching a definition catalogue | 132 | **1** |
| derived surface, one `_add(...)` definition | 133 files / 1,848 tests | **10 files / 121 tests** |

The ten: `features/tests/test_feature_definition_boundary.py` plus the nine-file governance
floor. None of the four end-to-end proofs. This is below the ~35 tracker figure the packet set
as the target, and the reason is worth stating: a feature-definition addition needs **no index
edit at all** — the catalogue module is already registered — so the only file in the diff is one
nothing reaches.

### F3 / F4

`tier_replay classify` on the synthetic addition: `ADDITIVE_CAPABILITY`, one row,
`features/definitions/physical_catalogue.py`, *registration file: insertion-only*. Nothing
generated in the diff (`registry.json` is untracked since B3).

`git diff --stat` over the six consumers the escalation table named is empty. `provider_host`,
`forward_outcomes/guard`, `output_manager`, `nt_runtime/modes/collect`, `generic_collector` and
`phase0` are byte-identical to main. `compiler.py` changed, but as a consumer of the *boundary*
(it imports `definition_files()` to seed the closure), not because the API moved.

## 3. Analysis ops — same rule, and the honest result

`OPS` / `OP_INPUTS` / `OP_CONTEXT` are gone from `diagnostic_ops.py`. Each op is declared in
`capabilities_index.d/analysis_ops.yaml` with `id`, `implementation`, `inputs`,
`needs_context`; `research/analysis/ops.py` resolves and dispatches. `lifecycle_v2` and
`compiler.py` changed at their import line. **A1 passes**: identical implementation, inputs and
context flag for all nine ops.

Not an exclusion list (**A3**): `test_no_exclusion_list_replaces_the_boundary` fails if the name
of any end-to-end proof appears in the boundary, the implementation module or either consumer.
Not a lazy import either: the reachability edge is gone because the resolver genuinely does not
import the implementation.

**A2 measured: 37 files / 428 tests, ADDITIVE_CAPABILITY.** The 36 → 37 is the new boundary test.
The three end-to-end files are still in it. The target of ~14 minutes was **not** reached, and
the reason is structural, not an import artifact:

| module | test files reaching it | of which the four heavy end-to-end proofs |
|---|---:|---:|
| `research/analysis/diagnostic_ops.py` | 32 → **3** | 4 → **0** |
| `research/analysis/ops.py` (the boundary) | 34 | 4 |
| `research_workflow/grammar/compiler.py` | 33 | **4** |
| `research_workflow/lifecycle_v2.py` | 24 | 4 |
| `research_workflow/capabilities.py` | 34 | 4 |
| `features/trackers/host_bindings.py` (B1, merged) | 35 | 4 |

The boundary did exactly what the packet predicted: **32 → 3** for the implementation module.
What it cannot remove is that an op's *registration* is an index entry, the compiler validates
declared op ids against the index, and `research_workflow/grammar/compiler.py` **on its own**
reaches all four of `test_supervisor_blackbox`, `test_redteam_packet_f`, `test_lifecycle_v2` and
`test_redteam_v2_model_authority` — 83 % of that tier's wall time. So does `lifecycle_v2` on its
own, which means **the previously proposed lazy import in `lifecycle_v2` would not have reached
~14 minutes either**; it would have moved the edge without moving the number.

Two readings, both true, as §7 asks:

1. **The rule works and the residue is genuine.** Reachability from a capability's
   implementation collapsed to 3. What remains is a real dependency: registering a capability
   changes the index; the compiler reads the index; the end-to-end proofs run the compiler.
   Under this reading A2 is correct at 37 and the tier is ~59 minutes, and so is the
   already-merged tracker tier (35 files, same four heavy proofs) — the earlier "~35 files ≈
   minutes" assumption was never validated against time and does not hold.
2. **The residue is an artifact of how a *registration* is derived.** Adding an op id cannot
   change how an existing declared op resolves, exactly as for feature definitions; charging the
   addition with everything the compiler can reach is the same over-approximation one level up.
   Under this reading the next boundary is the index reader itself, and ~14 minutes is reachable
   — by a change to the surface-derivation rule for an index-only edit, not by architecture.

Consequences: under (1), stop here and accept ~59 minutes for every capability tier, feature
definitions excepted. Under (2), the next change is to the derivation, and it must be a *rule*
("an index entry addition derives to the readers of that kind"), never a list of test names.
Not decided here.

## 4. The 138-file finding, and why the index was split

Making `features/registry.py` read the shared `capabilities_index.yaml` had a cost that only the
measurement exposed: because the surface rule attributes a data-file edit to every module that
reads it, and `reverse[features/registry.py]` is 138, a **one-line analysis-op addition derived
to 138 files instead of 37**. A boundary that reads the shared index charges every *other*
kind's edit to everything that boundary serves.

Fixed at the boundary, not with an exclusion: kinds that have a boundary keep their own index
file under `research_workflow/capabilities_index.d/`. `cap generate` merges the directory into
the one registry and refuses a kind declared twice (`CAPABILITY_KIND_DECLARED_TWICE`); the
aggregate keeps the kinds whose only reader is the generic one and stays the file
`cap propose/scaffold/promote` writes (neither moved kind is scaffoldable, so no writer
changed). The generated registry's `content_sha256` is unchanged by the move: `be22870e…`.

## 5. Nothing was weakened

* **Closure.** A dynamically resolved module is invisible to the import walk, so it is seeded by
  name: `definition_files()` at `_resolve_features`, `implementation_files(declared ops)` +
  the boundary at `_resolve_analysis`, and the same definition list in
  `scripts/resolve_execution_manifest.py` for the V1 manifest. Verified: the closure seeded at
  `features/registry.py` plus the declared catalogues covers `features/definitions/*` including
  `providers.py` and `features/feature_types.py` — the same code it covered when the definitions
  lived inside the resolver. Editing a feature definition or an analysis op stales a study's
  freeze exactly as before. For any study declaring only ops implemented in `diagnostic_ops.py`
  the seeded analysis set is identical to the previous unconditional seed.
* **Seal, manifest, reuse key, `test_delta` classifier**: untouched.
* **Study lifecycle**: untouched. Compile of `studies/first_p90_warning_horizon_march2024`
  returns a byte-identical 11-gap `CAPABILITY_GAP` card before and after.
* **No plugin framework, DI container or extension system** was added. The two boundaries are
  ~120 and ~140 lines and do one thing: read the index, import by dotted path.

## 6. Escalation — in-flight studies

Two leases are live (`research ws list`): `es_180s_model_c_portability` and
`supv1_shape_a_flip_180s_r2`. Both studies' compiled closures contain `features/registry.py`
**and** `research/analysis/diagnostic_ops.py`:

| study | closure composite |
|---|---|
| `es_180s_model_c_portability` | `6d44da61…` |
| `supv1_shape_a_flip_180s_r2` | `ee051527…` |

Merging this branch stales both freezes the moment their worktrees take main — PREPARE plus
stages 3–6 again, per CLAUDE.md §3. Their historical authority at their own commits is
untouched; nothing already sealed is invalidated in place. This is the ordinary cost of a
CORE_SURFACE platform merge (all 30 prior platform merges had it), but it is the owner's call
whether it lands before or after those two close.

## 7. Findings parked (packet §6: goes in a list and waits)

1. **`test_delta` baseline signature shift.** Baseline entry
   `features/tests/test_feature_system_v2.py::test_explicit_instances_and_collection_universe_share_canonical_status`
   records the message `… DID NOT RAISE <class 'features.registry.FeatureInstanceError'>`. The
   class now lives in `features.feature_types`, so the recorded message no longer matches. Same
   failure, same cause, renamed class path. Left unedited; classified in the gate card below.
2. **`tier_replay.py` (unmerged, `chore/tiered_gates`) needs three path updates** to classify
   this shape: `REGISTRATION_FILES` must point `_add` at `features/definitions/*.py` instead of
   `features/registry.py`, `CAPABILITY_MODULE_RE` should admit `features/definitions/`, and
   `SEED_FILES` must list the two `capabilities_index.d/` files. Done in the local copy used for
   the measurements above; the branch is untouched.
3. **The `analysis_ops` and `feature_definitions` kinds are not `cap scaffold`-able.**
   `capability_flow.KINDS` covers six kinds and neither of these; adding an op or a catalogue is
   still a hand-written index entry. Not a regression — it was already so — but it is the last
   hand edit in the additive path.
4. **`docs/RESEARCH_YAML_REFERENCE.md` is still generated *and* tracked** and conflicts on every
   grammar branch, the same shape B3 fixed for `registry.json`. Carried forward from Session 2.

## 8. Gate

Quick checks, all green in seconds: `cap generate --check` OK (224 capabilities, 0 broken,
`feature_definitions` 3 / `analysis_ops` 9, both `verified`); `scripts/lint_host.py` clear;
diff hygiene — 25 files, all UTF-8, zero mojibake hits.

Targeted, per commit:

| scope | result |
|---|---|
| `features/tests/test_feature_definition_boundary.py` | 17 passed |
| `research/analysis/tests/test_analysis_op_boundary.py` | 15 passed |
| `research/analysis/tests/test_diagnostic_ops.py` | 52 passed |
| `research_workflow/tests/test_declarative_analysis.py` + `test_replay_closure.py` + `test_closure_transitive_imports.py` | 26 passed |
| `research_workflow/tests/test_grammar_v2.py` + `test_docs_v2.py` + `scripts/tests/test_capabilities.py` | 44 passed |
| `features/tests` (whole scope) | 58 passed, 2 failed — both committed baseline entries |

Broad gate (CORE_SURFACE), run alone on the host, detached:

```
python scripts/test_delta.py research_workflow/tests scripts/tests features/tests tests \
       research/analysis/tests --baseline-reference ee16002e --json
```

Result: see §8.1 below.
