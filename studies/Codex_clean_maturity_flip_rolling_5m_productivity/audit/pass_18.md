<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor", "critical": 0, "warning": 0, "note": 1, "study": "Codex_clean_maturity_flip_rolling_5m_productivity", "audited_execution_composite_sha256": "44a42f5fc16b7a933689e4f755632521eba13f665a2e887c04c0b3bf0328a8fc"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 18

**Date:** 2026-08-18T00:00:00Z
**Scope:** `studies/Codex_clean_maturity_flip_rolling_5m_productivity/artifacts/phase0_source_manifest.json` (regenerated artifact only — no code diff). Re-read in full to resolve causality: `implementation/phase0.py` (`authenticate`, `write_manifest`, `authorize_execution`, `_read_config`, `_assert_no_forbidden_lineage` — unchanged), `audit/execution_manifest.json`, `audit/preflight.json`, `audit/status.json` (pass 17), `audit/pass_ledger.json`, `scripts/resolve_execution_manifest.py` (`canonical_file_sha256`), `tests/test_phase0.py`.
**Scope hash:** `execution_composite_sha256 44a42f5fc16b7a933689e4f755632521eba13f665a2e887c04c0b3bf0328a8fc` (preflight run `20260818T173736Z_7481c7314912`).
**Lint:** 0 critical / 0 warning (preflight `CAUSAL_LINT` PASSED, `CAUSAL_INVARIANTS` PASSED, `EXECUTION_MANIFEST` PASSED — `audit/preflight.json`).
**Verdict:** CLEAR

## Summary
- Critical: 0
- Warning: 0
- Note: 1

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 17 | 0 findings raised (pass 17 was CLEAR, 0/0/0) | N/A | Nothing to adjudicate. |

## Critical findings
None.

## Warnings
None.

## Notes
### [G/C-adjacent] `phase0.py`'s own source-hash function and `resolve_execution_manifest.py`'s canonical hash disagree on `features/registry.py` and `features/engine.py`
`artifacts/phase0_source_manifest.json:12450,12453` records `registry_sha256`/`source_code_sha256["features\\registry.py"]` = `a891f04c48...`; `audit/execution_manifest.json:307` records `repo:features/registry.py` = `7eaac1b9c0...` — same file, different digests. Same pattern on `features/engine.py` (`fc47f3e950...` vs `df9a9cab1b...`, `execution_manifest.json:304`). Root cause: `resolve_execution_manifest.py:43-64` (`canonical_file_sha256`) explicitly normalizes CRLF→LF before hashing text files (documented "W7" rationale: Windows `core.autocrlf=true` checkout reproducibility), whereas `phase0.py:39-40` (`sha256()`) hashes raw bytes with no normalization. This is a pre-existing, documented divergence between two independent hashing pipelines, not something introduced by this regeneration — confirmed by the fact that `implementation/collector.py`, `implementation/phase0.py`, and 5 tracker files hash identically across both pipelines (those files apparently carry LF-only bytes on disk), while the two larger, longer-lived files carry CRLF and diverge. **No causal impact**: `phase0.authorize_execution()` (`phase0.py:153-162`) only ever compares its own `authenticate()` output against itself — it never reads or compares against `execution_manifest.json`'s hashes — so this cross-tool digest mismatch cannot cause `authorize_execution` to spuriously pass or fail. Verified no forbidden-lineage tokens (`canonical_regime_scores_all.parquet`, `F3_top25`, `frozen_train_only_baselines`) appear anywhere in the 413KB manifest outside the token-declaration array itself (full-file grep), and `forbidden_collection_years: [2025, 2026]` correctly excludes both the OOS year (2024, allowed) and the unused/sealed years — consistent with the frozen train/OOS/unused/sealed year split in `config/study.yaml`.

## Verification of the regeneration claim

