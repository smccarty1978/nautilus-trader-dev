# Analysis Harness — A1–A4 Implementation Report

**Branch:** `worktree-analysis-harness-a1-a4` · **Worktree:** `.claude/worktrees/analysis-harness-a1-a4`
**Base commit:** `7cc5e0c` · **Date:** 2026-08-17
**Status:** `ANALYSIS_HARNESS_MVP_FROZEN`. Red Team findings H1–H4, M1–M8, N1, L2 and L10 remediated
(L6/N3 deferred — see §4b); 187 tests pass. **No real study model trained, no threshold derived from
real data, no DEV/OOS accessed, no research conclusion produced.** Further changes require a
demonstrated defect or a concrete requirement from a real study.

---

## 1. Scope and isolation

Built to `ANALYSIS_HARNESS_A0_CONTRACT.md`. The change surface is **additive only** — this workstream
adds 19 files and modifies none:

```
ANALYSIS_HARNESS_A0_CONTRACT.md            <- landed here by L10
ANALYSIS_HARNESS_IMPLEMENTATION_REPORT.md
analyses/fixture_a_structural_smoke.yaml
research/analysis/{__init__,errors,identity,loader,spec,slices,metrics,modeling,reporting}.py
scripts/tests/analysis_fixtures.py
scripts/tests/test_analysis_{loader,spec_slices_metrics,modeling,reporting,
                             reproducibility,redteam_regressions}.py
```

The freeze commit on this branch contains these files and nothing else — no collector, backtest,
audit-governance, seal, or study-output file is part of it.

**L10 — the branch is self-contained.** `ANALYSIS_HARNESS_A0_CONTRACT.md` previously existed only in
the main working tree, so the branch carried implementation without the contract governing it. The
contract now sits in the same commit as the code it governs, byte-identical to the version on the
backtest branch (sha256 `c33d2fb8aa8d5fbd…`, 35,694 bytes); its semantics are unchanged. It contains
no threshold or completeness clause that the M4/N1 closeout would have made stale.

Nothing in the backtest harness, the collector, `audit/`, seal files, or existing run artifacts was
touched. `research/analysis/` imports neither `backtests.nt_runtime` nor any collector module, so it
cannot perturb the collector's sealed execution closure.

> **Note on seal verification in this worktree.** A byte-level seal check run *inside* the worktree
> reports almost every sealed file as drifted. That is a checkout artifact, not drift: Windows
> `core.autocrlf` gives the worktree CRLF line endings. Verified — e.g. `utils/runner/data.py` has 0 CR
> bytes in the main tree and 36 here, and the files are **identical ignoring CR**. Seal status must be
> evaluated in the main working tree, where it remains exactly as the backtest-harness report left it:
> `REQUIRES_INDEPENDENT_RED_TEAM_RESEAL`, unchanged by this work.

---

## 2. Files added

| File | Phase | Purpose |
|---|---|---|
| `research/analysis/__init__.py` | — | Package surface |
| `research/analysis/errors.py` | — | 26 failure modes from A0 §7, one class each, all fail-closed |
| `research/analysis/identity.py` | A1 | `CollectionIdentity`, `dataset_identity.json`, canonical hashing, metadata fallback and outcome-column constants |
| `research/analysis/loader.py` | A1 | `load_collection` / `validate_collection` / `get_features_targets_metadata`, 20 ordered checks |
| `research/analysis/spec.py` | A2 | `AnalysisSpec` schema, strict parsing, `analysis_spec_sha256` |
| `research/analysis/slices.py` | A2 | direction, year, partition, maturity, regime, session, decile |
| `research/analysis/metrics.py` | A2 | 11 canonical metrics with safe empty/one-class/NaN behaviour |
| `research/analysis/modeling.py` | A3 | Thin sklearn/LightGBM wrappers + full provenance, A/B/C arms, threshold freeze |
| `research/analysis/reporting.py` | A4 | `StandardTable`, standard table set, `analysis_context.json`, completeness check |
| `analyses/fixture_a_structural_smoke.yaml` | A2 | The first real analysis spec (descriptive only; declares no arms) |
| `ANALYSIS_HARNESS_A0_CONTRACT.md` | — | The governing contract, landed in this branch (L10) |
| `scripts/tests/analysis_fixtures.py` | tests | Synthetic collection builder + real-fixture resolver |
| `scripts/tests/test_analysis_*.py` (6 files) | tests | 187 tests, incl. `test_analysis_redteam_regressions.py` |

