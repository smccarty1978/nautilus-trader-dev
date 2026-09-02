# Look-Ahead & Timestamp Audit — platform-v2 migration, Pass 01

**Scope:** migration delta `baseline/2026-09-platform..2138cc4` only (not the historical
repository). Checklist sections A, B, C1-C3, F, G, H.

## CRITICAL: `__all__` stripped from the v2 semantic closure hash lets a wildcard-imported
collector silently bind different code under an unchanged composite

`research_workflow/closure_hash.py:38-44` (`_Strip.visit_Module`) deletes every top-level
`__all__` `Assign`/`AugAssign`/`AnnAssign` before computing the v2 AST hash
(`research_workflow/closure_hash.py:62-72`). `__all__` is not decorative in this closure: the
canonical, still-imported strategy entry point does
`from research_workflow.generic_collector import *` (`strategies/flip_prediction_collector.py:7`),
and the same pattern recurs for `study_factory`, `compiler`, `preflight`, `output_manager`,
`readiness`, `phase0`, `seal`, `test_selection`, `feature_binding_engine`, etc. (14 wildcard
imports found repo-wide). `research_workflow/__init__.py:7-9` already declares an `__all__`
list gating one of these surfaces, and `AGENTS.md`/project memory record that a *cosmetic*
`__all__` edit is deliberately treated as execution-closure-relevant under v1 hashing.

**Failure path:** add or edit an `__all__` list in `research_workflow/generic_collector.py`
(it currently has none, so a wildcard import there resolves every public name — the widest
possible surface) so that a name the collector strategy shim relies on is added, removed, or
now points at a different re-exported symbol of the same name. `semantic_python_sha256`
strips exactly that statement before hashing, so the v2 composite is unchanged; a study frozen
under v2 would not detect that `strategies/flip_prediction_collector.py`'s namespace — and
therefore what code executes at candidate time T — has changed.

**Smallest fix:** do not strip `__all__` from the v2 AST before hashing (only docstrings are
safe to elide); or, if `__all__` truly must be excluded, first prove by static analysis that no
file inside any execution closure is ever the target of a wildcard import.

## CRITICAL: dataset root resolution proves a *recorded* digest, never a *live* one — a
stale or edited catalog opens silently under the same `dataset_id`

`research_workflow/roots.py:160-167` (`read_dataset_manifest`) only reads the cached
`dataset_manifest.json` written by a prior `write_dataset_manifest` call
(`roots.py:149-157`). `resolve_dataset` (`roots.py:191-255`) and readiness R1
(`research_workflow/readiness.py:166-197`, esp. `193-197`) both compare that *cached* value
against the committed `DatasetSpec.logical_digest` — neither path calls
`compute_catalog_digest` (`roots.py:135-146`) against the files actually under
`<root>/<dataset_id>/data` at resolution time. The module's own docstring even flags digest
staleness as unaddressed ("a row-level logical digest is a later dataset-version concern") but
understates it: even the *file-level* digest it does check is not re-verified against bytes on
disk.

**Failure path:** an operator (or an automated re-pull) replaces or patches files under a
configured `catalog_roots/<dataset_id>/data` — e.g. a corrected roll adjustment, a wrong
Databento pull — without re-running `write_dataset_manifest`/`research data manifest`. The
stale `dataset_manifest.json` still reports the old (matching) digest; `resolve_dataset` and
R1 both pass; every downstream collector/backtest reads the new, different bytes under the
identical `dataset_id` + `logical_digest` identity the seal/receipts record. Candidates and
labels are computed from a dataset that was never digest-verified.

**Smallest fix:** have `resolve_dataset`/R1 recompute `compute_catalog_digest` on the
resolved path (or at minimum compare the manifest's `generated_at_utc`/mtime against the
newest file mtime under `data/`) rather than trusting the cached manifest value.

## WARNING: DST-transition-day session-boundary arithmetic in the fast path is wrong, and
its "reference" shares the bug rather than independently proving correctness

`utils/session_boundaries.py:110-124` (`_session_hour_entry`) computes RTH start/end as
`ct.normalize() + pd.Timedelta(hours=..., minutes=...)`. Pandas `Timestamp + Timedelta` on a
tz-aware timestamp is absolute-time arithmetic (adds to the UTC-ns value, then redisplays),
not wall-clock arithmetic — so on the one calendar day per transition where CT midnight and
08:30/15:15 straddle different UTC offsets, `start_utc`/`end_utc` land exactly one hour off
true wall-clock 08:30/15:15 (verified by hand for 2023-03-12: `midnight`=06:00 UTC (CST) +
8h30m = 14:30 UTC = 09:30 CDT, not 08:30 CDT). Critically, `session_close_ns_reference`
(`utils/session_boundaries.py:181-188`), the function the equivalence test
(`scripts/tests/test_hot_path_equivalence.py:31-33`) treats as ground truth, uses the
*identical* `ts.normalize() + pd.Timedelta(...)` pattern — so `session_close_ns` and its
"reference" agree with each other while both are wrong, and the test cannot detect it.

