# Analysis Harness — Phase A0 Contract & Fixtures

**Status:** A0 complete — contract defined, fixtures selected, blockers identified. **A1 not started.**
**Date:** 2026-08-16 · **Base commit:** `7cc5e0c`
**Scope:** contract definition only. No loader, no slices, no metrics, no model fitting. No collector,
harness, or seal code was modified.

Every identity, hash, count and schema in this document was read from artifacts on disk, not assumed.

---

## 1. Fixtures

Two collections, chosen to be **structurally different in the ways that break loaders** — different
feature-set size, different join key, different chronology, different target base rate, different
declared metadata, and different seal status.

### Fixture A — hardened maturity/flip collection

```
run_id  : 20260815_213139_Gemini_clean_maturity_flip_rolling_5m_productivity_day
path    : runs/20260815_213139_Gemini_clean_maturity_flip_rolling_5m_productivity_day/
study_id: Gemini_clean_maturity_flip_rolling_5m_productivity
```

| Property | Value |
|---|---|
| `spec_sha256` | `2ce0817ac7df4c9ad5e16fd83f77fc5b865e9229eaa8265c9c6d134bac18b0a5` |
| `composite_seal_hash` | `f01abb545ab4c76fe633b21588cdd606382d5cd2362494401e834211d04f4e30` |
| `candidates_sha256` | `1ab64a105a9c7e0a5a92552ad9217cf90ecc654e1f990f1c7a7c4d0f523c4375` |
| `observations_sha256` | `f300195044a0199e3fda0a449941baaccde70b7c73695027963a082520b1979d` |
| `collection_manifest_sha256` (identity input, **canonical JSON**) | `47694865a3ebafaa8f1f426afa41f857418ba345b99b7bd9f8db5f63a5483568` |
| `collection_manifest` raw file sha256 (Windows/CRLF checkout — **not** an identity input) | `f4f8c027d0ffb6486c11ecb52941feffd96d213ba39460589da5c2f82ccff1c7` |
| shape | candidates `(2002, 73)` · observations `(2002, 7)` |
| features | 60, ordered, `feature_list_sha256 = 2a744cfa3acfa437ae0ff8219c56451e176a170ae83450c52b8ca42842b0cba5` |
| metadata columns | 13, **declared** in `study.yaml` |
| join key | `observation_ts, regime_start_ns, regime_direction, checkpoint_index` (4 cols) |
| target base rate | **0.3492** (699/2002) |
| `regime_direction` values | `[-1, +1]` — both directions present |
| chronology | train `[2021,2022,2023]` · dev `[2024]` · prohibited `[2025,2026]` |
| stage / window | `day` · 2023-03-03 (a TRAIN year) |
| observation policy | `required_source_relation: equal` |

This is the collection whose population moved 2032 → 2002 when the late-checkpoint causal defect was
repaired; 2002 is the post-fix count.

### Fixture B — structurally different collection

```
run_id  : 20260814_232113_reconstructed_long_rth_strict_retrain_day
path    : runs/20260814_232113_reconstructed_long_rth_strict_retrain_day/
study_id: reconstructed_long_rth_strict_retrain
```

| Property | Value |
|---|---|
| `spec_sha256` | `bd51e8c29eb7d0fa300c6bb638034541851e1c4db0c0552603714aa2bf4ecaa2` |
| `composite_seal_hash` | **`None`** — this collection is *not* sealed |
| `candidates_sha256` | `192c0f21d04127012bb6f7c51692df6c92a9efb539b3603f7a7960f5a4efd71e` |
| `observations_sha256` | `1ebe6720ff9f710ee90d4cf0acafa89acaaf36745b90fb346eda4761e656d2e4` |
| `collection_manifest_sha256` (identity input, **canonical JSON**) | `650f5e88a9e7073ebf9c65e12a0a65bb72080e2ab6e1823fe367f508455da554` |
| `collection_manifest` raw file sha256 (Windows/CRLF checkout — **not** an identity input) | `88160dc66088bcbdb7cba2f2f4fc7dccf96b6359e6c7419c51d9b8b619de4821` |
| shape | candidates `(3112, 37)` · observations `(3112, 6)` |
| features | 25, ordered, `feature_list_sha256 = 8bcfeb74ab3b5453635ad9895fa9d15fd65866044f23fa0415bfc796e5fd6299` |
| metadata columns | 12, **NOT declared** — falls back to the `OutputManager` default list |
| join key | `observation_ts, regime_start_ns, checkpoint_index` (3 cols — **no `regime_direction`**) |
| target base rate | **0.1621** (177/1092) **in-window**; see the warmup note below |
| pooled base rate (all 3112 rows) | 0.1793 (558/3112) — **contaminated**, do not quote |
| `regime_direction` values | `[-1]` only — constant, therefore not a usable slice |
| chronology | train `[2021,2022,2023,2024]` · dev `[2025]` · prohibited `[2026]` |
| stage / window | `day` · 2025-03-03 (a DEV year **for this study**, prohibited for Fixture A) |