**(a) The only changed file in the audited closure since pass 17 is the manifest itself.** Cross-referenced all 87 entries of `audit/execution_manifest.json:file_hashes` against pass 17's `audit/status.json:audited_files` (87-entry map) key-by-key: **86/87 hashes identical**; the sole difference is `study:artifacts/phase0_source_manifest.json` (`7ab1ab0d80...` pass 17 → `7dc0ac5786...` now). In particular `implementation/collector.py` (`fe7f3509fe...`), `implementation/phase0.py` (`28ef17c5c3...`), `backtests/nt_runtime/modes/collect.py` (`5da667f0bc...`), `utils/causal_registration.py` (`d01d3f8440...`), `utils/session_boundaries.py` (`30fce94572...`), `features/registry.py` (`7eaac1b9c0...`), `study.yaml` and `SPEC.md` are all byte-identical to pass 17 — confirms the task's premise exactly.

**(b) Manifest shape matches `authenticate()`'s real return contract.** Grepped for all 14 top-level keys `authenticate()` (`phase0.py:124-142`) produces (`schema_version`, `authenticated`, `config`, `candidate_count`, `candidate_features`, `candidate_inventory`, `study_yaml_sha256`, `registry_sha256`, `spec_sha256`, `source_code_sha256`, `forbidden_lineage_tokens`, `collection_input_allowlist`, `forbidden_collection_years`, `allowed_actions_after_exact_manifest_verification`) — all present, no extra/fabricated top-level keys, no placeholder/empty values.

**(c) Internal cross-checks land where they should.** `spec_sha256` in the manifest (`aced28d76f4...`) exactly equals `execution_manifest.json`'s independently-computed `study:SPEC.md` hash — same value from two different code paths, on a file that (per phase0's own text-mode hashing, `SPEC.md` being Markdown but apparently LF already) cross-validates cleanly. `source_code_sha256["...collector.py"]` / `["...phase0.py"]` / the 5 tracker entries also match `execution_manifest.json` exactly. This corroborates that the manifest reflects genuinely re-read, current file bytes rather than fabricated/copied values — a fabrication would have no reason to reproduce independently-computed cross-tool hashes exactly on 7 of 9 `source_code_sha256` entries while "coincidentally" diverging only on the two CRLF-bearing files.

**(d) `authorize_execution` will pass against this manifest.** `authorize_execution()` (`phase0.py:153-162`) re-derives `expected = authenticate()` fresh and compares byte-for-byte (after JSON round-trip) against the persisted file. Since (i) `phase0.py` is unchanged, (ii) every source file `authenticate()` reads (`registry.py`, `engine.py`, `collector.py`, the 5 tracker implementations, `config/study.yaml`, `SPEC.md`) is unchanged since the manifest was written (no intervening commit — confirmed via (a)), a fresh call to `authenticate()` right now will deterministically reproduce byte-identical output to what is on disk. The prior failure ("stale or altered") is explained by the manifest being a 2026-08-15 copy predating current repo state; this regeneration closes that gap by construction, not by weakening the check — `_read_config()`'s hardcoded frozen-value assertions (`phase0.py:59-86`) and `_assert_no_forbidden_lineage` are unmodified and still enforced on every call.

## Referred to contract-checker
- Seal-design note: two independent hash pipelines (`phase0.py`'s raw-byte hash vs. `resolve_execution_manifest.py`'s CRLF-normalized hash) compute different digests for the same source files; neither is wrong for its own purpose, but a reviewer diffing the two manifests side-by-side without the CRLF context would misread it as tampering. Worth a one-line disclosure in the manifest schema doc if not already present.

## Clean checks
- A1-A5, B1-B10, C1-C3, F1-F4, G1-G4 unaffected — no bar-processing, indicator, label, session, or data-integrity code changed this pass. H1-H4 not applicable (no bracket simulation in this study).
- `implementation/phase0.py`, `implementation/collector.py`, `backtests/nt_runtime/modes/collect.py`, `utils/causal_registration.py`, `utils/session_boundaries.py`, `features/registry.py` confirmed byte-identical to pass 17 via full 87-entry hash cross-reference.
- `phase0_source_manifest.json` confirmed to contain no forbidden-lineage tokens, correct forbidden-year exclusion, and a shape matching `authenticate()`'s real return contract — no fabricated bypass found.
- `phase0.authorize_execution` confirmed (by code-path analysis, since all its inputs are unchanged) to pass against the regenerated manifest without any weakening of `_read_config`'s frozen-value assertions or `_assert_no_forbidden_lineage`.
