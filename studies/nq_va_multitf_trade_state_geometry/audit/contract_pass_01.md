# Contract audit — pass 01 — nq_va_multitf_trade_state_geometry

Packet `f4bff7576fdf2f96`, plan `82b230f28f71c69c`, spec `71754d05046db119`, execution composite
`346c71526660948d`, registry `888bda0992e9461f`. Tests 158 passed / 0 failed.

---

## Binding completeness — CLEAR

28 declared primitives, **28 bound, 0 unbound**: 8 trackers and 20 feature instances. Each maps to
exactly one runtime implementation.

* 4 × `tracker.regime.dual_ema` → `features.trackers.host_bindings.DualEmaRegimeBinding`
  (1m / 5m / 15m / 1h, identical parameters `short_period 3`, `long_period 9`, `atr_period 14`).
* 4 × `tracker.regime.excursion` → `RegimeExcursionBinding` (one per timeframe).
* 20 feature instances → registered adapters; no instance is declared that a
  `RuntimeProviderAdapter` cannot render, so there are no silent nulls from an unbindable
  provider.

`instruments`: NQ only, `NQ_1S_V2_GLOBEX`, dataset digest `9e7aecb7a2910b44`, role execution.

## Chronology and year roles — CLEAR

`train: [2023]`, `dev: [2024]`, `prohibited: [2025, 2026]`, `diagnostic: []`. The four role sets
are pairwise disjoint and no year carries two roles. `year_role_table` is null because no partition
is reused across roles. `partition_reuse` is `off` (`effective: off`, `would_reuse: []`), and
`train-2023` reports `NO_PARTITION / reusable: false`, so this is a fresh collection with no
inherited frame.

2025 and 2026 are prohibited and no stage before `oos` may open 2024. Nothing in the plan reads a
prohibited year.

## Zero study Python — CLEAR

`study_python: {python_files: [], exception: null}`. The study tree contains no committed Python
and claims no `STUDY_PYTHON_EXCEPTIONS` entry. The first-passage oracle proof that previously
failed this check has been relocated to
`research_workflow/tests/test_first_passage_oracle_parity.py`; the study keeps only the JSON
evidence card it emits, which is data, not code.

## Column contract — CLEAR

93 observation columns, 20 features, 61 metadata, 3 identity, 0 derived.

* Identity `observation_ts`, `regime_start_ns`, `checkpoint_index` is present and is the row key.
* 64 milestone columns = 16 arms × `{_label, _disposition, _censor_reason, _resolution_seconds}`.
* 15 terminal columns (the C1 block), independent of the composite disposition.
* 39 of the 61 metadata columns are higher-timeframe state at 5m / 15m / 1h.

## Outcome columns are labels, never features — CLEAR, with one name worth stating

No `terminal_*`, `fp_*` or `target_*` column appears in the feature or metadata space. Feature and
label spaces are disjoint.

Four metadata names look outcome-like and are not: `pnl_atr_1m`, `pnl_atr_5m`, `pnl_atr_15m`,
`pnl_atr_1h`. These are `excursion_*.pnl_atr` — the **running** signed displacement of that
timeframe's *current regime* measured at the epoch from completed bars at or before T, i.e. causal
state, not a forward outcome. This is the same class of legitimate input as
`rolling_300s_giveback_atr`, which the forward-outcome guard is anchored precisely so as not to
reject. Flagging the name because a future reader scanning for "pnl" will pause on it: it is the
trade's progress *so far*, never its result.

## Deliverables — CLEAR for the sealed scope

`deliverables_by_stage` declares `compile → compiled_plan.json`, `prepare →
audit/frozen_execution_manifest.json`, `preflight → audit/preflight.json`, `causal_audit →
audit/status.json`, `contract_audit → audit/contract_status.json`, `seal → the pre-execution seal`,
`collection → _work/controller/partitions/train/<year>/{candidates,observations}.parquet`,
`merge → merged/{candidates,observations}.parquet + identity.json`. Every deliverable of every
stage up to and including collection and merge is declared and reachable.

## Findings

### NOTE K-1 — the claim stages have no declarations yet, by design

`model: null` and no `analysis` block. The deliverables table still lists `fit`, `freeze`, `oos`,
`analyze` and `close` artifacts (`artifacts/experiment_models.json`,
`artifacts/train_experiment_freeze.json`, `artifacts/experiment_analysis_v2.json`,
`artifacts/study_closure.json`). This study is sealed and run only through **merge**; it is a
descriptive dataset build and makes no claim. A later session that wants `analyze`/`close` must
declare the analysis, which will move `spec_sha256` and require a re-seal. Nothing to fix now —
recorded so the post-collection session does not read the deliverables table as a promise.

### NOTE K-2 — the seal is bound to a platform identity that is not on `main`

`execution_composite_sha256 = 346c71526660948d` includes the C1 repair (chore commit `7c4a2673`,
merged into the study branch as `185554c2`). C1 is deliberately **not** merged to `main`, because
the same chore branch carries the unaudited C0 fill-scope work. The study branch is therefore the
sole authority for this seal. Two consequences, both intended: results collected under this seal
cannot be reproduced from `main` until C1 lands there, and any later platform change — including
eventually merging C0/C1 to `main` and back — moves the composite and invalidates this seal.

### NOTE K-3 — provenance of the superseded fingerprints

`research_decision.yaml` records the two superseded plans (`9c49a06f` pre-arms/kernel flip,
`587b8423` arms added but pre-C1 with the terminal lost) alongside the sealed `82b230f2`. The
lineage from the retracted capability-gap verdict through to this plan is documented in the
contract rather than only in commit messages. Correct, and worth keeping intact.

## Invariants

| invariant | status |
|---|---|
| every declared primitive maps to exactly one runtime implementation | CLEAR — 28/28 bound |
| TRAIN/tuning/final-validation/OOS years disjoint | CLEAR — 2023 / 2024 / {2025,2026} disjoint, no reuse |
| no study Python for a tier-2 study unless `STUDY_PYTHON_EXCEPTIONS` names it | CLEAR — zero files, no exception claimed |
| identity columns on every row | CLEAR — `observation_ts`, `regime_start_ns`, `checkpoint_index` |
| outcome columns are labels, never features | CLEAR — disjoint; see the `pnl_atr_*` note |

## Verdict

**CLEAR.** Zero critical, zero warning, three notes. The declared contract is complete and
internally consistent for the sealed scope (through collection and merge).

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "contract", "audited_execution_composite_sha256": "346c71526660948dbeda7549a1812a1cd700a459307d514c62656edccc45f1b8", "auditor": "claude-contract-pass01", "critical": 0, "note": 3, "study": "nq_va_multitf_trade_state_geometry", "verdict": "CLEAR", "warning": 0}
<!-- AUDIT_SUMMARY_V2_END -->
