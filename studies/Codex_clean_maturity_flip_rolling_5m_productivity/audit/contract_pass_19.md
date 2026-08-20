# Contract Pass 19

**Reviewer identity:** contract-checker-pass19-smccarty (distinct from any causal-audit identity used on this study)
**Study:** Codex_clean_maturity_flip_rolling_5m_productivity
**Scope:** C4, D, E, and the SPEC.md Deliverables Manifest (`docs/CAUSAL_CHECKLIST.md`).

## Adjudication of pass 18

Pass 18 recorded 0 CRITICAL / 0 WARNING, CLEAR. Nothing to adjudicate.

## What changed since pass 18

`backtests/nt_runtime/modes/collect.py` — a shared framework file — gained one `hasattr`-gated block in
`_execute_collect` (lines 227-234), and is newly inside this study's audited closure because this study's
collector depends on it. `implementation/collector.py` and `implementation/phase0.py` are unchanged. 5 tests
were added to `scripts/tests/test_nt_runner_collect.py`.

### D — train/serve skew / config-building determinism

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| New `cfg_kwargs` branch is generic, not study-name-keyed | PASS | `backtests/nt_runtime/modes/collect.py:233-234` — condition is `hasattr(strategy_binding.config_cls, "phase0_manifest_path")`; value is `str(study_data.study_dir / "artifacts" / "phase0_source_manifest.json")`, derived only from `study_data.study_dir`. No string literal naming this or any other study appears anywhere in the diff (lines 191-234 read in full). | `test_execute_collect_resolves_phase0_manifest_path_generically` (`scripts/tests/test_nt_runner_collect.py:430-460`) uses a fixture study named `test_collect_study` and asserts the resolved path both derives from that unrelated name and does not contain `"Codex_clean_maturity_flip_rolling_5m_productivity"`. | None. |
| New branch follows the identical established pattern/ordering as the other 6 `hasattr` branches | PASS | `collect.py:211-234` — all 7 branches (`prevailing_regime`, `target_direction`, `horizon_seconds`, `feature_list`, `session`, `session_end_censoring`, `phase0_manifest_path`) share the same `if hasattr(strategy_binding.config_cls, "<field>"): cfg_kwargs["<field>"] = <value>` shape, same indentation level, same position (after data_plan/instrument fields, before `strategy_config = strategy_binding.config_cls(**cfg_kwargs)` at line 236). No branch reordering, no early return, no mutation of prior branches' values. | N/A (structural read). | None. |
| Non-declaring `config_cls` provably unaffected | PASS | The `hasattr` guard means `cfg_kwargs` gains no key when the attribute is absent; `strategy_binding.config_cls(**cfg_kwargs)` at line 236 is unchanged. | `test_execute_collect_leaves_non_phase0_config_unaffected` (lines 513-539) drives the real `flip_prediction_collector` binding through `_execute_collect`, asserts `not hasattr(binding.config_cls, "phase0_manifest_path")` before the call and `not hasattr(constructed_config, "phase0_manifest_path")` on the actually-constructed config object afterward — a genuine negative control on the pre-existing production binding, not a mock stand-in. | None. |
| Field-name collision risk across other studies' StrategyConfigs | PASS | Repo-wide search: `phase0_manifest_path` appears only in `collect.py`, the test file, and this study's `implementation/collector.py` / `implementation/run_collect.py`. No other `StrategyConfig` subclass in the repo declares this attribute name, so no other study's binding is affected by this branch, coincidentally or otherwise. | grep evidence (repo-wide, 4 files, 3 of which are this study/its tests). | None. |

### C4 / fail-closed phase-zero gate — unchanged

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| `authorize_execution` fail-closed logic byte-unchanged | PASS | `implementation/phase0.py:153-162` — missing file raises `"phase-zero authorization missing"` (unchanged default `""` still resolves to a non-existent `Path("")`, still refused); non-exact-match (including tampering) raises `"...stale or altered..."`. Neither branch nor the `authenticate()` comparison logic differs from what pass-level history describes as pre-existing. | `test_execute_collect_fails_closed_when_phase0_manifest_missing` and `..._stale` (lines 463-511) both drive the real, unmodified `authorize_execution` through `_execute_collect`'s new wiring and assert the corresponding `RuntimeError` message. `test_clean_flip_collector_constructs_via_generic_wiring` (542-595) proves the positive path: a genuinely-generated manifest (via `phase0.write_manifest`, not fabricated) lets the real `CleanFlipCollector.__init__` complete. | None. |
| Collector call site unchanged | PASS | `implementation/collector.py:96` (`phase0_manifest_path: str = ""`) and `:105` (`authorize_execution(Path(config.phase0_manifest_path))`) — confirmed unmodified; this pass only changes who supplies the non-default value. | Same tests as above. | None. |
| This fix does not itself constitute "governed execution" | PASS (not a finding) | Preflight seal (`audit/preflight.json`) shows a fresh `execution_composite_sha256` (`d2d9bcd27ea6e456bac279d8d13aa86939a1971dba8dfe5701fb2ec242fbeb04`, `status: CLEAR`, `RESEARCH_DECISION_FIDELITY: PASSED`) reflecting `collect.py`'s inclusion in the closure. No real collect run has executed under this study; per task scope, absent execution artifacts (`collection_manifest.json`, `observations`/`candidates` parquet, etc.) are correctly not flagged. | Preflight JSON re-run evidence. | None. |

### E — not implicated by this change (no backtest fill-model, warmup, or config touched).

## New findings this pass

None.

## Referred to lookahead-auditor

(none) — this change is a config-wiring/authentication fix, not a causal-timing change; the phase-zero gate
authenticates source/config identity, not event ordering.

## Blocking verdict

CLEAR

The only change since pass 18 is a generic, `hasattr`-gated addition to the shared `_execute_collect`
config-building block that follows the identical pattern, ordering, and derivation convention (from
`study_data.study_dir`, never from a study name literal) as the six pre-existing branches it sits beside.
Direct code reading confirms: no study-name string appears anywhere in the diff; a `config_cls` lacking the
attribute is provably unaffected (both by structural reasoning and by a negative-control test against the
real, unrelated `FlipPredictionCollector` binding); the fail-closed `phase0.authorize_execution` gate and its
missing/stale refusal paths are byte-unchanged in `implementation/phase0.py`; and no other study's
`StrategyConfig` declares a colliding `phase0_manifest_path` attribute, so no other study's collect-mode
behavior is altered. Preflight re-ran CLEAR with a fresh execution composite reflecting `collect.py`'s new
membership in this study's audited closure. This study remains pre-execution; no real collect/fit/score
output exists yet, and its absence is correctly not treated as a finding.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "contract-checker-pass19-smccarty", "blocking": 0, "warning": 0, "note": 0, "study": "Codex_clean_maturity_flip_rolling_5m_productivity", "audited_execution_composite_sha256": "d2d9bcd27ea6e456bac279d8d13aa86939a1971dba8dfe5701fb2ec242fbeb04"}
<!-- AUDIT_SUMMARY_V2_END -->
