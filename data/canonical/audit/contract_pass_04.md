# Contract audit — NQ canonical dense 1-second build — pass 04

Reviewer identity: `dense-contract-audit-pass04-2026-08-20`.
Declared execution composite: `47621eed1183c6394d02ad30e7f2c04e5a8561fafdcc8c1880ea30b47c39c9c8`.
Scope: frozen deliverables contract plus C4, D, and E; no causal theory assessed.

## Prior finding adjudication

- FIXED — partition fallback now records the caught failure and computes a logical SHA256 over sorted partition hashes at `scripts/build_dense_1s.py:453-466,490-502,520-545`; assertions are at `scripts/tests/test_build_dense_1s.py:180-200`.
- FIXED — expected coverage now uses an ordered merge comparison at `scripts/build_dense_1s.py:292-345`; missing-only/closure-only, delayed-open, and cross-source/year tests are at `scripts/tests/test_build_dense_1s.py:110-118,138-158`.
- FIXED — the required manifest is written before canonical rename at `scripts/build_dense_1s.py:550-554`; injected manifest-write failure proves no canonical output is published at `scripts/tests/test_build_dense_1s.py:203-218`.

## Compliance table

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen contract and declared execution binding | PASS | `data/canonical/config/deliverables_contract.json:1-55`; `data/canonical/audit/audit_packet.json:2-8` binds the three audited files to the declared composite | `preflight.json` is CLEAR, reports `18 passed`, and records no source read/output write | — |
| Authorized raw source, schema freeze, source hashes, deterministic CLI | PASS | `scripts/build_dense_1s.py:69-103,476-489,520-545,558-575` | Schema/order failures and CLI build paths are covered by the focused suite recorded in preflight | — |
| Dense native/fill contract and deterministic ordering | PASS | `scripts/build_dense_1s.py:139-256,348-389` | `scripts/tests/test_build_dense_1s.py:42-98,127-148` | — |
| Historical calendar regimes and required schedule/boundary cases | PASS | `scripts/build_dense_1s.py:106-136,292-345` | Regime/maintenance at `scripts/tests/test_build_dense_1s.py:71-80`; weekend, Sunday, holidays, early close, DST, delayed open, YTD, and source/year boundary at lines 95-118, 138-158 | — |
| Streaming Parquet and conditional chronological partition fallback | PASS | `scripts/build_dense_1s.py:416-466,490-502`; ZSTD, 250000-row-group limit, sorted partition hashes, logical output hash, and recorded reason are explicit | `scripts/tests/test_build_dense_1s.py:180-200` | — |
| Required manifest fields and validations | PASS | Result contains every field declared at `data/canonical/config/deliverables_contract.json:38-47`; implementations at `scripts/build_dense_1s.py:292-413,503-545` cover hashes, chronology, duplicates, coverage, closure rows, parity, fill validity, YTD, and 5s/30s/1m smoke | Validator/counter/smoke tests at `scripts/tests/test_build_dense_1s.py:127-167`; preflight records all focused tests PASS | — |
| Failure publication and terminal-label reachability | PASS | Failed validation writes only `.failed` manifest and raises at `scripts/build_dense_1s.py:547-549`; success manifest precedes canonical rename at lines 550-554; all exceptions reach `CANONICAL_DENSE_1S_BLOCKED` at lines 567-573 and success reaches READY at lines 574-575 | Validation, fallback, and manifest-write failure tests at `scripts/tests/test_build_dense_1s.py:170-218` | — |
| Materialized output and final manifest contents | NOT APPLICABLE | Contract-authorized build has not run; preflight explicitly records `source_inputs_read=false` and `canonical_output_written=false` | Completion validation awaits the materialized artifacts | Run the completion contract audit after the bounded build. |
| C4, D, E | NOT APPLICABLE | No selection seal, trained/served model, strategy, or backtest surface exists in this data-build contract | n/a | — |

## Referred to lookahead-auditor

None.

## Blocking verdict

CLEAR. Every pass-03 finding is fixed and the frozen pre-execution deliverables,
validation, failure, and test contracts are directly evidenced at composite
`47621eed1183c6394d02ad30e7f2c04e5a8561fafdcc8c1880ea30b47c39c9c8`.
This verdict authorizes the build gate only; materialized output and manifest
contents still require the completion contract audit.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "dense-contract-audit-pass04-2026-08-20", "blocking": 0, "warning": 0, "not_verified": 0, "note": 0, "study": "canonical", "audited_execution_composite_sha256": "47621eed1183c6394d02ad30e7f2c04e5a8561fafdcc8c1880ea30b47c39c9c8"}
<!-- AUDIT_SUMMARY_V2_END -->