---

## 3. Supported interfaces

### A1 — loader

```python
load_collection(run_id, *, runs_root=Path("runs"), studies_root=Path("studies")) -> Collection
validate_collection(collection, spec=None, *, oos_token_verifier=None) -> ValidationReport
get_features_targets_metadata(collection, spec, report) -> (X, y, meta)
write_dataset_identity(collection, report, out_path, spec=None) -> dict
assert_single_study(collections) -> None
```

`load_collection` raises only `MISSING_ARTIFACT`; everything else is reported by
`validate_collection`, so a broken collection produces a report rather than an import-time crash.
`get_features_targets_metadata` refuses to run without a passing report.

Checks implemented (each records its **measured** value, not just a verdict): artifacts present,
status SUCCESS, both parquet hashes recomputed, **4a study-dir self-consistency** vs **4b
collection-vs-compiled-contract**, feature order, ordered-feature hash, surplus/missing columns,
duplicate columns, empty observations, target present, join key resolved, join-key uniqueness, join
row loss, manifest row counts, warmup leakage, prohibited partitions, partition mixing, OOS lock,
seal policy, and four spec-binding checks (identity, study, feature hash, target horizon).

### A2 — spec, slices, metrics

```python
parse_analysis_spec(payload) / load_analysis_spec(path) -> AnalysisSpec   # .analysis_spec_sha256
build_slices(meta, names) -> {name: SliceResult}      # + slice_decile(values, n_buckets)
metrics: sample_count, positive_rate, roc_auc, pr_auc, brier, win_rate,
         expected_value, excursion(mfe|mae), drawdown, quantiles
         classification_bundle(...) / economic_bundle(...)
```

Every metric returns a `MetricResult`, never a bare float, carrying `status`, `reason`, `n`,
`n_missing` and its own definition.

### A3 — modeling

```python
fit_model(X, y, *, arm, estimator, seed, hyperparameters, split_policy,
          dataset_identity_sha256, analysis_spec_sha256, meta) -> FittedModel
fit_arms(X, y, spec, ...) -> {arm: FittedModel}          # declared A/B/C
score_and_record(model, X) -> (scores, prediction_sha256)
freeze_threshold(scores, y, *, meta, method, value, population=None, ...) -> dict
write_model_manifest(models, out_path) -> dict
```

Estimators: `logistic_regression`, `gradient_boosting`, `lightgbm`. A fit records ordered features,
dataset identity, analysis-spec identity, split policy, seed, library versions, hyperparameters,
model checksum, prediction identity, and a `fit_identity_sha256`.

`meta` carrying `_partition` is required by **both** `fit_model` and `freeze_threshold`: a threshold is
a fitted parameter and follows the same partition discipline as a fit. `population` survives only as an
optional caller assertion that is cross-checked against the derived label; it is never authoritative.

### A4 — reporting

```python
build_standard_tables(y, meta, *, scores, arm_scores, arm_provenance, ...) -> {name: StandardTable}
build_arm_table / build_slice_table / build_decile_table
build_analysis_context(...) -> dict ;  write_analysis_context(ctx, path)
check_report_completeness(ctx, tables) -> [problems]
```

Standard set: `by_arm`, `by_direction`, `by_year`, `by_partition`, `by_maturity`, `by_session`,
`by_regime`, `by_decile`. Every table records sample size, filters + slice definition, dataset
identity, analysis-spec identity, metric definitions, and caveats.

---

## 4. Tests and results

```
pytest scripts/tests/test_analysis_loader.py
       scripts/tests/test_analysis_spec_slices_metrics.py
       scripts/tests/test_analysis_modeling.py
       scripts/tests/test_analysis_reporting.py
       scripts/tests/test_analysis_reproducibility.py
       scripts/tests/test_analysis_redteam_regressions.py
→ 187 passed, 0 failed, 0 skipped in 5.92s
```

Baseline before the M4/N1 patch was 174 passed / 0 failed; the +13 are the M4 and N1 regressions.

