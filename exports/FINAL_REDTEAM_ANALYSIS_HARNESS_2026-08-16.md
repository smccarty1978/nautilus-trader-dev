# FINAL RED TEAM — Analysis Harness A1–A4

**Date:** 2026-08-16 · **Reviewer:** independent Red Team (no implementation authorship)
**Target:** `worktree-analysis-harness-a1-a4` @ `.claude/worktrees/analysis-harness-a1-a4` (base `7cc5e0c`, uncommitted)
**Contract:** `ANALYSIS_HARNESS_A0_CONTRACT.md` (main checkout — **absent from the worktree**)
**Implementation report reviewed:** `ANALYSIS_HARNESS_IMPLEMENTATION_REPORT.md`
(note: the brief names `ANALYSIS_HARNESS_A1_IMPLEMENTATION_REPORT.md`; no such file exists — the
report is unsuffixed)

**Method:** independent code inspection plus 20 executed adversarial probes against synthetic
fixtures in a temp directory, and read-only execution against the three real A0 fixtures.
No source, collector, backtest, seal, run artifact, or study output was modified.

---

## 1. Executive verdict

```text
FLOW_BLOCKED
```

**Why not `FLOW_CLEAR_WITH_WARNINGS`.** The governing question is whether the harness can load
validated collections and support future TRAIN-only modeling *without silently accepting schema,
join, identity, or partition errors*. I demonstrated a working silent failure in **each of those
four categories**, by ordinary non-malicious call patterns, on the shipped public API:

| Category | Demonstrated silent acceptance |
|---|---|
| **Identity** | `run_id="../secret_runs/<run>"` loads a run outside `runs_root`, and the recorded `identity.run_id` keeps only the basename — the traversal is erased from the artifact (**H1**) |
| **Partition** | `validate_collection(c)` → passing report → `get_features_targets_metadata(c, dev_spec, report)` returns **60 DEV rows**; `OOS_LOCKED` never fires (**H2**) |
| **Join** | A 4-column declared join key silently degrades to 3 columns when observations lose a key column; validation passes with zero failures (**H3**) |
| **Schema/reporting** | A standard slice table silently dropped **30 of 100 rows**; `total_sample_count=70`, completeness check reported "clean" (**H4**) |

None of these require a redesign. All four are bounded repairs (§6). This is a **blocked-pending-fix**
verdict on a fundamentally sound piece of work, not a rejection of the architecture.

**What is genuinely good, and verified by me rather than taken on trust:**

- The report's headline claim reproduces exactly: **120 tests pass in 16.56s**, and the real-fixture
  tests execute rather than skip.
- Every A0 §1 number for Fixture A reproduces from disk: `(2002, 73)` / `(2002, 7)`, 60 declared
  features, `metadata_source=declared`, the **4-column** join key, base rate **0.3492**, TRAIN 2002,
  `candidates_sha256=1ab64a10…`, `observations_sha256=f3001950…`, manifest sha `f4f8c027…`.
- The 4a/4b split works on real data: Fixture B fails `STALE_COMPILED_STUDY` while
  `collection_matches_compiled_contract` (4b) passes — the exact "old collection, evolved study"
  discrimination A0 §3 demanded, proven on a real artifact rather than a synthetic one.
- Outcome columns do **not** leak into `X` on the real end-to-end path (verified: `[]`).
- Score metrics are genuinely **omitted**, not nulled, when no scores exist (verified: real
  `by_direction` row keys are exactly `['group','n','sample_count','positive_rate']`).
- The A2 spec-rejection matrix is strong: unknown top-level keys, unknown collection keys, `latest`,
  undeclared partitions, imputation policies, bad `schema_version`, and duplicate arm features are
  all rejected (7/8 — see L4).
- Duplicate join keys in observations only are correctly caught (`join_key_unique` measured
  `{'candidates': 0, 'observations': 1}`).

**And one finding that credits the harness:** check 14 caught a **real, previously undocumented data
defect in A0's own Fixture B** — see M8.

---

## 2. Finding table

Severity: **H** = blocks authorization · **M** = must fix before real analysis · **L** = record and schedule.

### H1 — `run_id` path traversal escapes `runs_root`, and the traversal is erased from identity

- **Evidence:** `research/analysis/loader.py:113-119`; `research/analysis/identity.py:123-133`, `identity.py:156`
- The `latest` guard (`loader.py:113`) blocks four string literals. `CollectionPaths.for_run`
  (`identity.py:123`) then does a bare `Path(runs_root) / run_id` with no `resolve()`, no
  containment assertion, and no separator rejection. `build_identity` records
  `run_id=paths.run_dir.name` (`identity.py:156`) — the **basename only**.
- **Reproduction (probe P1c, executed):**
  ```
  load_collection("../secret_runs/20230101_000000_sx_day",
                  runs_root=base/"runs", studies_root=base/"studies")
  -> run_dir = ...\p1c\runs\..\secret_runs\20230101_000000_sx_day
  -> identity.run_id = '20230101_000000_sx_day'   # traversal erased
  -> validate_collection(c).passed = True
  ```
