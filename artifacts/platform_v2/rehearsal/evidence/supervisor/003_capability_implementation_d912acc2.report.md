# 003_capability_implementation_d912acc2 — CAPABILITY_IMPLEMENTATION — DONE

Branch `chore/rehearsal_checkpoint_norm-missing_capability`, worktree
`C:\Users\Scott McCarty\Projects\Nautilus Trader-rehearsal_checkpoint_norm-missing_capability`,
commit **`037e0645`** on top of `c94bfb3c` on top of `8bf26857`.

## Headline

**The capability is implemented and the study's spec now compiles — with no feature-authority
change of any kind.** 002 was right that there is no additive path into the active bundle. It
was not needed: the missing quantity is not a new feature, it is a **normaliser parameter** of
a feature the active bundle already carries as `verified`.

`structural_max_expansion_atr` and `structural_max_expansion_checkpoint_atr` are the *same
numerator* — `direction * (running structural extreme − structural origin price)` — under two
ATR denominators, written side by side in one `StructuralRegimeGeometryTracker.snapshot` call.
Declaring the second as a canonical NAME (002, `c94bfb3c`) is the exact pattern `AGENTS.md` §5
and `CLAUDE.md` §5 prohibit ("`prior_5m_regime_efficiency` is an output alias; the identity is
`regime_efficiency` with `timeframe: 5m`"), and it is also the only version of the change that
needs a bundle mutation. `c94bfb3c` is reverted in `037e0645`.

## What was implemented (commit `037e0645`)

| File | In claimed surface? | Change |
|---|---|---|
| `features/definitions/canonical.py` | no | `normalizer` parameter on `structural_max_expansion_atr`, domain `("regime_start_atr", "checkpoint_atr")`, **optional** — omitting it is the historical frozen-ATR reading, so no already-declared instance moves. Offered only on names whose provider snapshot actually emits a `_checkpoint_atr` column (`_CHECKPOINT_NORMALIZED`); `structural_giveback_atr` still rejects it. Reverts the `c94bfb3c` canonical name. |
| `features/registry.py` | **yes** | `generate_physical_alias` renders a non-default normaliser into the column name (`…_atr` → `…_checkpoint_atr`). Derived from the instance alone — no definition catalogue is consulted, so the registration boundary holds. Without it the two readings collapse into `DUPLICATE_PHYSICAL_ALIAS`. |
| `features/tests/test_structural_expansion_normalizer_parameter.py` | no | 17 targeted tests (replaces `c94bfb3c`'s file). |
| `features/tests/golden/feature_resolution.json` | no | regenerated. |

`research_workflow/provider_host.py` needed **no change**: `StructuralGeometryAdapter` selects
snapshot keys by `physical_alias`, and `structural_max_expansion_checkpoint_atr` has always been
in `_SNAPSHOT_KEYS`.

## Evidence, on `037e0645`

- **Compile probe.** The study's own `study.yaml`, byte-for-byte, with instance[4] re-declared as
  `{feature: structural_max_expansion_atr, context: current, normalizer: checkpoint_atr}`:
  `STATUS: COMPILED`, `features: 5`, `trackers: [regime_1m, excursion, regime_bar_5m, features]`,
  `plan_sha256 d36872837f0f…`. The compiled plan carries all five aliases, and both structural
  instances resolve `status: verified` through `_canonical_bundle("active")`.
- **Gap 2 is a pure cascade,** as 001 and 002 both said. `features.structural_snapshot_ready` is a
  long-standing predicate served by `features/trackers/host_bindings.py:580` and used by five
  committed studies; the compiler's `_resolve_features` returns at `if not ok:` before the feature
  host is bound, so the `features.*` namespace never registers. It clears with gap 1. No work done.
- **Binding proof.** `ProviderHost.verify_bindings` → `passed: True`, both aliases bound to
  `StructuralGeometryAdapter`.
- **Golden.** Exactly **3 lines** move against merge base `8bf26857`: the composite and the two
  `structural_max_expansion_atr` digests (`CANONICAL_FEATURE_DEFINITIONS` and `parameterised`). No
  other name moves. (`c94bfb3c` moved 14, including two universe listings and the 40-name
  `canonicalize_provider_columns` sample — the cost of a new name versus a new parameter.)
- **Fail-closed.** `normalizer: epoch_atr` → `UNSUPPORTED_FEATURE_PARAMETER_VALUE`;
  `structural_giveback_atr` + `normalizer` → `UNKNOWN_FEATURE_PARAMETER`;
  `structural_max_expansion_checkpoint_atr` is asserted **absent** from
  `CANONICAL_FEATURE_DEFINITIONS` as a regression guard.

## THE ONE THING THE STUDY MUST DO

`studies/rehearsal_checkpoint_norm/study.yaml` line 26 must change from

```yaml
    - {feature: structural_max_expansion_checkpoint_atr, context: current}
```

to

```yaml
    - {feature: structural_max_expansion_atr, context: current, normalizer: checkpoint_atr}
```

The old spelling is not a canonical name and never was. The output column is unchanged —
`structural_max_expansion_checkpoint_atr` — so nothing downstream of the collector moves. This
session may not touch `studies/`, so the relaunched design worker owns this one line.

## Findings for the rehearsal report (recorded, not fixed)

1. **The additive feature-DEFINITION path does not exist — 002's headline stands.** Independently
   re-confirmed. `compiler.py:491` binds identity through `_canonical_bundle("active")`; the only
   writer is `scripts/materialize_feature_candidate.py` (whole-catalogue, non-idempotent: 53
   `provider_sha256` drifts + one unrelated definition, 143 → 145). This change *routes around*
   that for this feature; it does not repair it. A genuinely new quantity would still be blocked.
2. **NEW — the per-definition promotion path is wired to nothing and is universally stale.**
   `features/registry.py:152 canonical_definition_status` grants `verified` from an
   evidence-backed record in `features/feature_definition_promotions.json` (audit artifact must
   exist, `reviewed_implementation_sha256` must match the provider file, parameter schema must
   match). It is consulted **only** by the archived-legacy `verified_registry_numeric_universe`
   branch — never by the active universe the compiler uses. And all **26** records are stale:
   every one pins `reviewed_implementation_sha256` at a value the provider file no longer has
   (e.g. `structural_max_expansion_atr` pins `36e97edd…`, the file is `e15b7b81…` — which is what
   the *bundle* records). `canonical_definition_status` therefore returns `provisional` for all 41
   canonical definitions, including ones the bundle calls verified. So 002's route (b) cannot be
   built by reviving these records without re-reviewing 26 implementations.
3. **NEW — `scripts/feature_ctl.py promote` never writes a promotion record** (its own docstring
   says so), yet all 26 records claim `"promoted_by": "feature_ctl promote"`. The writer named in
   the evidence no longer exists.
4. **NEW — `features/feature_scoped_promotions.json` is committed with TEST-fixture records**
   (`authority_id: test_idempotency_96978f9e_auth_v1`). Those records are what mark
   `regime_efficiency` verified in the active bundle, and therefore the root cause of the
   recurring `test_feature_system_v2::test_explicit_instances_and_collection_universe_share_canonical_status`
   failure. Governance data written by a test run.
5. **NEW — the loop 002 called closed is not quite closed, but is closed to *this* session.** A
   feature-candidate authority is a directory with `feature_candidate.yaml` and **no**
   `study.yaml` (`preflight.py:226`, `seal.py:114`, `causal_audit.py:125`), so it seals without
   compiling a research spec. That is the designed introduction path. It requires writing under
   `studies/` — which this packet forbids — and still ends at the non-idempotent whole-bundle
   re-materialization. There is no CLI for it: `research cap promote` is the tracker/op registry.
6. **`cap describe` does not advertise the new parameter.** `feature.structural_max_expansion_atr`
   still reports `"parameters": ["context"]`, because the capability card reads the bundle's
   `parameter_schema`, not the definition's. `required_tests` *did* pick up the renamed test file.
   A parameter added to an existing definition is invisible to `cap search`/`cap describe` — the
   design worker cannot discover `normalizer` from the capability registry.
7. **FR3 confirmed again, half-scale.** Claimed write surface: 8 files from `_SUGGESTED_FILES` in
   `research_workflow/handoff.py`. One of them (`features/registry.py`) is genuinely where half
   this change belongs; the other half is `features/definitions/canonical.py`, still not in the
   list. The merge gate will flag the diff.
8. **FR5 recurs.** `test_delta features/tests`: 77 ran, 75 passed, **2 NEW_FAILURE**, both
   `BASELINE_COMMIT_MISMATCH` (baseline pinned `ee16002e`, merge base `8bf26857`), both identical
   to the two 002 reproduced on clean HEAD. Neither is caused by this change — it does not alter
   bundle contents.
9. **FR6 recurs.** `cap generate --check` → `FAIL CAPABILITY_REGISTRY_STALE` on first run in a
   fresh worktree; `OK` after one `cap generate`, which produced **no tree change**.
10. **FR7 recurs, and cost a full worker.** Attempt 1 (002) ended `BLOCKED` with
    `next_state: OWNER_DECISION_REQUIRED`; the supervisor relaunched the identical packet rather
    than raising a decision card. That relaunch is what found the correct modelling — so the retry
    paid for itself here — but it was luck, not routing.

## Tests

- `python scripts/test_delta.py features/tests` — 77 ran, 75 passed, 2 `NEW_FAILURE`
  (`test_candidate_authority::test_real_candidate_requires_explicit_resolver_authority_and_active_does_not_use_it`,
  `test_feature_system_v2::test_explicit_instances_and_collection_universe_share_canonical_status`),
  both `reason: BASELINE_COMMIT_MISMATCH`, both pre-existing at `8bf26857`.
- `python -m pytest research_workflow/tests/{test_grammar_v2,test_provider_host,test_provider_host_audit,test_multi_window_features,test_ohlcv_window_features}.py` — **73 passed**.
- `python -m pytest features/tests/test_structural_expansion_normalizer_parameter.py` — 17 passed.
- `python scripts/research.py cap generate --check` — `OK` (after one `cap generate`, no tree change).

The broad `test_delta` scope was **not** run: it takes >2.5 h and `WORKFLOW.md` §N.3 puts the one
broad run before the merge, not before every commit.
