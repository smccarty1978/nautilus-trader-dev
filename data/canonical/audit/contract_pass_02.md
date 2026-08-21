# Contract audit — NQ canonical dense 1-second build — pass 02

Reviewer identity: `dense-contract-audit-pass02-2026-08-20`.
Declared execution composite: `23e6bed15694b680a6d3a80a193a5af1f1f9e755a201546c19a1ab4560f3627d`.
Scope: frozen deliverables contract plus C4, D, and E; no causal theory assessed.

## Prior finding adjudication

- FIXED — `data/canonical/config/deliverables_contract.json:1-55` now exists, is `FROZEN`, and is bound into `audit/audit_packet.json:2-8` at the declared composite.

## Compliance table

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen deliverables contract and preflight binding | PASS | `config/deliverables_contract.json:1-55`; `audit/audit_packet.json:2-8`; `audit/preflight.json` declares no source reads/output writes | Preflight records causal lint/compile clear and `9 passed` | — |
| Authorized source, schema preservation, streaming ZSTD/250000 rows, deterministic CLI | PASS | `scripts/build_dense_1s.py:69-103,139-200,406-430,480-497` | `scripts/tests/test_build_dense_1s.py:82-91` | — |
| Dense row/native parity mechanics and deterministic ordering | PASS | `scripts/build_dense_1s.py:207-256,264-378` | `scripts/tests/test_build_dense_1s.py:41-67,82-96` | — |
| Calendar regimes and full declared schedule-case coverage | NOT VERIFIED | Calendar implementation is at `scripts/build_dense_1s.py:106-136`; contract requires weekends, Sunday reopen, holidays, early/delayed opens, DST, and YTD at `config/deliverables_contract.json:12-20` | Tests cover only old/new break, maintenance, and a generic partial end at `scripts/tests/test_build_dense_1s.py:70-79,94-96` | Add focused calendar tests for every frozen schedule case. |
| Complete acceptance validation/manifest evidence | FAIL | Acceptance requires `YTD overrun rows` at `config/deliverables_contract.json:48-53`; emitted validations at `scripts/build_dense_1s.py:368-378,473` contain no `ytd_overrun_rows`, and scheduled-closure/missing counts at lines 333-334 can cancel when one missing row is replaced by one closure row | No test exercises `validate_output`, manifest contents, or aggregation smoke | Emit and test each frozen validation result independently, including exact YTD-overrun and closure/missing counts. |
| Failure publication atomicity | FAIL | Canonical path is published by `os.replace` at `scripts/build_dense_1s.py:430-431` before validations/smoke/overall at lines 436-449; a FAIL still leaves the canonical-named Parquet and writes a FAIL manifest at lines 450-476 | No failing-validation integration test | Validate the partial artifact first; publish canonical output and manifest only after overall PASS. |
| Required terminal failure and partition fallback semantics | FAIL | Contract declares blocked terminal and conditional partition fallback at `config/deliverables_contract.json:35,48-53`; `main` catches only `DenseBuildError` at `scripts/build_dense_1s.py:491-495`, while writer/filesystem/Arrow exceptions escape without `CANONICAL_DENSE_1S_BLOCKED`; no partition fallback exists | No CLI failure-label or writer-failure/fallback test | Catch build failures at the CLI boundary, emit the frozen failure label, and implement/document the conditional partition fallback path. |
| C4 walk-forward/seals/promotion | NOT APPLICABLE | No model selection, walk-forward, or promotion in the declared build | n/a | — |
| D2-D4 train/serve model transforms | NOT APPLICABLE | No model, encoding, imputation, or serving surface | n/a | — |
| E backtest configuration/fills/warmup | NOT APPLICABLE | No strategy or backtest execution | n/a | — |

### BLOCKING: failed validation publishes canonical output

A build with parity, coverage, fill, hash, or smoke failure reaches the canonical
filename before acceptance and remains there after the CLI returns blocked. This
creates an invalid canonical artifact and prevents a clean retry because the next
run fails `OUTPUT_ALREADY_EXISTS`.

### BLOCKING: terminal failure and fallback path incomplete

A filesystem, writer, or Arrow failure bypasses the declared blocked label, and
the conditional partitioned fallback has no implementation. Thus real failures
named by the frozen format contract cannot follow the required terminal workflow.

### BLOCKING: frozen validation evidence incomplete

The manifest cannot report the required YTD-overrun result, its missing/closure
counters can both report zero for offsetting defects, and the focused suite does
not verify the manifest, validator, smoke, or all frozen calendar cases. These
acceptance invariants are therefore failed or `NOT VERIFIED` pre-execution.

## Referred to lookahead-auditor

None.

## Blocking verdict

BLOCKED. Pass 01 is fixed, but the canonical publication boundary, required
failure/fallback workflow, and frozen validation evidence must be remediated and
tested before source data is read or a canonical output is produced.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "contract", "auditor": "dense-contract-audit-pass02-2026-08-20", "blocking": 3, "warning": 0, "not_verified": 1, "note": 0, "study": "canonical", "audited_execution_composite_sha256": "23e6bed15694b680a6d3a80a193a5af1f1f9e755a201546c19a1ab4560f3627d"}
<!-- AUDIT_SUMMARY_V2_END -->