- **Impact.** Directly falsifies A1 adversarial check #1. `dataset_identity.json` will assert
  `run_id: 20230101_000000_sx_day` for data read from an entirely different directory. Because
  `run_id` is a component of `collection_identity_sha256`, the substituted run gets a
  well-formed, self-consistent identity. A0 §2 rule 3 ("an artifact without it is not valid
  evidence") is satisfied in form while being false in substance.
- **Smallest repair:** in `CollectionPaths.for_run`, reject any `run_id` containing `/`, `\`, or
  `..`, or equal to `.`; then assert
  `run_dir.resolve().parent == Path(runs_root).resolve()`. Record the resolved absolute
  `run_dir` in the identity alongside `run_id`.

### H2 — `ValidationReport` is not bound to the spec it is used with → `OOS_LOCKED` / seal / identity bypass

- **Evidence:** `research/analysis/loader.py:243-248` (spec optional), `loader.py:408-441`
  (all spec-bound checks live inside `if spec is not None:`), `loader.py:500-519`
  (partition-mixing and OOS checks return early when `spec is None`),
  `loader.py:527-543` (extraction validates only `report.raise_if_failed()`).
- **Reproduction (probe P2, executed):**
  ```
  c   = load_collection(...)            # years 2023(train) + 2024(dev)
  rep = validate_collection(c)          # spec=None -> 19 checks, passed=True
                                        # seal_policy / oos_unlocked / no_partition_mixing /
                                        # collection_identity_matches_spec NEVER EMITTED
  X,y,meta = get_features_targets_metadata(c, spec(partitions=["dev"]), rep)
  -> 60 rows returned, meta['_partition'] == ['dev']
  ```
- **Impact.** This is the most serious finding. The OOS lock is the single most important safety
  control for all future work, and it is bypassed by the most natural two-line call sequence a
  researcher would write — no adversary required. It simultaneously defeats `UNSEALED_COLLECTION`,
  `IDENTITY_MISMATCH`, `FEATURE_HASH_MISMATCH`, target-horizon binding and `PARTITION_MIXING`.
  Falsifies A1 checks #3 and #8.
  Compounding (probe P2b): an **unsealed** collection passes spec-less validation with
  `passed=True`, and `write_dataset_identity` then records `validation_passed: true` for it
  (`loader.py:589-613`).
- **Smallest repair:** store the `analysis_spec_sha256` (and a `spec_was_supplied` flag) on
  `ValidationReport` at creation; in `get_features_targets_metadata`, raise `ValidationNotRun`
  unless `report.analysis_spec_sha256 == spec.analysis_spec_sha256`. One field, one assertion.

### H3 — The join key is *defined* as an intersection, so a missing key column is unreportable by construction

- **Evidence:** `research/analysis/loader.py:82-90` (`join_key()` = declared metadata ∩ observation
  columns), `loader.py:364-370` (`join_key_resolved` checks only that the derived key is present in
  **candidates**).
- A0 §3 check 9 requires "Observations contain the target column **and the full join key**"
  → `JOIN_KEY_MISSING`. Because the key is derived *from* the observation columns, every derived key
  is trivially present in observations. `JOIN_KEY_MISSING` can fire only when the intersection is
  empty. There is no declared-key-of-record to compare against, and `AnalysisSpec` has no `join_key`
  field to pin one.
- **Reproduction (probe P3, executed):** dropped `regime_direction` from a 4-key collection's
  observations and refreshed the manifest hash/count:
  ```
  join_key -> ['observation_ts','regime_start_ns','checkpoint_index']   # 3 cols, was 4
  validate_collection(c, spec).passed = True ; failures = []
  ```
- **Impact.** Falsifies A1 check #4 exactly as A0 §4 warned ("Hardcoding B's key silently produces a
  many-to-many join on A whenever a timestamp carries both directions"). The only backstop is
  `join_key_unique`, which is **data-dependent, not contract-dependent**: whenever the shortened key
  happens to remain unique, direction-crossing target assignment is accepted with zero failures.
  Fixture A is precisely the population at risk — it is the collection with both directions present.
- **Smallest repair:** make the declared key explicit — resolve it from declared metadata alone,
  then assert every declared key column is present in **both** frames, failing `JOIN_KEY_MISSING`
  with the missing names. Optionally add an `expected_join_key` field to `AnalysisSpec` and bind it.

### H4 — Slice tables silently drop rows; no `Σ(group n) == N` reconciliation anywhere

- **Evidence:** `research/analysis/reporting.py:114-123` (groups come from
  `labels.dropna().unique()`, so NaN-labelled rows belong to no group),
  `slices.py:118-123` (`pd.cut` yields NaN outside its bins), `slices.py:158-171`
  (`qcut` yields NaN for NaN inputs), `reporting.py:322-342` (completeness check never reconciles
  counts).
- **Reproduction (probe P4, executed):** 100 rows, 30 with `regime_age_seconds = -5`
  (below the `MATURITY_EDGES` floor of 0.0):
  ```
  total_sample_count = 70   vs   len(y) = 100      # 30 rows vanished
  caveats            = ["slice 'maturity' has 1 group(s) ..."]   # says nothing about the 30
  check_report_completeness -> []                  # "complete"
  ```
- **Impact.** Falsifies the A2 requirement that slicing "cannot silently drop or duplicate rows".
  A negative or NaN `regime_age_seconds`, a NaT timestamp, or a NaN score is enough. This is the
  cross-partition-reconciliation defect class this project has already been burned by: per-group
  checks cannot see a row that is in no group. It is materially worse than a wrong number, because
  the table still *looks* internally coherent.
  *(On real Fixture A all six standard tables reconcile exactly — 2002/2002. The defect is latent,
  not currently active.)*
- **Smallest repair:** in `build_slice_table`, compute `unassigned = len(y) - Σ n`; if non-zero,
  emit an explicit `unassigned` row **and** a caveat, and add
  `total_sample_count == n_input_rows` to `check_report_completeness`.

### M1 — Collection identity is platform-dependent: raw byte hash of a git-tracked, CRLF-normalized JSON file

- **Evidence:** `research/analysis/identity.py:37-42` (`sha256_file`), `identity.py:161`
  (`collection_manifest_sha256=sha256_file(...)`), feeding `collection_identity_sha256`
  (`identity.py:78-79`).
- **Measured:**
  ```
  git config core.autocrlf            -> true
  .gitattributes                      -> ABSENT
  runs/**/collection_manifest.json    -> TRACKED (not gitignored; only *.parquet is)

  working tree (Windows) : 93 CR bytes, len 3428, sha256 f4f8c027d0ffb6486c11…
  git blob (index)       :  0 CR bytes, len 3335, sha256 4d2223ba3cccda008fd9…
  ```
- **Impact.** A0 §1 records `f4f8c027…` — the **Windows-checkout CRLF** value. Any Linux/macOS/CI
  checkout, or Windows with `core.autocrlf=input`, produces `4d2223ba…`, a different
  `collection_manifest_sha256`, and therefore a different `collection_identity_sha256` **for byte-identical
  collection data**. Consequences: a spec that pins `collection_identity_sha256` (which the report's
  prerequisite #4 says a real analysis *must* do) raises a false `IDENTITY_MISMATCH` off-platform, and
  A1 check #7 — "`dataset_identity.json` is stable for equivalent data" — fails. See §5 for the policy.
- **Smallest repair:** hash **parsed canonical JSON** for manifest identity —
  `canonical_sha256(json.loads(text))`, which already exists at `identity.py:45` — and keep raw-byte
  hashing for `*.parquet` only. Additionally add `.gitattributes` with `runs/** -text` (or
  `*.json text eol=lf`).

### M2 — `fit_identity_sha256` binds *asserted* identities, never the actual training data

- **Evidence:** `research/analysis/modeling.py:96-108`. The hashed payload is
  `{arm, estimator, ordered_features, seed, hyperparameters, split_policy,
  dataset_identity_sha256, analysis_spec_sha256}`. It omits `n_rows`, `library_versions`,
  `model_sha256`, and any hash of `X`/`y`. `dataset_identity_sha256` is a caller-supplied string
  (`modeling.py:174`), never verified against the frame passed in.
- **Reproduction (probe P6, executed):**
  ```
  m1 = fit_model(X1(n=200), y1, arm="A", seed=1, dataset_identity_sha256="DECLARED")
  m2 = fit_model(X2(n=80, different distribution), y2, arm="A", seed=1,
                 dataset_identity_sha256="DECLARED")
  m1.fit_identity_sha256 == m2.fit_identity_sha256   -> True  (748b4ff227f4801c…)
  mutating provenance.library_versions['sklearn']='999.0' -> identity UNCHANGED
  ```
- **Impact.** Falsifies the A3 requirement to "verify model, prediction and threshold identities
  actually bind the stated inputs", and the explicit sub-check "change … library versions without
  changing recorded identities". Two fits on entirely different populations are mechanically
  indistinguishable. Note `library_versions` *is* recorded in provenance — it is simply not hashed.
- **Smallest repair:** add `n_rows`, `library_versions`, and a content hash of the fitted frame
  (e.g. `canonical_sha256([prediction_identity(X[c]) for c in ordered])` plus
  `prediction_identity(y)`) to the `fit_identity_sha256` payload.

### M3 — The TRAIN/DEV fit guard is opt-in on an optional kwarg

- **Evidence:** `research/analysis/modeling.py:194-209` — the `PartitionMixing` check runs only
  `if meta is not None and "_partition" in meta.columns`.
- **Reproduction (probe P7, executed):** identical 50-train/50-dev rows.
  With `meta`: `PartitionMixing` raised (guard works). Without `meta`: fits cleanly, and provenance
  records `split_policy = {'kind': 'none', …, 'description': 'no partition metadata supplied'}`.
- **Impact.** The provenance actively asserts an innocent explanation for the omission. Combined with
  H2 (which produces DEV rows in the first place), this is the second half of a complete
  TRAIN/DEV contamination path.
- **Smallest repair:** require `meta` (or an explicit
  `split_policy=SplitPolicy(kind="none", …)` opt-out that is recorded as a caveat) — refuse to fit
  when partition provenance is simply absent.

### M4 — `freeze_threshold` accepts an empty or false derivation population

- **Evidence:** `research/analysis/modeling.py:244-289`. `population: str = ""` is never validated;
  `threshold_freeze_sha256` (`modeling.py:286-288`) hashes the asserted **label**, not the rows.
- **Reproduction (probe P8, executed):** `freeze_threshold(scores, y)` with no population emits
  `derivation_population=''` and a well-formed `threshold_freeze_sha256=ea8242749dcdeda3…`.
  A DEV-derived threshold labelled `population="train"` is byte-indistinguishable from a real
  TRAIN freeze.
- **Impact.** Falsifies the A3 check "derive/freeze a threshold from the wrong population". The
  docstring's claim that "the population is mandatory context" is not enforced anywhere.
- **Smallest repair:** make `population` a required keyword, reject empty, and derive it from the
  `meta['_partition']` of the scored rows rather than accepting a caller assertion.

### M5 — `check_report_completeness` never reads the validation verdict or seal status

- **Evidence:** `research/analysis/reporting.py:331-332` — it asserts only that a `validation`
  **key exists**, never that `validation["passed"]` is true, and never inspects `sealed`.
- **Reproduction (probe P9, executed):** a context built with
  `validation={"passed": False, "checks":[{"check":"candidates_hash_matches_manifest","passed":False}]}`
  and `sealed=False` returns `check_report_completeness(...) -> []` — i.e. "complete".
- **Impact.** Falsifies the A4 check that the context "cannot conceal invalid validation status".
  The verdict is not *hidden* — `build_analysis_context` does copy `passed` and `failed_checks`
  through (`reporting.py:289-295`) — but the only mechanical gate over the packet declares a
  hash-mismatched, unsealed analysis complete.
- **Smallest repair:** add to `check_report_completeness`: flag when
  `validation.passed is not True`, and when `sealed is False` without a recorded
  `allow_unsealed_collection: true`.

### M6 — Non-finite metrics are reported as `status: ok, value: null`; AUC crashes the whole table build

- **Evidence:** `research/analysis/metrics.py:45-55` (`to_dict` emits `status: "ok"` whenever
  `computable=True`, while `_jsonable` at `metrics.py:58-67` converts inf/NaN to `None`);
  `metrics.py:125-131` (`_auc_like` catches only `ImportError`, not sklearn's `ValueError`);
  `reporting.py:80-88` (`_row_metrics` adds `*_status`/`*_reason` **only** when status ≠ ok).
- **Reproduction (probe P5, executed):**
  ```
  brier([0,1],[inf,0.5])          -> {'status':'ok','value':None,'reason':'','n':2}
  expected_value([1.0, inf])      -> {'status':'ok','value':None,'reason':''}
  excursion([1.0, inf],kind=mfe)  -> {'status':'ok','value':None}, extra={'q50':None,'q90':None}
  roc_auc([0,1,0,1],[0.1,inf,…])  -> UNCAUGHT ValueError: Input contains infinity…
  build_standard_tables(..., scores with one inf) -> UNCAUGHT ValueError  # entire table set fails
  ```
- **Impact.** Both halves fail the A2 requirement to handle NaN/inf honestly. A non-finite computed
  value emits a bare `null` with **no** `*_status`/`*_reason` key — on the wire this is identical to
  the "metric absent" case the implementation report (§4) presents as the honest signal, collapsing
  the very distinction it claims to have pinned. And a single inf score aborts the entire standard
  table build with an unhandled exception instead of a `METRIC_NOT_COMPUTABLE` report.
- **Smallest repair:** in `MetricResult.to_dict`, downgrade non-finite values to
  `computable=False, reason="non-finite value"`. In `_auc_like`, catch `ValueError` and return
  `_not_computable`.

### M7 — The cross-study pooling guard is unwired and unexported

- **Evidence:** `research/analysis/loader.py:616-624` defines `assert_single_study`; it has
  **zero callers** in `research/analysis/` (grep: only `loader.py` definition + two test call sites),
  and it is absent from `research/analysis/__init__.py:__all__`.
- **Reproduction (probe P11, executed):** `"assert_single_study" in research.analysis.__all__` → `False`.
- **Impact.** A0 §5 requires that "A1 must refuse to load two `study_id`s into one dataset".
  The refusal exists only as a helper the analyst must already know to call by hand, and it is not
  reachable from the documented package surface. `CROSS_STUDY_POOLING` is a control on paper.
  (The pooling risk is concrete: 2024 is TRAIN for Fixture B and locked DEV for Fixture A.)
- **Smallest repair:** export it, and call it from any multi-collection entry point when one is added
  in A5; until then, document it in the package docstring as a required caller obligation.

### M8 — Undisclosed: A0's Fixture B fails `WARMUP_LEAKAGE` on 2020 of 3112 rows, and its quoted base rate pools warmup

- **Evidence:** measured by me against the real fixture:
  ```
  run_manifest dates: {'start':'2025-03-03','end':'2025-03-03','warmup_start':'2025-02-26T00:00:00+00:00'}
  observation_ts range: 2025-02-26 14:30 UTC .. 2025-03-03 20:45 UTC
  rows by UTC date: 02-26:518  02-27:1122  02-28:380  03-03:1092
  validate_collection(FixtureB) -> FAIL no_warmup_leakage  {'rows_outside_window': 2020, ...}

  A0-quoted base rate (all 3112) : 0.1793
  in-window only (2025-03-03)    : 0.1621  n=1092
  warmup rows only               : 0.1886  n=2020
  ```
- **Impact.** This is a **working control that found a real defect** — check 14 correctly detected
  that Fixture B emitted 65% of its candidates during its declared warmup window. But neither
  artifact says so. A0 §1 tabulates Fixture B as `3112 rows · base rate 0.1793 · window 2025-03-03`
  and A0 §9 marks it `P` on rows/target/partition; the implementation report §4 lists Fixture B's
  real-fixture result as `STALE_COMPILED_STUDY` only, omitting the second failure. A0's headline
  Fixture B statistic is therefore a warmup-contaminated pooled number, and any future use of
  Fixture B as a "3112-row" fixture inherits that contamination.
- **Smallest repair:** documentation only — correct A0 §1/§9 and the implementation report to record
  Fixture B's two failures and its in-window population (1092 rows, base rate 0.1621).

### L-series

| # | Finding | Evidence | Repair |
|---|---|---|---|
| **L1** | Spec-less `validate_collection` omits seal/OOS/mixing/identity checks yet `write_dataset_identity` records `validation_passed: true` | `loader.py:408`, `loader.py:589-613`; probe P2b | Record `spec_supplied` and the list of *skipped* checks in `dataset_identity.json` |
| **L2** | Feature contract passes vacuously when the study dir is absent: `declared=[]` ⇒ `feature_order_preserved=True` and `feature_list_hash_matches=True` (`None in {None,None}`) | `loader.py:301-320`; probe P12 | Fail `SCHEMA_MISSING` when `declared_features` is empty or `feature_list_sha256` is `None` |
| **L3** | `collection_identity_sha256` changes when working-tree `study.yaml` changes, though zero collection bytes moved — contradicts A0 §2 rule 2 ("identity is immutable") | `identity.py:162` (`feature_list_sha256` read from current `study.yaml`); probe P13 | Inherited from A0 §2; either source `feature_list_sha256` from the run/compiled artifact, or split "collection identity" from "contract identity" |
| **L4** | Invalid slice names are accepted into the spec and into `analysis_spec_sha256`; they surface only later as a non-derivable table | `spec.py:212`; `slices.py:195-197` | Validate `slices` against `available_slices()` in `parse_analysis_spec` |
| **L5** | `allow_stale_compiled_study` is an escape hatch for check 4a that appears nowhere in A0 §6/§7 | `spec.py:31`, `loader.py:283` | Add it to the A0 contract, or remove it |
| **L6** | `build_arm_table` unconditionally emits the caveat "All arms are scored on the identical evaluation rows" without verifying it | `reporting.py:177-180` | Assert equal length/index across `arm_scores` before emitting the claim |
| **L7** | The `latest` guard is a 4-literal blocklist; A0 §2's alias mechanism ("an alias that resolves to exactly one `run_id` and is recorded alongside it") is unimplemented | `loader.py:113`; probe P1b | Either implement recorded alias resolution or drop the alias language from A0 |
| **L8** | Harness-written artifacts are themselves EOL-nondeterministic: table CSV/JSON, `analysis_context.json`, `dataset_identity.json`, `model_manifest.json` all use text-mode writes ⇒ CRLF on Windows, LF elsewhere | `reporting.py:69-70`, `reporting.py:318`, `loader.py:612`, `modeling.py:351`; measured CR=36/LF=36 on a table JSON | Pass `newline="\n"` (and `lineterminator="\n"` for `to_csv`) |
| **L9** | `load_collection` swallows *all* exceptions reading `observations.parquet` and substitutes an empty frame, so corruption is reported as emptiness | `loader.py:143-146` | Catch narrowly; distinguish `ARTIFACT_UNREADABLE` from `EMPTY_OBSERVATIONS` |
| **L10** | The A0 contract is absent from the implementation worktree (written after base `7cc5e0c`), so the harness cannot be audited self-containedly from its own tree | worktree file listing | Copy the contract into the branch with the implementation |

---

## 3. Control matrix

Legend: **PASS** = control works as contracted (verified) · **WEAK** = present but bypassable or
data-dependent · **FAIL** = demonstrated silent acceptance · **ABSENT** = not implemented.

### A1 — collection loading and identity

| A0 / brief control | Status | Evidence |
|---|---|---|
| No implicit `latest` (literal forms) | PASS | `loader.py:113`; probe P1b |
| Alias resolves to one `run_id` and is recorded | ABSENT | L7 |
| Path traversal rejected | **FAIL** | **H1** — probe P1c |
| Unrelated run substitution detected via pinned identity | WEAK | Works when spec supplied *and* pinned; defeated by H2; false-positives off-platform (M1) |
| 4a stale-compiled vs 4b spec-drift distinguished | PASS | Real Fixture B: 4a FAIL / 4b PASS |
| Historical collection not wrongly rejected | PASS | Fixture B loads; `allow_stale_compiled_study` available (L5) |
| Inconsistent stored run-time contract rejected | PASS | Fixture N → `SPEC_DRIFT` |
| Parquet hashes recomputed vs manifest | PASS | Fixture A verified against A0 values |
| 4-col join not degraded to 3-col | **FAIL** | **H3** — probe P3 |
| Duplicate join keys | PASS | probe P14 (`{'candidates':0,'observations':1}` → fail) |
| Missing targets / empty observations | PASS | Fixture N → `EMPTY_OBSERVATIONS` |
| Reordered features / feature-hash mismatch | PASS (WEAK when study dir absent) | `loader.py:301-320`; L2 |
| Schema surplus/missing | PASS | Fixture N → `SCHEMA_MISSING` (35 features) |
| Cross-study pooling requires explicit contract | **WEAK** | **M7** — unwired, unexported |
| `dataset_identity.json` stable for equivalent data | **FAIL** | **M1** (platform), L3 (working-tree drift) |
| Fail-closed report never progresses to fit/report | **FAIL** | **H2** — probe P2 |
| Outcome columns excluded from features | PASS | Real Fixture A: `[]`; `loader.py:561-567` |

### A2 — specs, slices, metrics

| Control | Status | Evidence |
|---|---|---|
| Unknown spec keys rejected | PASS | probe: top-level + collection both rejected |
| `latest`-style IDs rejected | PASS | probe |
| Implicit imputation rejected | PASS | `missing_values: mean` rejected |
| Undeclared partitions rejected | PASS | `partitions: [oos]` rejected |
| Invalid slices rejected | **WEAK** | **L4** — accepted into spec and hash |
| Tables retain N, filters, identities, definitions, caveats | PASS | `REQUIRED_TABLE_KEYS`; verified on real Fixture A |
| Empty / single-class handled honestly | PASS | `_not_computable` with reason; verified |
| NaN/inf handled honestly | **FAIL** | **M6** — silent null (status ok) *and* uncaught `ValueError` |
| Absent score metrics not shown as measured | PASS | real row keys carry no `roc_auc` at all |
| Slicing cannot silently drop/duplicate rows | **FAIL** | **H4** — probe P4 (30/100 lost) |

### A3 — modeling and thresholds

| Control | Status | Evidence |
|---|---|---|
| Refuses TRAIN+DEV in one arm | **WEAK** | **M3** — guard opt-in on optional `meta` |
| Refuses outcome/target leakage columns | PASS | `modeling.py:188-192`; verified raises |
| Feature reorder handled | PASS | `modeling.py:123-125` reindexes to fitted order |
| Seed / feature order / split policy / params change identity | PASS | in `fit_identity_sha256` payload |
| Library-version change changes identity | **FAIL** | **M2** — recorded but not hashed |
| Identity binds actual training data | **FAIL** | **M2** — n=200 vs n=80 ⇒ same hash |
| Threshold bound to correct population | **FAIL** | **M4** — free-text, default `""`, unverified |
| Refuses to fit when arms undeclared | PASS (`fit_arms`) | `modeling.py:297-311`; `fit_model` is the unguarded primitive by design |
| Prediction identity | PASS | `prediction_identity` hashes rounded scores |

### A4 — context and reporting

| Control | Status | Evidence |
|---|---|---|
| Context references artifacts, does not embed data | PASS | `reporting.py:297-312` — paths + counts only |
| Cannot conceal invalid validation status | **WEAK/FAIL** | **M5** — verdict is copied through, but the completeness gate ignores it |
| Cannot conceal missing caveats | PASS | table caveats aggregated with `[table]` prefix |
| Tables cannot claim metrics when status is not computable | PASS for one-class/empty; **FAIL** for non-finite | **M6** |
| Valid for A0 real fixtures | PASS | end-to-end Fixture A: 6 tables, all reconcile, completeness `[]` |
| Valid for synthetic negative fixtures | PASS | 120 tests |

---

## 4. Test commands and results

All commands run read-only; synthetic fixtures written to a temp directory outside the repo.

```bash
# 1. Reproduce the implementation report's headline claim
cd .claude/worktrees/analysis-harness-a1-a4
python -m pytest scripts/tests/test_analysis_loader.py \
    scripts/tests/test_analysis_spec_slices_metrics.py \
    scripts/tests/test_analysis_modeling.py \
    scripts/tests/test_analysis_reporting.py \
    scripts/tests/test_analysis_reproducibility.py -q
# -> 120 passed in 16.56s        [claim CONFIRMED]

# 2. Adversarial probe suites (scratchpad)
python redteam_probes.py     # P1,P1b,P2,P2b,P3,P4,P6,P7,P8,P9,P11,P12,P13
python redteam_probes2.py    # P5a,P5b,P5c,P1c,P14
python redteam_real.py       # real Fixture A/B/N + end-to-end

# 3. Line-ending / identity facts
git config --get core.autocrlf                                  # -> true
ls .gitattributes                                               # -> absent
git ls-files --error-unmatch runs/<A>/collection/collection_manifest.json   # -> TRACKED
git cat-file -p :runs/<A>/collection/collection_manifest.json    # -> 0 CR bytes, sha 4d2223ba…
# working tree                                                   # -> 93 CR bytes, sha f4f8c027…
```

**Probe results summary**

| Probe | Result |
|---|---|
| P1 traversal to non-existent path | OK — rejected `MissingArtifact` |
| P1b `latest` blocklist scope | INFO — 4 literals only; `LATEST_RUN` loads (L7) |
| **P1c traversal to existing path outside `runs_root`** | **VULNERABLE (H1)** — loaded; identity records basename only |
| **P2 report/spec decoupling** | **VULNERABLE (H2)** — 60 DEV rows returned, `OOS_LOCKED` never fired |
| **P2b unsealed passes spec-less validate** | **VULNERABLE (H2)** — `passed=True`; 4 checks never emitted |
| **P3 4-col → 3-col join** | **VULNERABLE (H3)** — `passed=True`, `failures=[]` |
| **P4 slice row loss** | **VULNERABLE (H4)** — 70 vs 100; completeness `[]` |
| **P5a inf metrics** | **VULNERABLE (M6)** — `status:'ok', value:None` |
| **P5b/P5c inf AUC** | **VULNERABLE (M6)** — uncaught `ValueError`, whole table set aborts |
| **P6 fit identity** | **VULNERABLE (M2)** — different data ⇒ identical hash |
| **P7 fit without meta** | **VULNERABLE (M3)** — mixed TRAIN/DEV fits cleanly |
| **P8 threshold population** | **VULNERABLE (M4)** — `''` accepted, hash emitted |
| **P9 completeness on failed validation** | **VULNERABLE (M5)** — `[]` (complete) |
| **P11 pooling guard** | **VULNERABLE (M7)** — unwired, unexported |
| P12 feature contract w/o study dir | INFO (L2) — two checks pass vacuously |
| P13 identity vs working-tree `study.yaml` | INFO (L3) — identity moved, data did not |
| P14 duplicate observation keys | **OK** — correctly caught |
| Real Fixture A end-to-end | **PASS** — all A0 numbers reproduce; tables reconcile 2002/2002 |
| Real Fixture B | 2 failures: `STALE_COMPILED_STUDY` + **undisclosed `WARMUP_LEAKAGE` 2020/3112 (M8)** |
| Real Fixture N | 4 failures incl. `EMPTY_OBSERVATIONS` — as contracted |

---

## 5. Line-ending policy (required assessment)

**The claim under review** (implementation report §1): *"A byte-level seal check run inside the
worktree reports almost every sealed file as drifted. That is a checkout artifact, not drift …
the files are identical ignoring CR."*

**Assessment: the observation is correct, the generalization is not.** "Ignore CR" must **not**
become a blanket identity rule. Line endings are harmless in one place here and load-bearing in
three others. The correct policy is per-artifact-class:

| Artifact class | Tracked? | Normalized by `autocrlf`? | Current hashing | Can EOL alter identity? | Correct policy |
|---|---|---|---|---|---|
| `*.parquet` (candidates/observations) | No (gitignored) | No (binary) | raw bytes — `sha256_file` | **No** | **Keep raw-byte hashing.** Correct as-is. |
| `runs/**/*.json` manifests | **Yes** | **Yes** | raw bytes — `sha256_file` | **YES — measured** | **Hash parsed canonical JSON**, not bytes |
| `study.yaml` → `spec_sha256` | Yes | Yes | `StudySpec.model_validate(...).compute_sha256()` (`research/schemas/study_spec.py:335-339`) | **No** — hashes the parsed model | Correct as-is; this is the pattern to copy |
| Harness-written artifacts (`analysis_context.json`, tables, `dataset_identity.json`, `model_manifest.json`) | n/a | n/a | text-mode writes | **YES — measured (L8)** | Write with `newline="\n"` |
| Sealed source files (`utils/…`, `backtests/…`) | Yes | Yes | collector seal (out of scope) | Yes | See below |

**Answers to the four specific questions:**

1. **Dataset/analysis identities — YES, EOL alters them.** `collection_manifest_sha256` is a raw byte
   hash of a git-tracked JSON file (`identity.py:161`); measured `f4f8c027…` (Windows/CRLF) vs
   `4d2223ba…` (repo blob/LF). It propagates into `collection_identity_sha256` and therefore into
   `IDENTITY_MISMATCH`, `dataset_identity.json`, and every artifact that embeds the identity.
2. **Generated report hashes — YES.** Every harness artifact is written in text mode; measured CRLF on
   Windows (L8). Any downstream hash-of-artifact comparison is platform-dependent.
3. **Source/artifact lookup — NO.** Lookup is by path; nothing resolves by content hash.
4. **Cross-worktree reproducibility — YES, but not between *these two* worktrees.** Both are Windows
   checkouts with `autocrlf=true`, so both produce `f4f8c027…` (measured identical). The break appears
   on the first Linux/macOS/CI checkout or on `core.autocrlf=input`. This is latent today and will
   surface silently as a false `IDENTITY_MISMATCH` the moment analysis runs anywhere but this machine.

**Recommended narrowly scoped policy:**

> Identity over **generated binary data** (`*.parquet`) is a raw byte hash — no normalization, ever.
> Identity over **structured text artifacts** (JSON/YAML manifests) is a hash of the **parsed
> canonical form** (`canonical_sha256`), which is invariant to line endings, key order and
> indentation, and which the repo already uses for `spec_sha256`. All harness-written artifacts are
> emitted with `newline="\n"`. A `.gitattributes` (`runs/** -text`, `*.json text eol=lf`) is added as
> defence in depth so tracked manifests are byte-identical in every checkout.
>
> For the **collector seal**, "identical ignoring CR" is acceptable **only** if the seal contract
> explicitly declares an EOL-normalizing canonicalization for text members. Until it does, a seal
> comparison performed in a CRLF worktree is *inconclusive*, not *passing* — and it must be
> evaluated in the tree whose EOL convention the seal was computed under, exactly as the
> implementation report did. Do not weaken the seal comparator to reach a green result.

---

## 6. Separate status

### HARNESS_NOT_READY

Four demonstrated silent-acceptance defects (H1–H4), one in each category the governing question
names. The architecture, the check ordering, the fail-closed design, the 4a/4b split, the
measured-value reporting and the negative-fixture coverage are all sound and worth keeping — this is
a repair list, not a rewrite.

**Promotes to `HARNESS_READY` when H1–H4 and M1–M6 are fixed and re-tested**, with new regression
tests that assert each probe's failure (traversal rejected; report/spec binding enforced; declared
join key fully asserted in both frames; `Σ n == N` reconciliation; canonical-JSON manifest identity;
fit identity bound to data; partition guard mandatory; threshold population derived; completeness
reads the verdict; non-finite metrics not computable).

### NOT_AUTHORIZED — real analysis

This is **independent of** the harness defects and would hold even at `HARNESS_READY`. The
implementation report is candid and correct on this point, and I confirm its prerequisite list:

| # | Prerequisite | Status |
|---|---|---|
| 1 | **Collector reseal** (`REQUIRES_INDEPENDENT_RED_TEAM_RESEAL`) — collect mode verifies the seal, so no new collection can be produced at all | **OPEN** — blocks everything below |
| 2 | **A TRAIN-stage collection** — all 23 runs on disk are `stage: day` smokes; largest real one is 3,112 rows (of which, per M8, only 1,092 are in-window) | **OPEN** |
| 3 | **OOS unlock token** for the study under analysis | **OPEN** — only the negative direction is testable; the positive path is proven solely with an injected verifier |
| 4 | **Pinned `collection_identity_sha256`** in the analysis spec | **OPEN** — the shipped example deliberately leaves it unset; blocked in practice by M1 until identity is platform-stable |
| 5 | **Predeclared model arms** in the research decision contract | **OPEN** |
| 6 | Resolve Fixture B's `STALE_COMPILED_STUDY` if a second clean positive fixture is wanted | **OPEN** — and now also its `WARMUP_LEAKAGE` (M8) |
| 7 | Promote `DEFAULT_METADATA_COLUMNS` to one shared constant | **OPEN** — not blocking; latent drift risk |

**Two distinctions worth stating plainly for the record:**

- *No research conclusion is at risk from this review.* I verified the report's out-of-scope claims:
  no real model was trained, no threshold derived from real data, no DEV/OOS data accessed, and the
  shipped spec declares no `model_arms`, so it structurally cannot fit or freeze anything.
- *H2 does not mean DEV data has been read.* It means the control that would prevent it is
  non-functional **before** any TRAIN collection exists. Fixing it now, while there is nothing to
  leak, is the cheap moment.

---

## 7. Minimal remediation list

Ordered by dependency. Nothing here requires touching the collector, the backtest harness, or any seal.

**Blocking (H) — required for `HARNESS_READY`:**

1. `identity.py:123` — reject `run_id` containing `/`, `\`, `..`; assert
   `run_dir.resolve().parent == runs_root.resolve()`; record the resolved path in the identity. *(H1)*
2. `loader.py` — add `analysis_spec_sha256` + `spec_supplied` to `ValidationReport`; make
   `get_features_targets_metadata` reject a report not produced with the same spec. *(H2)*
3. `loader.py:82,364` — resolve the declared join key from metadata alone; assert every declared key
   column is present in **both** frames → `JOIN_KEY_MISSING`. *(H3)*
4. `reporting.py:117,322` — emit an `unassigned` row + caveat when `Σ group n < N`; add the
   reconciliation to `check_report_completeness`. *(H4)*

**Required before real analysis (M):**

5. `identity.py:161` — hash parsed canonical JSON for manifest identity; add `.gitattributes`;
   write all artifacts with `newline="\n"`. *(M1, L8)*
6. `modeling.py:96` — add `n_rows`, `library_versions` and a content hash of `X`/`y` to
   `fit_identity_sha256`. *(M2)*
7. `modeling.py:194` — make partition provenance mandatory for a fit. *(M3)*
8. `modeling.py:244` — require a non-empty `population`, derived from `meta['_partition']`. *(M4)*
9. `reporting.py:331` — completeness must read `validation.passed` and seal status. *(M5)*
10. `metrics.py:45,125` — non-finite ⇒ `not_computable`; catch sklearn `ValueError` in `_auc_like`. *(M6)*
11. `loader.py:616` / `__init__.py` — export `assert_single_study`; document the caller obligation. *(M7)*
12. **Documentation only:** correct A0 §1/§9 and the implementation report to record Fixture B's
    `WARMUP_LEAKAGE` (2020/3112) and its in-window population (1,092 rows, base rate 0.1621). *(M8)*

**Schedule (L):** L1–L7, L9, L10 as listed in §2.

---

*No findings were fixed. No implementation file, seal, run artifact, audit, or study output was
modified. Scratch fixtures were written only to the session scratchpad and a system temp directory.*
