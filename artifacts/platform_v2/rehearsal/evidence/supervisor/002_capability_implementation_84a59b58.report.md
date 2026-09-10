# 002_capability_implementation_84a59b58 — CAPABILITY_IMPLEMENTATION — BLOCKED

Branch `chore/rehearsal_checkpoint_norm-missing_capability`, worktree
`C:\Users\Scott McCarty\Projects\Nautilus Trader-rehearsal_checkpoint_norm-missing_capability`,
commit `c94bfb3c` on top of `8bf26857`.

## What the gap actually was

`CAPABILITY_GAP_HANDOFF.json` carries two gaps. The second
(`UNSUPPORTED_COMPOSITION: predicate references unknown context tracker 'features'` on
`population.qualify`) is downstream, exactly as the design worker's card said: the compiler
skips the feature host when a feature instance fails, so the `features.*` predicate namespace
never gets registered. It needs no work and none was done.

The first is genuine: `structural_max_expansion_checkpoint_atr` (`context: current`) had no
canonical identity. The value itself has always existed —
`features/trackers/structural_regime_geometry.py:145` writes it beside
`structural_max_expansion_atr` (identical numerator `direction * (running structural extreme −
structural origin price)`, denominator `checkpoint_atr` instead of the prevailing 1m regime's
`atr_start`), and `StructuralGeometryAdapter._SNAPSHOT_KEYS`
(`research_workflow/provider_host.py:332`) already rendered it. Only the declaration was missing.

## What was implemented and committed

| File | Change |
|---|---|
| `features/definitions/canonical.py` | the canonical definition, same shape as its frozen-ATR sibling (family `structural_regime_geometry`, provider `STRUCTURAL_IMPL`, `parameter_schema ("context",)`, domain `{"context": ("current",)}`) |
| `features/tests/test_structural_max_expansion_checkpoint_atr.py` | new, 8 tests: declaration, fail-closed parameter domain, adapter `can_emit` + required streams, the two normalisations share a numerator and differ only by denominator, the checkpoint denominator is the epoch ATR the host passes (`episode_state.family_a_atr`), unavailable structural state yields `None` |
| `features/tests/golden/feature_resolution.json` | regenerated boundary golden |
| `features/tests/test_feature_definition_boundary.py` | canonical-definition count 41 → 42 |

Every line that moved in the golden is attributable to the one added name:
`CANONICAL_FEATURE_DEFINITIONS_order` (verbatim), its own `CANONICAL_FEATURE_DEFINITIONS` /
`canonical` / `parameterised` digests, `runtime_feature_aliases[legacy]` and
`source_universes['canonical_verified_definition_universe'|legacy|*]` (the explicitly-legacy
authority lists the whole Python catalogue unfiltered — pre-existing behaviour, every other
provisional definition is already in it), and `canonicalize_provider_columns` (its sample is
`sorted(CANONICAL_FEATURE_DEFINITIONS)[:40]`, so a 42nd name shifts the cut).

## Why this is BLOCKED and not DONE

**The definition alone does not unblock the study, and no path from a chore session to the
thing that would is available.**

`research_workflow/grammar/compiler.py:_resolve_features` resolves feature identity through the
**active feature authority bundle**, not through the definition catalogue:

```
bundle = _canonical_bundle("active")                       # features/authority/active.json -> candidate/
definition = _canonical_definition_by_name(bundle, name)   # None -> KeyError -> MISSING_CAPABILITY
res = resolve_feature_instances("canonical_verified_definition_universe", (inst,))
                                                           # status != "verified" -> UNVERIFIED_CANONICAL_FEATURE
```

Verified by direct probe on this commit: a synthetic `study.yaml` declaring both structural
instances still compiles to
`MISSING_CAPABILITY: unknown canonical feature 'structural_max_expansion_checkpoint_atr'`
at `features.instances[1]`, and `research cap search structural_max_expansion` still returns
only `feature.structural_max_expansion_atr` (`cap list features` counts 143 — the bundle, not
the 42 canonical definitions).

The bundle is written **only** by `scripts/materialize_feature_candidate.py`, which marks a
definition `verified` from exactly two sources:

1. `scratch/feature_system_v2_canonical_promotion_inventory.json` — the 693-alias legacy parity
   migration. A genuinely new feature has no legacy alias, so this is closed by construction.