| Suite | Tests | Covers |
|---|---:|---|
| `test_analysis_loader.py` | 41 | invalid identities, drift distinction, schema, join failures, partitions, extraction, **5 real-fixture tests** |
| `test_analysis_spec_slices_metrics.py` | 39 | spec rejection matrix, slice derivation/degeneracy, metric edge cases |
| `test_analysis_modeling.py` | 19 | provenance, determinism, guardrails, A/B/C arms, threshold freeze |
| `test_analysis_reporting.py` | 15 | table completeness, caveats, context packet, **end-to-end on real Fixture A** |
| `test_analysis_reproducibility.py` | 6 | equal identity → equivalent artifacts; changed identity visibly different |
| `test_analysis_redteam_regressions.py` | 67 | one test per Red Team probe (H1–H4, M2–M7, **M4**, **N1**); every one passed *before* its fix |

### Real-fixture coverage (not synthetic)

The A0 fixtures' parquet is gitignored and therefore absent from a worktree checkout. The test
resolver walks up from `.claude/worktrees/<name>` to the owning repository; all real-fixture tests
**executed and passed** rather than skipping.

| Assertion proved against real data | Result |
|---|---|
| Fixture A loads, sealed, 60 features, `(2002, 73)`, metadata **declared** | ✅ |
| Fixture A join key is the 4-column form; TRAIN partition = 2002 rows | ✅ |
| Fixture B is **unsealed**, 25 features, metadata **fallback**, join key has **3** columns without `regime_direction` | ✅ |
| Fixture B is a real on-disk `STALE_COMPILED_STUDY`, while 4b (collection-vs-compiled) still passes | ✅ |
| Fixture B **also** fails `WARMUP_LEAKAGE`: 2,020 of 3,112 rows precede its declared window | ✅ |
| Fixture N: 717 candidates, `observation_cols == 0` → `EMPTY_OBSERVATIONS` | ✅ |
| Pooling A and B raises `CROSS_STUDY_POOLING` | ✅ |
| End-to-end A: load → validate → extract → tables → context, completeness clean | ✅ |

### Negative coverage (synthetic, so no malformed collection lives in the repo)

`latest`-style run ids · unknown run · identity mismatch · study mismatch · corrupted parquet hash ·
unsealed default-blocked and explicitly-allowed · non-SUCCESS status · stale-compiled vs spec-drift ·
feature-order shuffle · surplus column · spec feature-hash mismatch · empty observations · missing
target · duplicate join keys · join row loss · shorter join key · prohibited-year rows ·
partition mixing · DEV without token · DEV with token · warmup leakage · cross-study pooling ·
extraction without validation · extraction after failed validation · outcome-as-feature.

### Two behaviours worth a reviewer's attention

**Score metrics are omitted, not nulled, when no scores exist.** A table built without predictions has
no `roc_auc` key at all. An absent column is honest; a null column invites being read as "measured and
undefined". My first draft of the end-to-end test asserted the opposite and failed — the test now pins
the intended behaviour.

**One-class groups refuse rather than return a number.** At these sample sizes a direction or maturity
group is easily single-class; the row carries `roc_auc: null`, `roc_auc_status: "not_computable"`, and
a reason.

---

## 4b. Red Team remediation status

Findings from the independent Red Team review (2026-08-16). Each fixed item has a named regression
test in `test_analysis_redteam_regressions.py`.

| # | Finding | Status | Control now in place |
|---|---|---|---|
| H1 | `run_id` path traversal escaped `runs_root` | FIXED | `run_id` must be a plain directory name; `INVALID_RUN_ID` |
| H2 | A spec-less / unsealed `ValidationReport` authorised a DEV extraction | FIXED | Report is bound to its `AnalysisSpec`; spec-less checks are recorded as skipped |
| H3 | A declared 4-column join key silently degraded to 3 | FIXED | Declared key enforced, never intersected |
| H4 | A slice table dropped 30 of 100 rows and reported "complete" | FIXED | Every input row assigned or reported as `unassigned`; completeness reconciles Σn vs `n_input_rows` |
| M1 | Collection identity was not canonical | FIXED | Canonical JSON hashing |
| M2 | Two fits on different populations shared a fit identity | FIXED | Identity binds measured X/y content hashes + library versions |
| M3 | A fit without partition provenance proceeded silently | FIXED | `meta._partition` required, or an explicit recorded `SplitPolicy` opt-out |
| **M4** | **A threshold could be frozen with a caller-declared or mixed population** | **FIXED (this pass)** | `meta` mandatory; population *derived* from `_partition`; mixing refused; `population` is a cross-check only |
| M5 | Completeness returned `[]` for a failed, unsealed validation | FIXED | Reads the verdict, not the presence of a verdict field |
| M6 | Non-finite metrics reported `ok` / aborted the table build | FIXED | Per-group `not_computable` status with a reason |
| M7 | The cross-study pooling guard was unexported | FIXED | `assert_single_study` exported and tested |
| M8 | Fixture B's warmup contamination was undocumented | FIXED | §6 prerequisite 6 records 1,092 in-window rows at base rate 0.1621 |
| **N1** | **Completeness validated a table set different from the packet's own** | **FIXED (this pass)** | Table-name identity plus per-table reconciliation of `slice`, `n_groups`, `total_sample_count`, `n_input_rows`, `reconciles_rows`, `unassigned_rows` |
| L2 | Empty feature contract passed | FIXED | Fails closed |
| L10 | Contract absent from the implementation branch | FIXED (this pass) | Contract landed in the worktree, byte-identical |