This is currently **not reachable**: US DST transitions always fall on a Sunday, and every
call site is weekday-gated before `T` reaches `session_close_ns` —
`is_in_session(T, "RTH")` (`research_workflow/generic_collector.py:1480`, guarding
`_track_pending`'s only path to `session_close_ns` at lines 732/769/785) short-circuits to
`False` on Sunday via the `weekday and (...)` term in `is_in_session`
(`utils/session_boundaries.py:153-155`), independent of the buggy boundary values. So no
candidate observed in production carries a wrong `session_close_ts`. `is_in_session` itself is
therefore also unaffected for RTH classification (only `session_close_ns`'s absolute value is
wrong, and only on Sunday).

**Smallest fix:** compute `session_close_ns_reference` (and the fast-path boundaries) by
localizing the target wall-clock components directly (as `is_in_session_reference` already
does via `.time()` comparison), not via `normalize() + Timedelta`; add an explicit assertion
in `session_close_ns`/`_session_hour_entry` that the resolved day is a weekday, so the latent
bug fails loud instead of silently if a future caller ever invokes it off the RTH-gated path.

## Clean checks

- `is_five_minute_boundary_ns` / `minutes_since_rth_open_ns`
  (`research_workflow/generic_collector.py:119-132`) and `ct_hour_of_day`
  (`utils/session_boundaries.py:130-139`): correct — America/Chicago's whole-hour UTC offset
  means CT minute == UTC minute and DST transitions always land on a UTC-hour boundary, so
  per-UTC-hour caching of the CT hour is exact, not approximate. A1-A5, B1-B7 (no in-scope
  changes touch feature math besides the delegated regime tracker, itself clean).
- `features/trackers/regime_dual_ema.py`: single authoritative dual-EMA/Wilder-ATR
  implementation; `RegimeEngine(DualEmaRegimeTracker)` (`research_workflow/generic_collector.py:187-199`)
  preserves the legacy `ALPHA3=0.5`/`ALPHA9=0.2` constants exactly (`alpha=2/(n+1)` for
  `short_period=3, long_period=9`). B9, B10 clean.
- `research_workflow/provider_host.py` (Q3): `_subscribers` is cached from
  `adapter.required_streams()` on first dispatch (`provider_host.py:783-788, 916-920`), but
  every adapter's `required_streams()` is a pure function of `self.instances`, fixed once at
  construction — no adapter mutates it afterward, so the cache cannot go stale. The module is
  also explicitly not yet wired into the collector (Stage-1 scope per its own docstring), so
  this is inert in the current runtime regardless. F-5 (`NonMonotonicRuntimeEvent`,
  `SnapshotBeforeLatestRuntimeEvent`) causal-order guards are present and fail closed. Clean.
- `research_workflow/controller_actions.py`: `_train_matrix` (`controller_actions.py:135-165`)
  hard-fails `NON_TRAIN_ROWS_IN_FIT_INPUT` if any merged/labelled row's partition isn't
  `"train"`; OOS opens only through `assert_oos_open` (`controller_actions.py:348-350`); label
  column is declared-or-explicit, never guessed (`controller_actions.py:122-132`). C2, C3
  clean.

## Referred to contract-checker

- `research_workflow/model_store.py:213-225` `build_golden_frame` and
  `research_workflow/model_migration.py:64-111` sample rows from whatever `train_frame`
  parquet the operator passes (`scripts/research.py:127-129`, `--train-frame`); nothing in the
  golden-frame path programmatically checks the frame's rows are TRAIN-only or excludes 2024 —
  relevant to the declared "2024 not accessed" / model-integrity invariant, not to
  feature-at-T computation.
- `research_workflow/capabilities.py` reads `.__doc__` to build the generated capability
  registry (`research_workflow/capabilities_index.yaml`/`registry.json`); v2 closure hashing
  strips docstrings, so a docstring-only edit changes generated capability metadata without
  moving a study's composite — a completeness/registry-accuracy question, not a causal one.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "causal", "auditor": "lookahead-auditor/platform-v2-pass-01", "critical": 2, "warning": 1, "note": 0, "study": "platform_v2_migration", "audited_execution_composite_sha256": "2138cc4"}
<!-- AUDIT_SUMMARY_V2_END -->