2. a `promotion_decision: PROMOTE` record in `features/feature_scoped_promotions.json`. Those
   records are produced by `scripts/materialize_scoped_promotions.py`, which requires an
   authorizing study's `feature_candidate.yaml` + `audit/frozen_execution_manifest.json` +
   `artifacts/preexec_audit_seal.json`, and `check_feature_promotion.check_scoped_promotions`
   requires `authority_id`, `feature_candidate_composite` and `seal_identity` to be real.

A chore session has no study to seal. The study cannot seal, because it cannot compile. That is
a closed loop, and hand-writing a scoped promotion record with an invented `seal_identity` is
precisely the evidence-laundering that `scripts/check_feature_promotion.py` exists to stop, so
it was not done.

`research cap propose/scaffold/promote` is not the missing route either: it operates on
`research_workflow/capabilities_index.yaml` and `research_workflow/capabilities/registry.json`
(trackers, ops), never on `features/authority/`. Its anti-bloat gate also refuses a proposal
naming fewer than two serving studies.

Running the materializer was **tried and reverted**. It is not idempotent against the committed
bundle: it changes `provider_sha256` on **53 existing definitions** (the committed bundle's
provider hashes are stale relative to HEAD) and adds the unrelated
`trend_normalized_est_delta_acceleration`, which commit `60ff6a8d` deliberately kept out of the
bundle. Definition count would go 143 → 145. That is a repository-wide mutation of the active
feature authority, not a bounded capability edit, and it also stales every seal bound to the
bundle composite. It needs an owner decision, not a worker's judgement.

## The decision the owner has to make

Pick one:

- **(a)** authorize a bounded, additive bundle append for this one definition (append the entry
  + its promotion fact, update `manifest.json` and the `active.json` composite by hand, do not
  re-materialize), and state what evidence stands in for the parity artifact;
- **(b)** build the missing governed path — a `cap promote --feature <canonical_name>` that
  appends one verified definition to the bundle from targeted-test + causal-audit evidence,
  without re-deriving the other 143;
- **(c)** re-materialize the whole bundle and accept the 53 `provider_sha256` updates and the
  extra definition as a separate, reviewed platform change first.

(b) is the one that makes the additive feature-definition path real; (a) unblocks this rehearsal
fastest.

## Write surface deviation (worth recording for the rehearsal)

The packet's claimed write surface —
`features/library.py`, `features/library_mtf.py`, `features/registry.py`,
`features/trackers/host_bindings.py`, `research_workflow/grammar/compiler.py`,
`research_workflow/grammar/predicates.py`, `research_workflow/host/predicate_eval.py`,
`research_workflow/provider_host.py` — comes from `_SUGGESTED_FILES` in
`research_workflow/handoff.py` and is **stale post-registration-boundary** (merged `2194055d`).
A feature-definition addition now lands in `features/definitions/canonical.py`; none of the
eight claimed paths is where it goes, and putting it in `features/registry.py` would break the
registration boundary and its own golden test. Nothing outside `features/definitions/` and
`features/tests/` was touched. The supervisor merge gate will flag the diff as outside the
claimed surface; that flag is correct about the claim and wrong about the code.

## Tests

`python scripts/test_delta.py features/tests` — 68 ran, 66 passed, 2 failed, both
`NEW_FAILURE` with `reason: BASELINE_COMMIT_MISMATCH`:

- `test_candidate_authority.py::test_real_candidate_requires_explicit_resolver_authority_and_active_does_not_use_it`
  — asserts the active bundle holds 129 definitions; it holds 143.
- `test_feature_system_v2.py::test_explicit_instances_and_collection_universe_share_canonical_status`
  — asserts `regime_efficiency` resolves `UNVERIFIED_CANONICAL_FEATURE`; it resolves verified.

Both were **reproduced at HEAD `8bf26857` with all four files reverted**, so neither is caused by
this change. They classify NEW only because `config/test_failure_baseline.json` is pinned at
`ee16002e` while the merge base is `8bf26857`; the run reports
`baseline_issues: ["BASELINE_COMMIT_MISMATCH"]` and no baseline evidence can be consumed. Every
targeted `test_delta` run on this platform commit will do the same until the baseline is
re-recorded — a recurring friction point for the rehearsal.

`python scripts/research.py cap generate --check` — `FAIL: CAPABILITY_REGISTRY_STALE` on first
run, `OK` after one `research cap generate`, which produced **no file change** (committed
`registry.json` already in sync, `content_sha256 128235df…`). The stale local cache is a
pre-existing false negative, not a tree change.