### M4 — what changed

`freeze_threshold` previously accepted `population="train"` with `meta=None` and recorded
`derivation_population_source="caller_declared"`, so DEV rows could be labelled TRAIN by *omitting*
provenance — the bypass cost one keyword argument. It also accepted 50 train + 50 dev rows and recorded
`derivation_population="dev+train"`, naming the contamination instead of refusing it.

Now: `meta` is required (its `None` default exists only so the failure carries
`PARTITION_PROVENANCE_MISSING` rather than a bare `TypeError`); a missing `_partition` column, an
all-null one, or a length mismatch against the scores blocks; more than one partition raises
`PARTITION_MIXING`; a single partition is derived and recorded with
`derivation_population_source="derived_from_meta_partition"`. Deriving `"dev"` is mechanically allowed —
this function reports what the rows *are*; whether such a freeze is authorised is spec and seal policy,
which is deliberately not owned here. The threshold identity binds the derivation population, its
source, the row count and the threshold inputs.

### N1 — what changed

`check_report_completeness` iterated only over the `tables` argument, so a context built from six
tables over 120 rows was reported complete when handed `{}`, or when handed unrelated tables over 30
rows. A check that derives its own scope from its argument cannot detect that the scope is wrong. The
gate now requires `set(context["tables"]) == set(tables)` and reconciles each table's recorded summary
against the object supplied. `build_analysis_context` records `n_input_rows`, `reconciles_rows` and
`unassigned_rows` per table so that reconciliation has something to bind to.

### Deferred — not fixed in this pass

| # | Finding | Disposition |
|---|---|---|
| L6 | `build_arm_table` emits the "all arms scored on identical evaluation rows" caveat unconditionally, even when arm score lengths differ | **Backlog.** Classified LOW and explicitly retained as deferred by the Red Team; unchanged here. |
| N3 | — | Deferred with L6; not addressed in this pass. |

---

## 5. Contract decisions worth flagging

1. **`DEFAULT_METADATA_COLUMNS` is duplicated** in `research/analysis/identity.py` rather than imported
   from `backtests/nt_runtime/output_manager.py`, because that module is inside the collector's sealed
   closure and importing it would couple the analysis harness to sealed code. A0 blocker #5 already
   recommends promoting this list to one shared constant; until then the duplication is deliberate and
   documented at the definition site.
2. **The OOS unlock check is injected** (`oos_token_verifier`) rather than importing
   `scripts.generate_oos_unlock` directly, so validation stays testable in both directions and the
   analysis harness does not depend on a sealed script. Production callers pass
   `verify_oos_unlock_token`.
3. **Feature-hash verification accepts the collector's hashing convention** (`json.dumps` default
   separators), which is what `study.yaml:feature_list_sha256` actually records. Both fixtures verify
   against it.
4. **`validate_collection` returns a report; it does not raise.** `report.raise_if_failed()` converts
   the first failure into its typed exception. This keeps "tell me everything that is wrong" and "stop
   now" as separate operations.

---

## 6. Exact prerequisites before real TRAIN/DEV/OOS analysis

The harness is complete; the **data and authorization are not**. In dependency order:

