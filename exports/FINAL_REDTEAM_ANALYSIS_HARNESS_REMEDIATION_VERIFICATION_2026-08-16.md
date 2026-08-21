# FINAL RED TEAM — Analysis Harness Remediation Verification (BOUNDED RE-AUDIT)

**Date:** 2026-08-16 · **Reviewer:** independent Red Team · **Implementation authorship: NONE**
**Target:** `worktree-analysis-harness-a1-a4` @ `.claude/worktrees/analysis-harness-a1-a4` (base `7cc5e0c`, uncommitted)
**Governing audit:** `exports/FINAL_REDTEAM_ANALYSIS_HARNESS_2026-08-16.md`
**Claim under test:** `REMEDIATION_IMPLEMENTATION_COMPLETE`

**Method:** independent code inspection plus **103 executed adversarial probes** across four scratchpad
probe suites, an independent re-run of the full test suite, and read-only execution against the three
real A0 fixtures. Nothing was fixed. No source, collector, backtest, seal, run artifact, audit, or
study output was modified. Probe fixtures were written only to a system temp directory.

---

## A. EXECUTIVE VERDICT

```text
HARNESS_READY_WITH_WARNINGS
```

**All four blocking (H) findings are independently confirmed closed**, each verified by replaying the
original exploit rather than by reading the diff. Of the M-series, **five of six are fully closed**;
**M4 is PARTIAL** — the threshold-population control is derived only when the caller volunteers the
`meta` frame, and a caller who omits it may still assert any population string.

Why `WITH_WARNINGS` rather than `NOT_READY`: the M4 residual is **not a silent acceptance**. The
artifact records `derivation_population_source: "caller_declared"` versus
`"derived_from_meta_partition"`, and that field is inside `threshold_freeze_sha256`, so the two cases
are mechanically distinguishable — a strict improvement on the original defect, which emitted
`derivation_population: ""` with no source field at all. The residual is also unreachable on any
currently shippable path: the only analysis spec in the tree declares no model arms, so it cannot fit
a model or freeze a threshold, and no TRAIN-stage collection exists to freeze one on.

Why not `HARNESS_READY`: §19 requires M4 FIXED, and it is not. The gap is a two-line repair
(require `meta`; refuse a pooled `train+dev` population), not a redesign.

