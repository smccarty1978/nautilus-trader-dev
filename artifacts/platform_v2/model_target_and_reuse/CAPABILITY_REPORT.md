# Capability report — `model_target_and_reuse`

Chore branch `chore/model_target_and_reuse` from main `ff47868d`, for `studies/nq_mtf_structural_predictive_ranking`.
No collector ran over 2023 or 2024, no persisted observation row was changed, and 2025/2026 were never touched.

## Phase 1 — feasibility (`phase1_feasibility.json`)

The question was not "do the hashes differ" but "could the delta have changed any byte of the persisted partitions".

| | |
|---|---|
| recorded atlas replay plan | `d917443a…` |
| current replay plan | `d917443a…` — **identical** |
| recorded replay closure | `16aa9039…` |
| current replay closure | `2e30c4f7…` (differs) |
| closure **membership** | identical, 140 files both |
| replay-closure files differing in content | **exactly one**: `research_workflow/grammar/spec.py` |

`spec.py` is on the replay path only through `features/trackers/host_bindings.py:172,269`, which import
`duration_seconds`; that function's source is unchanged. The diff is confined to `ModelSpec`, a compile-time
schema class the replay never touches.

**Empirical proof, which is what the verdict rests on:** re-replaying the recorded smoke day (2023-10-02) under
the current closure with the requesting study's plan produced **byte-identical** output to the run recorded under
the recorded closure — candidates `4ca2e159…`, observations `e79814a8…`, 213,431 bars, 558 rows. So the answer to
§4 is **NO, the delta cannot have changed a persisted byte**, and it is proved mechanically, not argued.

One nuance worth recording: a standalone one-day replay is **not** byte-equal to the same day sliced out of a
year-long run — `atr_15m` legitimately differs because the year run has months of history behind it. The
equivalence test is therefore like-for-like (bounded replay vs bounded replay), never day-vs-slice.

## Capability A — `model.target`

`model.target: {id, expr}` derives the fit label from columns the collected frame already carries, in the bounded
`analysis.derive.columns` grammar (parsed; never `eval`/`exec`).

- Compile proves every referenced column against the plan, refuses an unknown column and a syntax error, and records the canonical AST hash (`expression_sha256`) in the modeling contract.
- **Forward-outcome columns are legitimate TARGET inputs** — a label resolves after its entry by definition — and remain forbidden as model FEATURES. The same column, two answers, both enforced (`test_target_may_read_outcome_columns_but_features_may_not`).
- The expression must resolve to a boolean; `{0, 1, null}` with explicit null propagation (`MODEL_TARGET_NOT_BINARY` otherwise).
- Derivation happens after collection/reuse, on the merged frame; it cannot alter a persisted partition.
- The fit receipt records `eligible_n`, `positive_n`, `negative_n`, `null_n`.

Proved on the real frame: `terminal_gross_pnl_atr > 0` gives **85,458 positive / 176,094 negative / 445 null of 261,997 rows**. `terminal_gross_pnl_atr` itself was not modified.

## Capability B — vacuous fit

**Correction to the record.** My previous session reported that a single-class target would "silently write zero
models and report PASS". That was wrong: `CELL_FINAL_FIT_DEGENERATE` already hard-failed such a cell at main
`ff47868d`. I had inferred a `continue` from an elided grep line instead of reading the code.

What this chore adds is earlier and clearer failure, plus a backstop:

- `MODEL_TARGET_SINGLE_CLASS` — names the target and its class counts before any cell is fitted;
- `MODEL_FIT_PRODUCED_NO_MODELS` and `MODEL_FIT_INCOMPLETE` — an empty or short model set can never be a PASS;
- `MODEL_TARGET_UNRESOLVED`, `MODEL_TARGET_NOT_BINARY`, `MODEL_TARGET_IN_FEATURE_SURFACE`, `MODEL_FEATURE_COLUMNS_UNBOUND`.

Regression tests pin that an all-positive target cannot pass, by either route.

## Capability C — re-attestation (`research_workflow/partition_reattest.py`)

`attestation_permits` excuses **exactly two** key components and nothing else:

| component | excused only when |
|---|---|
| `replay_closure_composite_sha256` | closure **membership** identical **and** a bounded replay under the current closure reproduced a reference replay under the recorded closure **byte for byte** |
| `authorization_sha256` | the authorised **year roles** are identical and the only differing fields are `study_id` / `study_path` |

The second was unavoidable and is not a loophole: `authorization_sha256` hashes the study id and path together
with the year roles (`lifecycle_v2.py:392-395`), so a partition produced by another study can never match it even
when the authorised years are identical. What authorises a replay is the year roles; which study ran it is
provenance. Widened years are refused (`REATTEST_AUTHORIZATION_YEARS_DIFFER`).

Everything else still matches exactly — replay plan, dataset, partition interval, replay-time data files — and the
artifact-bytes check still runs on every reuse. Tests pin that a differing plan, dataset or interval is refused,
that a missing or failed byte-equality proof is refused, that changed closure membership is refused, and that no
attestation means no reuse.

The receipt (`artifacts/partition_reattestation.json`) answers all four provenance questions: which historical
partition was used (source study, path, original `plan_sha256`, seal, parquet hashes, row counts, original
`elapsed_s`), under which closure it was produced, under which closure it was re-attested, and why replay was
unnecessary.

## Phase 3 — acceptance on the real atlas partitions (`phase3_acceptance.json`)

| step | result |
|---|---|
| replay plan | `d917443a…`, identical to the atlas |
| re-attestation | both partitions, **80 s** (one bounded day) |
| reuse verdict | `train-2023` and `train-2024` both **`REUSABLE_BY_CLOSURE_ATTESTATION`**; `would_reuse: [train-2023, train-2024]` |
| partitions untouched | manifests byte-identical to the atlas's, original `plan_sha256` `4e7538b4` / `c408c4d9`, original `written_at_utc` and `elapsed_s` preserved |
| merge | 261,997 rows, years `[2023, 2024]`, 11 s |
| target | `terminal_gross_pnl_atr > 0` → 85,458 / 176,094 / 445 |
| fit | 4 arms × cell `t0`, **`final_fit_rows` 7,475 = the 2023 T0 rows**, `tuning_years [2023]`, 13.5 s |
| max training year | **2023**; 2024 not in the fit |
| freeze → score | freeze, then 500 **2024** rows scored after freeze, model authenticated, lineage `train_years [2023]`, `validation_years [2024]`, 78 ordered inputs |

**Total replay cost: two bounded days (~160 s)** — the re-attestation day and the study's own smoke day, which the
reuse gate requires. Neither year was replayed; the alternative was ~2 h.

## Finding for the study session (not a blocker)

`validation.final_train_validation_years: [2024]` makes the fit stage compute a `final_validation` metric on the
2024 rows (n = 7,047) **at fit time, before freeze**. With no search and no selection it influences nothing, but
the study's frozen contract says 2024 is scored once after the model is frozen. To keep 2024 completely dark
until freeze, declare `final_train_validation_years: []` and score 2024 through the post-freeze path only. That
is the study owner's call; it changes no capability.

## Not done, recorded

- `duration_seconds` still lives in `spec.py`; moving it would prevent the next occurrence but would not restore
  these partitions (it changes the closure file list). Explicitly out of scope per the brief.
- The registry `content_sha256` (which includes test-file attribution) remains inside the reuse key. This chore's
  test file does not perturb it; verified `88bebf75…` unchanged.