| # | Prerequisite | Why it blocks | Owner |
|---|---|---|---|
| 1 | **Collector reseal** — independent causal + contract audits → status ingestion → seal → bounded smoke → smoke validation | Collect mode verifies the seal before running, so **no new collection can be produced at all** until this completes. Everything below depends on it. | Independent Red Team |
| 2 | **A TRAIN-stage collection** | All 23 collections on disk are `stage: day` smokes; the largest real one is 3,112 rows — of which only **1,092 are in-window**, the other 2,020 being warmup leakage (see #6). Partition rules are unit-tested against synthetic timestamps but have never been exercised on multi-year data, and no model fitted on 2,002 single-day rows means anything. | Collector, post-reseal |
| 3 | **OOS unlock token** for the study under analysis | `partitions: [dev]` fails `OOS_LOCKED` without one. Only the negative direction is currently testable; the positive path is proven only with an injected verifier. | Study owner |
| 4 | **A pinned `collection_identity_sha256` in the analysis spec** | The shipped example deliberately leaves it unset so the file survives re-capture. A real analysis must pin it, or `IDENTITY_MISMATCH` cannot fire. | Analysis author |
| 5 | **Predeclared model arms** for any A/B/C claim | `fit_arms` refuses to run without them — an arm comparison invented after seeing results is not a predeclared comparison. A0 names the intended `A = frozen Top-25 / B = + structural / C = + rolling-productivity` ablation. | Research decision contract |
| 6 | **Resolve Fixture B's `STALE_COMPILED_STUDY` _and_ its `WARMUP_LEAKAGE`** if a second clean positive fixture is wanted | Fixture A is currently the **only** collection passing both 4a and 4b. Recompiling B changes its contract hash and would then fail 4b against its existing collection, so this needs a decision plus a fresh collection, not a mechanical fix. Separately, check 14 finds that **2,020 of B's 3,112 rows (65%) were emitted during its declared warmup window** (2025-02-26 .. 2025-02-28, window `2025-03-03`). Its in-window population is **1,092 rows at base rate 0.1621**; the previously quoted "3,112 rows · 0.1793" is a warmup-pooled figure and must not be used. | Study owner |
| 7 | **Promote `DEFAULT_METADATA_COLUMNS` to one shared constant** | Two copies can drift. Not blocking, but it is a latent correctness risk for every study that declares no `metadata_columns`. | Whoever owns `output_manager.py` (post-reseal) |

**Until #1 and #2 are satisfied, any run of this harness on real data is descriptive infrastructure
validation only and must not be presented as a research result.** The shipped example spec encodes
that: it declares no model arms, so it cannot fit a model or freeze a threshold.

---

## 7. Out of scope — not done

- No real study model trained; every fit in the tests is on synthetic data.
- No threshold derived from real data.
- No OOS/DEV data accessed; the DEV path is exercised only with an injected test verifier.
- No research conclusion drawn, and no existing conclusion altered.
- No `scripts/run_analysis.py` CLI — A4 delivers the library surface; a CLI belongs with A5 adoption.
- No changes to collector, backtest harness, seals, audits, or existing run artifacts.
- Not pushed; the freeze commit sits on `worktree-analysis-harness-a1-a4` locally.

---

## 8. Freeze

`ANALYSIS_HARNESS_MVP_FROZEN` — recorded against a single commit on
`worktree-analysis-harness-a1-a4` containing the contract, the implementation and the tests together.

| Freeze condition | State |
|---|---|
| Contract + implementation + tests committed together | ✅ one commit, 19 files, nothing else |
| Full suite green on the committed tree | ✅ 187 passed, 0 failed |
| Fixture A preserved | ✅ 2,002 rows · base rate 0.3492 · 60 features · 4-column join key · six tables reconciling 2002/2002 · completeness `[]` |
| Fixture B still negative | ✅ `STALE_COMPILED_STUDY` + `WARMUP_LEAKAGE`; 2,020 of 3,112 rows out of window → 1,092 in-window at base rate 0.1621 |
| Worktree clean | ✅ `git status --porcelain` empty |

No fixture data was modified. The harness is infrastructure only: it has produced no research result,
and running it on the fixtures is structural validation, not analysis.

Future modification requires a demonstrated defect or a concrete requirement from a real study — not a
refactor, not a feature added on speculation. The deferred items (L6, N3 in §4b) stay deferred until
one of those two conditions is met.