> [!WARNING]
> **Fixture B emits 65% of its candidates during its own declared warmup window.**
> This is a second, independent failure alongside the `STALE_COMPILED_STUDY` case below, found by
> check 14 (`no_warmup_leakage`) — the check working as contracted on a real artifact. Measured:
>
> | | value |
> |---|---|
> | declared run window | `start=2025-03-03`, `end=2025-03-03`, `warmup_start=2025-02-26T00:00:00+00:00` |
> | `observation_ts` range | 2025-02-26 14:30 UTC .. 2025-03-03 20:45 UTC |
> | rows by UTC date | 02-26: 518 · 02-27: 1122 · 02-28: 380 · **03-03: 1092** |
> | `validate_collection(FixtureB)` | `FAIL no_warmup_leakage` — `rows_outside_window = 2020` of 3112 |
> | base rate, in-window only (2025-03-03) | **0.1621**, n = **1,092** |
> | base rate, warmup rows only | 0.1886, n = 2,020 |
>
> Consequently the "3112 rows · base rate 0.1793" figure is a **warmup-pooled** number and must not
> be used as this collection's population statistic. Any future use of Fixture B as a "3112-row"
> fixture inherits the contamination. The usable in-window population is 1,092 rows at 0.1621.
>
> Fixture B therefore fails **two** checks, not one: `STALE_COMPILED_STUDY` **and**
> `WARMUP_LEAKAGE`. Both must be resolved before it could serve as a clean positive fixture
> (blocker #7 in §10).

**Why these two.** Anything that works on both cannot have hardcoded: the feature count, the join key,
the presence of `regime_direction`, the metadata list, the chronology, the target base rate, or the
existence of a seal. Fixture B's window (2025) is *prohibited* under Fixture A's chronology, which
makes cross-contamination between the two immediately detectable.

> [!WARNING]
> **Fixture B is currently unloadable through the canonical study loader.**
> `load_compiled_study("studies/reconstructed_long_rth_strict_retrain")` raises
> `StaleCompiledStudyError`. Measured:
>
> | | value |
> |---|---|
> | `study.yaml` computed hash (today) | `7ab8a81ff0b74e1e6ad6784a09c0727b24167a93ba9dd346b9bfaecf525ce8bb` |
> | `compiled_study.json:spec_sha256` | `bd51e8c29eb7d0fa300c6bb638034541851e1c4db0c0552603714aa2bf4ecaa2` |
> | `run_manifest.json:spec_sha256` | `bd51e8c29eb7d0fa300c6bb638034541851e1c4db0c0552603714aa2bf4ecaa2` |
>
> The collection ran 2026-08-14 23:21; `study.yaml` was first committed later, at `97b97db`
> (2026-08-15 17:08), and `compiled_study.json` was never recompiled against it.
>
> **The collection itself is internally consistent** — its run manifest and the compiled artifact
> agree, so the data is trustworthy evidence of what was collected. What has moved on is the working
> tree. Fixture A is unaffected and loads cleanly.
>
> Consequence for A1: Fixture B serves as a **real, on-disk negative fixture** for
> `STALE_COMPILED_STUDY` (a better test than a synthetic one). It cannot be used as a *clean positive*
> fixture until the study is recompiled — see blocker #7 in §10. Every schema/target/join fact
> tabulated above was read directly from the run's artifacts and remains accurate regardless.

### Fixture N — negative fixture (must be rejected)

```
run_id : 20260815_003408_Gemini_clean_maturity_flip_rolling_5m_productivity_day
```

717 candidates, and `observations.parquet` is **`(0, 0)` — zero rows and zero columns.** A naive
loader inner-joins this to an empty frame and reports "0 samples" rather than an error, or crashes on
a missing target column. Any A1 implementation must reject it by identity/schema check before it ever
reaches a join. This is a real artifact on disk, not a constructed test case.

---

## 2. Immutable collection / run identity

An analysis binds to exactly one collection run. **There is no `latest`.** Resolution is by explicit
`run_id` or by an alias that resolves to exactly one `run_id` and is recorded alongside it.

`CollectionIdentity` is the tuple that every downstream artifact must carry:

| Field | Source |
|---|---|
| `run_id` | run directory name |
| `study_id` | `collection_manifest.json:study_id` |
| `spec_sha256` | `run_manifest.json:spec_sha256` |
| `composite_seal_hash` | `run_manifest.json:composite_seal_hash` (may be `null`; see §7 failure `UNSEALED_COLLECTION`) |
| `candidates_sha256` | `collection_manifest.json` |
| `observations_sha256` | `collection_manifest.json` |
| `collection_manifest_sha256` | sha256 of the manifest's **parsed canonical JSON** (see rule 5) |
| `feature_list_sha256` | `study.yaml:features.feature_list_sha256` |
| `stage`, `start_date`, `end_date`, `warmup_start` | `run_manifest.json:stage`, `:dates` |
| `timestamp_contract` | `run_manifest.json:timestamp_contract` |

`collection_identity_sha256` = sha256 over the canonical JSON of the above, sorted keys. This single
value is what a reviewer compares to answer "is this the same data?".

**Rules**

1. Identity is computed from artifacts on disk and re-verified at load: recorded parquet hashes must
   match recomputed file hashes. A manifest that disagrees with its own parquet is a hard failure.
2. Identity is immutable. If any component changes, it is a different collection, not an update.
3. Every analysis artifact embeds `collection_identity_sha256`. An artifact without it is not valid
   evidence.
4. `composite_seal_hash` is recorded but is **not** silently required — Fixture B has none. Whether an
   unsealed collection may be analysed is an explicit flag in the analysis spec
   (`allow_unsealed_collection`), defaulting to `false`.
5. **Hashing is per artifact class, and the classes are not interchangeable.**
   - *Generated binary data* (`candidates.parquet`, `observations.parquet`): **raw byte hash**, no
     normalisation, ever. These files are gitignored and never EOL-translated.
   - *Structured text* (`collection_manifest.json` and any JSON/YAML manifest): hash of the
     **parsed canonical form** (sorted keys, no whitespace). These files are git-tracked, so under
     `core.autocrlf` a Windows checkout and a Linux checkout hold byte-different but semantically
     identical text. A raw byte hash there makes `collection_identity_sha256` platform-dependent
     for byte-identical collection *data*, which both breaks "identity is stable for equivalent
     data" and raises a false `IDENTITY_MISMATCH` off-platform. This is the same convention
     `spec_sha256` already uses (`StudySpec.model_validate(...).compute_sha256()`).
   - *Harness-written artifacts* (`dataset_identity.json`, `analysis_context.json`,
     `model_manifest.json`, table CSV/JSON) are emitted with `newline="\n"` so their own bytes do
     not depend on the host OS.
6. The run directory is resolved under `runs_root` and **containment is asserted**: a `run_id` is a
   plain directory name, never a path. Anything containing `/`, `\`, `..`, `.` or `:` is rejected
   (`INVALID_RUN_ID`), and `run_dir.resolve().parent` must equal `runs_root.resolve()`. The resolved
   absolute directory is recorded in `dataset_identity.json` — but deliberately *outside* the hashed
   identity tuple, because an absolute path is machine-specific and rule 2 requires the identity to
   be portable.

---

## 3. Manifest, schema and ordered-feature-hash checks

Ordered, fail-closed, cheapest first. Every check names the failure mode from §7.

| # | Check | Failure |
|---|---|---|
| 1 | Run dir, `run_manifest.json`, `collection/collection_manifest.json`, `candidates.parquet`, `observations.parquet` all exist | `MISSING_ARTIFACT` |
| 2 | `status.json:status == "SUCCESS"` | `COLLECTION_NOT_SUCCESSFUL` |
| 3 | Recomputed `candidates`/`observations` file sha256 equal the manifest's recorded values | `ARTIFACT_HASH_MISMATCH` |
| 4a | `study.yaml` computed hash equals `compiled_study.json:spec_sha256` (the study dir is self-consistent *now*) | `STALE_COMPILED_STUDY` |
| 4b | `compiled_study.json:spec_sha256` equals `run_manifest.json:spec_sha256` (the collection was produced from that contract) | `SPEC_DRIFT` |
| 5 | Candidate columns ⊇ declared `feature_list`; **order preserved** as declared | `FEATURE_ORDER_MISMATCH` |
| 6 | `sha256(json(ordered_feature_list))` equals `features.feature_list_sha256` | `FEATURE_HASH_MISMATCH` |
| 7 | Candidate columns = `feature_list` ∪ `metadata_columns` exactly; no surplus, no missing | `SCHEMA_SURPLUS` / `SCHEMA_MISSING` |
| 8 | No duplicate column names in either frame | `DUPLICATE_COLUMNS` |
| 9 | Observations contain the target column and the full join key | `TARGET_MISSING` / `JOIN_KEY_MISSING` |
| 10 | Observations non-empty when candidates are non-empty | `EMPTY_OBSERVATIONS` ← catches Fixture N |
| 11 | Join key unique in **both** frames | `DUPLICATE_KEYS` |
| 12 | Join is 1:1 and loses no candidate rows | `JOIN_ROW_LOSS` |
| 13 | Row counts match `collection_manifest.json` | `ROW_COUNT_MISMATCH` |
| 14 | `observation_ts` within `[start_date, end_date]`; nothing from the warmup window | `WARMUP_LEAKAGE` |

**Checks 4a and 4b are deliberately separate**, because they fail for different reasons and warrant
different responses. 4b failing means the collection was produced from a different contract than the
one compiled — the data is suspect. 4a failing means the *working tree* has moved on since compilation
— the historical data may still be perfectly good evidence, but the study directory cannot currently be
loaded. Fixture B fails 4a and passes 4b, which is exactly the "old collection, evolved study" case.
Collapsing these into one check would either block legitimate analysis of historical collections or
mask a genuine contract substitution.

Check 6 must recompute the hash from the **emitted** ordered feature list, not re-read the declared
one — otherwise it only proves the config equals itself. Both fixtures currently pass checks 11 and 12
with 0 duplicate keys and 0 row loss; that is a measured property to be re-asserted, not assumed.

---

## 4. Target and metadata contract

**The target is not in `candidates.parquet`.** It lives in `observations.parquet`, and the two are
joined on the study's key. Loaders that read only candidates will silently find no label.

`observations.parquet` columns:

| Column | Fixture A | Fixture B | Role |
|---|---|---|---|
| `observation_ts` | ✔ | ✔ | join key |
| `regime_start_ns` | ✔ | ✔ | join key |
| `regime_direction` | ✔ | **absent** | join key **for A only** |
| `checkpoint_index` | ✔ | ✔ | join key |
| `flip_ts` | ✔ | ✔ | outcome timestamp |
| `time_to_flip_seconds` | ✔ | ✔ | outcome timing |
| `target_flip_within_horizon` | ✔ | ✔ | **the target** |

**Target contract.** `target_flip_within_horizon`: `int64`, values ⊆ `{0,1}`, no nulls in either
fixture. Its meaning comes from `study.yaml:target` — `{type: flip, event: confirmed_flip,
horizon_seconds: 300, confirmation: {mode: bar_close, confirmation_bars: 1}}` — and `direction`
differs (`both` for A, `bullish` for B). The horizon and confirmation mode are part of target identity:
two collections with different `horizon_seconds` do not have comparable targets and must not be pooled.

`flip_ts` and `time_to_flip_seconds` are **outcome** columns, known only after the horizon resolves.
They are never features. A1 must expose them as outcome metadata and must refuse to return them from
`get_features_targets_metadata(...)` in the feature block.

**Join key is per-study, DECLARED, never hardcoded and never read off the observation frame.**
Fixture A's key is 4 columns, Fixture B's is 3. Hardcoding A's key raises `JOIN_KEY_MISSING` on B;
hardcoding B's key silently produces a many-to-many join on A whenever a timestamp carries both
directions — so the key must be resolved per study.

But it must not be resolved *from the live observations frame*. A key defined as "declared metadata ∩
observation columns" is unfalsifiable by construction: every derived column is trivially present in
observations, so `JOIN_KEY_MISSING` can only fire on an empty intersection, and a key column that goes
missing from observations silently shortens the key from 4 to 3 while validation reports zero
failures. The only remaining backstop, `join_key_unique`, is *data-dependent*: whenever the shortened
key happens to stay unique, direction-crossing target assignment is accepted silently. Fixture A — the
collection with both directions present — is precisely the population at risk.

The key of record is therefore resolved in this order, strongest declaration first:

1. `collection.expected_join_key` pinned in the analysis spec;
2. `features.join_key` declared in the study contract;
3. the observation columns the **collection manifest records having emitted**, intersected with the
   declared metadata columns — the producer's own declaration, fixed at collection time and covered
   by `collection_manifest_sha256`;
4. declared metadata ∩ **candidate** columns — last resort, and still not the frame whose scope loss
   is being checked.

Every resolved key column must then be present in **both** frames; any absence is `JOIN_KEY_MISSING`,
naming the missing columns and the frame they are missing from. The resolution source is recorded on
the validation report (`join_key_source`) and in `dataset_identity.json`.

Note the residual: a tampered collection that *also* rewrites `columns.observations` in its manifest
is internally self-consistent and resolves at level 3 to the shortened key. That rewrite moves
`collection_manifest_sha256` and therefore `collection_identity_sha256`, so a spec pinning the
identity (§10 prerequisite 4) detects it; pinning `expected_join_key` refuses it outright. An analysis
that pins neither is trusting the producer's declaration, which is a choice the spec should make
explicitly.

**Metadata contract.** Fixture A declares 13 `metadata_columns`. Fixture B declares none, so the
`OutputManager` default list applies (the same 13 minus `triggering_1s_ts_init`, which B does not
emit). A1 must resolve metadata as *declared if present, documented fallback otherwise*, and record
which of the two it used in the analysis manifest.

**Missing values are declared, never imputed.** Fixture A has NaNs in 13 feature columns, Fixture B in
7 (both include `rth_elapsed_seconds`, `rth_vol_cum`, and the opening-range distances — structurally
undefined before the session opens). A1 reports per-feature null counts; it does not fill them. Any
imputation is a modelling decision that belongs to a declared analysis spec, not to the loader.

---

## 5. TRAIN / DEV / OOS partition rules

Partitions come from `study.yaml:chronology`, per study, and never from a default:

| | Fixture A | Fixture B |
|---|---|---|
| TRAIN | 2021, 2022, 2023 | 2021, 2022, 2023, 2024 |
| DEV | 2024 | 2025 |
| PROHIBITED | 2025, 2026 | 2026 |

**Rules**

1. A row's partition is derived from `observation_ts` (UTC → calendar year), never from a filename,
   directory name, or manifest date string.
2. **Prohibited years are a load-time failure**, not a filter. If any row falls in a prohibited year,
   the load fails `PROHIBITED_PARTITION_PRESENT`. Silently dropping them would let an analysis report
   a sample size it never had.
3. DEV/OOS is locked. Reading DEV requires an explicit `analysis_spec.partitions: [dev]` **and** a
   valid OOS unlock token (`scripts/generate_oos_unlock.py` / `verify_oos_unlock_token`), matching the
   rule already enforced by `resolve_data_plan`. Absent the token: `OOS_LOCKED`.
4. TRAIN and DEV rows may never appear in the same fitted arm. Requesting both in one fit is
   `PARTITION_MIXING`. Comparing them is legitimate only as separate, separately-recorded runs.
5. Warmup rows never enter any partition. Fixture A's spec is explicit:
   `warmup.candidate_emission: false`, `warmup.target_generation: false`,
   `permitted_partition_relationship: pre_train_only`. Enforced by check 14.
6. The partition set actually present is recorded in the analysis manifest, with row counts per
   partition, so a reviewer sees what was used rather than what was requested.

**Cross-study pooling is prohibited by default.** The two fixtures disagree on TRAIN membership: 2024
is TRAIN for B and DEV for A. Pooling them would put A's locked DEV year into B's training data. A1
must refuse to load two `study_id`s into one dataset unless an analysis spec explicitly declares a
cross-study comparison and states the partition reconciliation.

**Current limitation.** Both fixtures are single-day `stage: day` smoke collections. Partition rules
can be *specified* and *unit-tested* against synthetic timestamps, but cannot be *exercised* on real
multi-year data until a TRAIN-stage collection exists (§8).

---

## 6. Analysis-spec identity

An analysis is defined by a declarative spec (proposed location `analyses/<name>.yaml`; **the
directory does not exist yet**). Minimum fields:

```yaml
analysis_id: <stable name>
schema_version: 1
collection:
  run_id: <exact run id>            # no aliases resolving to 'latest'
  study_id: <expected study>        # cross-checked, not trusted
  collection_identity_sha256: <expected>   # refuses a substituted run
  allow_unsealed_collection: false
target:
  column: target_flip_within_horizon
  horizon_seconds: 300              # cross-checked against study.yaml
partitions: [train]                 # explicit; dev requires an unlock token
features:
  feature_list_sha256: <expected>   # ordered-set binding
  set: declared                     # declared | subset:<named>
missing_values: report_only         # loader never imputes
seed: 20260816
```

`analysis_spec_sha256` = sha256 of the canonical JSON of the resolved spec. It is recorded in every
output artifact. Changing the seed, the partition list, the feature set, or the target changes the
hash — so two results that claim to be comparable can be checked mechanically.

**Analysis identity** = `(collection_identity_sha256, analysis_spec_sha256, code_version)`. Equal
identity must produce equivalent artifacts; different identity must be visibly different.

---

## 7. Required analysis artifacts and failure modes

### Artifacts (every analysis run)

```
analysis_runs/<ts>_<analysis_id>/
├── analysis_manifest.json   # both identities, resolved spec, code version, partition row counts
├── validation.json          # every §3 check with PASS/FAIL + measured value
├── metrics.json             # headline metrics with n and definitions
├── tables/*.csv|parquet     # one file per declared slice; each carries n, filters, null treatment
└── analysis_context.json    # compact reviewer packet: question, identity, metrics, caveats, paths
```

`validation.json` must record **measured values**, not just verdicts — e.g. duplicate-key count `0`,
join row loss `0`, target base rate `0.3492`. A check that only ever prints PASS is not evidence.

### Failure modes — all fail closed, none degrade silently

| Failure | Trigger |
|---|---|
| `MISSING_ARTIFACT` | any required file absent |
| `INVALID_RUN_ID` | `run_id` is not a plain directory name inside `runs_root` (path syntax, or resolves outside it). A subclass of `MISSING_ARTIFACT` |
| `COLLECTION_NOT_SUCCESSFUL` | `status.json` not SUCCESS |
| `ARTIFACT_HASH_MISMATCH` | recomputed parquet hash ≠ manifest |
| `STALE_COMPILED_STUDY` | `study.yaml` hash ≠ `compiled_study.json` — study dir not self-consistent (Fixture B today) |
| `SPEC_DRIFT` | `compiled_study.json` hash ≠ run's `spec_sha256` — collection produced from a different contract |
| `IDENTITY_MISMATCH` | resolved identity ≠ spec's expected identity |
| `UNSEALED_COLLECTION` | no `composite_seal_hash` and `allow_unsealed_collection: false` |
| `FEATURE_ORDER_MISMATCH` | same features, different order |
| `FEATURE_HASH_MISMATCH` | recomputed ordered-feature hash ≠ declared |
| `SCHEMA_SURPLUS` / `SCHEMA_MISSING` | undeclared or absent columns |
| `DUPLICATE_COLUMNS` / `DUPLICATE_KEYS` | non-unique names or join keys |
| `TARGET_MISSING` / `JOIN_KEY_MISSING` | observations lack target or key |
| `EMPTY_OBSERVATIONS` | candidates non-empty, observations empty (Fixture N) |
| `JOIN_ROW_LOSS` | inner join drops candidate rows |
| `ROW_COUNT_MISMATCH` | frame rows ≠ manifest counts |
| `WARMUP_LEAKAGE` | `observation_ts` outside the declared window |
| `PROHIBITED_PARTITION_PRESENT` | any row in a prohibited year |
| `OOS_LOCKED` | DEV requested without a valid unlock token |
| `PARTITION_MIXING` | TRAIN and DEV in one fitted arm |
| `PARTITION_PROVENANCE_MISSING` | a fit was requested with no `_partition` record and no explicit, recorded opt-out. A subclass of `PARTITION_MIXING` |
| `CROSS_STUDY_POOLING` | two `study_id`s without an explicit declaration |
| `VALIDATION_NOT_RUN` | extraction attempted with no report, or with a report produced under a different (or no) analysis spec |
| `METRIC_NOT_COMPUTABLE` | one-class, empty, or **non-finite** slice — reported as such, never as a score |

`METRIC_NOT_COMPUTABLE` matters at this sample size: a slice of a 2002-row single-day collection can
easily be one-class, and an AUC of `0.5` or `nan` presented as a number is worse than an explicit
refusal. The same applies to a computed-but-non-finite value: emitting it as a bare `null` under
`status: ok` makes it byte-identical on the wire to a metric that was never computed, which collapses
exactly the distinction this layer exists to draw. Non-finite results are downgraded to
`not_computable` with a reason, and a single `inf` score must never abort a whole table build.

**A validation report is an authorisation, not a fact.** `validate_collection(collection)` without a
spec cannot run `seal_policy`, `oos_unlocked`, `no_partition_mixing` or any of the identity bindings —
it has nothing to bind them to. Such a report may still be produced (it is useful for triage), but it
carries `spec_supplied: false` plus the list of checks it skipped, and
`get_features_targets_metadata` refuses it: extraction requires a report whose
`analysis_spec_sha256` equals the spec being used. Otherwise the two most natural lines a researcher
would write — `rep = validate_collection(c)` then `get_features_targets_metadata(c, dev_spec, rep)` —
return DEV rows with `OOS_LOCKED` never emitted.

---

## 8. Proposed minimal A1 loader API

**Not implemented in A0.** Three functions, no more:

```python
load_collection(run_id: str, *, runs_root: Path = Path("runs")) -> Collection
    # Resolves an EXACT run id. No 'latest', no globbing, no most-recent fallback.
    # Reads manifests + both parquets, computes CollectionIdentity, performs NO validation.
    # Raises MISSING_ARTIFACT only.

validate_collection(collection: Collection, spec: AnalysisSpec | None = None) -> ValidationReport
    # Runs every §3 check plus §5 partition rules in order, fail-closed.
    # Returns a report carrying the MEASURED value of each check, not just verdicts.
    # With a spec: additionally enforces identity, feature-hash, partition and seal expectations.

get_features_targets_metadata(collection: Collection, spec: AnalysisSpec)
        -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]
    # Requires a passing ValidationReport; refuses to run otherwise.
    # Returns (features_in_declared_order, target, metadata_incl_partition_and_outcomes).
    # Outcome columns (flip_ts, time_to_flip_seconds) go in metadata, never in features.
```

Design constraints carried from the harness work: no implicit "latest"; identity re-verified from disk
rather than trusted from a manifest; the join key derived per study; validation separated from loading
so a failure is reportable rather than fatal at import; and no imputation, ranking, or filtering inside
the loader.

---

## 9. Validation matrix

`P` = must pass · `F:<mode>` = must fail with that mode · `n/a` = not applicable.

| # | Case | Fixture A | Fixture B | Fixture N |
|---|---|---|---|---|
| 1 | Artifacts present, status SUCCESS | P | P | P |
| 2 | Parquet hashes match manifest | P | P | P |
| 3a | Study dir self-consistent (`study.yaml` = `compiled_study.json`) | P | **`F:STALE_COMPILED_STUDY`** | P |
| 3b | Collection produced from compiled contract (`compiled_study.json` = run) | P | P | P |
| 4 | Feature count | 60 | 25 | 37 cols, unusable |
| 5 | Ordered feature hash matches declared | P | P | — |
| 6 | Declared metadata present | P (13, declared) | P (12, fallback) | — |
| 7 | Join key resolved per study | 4 cols | 3 cols | — |
| 8 | Duplicate join keys | 0 → P | 0 → P | — |
| 9 | Join 1:1, no row loss | 2002 → P | 3112 → P | `F:EMPTY_OBSERVATIONS` |
| 10 | Target present, `{0,1}`, no nulls | P (rate 0.3492) | P (in-window rate **0.1621**, n=1,092; pooled 0.1793 is warmup-contaminated) | `F:TARGET_MISSING` |
| 11 | Rows match manifest counts | 2002 → P | 3112 → P | `F:ROW_COUNT_MISMATCH` |
| 11b | No rows outside the declared run window (check 14) | P | **`F:WARMUP_LEAKAGE`** (2,020 of 3,112 rows precede 2025-03-03) | — |
| 12 | No prohibited-year rows | P (2023 ∈ TRAIN) | P (2025 ∈ DEV) | — |
| 13 | Load DEV without unlock token | `F:OOS_LOCKED` | `F:OOS_LOCKED` | — |
| 14 | Unsealed collection, default spec | P (sealed) | `F:UNSEALED_COLLECTION` | — |
| 15 | Unsealed with `allow_unsealed_collection: true` | n/a | P, recorded | — |
| 16 | Reordered feature list, same members | `F:FEATURE_ORDER_MISMATCH` | `F:FEATURE_ORDER_MISMATCH` | — |
| 17 | Spec pinned to A's identity, given B | `F:IDENTITY_MISMATCH` | `F:IDENTITY_MISMATCH` | — |
| 18 | A's join key applied to B | n/a | `F:JOIN_KEY_MISSING` | — |
| 19 | Pool A + B into one dataset | `F:CROSS_STUDY_POOLING` | `F:CROSS_STUDY_POOLING` | — |
| 20 | TRAIN + DEV in one fitted arm | `F:PARTITION_MIXING` | `F:PARTITION_MIXING` | — |
| 21 | `regime_direction` slice | 2 groups, valid | 1 group → `METRIC_NOT_COMPUTABLE` | — |
| 22 | One-class slice metric | `F:METRIC_NOT_COMPUTABLE` | `F:METRIC_NOT_COMPUTABLE` | — |
| 23 | Same identity twice → same artifacts | P | P | — |
| 24 | Changed seed → different `analysis_spec_sha256` | P | P | — |

Cases 16–20 require constructing a mutated copy of a fixture; none mutate the real run directories.

---

## 10. Missing artifacts that would block A1

| # | Blocker | Impact | Resolution |
|---|---|---|---|
| 1 | **No TRAIN-stage collection exists.** All 23 collection runs on disk are `stage: day` single-day smokes (largest real research collection: 3112 rows). | Partition rules can be specified and unit-tested against synthetic timestamps, but no real TRAIN/DEV split can be exercised, and no model could be fit on a meaningful sample. **This is the principal blocker for anything past A1 validation.** | An authorized full TRAIN collection — which is gated behind the collector reseal (below). |
| 2 | **Collector seal is stale** (`REQUIRES_INDEPENDENT_RED_TEAM_RESEAL`). | Fixture A's existing artifacts remain valid evidence of what *was* collected, but the collection **cannot be regenerated or extended** until the seal is restored, because collect mode verifies the seal before running. | Independent causal + contract audits → status ingestion → seal → bounded smoke → smoke validation. |
| 3 | **No analysis-spec schema or `analyses/` directory.** `research/schemas/` contains only `study_spec.py`. | §6 is a specification with no validator. A1 needs an `AnalysisSpec` schema to parse and hash. | Add `research/schemas/analysis_spec.py` + `analyses/` as the first A1 task. |
| 4 | **No OOS unlock token exists** for either study. | Case 13 can be tested only in its negative direction (`OOS_LOCKED`). The positive path — DEV legitimately unlocked — is untestable. | Generate a token via the existing verified dependency chain when a DEV analysis is actually authorized. |
| 5 | **Fixture B declares no `metadata_columns`.** | The fallback list is currently implicit in `OutputManager`. A loader relying on it is depending on undocumented behaviour. | Either declare `metadata_columns` in that study's `study.yaml`, or promote the default list to a named, importable constant. Recommend the latter — it fixes every past and future study at once. |
| 6 | **`bars_breakdown.callbacks` is empty for Fixture A** (`{}`) while populated for Fixture B. | Warmup-dispatch evidence is not uniformly available, so check 14 must rely on `observation_ts` bounds rather than callback counts. | Not blocking; noted so A1 does not assume callback telemetry exists. |
| 7 | **Fixture B's study directory is not self-consistent.** `load_compiled_study` raises `StaleCompiledStudyError`: `study.yaml` computes `7ab8a81f…` while `compiled_study.json` and the run both record `bd51e8c2…`. | Fixture B cannot serve as a *clean positive* fixture. It remains fully usable as a real negative fixture for `STALE_COMPILED_STUDY`, and all its measured schema/target/join properties stay valid. | Run `python scripts/compile_study.py --study studies/reconstructed_long_rth_strict_retrain` to recompile against the current `study.yaml`. **Note this changes the study contract hash**, so the recompiled study no longer matches the existing collection — that is precisely the `SPEC_DRIFT` (4b) condition, and would require a fresh collection for a clean positive fixture. Alternatively, select a third collection for the positive role and keep B as the negative. This is a decision for whoever owns that study, not a mechanical fix. |
| 8 | **Fixture A is the only collection in the repository that passes both 4a and 4b.** Every alternative was checked: `reconstructed_long_rth_strict_retrain` fails 4a; `test_minimal_checkpoint_collector` and `test_level_break_collector` load cleanly but their run-recorded spec no longer matches their compiled contract, so both fail 4b. | There is exactly one fully clean positive fixture. A1's positive-path tests therefore rest on a single collection, and any regression in it removes the only clean example. | Not fixable by A1. Either recompile-and-recollect one other study, or accept that A1's positive path is single-fixture and make the negative-path coverage (cases 3a, 9, 10, 16–20) carry proportionally more weight. Recommend the latter for A1 and revisiting once a TRAIN collection exists (blocker #1). |

**Not blocking:** the absence of a target column in `candidates.parquet` (it is in `observations.parquet`
by design), and the differing join keys (handled by per-study derivation).

---

## 11. A0 exit criteria — status

| Criterion | Status |
|---|---|
| Two structurally different collections selected, with real paths and identities | ✅ §1 |
| Immutable collection/run identity defined | ✅ §2 |
| Manifest / schema / ordered-feature-hash checks defined | ✅ §3 |
| Target and metadata contract defined | ✅ §4 |
| TRAIN/DEV/OOS partition rules defined | ✅ §5 |
| Analysis-spec identity/hash defined | ✅ §6 |
| Required artifacts and failure modes defined | ✅ §7 |
| Minimal A1 loader API proposed | ✅ §8 |
| Validation matrix | ✅ §9 |
| Blockers identified | ✅ §10 |
| Loader implemented | ❌ **out of scope — A1** |
| Any model fitted | ❌ **out of scope** |

**A0 exit condition from the roadmap** — *"an analysis detects a mismatched run, schema, feature order,
or partition before model fitting"* — is **specified and covered** by matrix cases 5, 9, 10, 16, 17, 18,
19 and 20. It is not yet *demonstrated*, because demonstration requires the A1 loader.
