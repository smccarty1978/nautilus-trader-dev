<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor", "critical": 0, "warning": 0, "note": 1, "study": "Codex_clean_maturity_flip_rolling_5m_productivity", "audited_execution_composite_sha256": "d5ebb932ccf38bd47d06a17850bca001ddb2463d5886cbf5bb0c2193952bc22e"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 15

**Date:** 2026-08-18T00:00:00Z
**Scope:** `studies/Codex_clean_maturity_flip_rolling_5m_productivity/tests/test_run_exploratory_runner_integration.py` (new file only). No execution-affecting code in `implementation/{collector,phase0,execution,run_exploratory_models}.py` changed since Pass 14; those files were re-read only to verify the fixture genuinely exercises real code paths.
**Scope hash:** not computed this pass (no shell/hash tool available to this invocation); preflight `code_hash fd46e2fdeb7c...` and `execution_composite_sha256 d5ebb932ccf38bd47d06a17850bca001ddb2463d5886cbf5bb0c2193952bc22e` from `audit/preflight.json` confirm no implementation file changed.
**Lint:** 0 critical / 0 warning (preflight CAUSAL_LINT PASSED, `audit/preflight.json`)
**Verdict:** CLEAR

## Summary
- Critical: 0
- Warning: 0
- Note: 1

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| — | Pass 14 raised no findings (0 critical/0 warning/0 note, verdict PASS) | N/A — nothing to adjudicate | `audit/pass_14.md`, `audit/status.json` |

## Critical findings

None.

## Warnings

None.

## Notes

- **[B9]** `test_run_exploratory_runner_integration.py:47-68` (`_synthetic_frame`) constructs every row with 100% structural-field coverage (`structural_available=True`, all `STRUCTURAL_FEATURES` finite) and does not exercise the sub-threshold/refusal branch of `_assert_structural_coverage` (`run_exploratory_models.py:108-131`). This is disclosed in the file's own docstring as scoped to two specific gaps (marker persistence + phase-zero refusal), not exhaustive coverage-threshold testing, and that boundary case already has dedicated coverage in the pre-existing `tests/test_structural_coverage_gate.py` (unchanged). Not a defect — recorded for completeness only.

## Fixture causal-fidelity check (task item a)

Verified line-by-line against `run_exploratory_models._load_partitions` (`run_exploratory_models.py:134-184`), which the new tests drive through the public `run()` entrypoint (no mocking/monkeypatching of `_load_partitions`, `authorize_stage`, or `authenticate` — no `unittest.mock` import in the file):

| Real filter | Fixture behavior | Genuinely satisfied, not bypassed |
|---|---|---|
| Exact 5s cadence (`checkpoint_decision_ns % 5e9 == 0`) | `base_ns` derived from `int(datetime(...).timestamp())` at an on-the-second RTH time (16:00:00 UTC); seconds-since-midnight (57600) and days×86400 are both multiples of 5, so `base_ns` and every `base_ns + offset*5*NS` row is a true multiple of 5s | Yes — arithmetic identity, not a stub |
| Checkpoint uniqueness (`n_unique == height`) | A single `itertools.count()` shared across all rows in a `_load_partitions` call (all TRAIN years share one counter; OOS uses its own) guarantees strictly increasing, non-colliding `checkpoint_decision_ns` | Yes |
| RTH window (`08:30–15:00 America/Chicago`, close-time gate) | Base time is 10:00 CST (clear of DST, per in-file comment); max cumulative offset drift (~18 min for TRAIN, ~5 min for OOS) stays inside the window | Yes |
| `regime_age_seconds > 120`, bucket assignment (`_bucket`) | Ages fixed at 450/750/1200s — interior points of the three `PRIMARY_BUCKETS`, matching the production bucket boundaries imported nowhere by the test (bucket names/thresholds live only in `run_exploratory_models.py`) | Yes — real bucketing logic exercised, not hardcoded |
| `running_mfe_atr >= 1.0`, `new_progress_windows >= 2`, `retained_mfe_ratio >= 0.5` | Fixture rows set 1.5 / 3 / 0.7 respectively — comfortably inside, not gamed to a boundary that would mask an off-by-one | Yes |
| Temporal ordering `regime_start_ns < checkpoint_decision_ns` | `regime_start_ns = checkpoint_decision_ns - age*NS`, age always positive | Yes — no reversed causality |
| Phase-zero lineage (`phase0_sha256` match) | `phase0.write_manifest` is the real production function (re-derives from actual `study.yaml`/`registry.py`/source hashes via `authenticate()`); test 2 corrupts only the OOS-side `manifest.json` copy, test 3 corrupts the authenticated manifest file itself, both drive the exact production raise sites (`"different phase-zero lineage"` at `run_exploratory_models.py:148`, `"stale or altered"` at `phase0.py:161`) | Yes |

No forward-looking values were required for TRAIN vs. OOS separation checks here since that ordering (fit completes before `_load_partitions(oos_dirs, ...)` is ever called) is unchanged code already verified clean in Pass 13/14; this pass only confirms the new fixture does not disturb it — `implementation/run_exploratory_models.py` diff is empty per the task statement and confirmed by an unchanged `code_hash` in `audit/preflight.json`.

`BASELINE_CANDIDATES`/`STRUCTURAL_FEATURES`/`ROLLING_FEATURES` column names are imported directly from `collector.py` (not re-declared in the test), so the fixture schema cannot silently drift from the production feature contract.

## Test-only helper leakage check (task item b)

`phase0.py`, `execution.py` inspected in full; `run_exploratory_models.py` inspected in full. No test-conditional branches, env-var bypass flags, or dev-only hooks present in any implementation file. All helper functions used by the new test (`_sha`, `_rth_base_ns`, `_synthetic_frame`, `_write_partition`, `_build_fixture`) are defined locally inside the test file itself; none were added to `implementation/`.

## Referred to contract-checker

- None newly referred this pass.

## Clean checks

- A1-A5, B1-B10, C1-C3, F1-F4, G1-G4 unaffected — no execution-affecting code changed. H1-H4 not applicable (no bracket simulation in this study).
- New test file: exact-5s-cadence, checkpoint-uniqueness, RTH close-time, maturity-bucket, and phase-zero-lineage filters in `run_exploratory_models._load_partitions`/`authorize_stage` verified genuinely exercised end-to-end, not bypassed or mocked.