Falsification results against the eleven claims in §21: **claims 1–3 and 5–7 and 9–11 survived
adversarial testing. Claim 4 survived. Claim 8 ("threshold provenance is derived rather than
asserted") was falsified.**

---

## B. BLOCKER SCORECARD

| # | Finding | Verdict | Basis |
|---|---|---|---|
| **H1** | `run_id` path traversal escapes `runs_root` | **FIXED** | 10/10 traversal forms rejected `INVALID_RUN_ID`; legitimate child loads; resolved dir recorded truthfully |
| **H2** | `ValidationReport` not bound to its spec | **FIXED** | Spec-less, cross-spec, unsealed-laundering and DEV paths all refuse; failure surfaces before binding complaint |
| **H3** | Declared join key degrades by intersection | **FIXED** | Key of record no longer read from the observation frame; both frames asserted; one documented residual (below) |
| **H4** | Slice tables silently drop rows | **FIXED** | `unassigned` row + caveat + `Σn == N` reconciliation in the completeness gate |

### H1 — FIXED

`assert_plain_run_id` + resolved-containment in `CollectionPaths.for_run` (`identity.py:137-196`).

| Probe | Input | Result |
|---|---|---|
| A | `../secret_runs/<run>` | `InvalidRunId:INVALID_RUN_ID` |
| B | `..\secret_runs\<run>` | `InvalidRunId:INVALID_RUN_ID` |
| C | `.` | `InvalidRunId:INVALID_RUN_ID` |
| D | `nested/path/<run>` | `InvalidRunId:INVALID_RUN_ID` |
| E | valid direct child | **LOADED** (no false positive) |
| F | `foo/../bar`, `foo\..\bar`, `..`, absolute path, trailing separator, embedded NUL | all rejected |

A real collection was planted outside `runs_root` and is **not reachable by any probed form**.
Identity is truthful: `identity.run_id = '20230101_000000_sx_day'` and
`dataset_identity.json:resolved_run_dir` records the actual absolute source directory, matching
`paths.resolved_run_dir`. The resolved path is deliberately **outside** the hashed identity tuple
(machine-specific), which is correct and documented at the write site (`loader.py:742-746`).

*Not probed:* symlink smuggling — Windows refused symlink creation without elevation
(`WinError 1314`). Containment is asserted on `.resolve()`, which dereferences links, so the code
path is correct by inspection; recorded as untested-by-environment, not as a gap.

### H2 — FIXED

`ValidationReport.spec_supplied` / `.analysis_spec_sha256` / `.authorizes()` (`loader.py:230-267`),
enforced at `loader.py:658`.

| Probe | Sequence | Result |
|---|---|---|
| A | `validate(c)` → extract with TRAIN spec | `ValidationNotRun` |
| B | `validate(c)` → extract with DEV spec | `ValidationNotRun` |
| C | `validate(c, SpecA)` → extract with SpecB | `ValidationNotRun` |
| D | `validate(c, SpecA)` → extract with SpecA | **EXTRACTED n=60, partitions=['train']** |
| E | failed report + matching spec | `SchemaSurplus` — the *validation* failure, not the binding complaint |
| F | unsealed + spec-less report | `ValidationNotRun`; with matching spec → `UnsealedCollection` |
| G | DEV spec, properly validated | `OOSLocked` |

The original two-line exploit now returns **zero DEV rows**. `skipped_checks` is materialised on the
report and echoed into `dataset_identity.json` (`validation_spec_supplied`,
`validation_skipped_checks`), closing L1 as a side effect. Probe E confirms the correct ordering:
`raise_if_failed()` runs *before* `authorizes()`, so a broken collection still reports its own defect.

### H3 — FIXED (one documented, non-silent residual)

`Collection.declared_join_key` (`loader.py:82-125`) now resolves the key of record from, in order:
pinned `expected_join_key` → `study.yaml features.join_key` → the manifest's **recorded** observation
columns → declared metadata ∩ candidates. It is never read from the live observation frame.

| Probe | Result |
|---|---|
| A — drop `regime_direction` from observations, refresh hashes | key stays **4 cols**; `JOIN_KEY_MISSING`, `missing_from_observations=['regime_direction']` |
| B — drop a key column from candidates | `JOIN_KEY_MISSING`, `missing_from_candidates=['regime_direction']` |
| C — both frames complete | PASS, 4-column key |
| D — duplicate observation join keys | `DUPLICATE_KEYS` `{'candidates': 0, 'observations': 1}` |
| E — Fixture A | 4 columns, `src=collection_manifest.columns.observations` |
| F — Fixture B | 3 columns, `join_key_resolved` **PASS** — historical key not falsely rejected |

**Residual (as documented by the implementer, verified by me).** If the manifest's own
`columns.observations` list is *also* rewritten so the collection is internally self-consistent, the
key of record legitimately becomes 3 columns and validation passes. Both stated protections work:

- pinned `collection_identity_sha256` → **`IDENTITY_MISMATCH`** (the manifest is inside the canonical
  identity, so the rewrite moves it);
- pinned `expected_join_key` → **`JOIN_KEY_MISSING`** with `source=analysis_spec.collection.expected_join_key`.

Neither pin is mandatory, and the shipped example spec sets neither — but it names both omissions in
comments and states a real analysis MUST pin them. This is the correct residual to have: shortening
the key now requires forging the producer's own declaration, which is itself detectable. The defect
class the prior audit demonstrated — *a column vanishes from the frame and the key silently shrinks* —
is closed. The regression tests are honest about exactly this boundary
(`test_p3_shortened_join_key_is_blocked_even_when_the_manifest_is_rewritten` asserts the pinned case
only, and `test_p3_rewriting_the_manifest_moves_the_collection_identity` covers the other pin).

### H4 — FIXED

`build_slice_table` emits an explicit `unassigned` row plus a caveat; `StandardTable` carries
`n_input_rows` / `reconciles_rows` / `unassigned_rows`; `check_report_completeness` reconciles.

| Probe | Result |
|---|---|
| A — 100 rows, 30 with `regime_age_seconds = -5` | `n_input=100`, `Σn=100`, rows `[establishing 16, mature 22, old 25, young 7, **unassigned 30**]`, explicit caveat |
| B — NaN slice values | `Σn=100` (`establishing 80`, `unassigned 20`) |
| C — NaT-derived slices | session `Σn=100`; year `Σn=100` (`2023: 85`, `unassigned 15`) |
| D — real Fixture A | all six standard tables reconcile **2002/2002** |
| E — hand-malformed table `n_input=100`, `total=70` | completeness returns *"table by_maturity does not account for every input row: total_sample_count=70 vs n_input_rows=100 (30 unreconciled)"* |

`reconciles_rows=False` on `by_arm` is correct and self-documenting (every arm scores all rows, so
`Σn = n_arms × N` by construction) and the table states this in `row_reconciliation`.

---

## C. REAL-ANALYSIS READINESS SCORECARD

| # | Finding | Verdict | Evidence |
|---|---|---|---|
| **M1** | Platform-dependent collection identity | **FIXED** | LF and CRLF manifests → identical canonical sha; semantic change → different; key-order/indent insensitive; parquet still raw-byte; artifacts LF |
| **M2** | `fit_identity_sha256` binds asserted, not actual, data | **FIXED** | different X, different y, different `n_rows`, changed library version each move the identity; identical experiment reproduces it |
| **M3** | TRAIN/DEV fit guard opt-in | **FIXED** | `meta` missing → `PARTITION_PROVENANCE_MISSING`; no `_partition` → same; mixed → `PARTITION_MIXING`; all-TRAIN fits; no implicit `split_policy=none` |
| **M4** | Threshold population accepted, not derived | **PARTIAL** | see below |
| **M5** | Completeness ignores validation verdict and seal | **FIXED** | `passed=False`, `sealed=False`, missing validation, `spec_supplied=False` all flagged; clean context → `[]` |
| **M6** | Non-finite metrics reported as `ok`/null; AUC crashes | **FIXED** | EV / Brier / MFE / MAE / ROC-AUC all `not_computable` with a reason; full table set builds with an infinite score present |
| **M7** | Cross-study guard unwired and unexported | **FIXED** | in `__all__`; rejects mixed study ids (`CROSS_STUDY_POOLING`); caller obligation in the package docstring |
| **M8** | Fixture B warmup leakage undisclosed | **FIXED** | A0 §1/§9 and the implementation report now record both failures and the in-window population |
| **L2** | Empty feature contract passes vacuously | **FIXED** | absent study dir → `feature_contract_declared`, `feature_order_preserved`, `feature_list_hash_matches` all FAIL `SCHEMA_MISSING` |

### M1 — FIXED (verified from disk, not from docs)

```text
LF manifest   canonical sha 47694865…   raw sha 3a8e…      identical canonical
CRLF manifest canonical sha 47694865…   raw sha 4b40…      ✔
semantic edit (candidates_count +1)  -> different canonical sha        ✔
key-reorder + reindent               -> identical canonical sha        ✔
parquet                               -> sha256_file (raw bytes) unchanged ✔
dataset_identity.json                 -> CR=0, LF only                 ✔
table CSV / table JSON / model_manifest.json -> CR=0                   ✔
```

Fixture A, measured from disk — **all three implementation claims confirmed exactly**:

| | value |
|---|---|
| old raw manifest sha (audit's `f4f8c027…`) | `f4f8c027d0ffb6486c11ecb52941feffd96d213ba39460589da5c2f82ccff1c7` |
| new canonical manifest sha (claim `47694865…`) | `47694865a3ebafaa8f1f426afa41f857418ba345b99b7bd9f8db5f63a5483568` |
| new collection identity (claim `2d87069d…`) | `2d87069dded5bdd723396d5cddd7c1207c183597ec87010133f9d70cd584bbf9` |

### M2 — FIXED

`FitProvenance.fit_identity_sha256` now hashes `n_rows`, `x_content_sha256`, `y_content_sha256`,
`library_versions` and `partition_provenance` alongside the asserted identities. The original
reproduction (`n=200` vs `n=80`, different distributions, same declared identity → same hash) no
longer holds:

| Probe | Result |
|---|---|
| same metadata/config, different X | different identity ✔ |
| same X, different y | different identity ✔ |
| same X/y content, different `n_rows` | different identity ✔ |
| recorded sklearn version mutated to `999.0` | different identity ✔ |
| same everything | **identical** identity (deterministic) ✔ |

`frame_content_identity` hashes per column, so it is sensitive to values, column names **and column
order** while being insensitive to dtype backend — a good choice. Note `dataset_identity_sha256`
remains a caller assertion, but it is no longer the *only* binding.

### M3 — FIXED

`fit_model` refuses when partition provenance is absent, and the old self-exculpating
`split_policy={'kind':'none', …,'description':'no partition metadata supplied'}` is gone. The
explicit `SplitPolicy` opt-out is accepted but recorded as `partition_provenance="explicit_opt_out"`,
so the omission is on the artifact rather than inferable only by absence.

### M4 — **PARTIAL** (the one gap)

Closed: empty/whitespace population blocked; population derived from `meta["_partition"]` when `meta`
is supplied; a DEV population labelled `"train"` **with meta present** raises `InvalidAnalysisSpec`;
meta of the wrong length rejected; `derivation_population_source` recorded and inside the freeze hash.

Two required probes did not behave as specified:

**M4-C — mixed TRAIN+DEV is accepted, not blocked.**

```text
freeze_threshold(scores, y, meta=DataFrame({'_partition': ['train']*50 + ['dev']*50}))
  -> OK   derivation_population = 'dev+train'
          derivation_population_source = 'derived_from_meta_partition'

fit_model(X, y, arm='A', meta=<same mixed meta>)
  -> PartitionMixing  (BLOCKED)
```

The label is honest, but the two modelling entry points now disagree about the same contamination:
a fit spanning TRAIN and DEV is refused, while a **threshold** frozen on the pooled population is
accepted. A threshold is a fitted parameter; this asymmetry has no stated justification.

**M4-RESIDUAL — the derivation is optional, so the original exploit survives with `meta` omitted.**

```text
freeze_threshold(dev_scores, y, population='train')     # meta not supplied
  -> OK   derivation_population        = 'train'
          derivation_population_source = 'caller_declared'
          derivation_n                 = 100
          threshold_freeze_sha256      = 531fbb7e45fee4d1…
```

These are DEV rows labelled TRAIN, and the harness has no way to know. The remediation claim
"population derived from `meta['_partition']`" holds only when the caller volunteers `meta`; nothing
requires it. This is the same defect shape M3 just closed on the fit path — absence of provenance is
not evidence of a clean population — left open on the threshold path.

**Mitigating, and why this is a warning rather than a blocker:** the artifact distinguishes the two
cases (`caller_declared` vs `derived_from_meta_partition`), and that field is hashed into
`threshold_freeze_sha256`, so a reviewer or a downstream gate can mechanically refuse a
`caller_declared` freeze. That is materially better than the original `derivation_population: ""`.
The new regression tests pin the current behaviour honestly but **do not cover the `caller_declared`
gap** — `test_p8_declared_population_still_works_when_it_agrees` only exercises the case where `meta`
is present and agrees.

**Smallest repair:** make `meta` required in `freeze_threshold` (mirroring `fit_model`'s
`PartitionProvenanceMissing`), and refuse a derived population containing more than one partition.

### M5 / M6 / M7 / M8 / L2 — FIXED

M5 flags `validation.passed is not True`, `sealed is False` without recorded authorisation, missing
validation, and `spec_supplied is False`; a clean sealed context returns `[]`. Confirmed end-to-end,
not only on hand-built dicts: a real unsealed synthetic collection produces
`["validation did not pass (passed=False; failed checks: ['seal_policy'])", "collection is unsealed and no allow_unsealed_collection authorisation is recorded"]`.

M6: the downgrade happens in `MetricResult.__post_init__`, so `.computable` is honest everywhere
rather than only in `to_dict()` — a better fix than the one recommended. `_auc_like` guards
non-finite inputs *before* calling sklearn and also catches `ValueError`. A table set built with one
infinite score produced all seven tables with explicit `roc_auc_status` / `roc_auc_reason`.

M8: A0 §1 now records `0.1621 (177/1092) in-window` and tags the pooled `0.1793` **"contaminated, do
not quote"**; §9 row 11b records `F:WARMUP_LEAKAGE (2,020 of 3,112)`. The implementation report §4
and §6 record both failures. Independently reproduced from disk: `n=1092`, base rate `0.1621`.

---

## D. ATTACK MATRIX

| Attack | Verdict | Note |
|---|---|---|
| path traversal | **BLOCKED** | 10/10 forms; resolved-parent containment |
| spec-less validation reuse | **BLOCKED** | `ValidationNotRun` |
| cross-spec report reuse | **BLOCKED** | `ValidationNotRun` |
| 4→3 join degradation | **BLOCKED** | frame-level shortening refused; forged-manifest variant needs an unpinned spec and is detectable by either pin |
| slice row loss | **BLOCKED** | explicit `unassigned` row + caveat + `Σn == N` gate |
| CRLF/LF identity drift | **BLOCKED** | canonical-JSON manifest identity |
| different X same fit identity | **BLOCKED** | `x_content_sha256` |
| different y same fit identity | **BLOCKED** | `y_content_sha256` |
| missing partition provenance | **BLOCKED** | `PARTITION_PROVENANCE_MISSING` |
| mixed TRAIN/DEV fit | **BLOCKED** | `PARTITION_MIXING` |
| wrong threshold population | **BYPASSED** | `meta` omitted → any caller-asserted label accepted (`caller_declared`); pooled `train+dev` accepted with `meta` |
| failed validation marked complete | **BLOCKED** | reads `validation.passed` |
| unsealed analysis marked complete | **BLOCKED** | unless `allow_unsealed_collection` recorded |
| inf metric | **BLOCKED** | `not_computable` + reason |
| inf AUC | **BLOCKED** | refused before sklearn; `ValueError` also caught |
| cross-study pooling | **BLOCKED** | exported + rejects; no multi-collection entrypoint exists to auto-wire (correctly not invented) |
| empty feature contract | **BLOCKED** | `SCHEMA_MISSING` ×3 |

---

## E. REAL FIXTURE RESULTS

### Fixture A — `20260815_213139_Gemini_clean_maturity_flip_rolling_5m_productivity_day`

| Assertion | Expected | Measured |
|---|---|---|
| rows | 2002 | **2002** ✔ |
| base rate | 0.3492 | **0.3492** ✔ |
| join key | 4 columns | `[observation_ts, regime_start_ns, regime_direction, checkpoint_index]` ✔ |
| features in X | 60 | **60** ✔ |
| outcome columns in X | none | **[]** ✔ |
| candidates / observations shape | (2002,73) / (2002,7) | ✔ / ✔ |
| metadata source | declared | **declared** ✔ |
| partition counts | train 2002 | `{'train': 2002}` ✔ |
| six standard tables | all reconcile 2002/2002 | all six ✔ |
| completeness | `[]` | **`[]`** ✔ |
| score metrics with no scores | omitted | row keys `['group','n','positive_rate','sample_count']` ✔ |
| duplicate-key guard | functional | detects injected duplicate ✔ |

Run end-to-end against the shipped `analyses/fixture_a_structural_smoke.yaml`; validation passed with
zero failures. **Fixture A reproduces exactly, with no research statistic changed.**

### Fixture B — `20260814_232113_reconstructed_long_rth_strict_retrain_day`

| Assertion | Expected | Measured |
|---|---|---|
| 4a study dir self-consistent | FAIL | `False / STALE_COMPILED_STUDY` ✔ |
| 4b collection vs compiled contract | PASS | `True` ✔ |
| join key | historical 3-column allowed | `[observation_ts, regime_start_ns, checkpoint_index]`, `join_key_resolved=True` ✔ |
| warmup leakage | honestly reported | `False`, `rows_outside_window=2020`, window `['2025-03-03','2025-03-03']` ✔ |
| sealed | False | `False` ✔ |
| in-window population | 1,092 @ 0.1621 | **1092 @ 0.1621** ✔ |
| overall | still a negative fixture | `passed=False`, failures `['study_dir_self_consistent','no_warmup_leakage','seal_policy']` ✔ |

**Fixture B was not converted into a positive fixture.** Its data was not modified.

---

## F. TEST RESULTS

```text
$ python -m pytest scripts/tests/test_analysis_loader.py \
                   scripts/tests/test_analysis_spec_slices_metrics.py \
                   scripts/tests/test_analysis_modeling.py \
                   scripts/tests/test_analysis_reporting.py \
                   scripts/tests/test_analysis_reproducibility.py \
                   scripts/tests/test_analysis_redteam_regressions.py -q

174 passed, 3 warnings in 14.57s
```

| | collected | passed | failed | skipped |
|---|---:|---:|---:|---:|
| total | **174** | **174** | **0** | **0** |

| Suite | Tests |
|---|---:|
| `test_analysis_loader.py` | 41 |
| `test_analysis_spec_slices_metrics.py` | 39 |
| `test_analysis_modeling.py` | 19 |
| `test_analysis_reporting.py` | 15 |
| `test_analysis_reproducibility.py` | 6 |
| `test_analysis_redteam_regressions.py` | **54** (new) |

The claimed `174 = 120 + 54` split reconciles exactly. The 3 warnings are numpy `RuntimeWarning`s
raised *inside* the deliberately-infinite M6 fixtures — expected, not defects.

**Do the new tests reproduce the exploits, or only happy paths?** Reproduce them. Every P-series test
is written as the original attack and asserts a refusal, with the finding restated in the docstring
(e.g. *"P3: dropping regime_direction from a 4-key collection shortened the key to 3 and validation
passed with zero failures"*). Coverage of the named probes:

| Probe | Covered | Tests |
|---|---|---|
| P1c | ✔ | 11 (8 parametrised traversal forms + outside-root + no-false-positive + resolved-dir recorded) |
| P2 / P2b | ✔ | 4 |
| P3 | ✔ | 5 — including both residual protections and the "not read from the observation frame" invariant |
| P4 | ✔ | 4 |
| P5a / P5b / P5c | ✔ | 5 |
| P6 | ✔ | 5 |
| P7 | ✔ | 4 |
| P8 | ✔ | 5 — but **none covers the `caller_declared` gap** (see M4) |
| P9 | ✔ | 4 |
| P11 | ✔ | 3 |
| P12 (L2) | ✔ | `test_l2_absent_feature_contract_fails_schema_missing` |
| P14 | ✔ (indirectly) | no dedicated `test_p14_*`; duplicate-key behaviour is covered by the pre-existing loader suite and re-verified by my probe H3-D (`{'candidates': 0, 'observations': 1}` → `DUPLICATE_KEYS`) |

Three tests are notably stronger than the finding required: `test_p3_rewriting_the_manifest_moves_the_collection_identity`,
`test_p7_meta_that_does_not_describe_these_rows_is_rejected`, and
`test_p5a_non_finite_values_in_extras_are_caught_too`.

---

## G. IDENTITY MIGRATION

| | |
|---|---|
| old Fixture A `collection_manifest` sha (raw bytes, Windows/CRLF) | `f4f8c027d0ffb6486c11ecb52941feffd96d213ba39460589da5c2f82ccff1c7` |
| new Fixture A `collection_manifest_sha256` (parsed canonical JSON) | `47694865a3ebafaa8f1f426afa41f857418ba345b99b7bd9f8db5f63a5483568` |
| new Fixture A `collection_identity_sha256` | `2d87069dded5bdd723396d5cddd7c1207c183597ec87010133f9d70cd584bbf9` |
| reason | M1 — manifest identity moved from a raw byte hash of a git-tracked, CRLF-normalized text file to a hash of its parsed canonical form |
| **collection data bytes unchanged?** | **YES** |

Verified rather than assumed:

- `candidates.parquet` = `1ab64a105a9c7e0a5a92552ad9217cf90ecc654e1f990f1c7a7c4d0f523c4375`
  and `observations.parquet` = `f300195044a0199e3fda0a449941baaccde70b7c73695027963a082520b1979d` —
  both **identical to the values the prior audit recorded**, and both still match what the manifest
  itself records (recomputed and compared).
- Fixture A's research statistics are unchanged: 2002 rows, base rate 0.3492, 4-column key, 60
  features, all six tables reconciling 2002/2002.
- A stale identity pin correctly fails `IDENTITY_MISMATCH`; a newly captured canonical pin passes.
- The change is attributable **entirely** to the hashing convention — parquet hashing is untouched
  (`sha256_file`), and only `identity.py:225` switched to `sha256_json_file`.

**This is the expected migration, not a regression.** It is correctly documented in A0 §2 rule 5,
which now states the per-artifact-class hashing policy explicitly and records the raw sha alongside as
*"not an identity input"*.

---

## H. NEW FINDINGS

Only genuine defects, all outside the four blocking categories.

### N1 — `check_report_completeness` is not bound to the packet it is checking (MEDIUM)

`check_report_completeness(context, tables)` reconciles the `StandardTable` **objects handed to it**
and never reads `context["tables"]`, which carries the packet's own recorded `total_sample_count` per
table. Two demonstrated consequences:

```text
ctx built from 6 tables over 120 rows
check_report_completeness(ctx, {})        -> []      # an analysis with NO tables is "complete"
check_report_completeness(ctx, tables_30) -> []      # ctx says total_sample_count=120,
                                                     # supplied tables total 30; unreported
```

This is the same defect class as M5 and H4 — a gate whose scope is supplied by the caller cannot
detect scope loss — and it sits directly on top of the H4 repair: the row reconciliation is defeated
if the table set given to the checker is not the one the packet describes. It does not require a
redesign, and it is not reachable by the intended call sequence (which passes the same dict to both
functions), so it does not block. **Smallest repair:** reconcile `context["tables"][name]["total_sample_count"]`
against the supplied tables, flag names present in one and not the other, and flag an empty table set.

### N2 — implementation report is stale with respect to its own remediation (LOW, documentation)

`ANALYSIS_HARNESS_IMPLEMENTATION_REPORT.md` (mtime 22:55, i.e. touched during remediation) received
the M8 correction but not the rest: §1 still lists the untracked change surface **without**
`scripts/tests/test_analysis_redteam_regressions.py`, and §4 still reports *"120 passed in 4.83s"*.
The document a reviewer is pointed at understates the delivered work by 54 tests and describes none of
the H1–H4 repairs. Documentation only; no code impact.

### N3 — L6 confirmed still open, and it now produces a misleading row (LOW, previously deferred)

Recorded because it interacts with the M6 repair rather than as a new scope expansion. `build_arm_table`
with arms of unequal score length emits, for an arm scored on 10 of 60 rows, `n=60` with
`roc_auc_status='not_computable'`, **while the unconditional caveat still asserts** *"All arms are
scored on the identical evaluation rows"*. The metric refusal makes this non-silent, so it does not
meet the §18 bar for blocking. Deferred as before.

### Not findings — tested and cleared

- **A short `expected_join_key` pin.** An analyst can pin a 1- or 2-column key on Fixture A and
  validation passes. I traced this to a *correct* outcome rather than a defect: `join_key_unique`,
  `join_no_row_loss` and the `validate="one_to_one"` merge in extraction together force any accepted
  key to induce a bijection, and a bijection on a coarser key that loses no rows necessarily coincides
  with the finer key's pairing. Verified on real Fixture A — 4-, 3-, 2- and 1-column pins all extract
  **the identical 2002 rows at 0.3492**. A non-unique short key is blocked by `DUPLICATE_KEYS`.
- **`score_and_record` takes no partition guard.** Evaluation, not fitting; A0 does not require it,
  and the fit-side guard is what M3 covers. Recorded as INFO only.

---

## I. CHANGE BOUNDARY

Recorded per §1, and it is **not** what the claim describes.

| | |
|---|---|
| worktree | `.claude/worktrees/analysis-harness-a1-a4` |
| branch | `worktree-analysis-harness-a1-a4` @ `7cc5e0c` |
| tracked modifications in the worktree | **zero** — `git status --porcelain` shows only `??` entries |

**Added (untracked, all additive):** `research/analysis/{__init__,errors,identity,loader,spec,slices,metrics,modeling,reporting}.py`,
`analyses/fixture_a_structural_smoke.yaml`, `scripts/tests/analysis_fixtures.py`,
`scripts/tests/test_analysis_{loader,spec_slices_metrics,modeling,reporting,reproducibility,redteam_regressions}.py`,
`ANALYSIS_HARNESS_IMPLEMENTATION_REPORT.md`.

Consistent with the claim: `errors.py`, `identity.py`, `loader.py`, `spec.py`, `metrics.py`,
`modeling.py`, `reporting.py`, `__init__.py` were all modified (mtimes 22:44–22:49);
`slices.py` was not (13:32) — correctly, since no finding touched it.
`test_analysis_redteam_regressions.py` is new (22:52); `test_analysis_loader.py` was adjusted (22:49),
matching "limited adjustment to existing loader test".

**No unrelated collector, backtest, seal, or governance code changed in this worktree.** Verified two
ways: zero tracked modifications, and `research/analysis/*` imports nothing outside the standard
library, numpy/pandas, and itself (with `yaml`, `sklearn`, `lightgbm` and `research.schemas.study_spec`
imported lazily inside functions). It cannot perturb the collector's sealed closure.

**Two boundary discrepancies worth recording:**

1. **`ANALYSIS_HARNESS_A0_CONTRACT.md` does not exist in this worktree at all.** The claimed doc
   change landed in the **main working tree on a different branch**
   (`study/Codex_clean_maturity_flip_rolling_5m_productivity` @ `b8f86f1`, +100/−11). I verified its
   content there and it is correct and complete — M1's per-artifact-class hashing rule, H1's
   containment rule, H3's declared-key language, and M8's Fixture B warning are all present. But
   **prior finding L10 is now worse, not merely unfixed**: the contract describing the remediation
   lives on a different branch from the code implementing it, so neither tree can be audited
   self-containedly. This is a process issue, not a correctness one.
2. The main working tree carries substantial unrelated modifications (`backtests/nt_runtime/modes/backtest.py`,
   `scripts/capture_baseline_fixtures.py`, `scripts/run_preexec_audits.py`, `.codex/agents/*`, seal-adjacent
   test files, `BACKTEST_HARNESS_REMEDIATION_REPORT.md`). These are attributable to the **separate
   backtest-harness remediation workstream**, not to this one, and none of them is imported or
   exercised by `research/analysis/`. Flagged for the record; not charged against this change.

---

## J. FINAL STATUS

```text
HARNESS_READY_WITH_WARNINGS
```

**Conditions carried forward, in priority order:**

1. **M4** — make `meta` mandatory in `freeze_threshold` and refuse a pooled `train+dev` derivation
   population. Until then, treat any threshold record whose
   `derivation_population_source == "caller_declared"` as unverified provenance. Two lines.
2. **N1** — bind `check_report_completeness` to `context["tables"]`; flag an empty table set.
3. **N2** — refresh the implementation report's §1 file list and §4 test count.
4. **L10** — land the A0 contract on the implementation branch before this work is committed.

Unchanged and still governing: the harness remains **infrastructure-validated only**. The
implementation report's prerequisites #1 (collector reseal) and #2 (a real TRAIN-stage collection)
are not satisfied, and the shipped spec declares no model arms, so no run of this harness on real data
may be presented as a research result. The M4 residual is unreachable until a threshold is actually
frozen, which those prerequisites gate.

Deferred and explicitly **not** re-opened, per §18: L1 (now closed as a side effect of H2), L3, L4,
L5, L6 (see N3), L7, L9, L10 (see §I), and `.gitattributes`.

---

*No findings were fixed. No implementation file, seal, run artifact, audit, or study output was
modified. Probe fixtures were written only to a system temp directory and the session scratchpad.*
