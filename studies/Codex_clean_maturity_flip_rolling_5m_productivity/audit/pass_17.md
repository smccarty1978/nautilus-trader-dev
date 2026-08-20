<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor", "critical": 0, "warning": 0, "note": 0, "study": "Codex_clean_maturity_flip_rolling_5m_productivity", "audited_execution_composite_sha256": "d2d9bcd27ea6e456bac279d8d13aa86939a1971dba8dfe5701fb2ec242fbeb04"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 17

**Date:** 2026-08-18T00:00:00Z
**Scope:** `backtests/nt_runtime/modes/collect.py` (`_execute_collect`, new `phase0_manifest_path` `hasattr` block, `:227-234`). Read in full to resolve causality: `backtests/nt_runtime/compiled_study_loader.py` (`CompiledStudyData`, `load_compiled_study`), `studies/.../implementation/phase0.py` (`authorize_execution`, unchanged), `studies/.../implementation/collector.py` (`CleanFlipCollector.__init__`, unchanged), `scripts/tests/test_nt_runner_collect.py` (5 new tests, §10), `audit/execution_manifest.json`, `audit/preflight.json`.
**Scope hash:** `execution_composite_sha256 d2d9bcd27ea6e456bac279d8d13aa86939a1971dba8dfe5701fb2ec242fbeb04` (preflight run `20260818T164126Z_ed3783810db5`).
**Lint:** 0 critical / 0 warning (preflight `CAUSAL_LINT` PASSED, `CAUSAL_INVARIANTS` PASSED — `audit/preflight.json`).
**Verdict:** CLEAR

## Summary
- Critical: 0
- Warning: 0
- Note: 0

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 16 Note [F2/G-adjacent] | `study.yaml` 5-date smoke window doesn't state RTH catalog completeness | WITHDRAWN (out of scope this pass) — `study.yaml` did not change in this diff (hash `44ea8ffe0fbeda5...` unchanged from pass 16's scope); this pass's change is confined to `backtests/nt_runtime/modes/collect.py` config-kwarg wiring and has no bearing on catalog date coverage. Not re-raised. |

## Critical findings
None.

## Warnings
None.

## Notes
None.

## Verification detail

**(a) `study_data.study_dir` is resolved at run-setup, not from event-loop state.**
`backtests/nt_runtime/compiled_study_loader.py:28-36` — `CompiledStudyData` is a `@dataclass(frozen=True)`; `study_dir = Path(study_path).resolve()` (`:52`) is computed once inside `load_compiled_study`, called at `run_collect_mode` step 1 (`modes/collect.py:34`), which precedes seal check (`:38`), run/data-plan resolution (`:41,149`), strategy binding (`:153`), and `engine.run()` (`:241`) by construction. `_execute_collect` receives `study_data` as a parameter and reads `study_data.study_dir` at `:234` — a plain attribute access on a frozen dataclass, not a cache/bar/state lookup. No bar callback, `on_bar`, or event handler anywhere in `collect.py`, `collector.py`, or `phase0.py` reassigns or derives `study_dir`; the frozen dataclass makes reassignment impossible post-construction. Confirmed static, pre-`engine.run()`, cannot vary causally across the run.

**(b) Collector causal ordering byte-identical to what Pass 16 audited.**
`audit/execution_manifest.json` file_hashes: `implementation/collector.py` → `fe7f3509fe7f554239b1aa387a28b358cb566cc1f12fd6576c0168952df6de1d`, `implementation/phase0.py` → `28ef17c5c35cd57548d99a6a308d3c06b5315c9c982f0bde4fe4c4ed9c0d7b1e` — both identical to the hashes Pass 16 recorded (`fe7f3509fe7f...` / `28ef17c5c35c...`). `utils/causal_registration.py` (`d01d3f8440ce...`) and `utils/session_boundaries.py` (`30fce9457280...`) are both listed in `runtime_closure`/`governance_closure` and preflight's `CAUSAL_INVARIANTS` check is PASSED against the current composite — no diff surface in 1s-before-1m dispatch order, RTH gating, or checkpoint cadence. `collector.py:100-119` (`CleanFlipCollector.__init__`) read in full: `authorize_execution` runs first (`:105`), before any regime/feature engine construction — a pure gate, unrelated to bar timing.

**(c) New test exercises the real, unmodified `authorize_execution`.**
`scripts/tests/test_nt_runner_collect.py:542-596` (`test_clean_flip_collector_constructs_via_generic_wiring`): imports `phase0 as codex_phase0` from the actual study module (`:553`), calls `codex_phase0.write_manifest(fresh_manifest_path)` — the real, unmodified `authenticate()`/`write_manifest` (`phase0.py:112-150`) — to produce a genuine manifest at test time rather than asserting a fabricated one (`:564-569`). `CleanFlipCollector` itself is constructed for real via `strategy_binding.strategy_cls(strategy_config)` inside the unmodified `_execute_collect` code path (only `build_engine`/`engine.run()` are stubbed, via `patch(...build_engine...)` and a `side_effect` exception raised strictly after `add_strategy` — `:575-589`), so `CleanFlipCollector.__init__` → `authorize_execution(Path(config.phase0_manifest_path))` (`collector.py:105`) runs unmocked and unmodified. No monkeypatch of `authorize_execution`, `authenticate`, or any equality check found in this test or the other 4 new tests (`:391-539`), including the two explicit negative-path tests (missing manifest, tampered manifest) that assert the real `RuntimeError` messages ("phase-zero authorization missing" / "is stale or altered") are raised, not bypassed.

**Causal impact of the change itself.** The added block (`modes/collect.py:233-234`) only decides which string is assigned to `cfg_kwargs["phase0_manifest_path"]` before `strategy_config = strategy_binding.config_cls(**cfg_kwargs)` (`:236`) — i.e., before strategy construction, before `engine.add_strategy` (`:238`), before `engine.run()` (`:241`). It touches no bar, timestamp, ordering, or session-gating logic; it follows the exact same `hasattr`-gated pattern already used for `prevailing_regime`/`target_direction`/`horizon_seconds`/`feature_list`/`session`/`session_end_censoring` immediately above it (`:211-226`), which Pass 16 (and earlier passes) already reviewed as a class of change. Previously this field was silently left at `""` for every collector declaring it, making the phase-zero gate permanently self-refusing regardless of manifest validity — a fail-closed defect (never fail-open), now corrected to feed a real, still-verified-at-authorization-time path.

## Referred to contract-checker
- None newly referred this pass.

## Clean checks
- A1-A5, B1-B10, C1-C3, F1-F4, G1-G4 unaffected — no bar-processing, indicator, label, session, or data-integrity code changed. H1-H4 not applicable (no bracket simulation in this study).
- `study_data.study_dir` confirmed resolved once at run-setup on a frozen dataclass, immutable for the run duration.
- `implementation/collector.py`, `implementation/phase0.py`, `utils/causal_registration.py`, `utils/session_boundaries.py` confirmed byte-identical to Pass 16 via `execution_manifest.json` hashes; `CAUSAL_INVARIANTS` PASSED in current preflight.
- New tests confirmed to exercise the real, unmodified `phase0.authorize_execution`/`authenticate`/`write_manifest` with no fabricated bypass.
