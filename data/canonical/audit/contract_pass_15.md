# Dense canonical 1-second build contract audit — pass 15

## Prior finding adjudication

- FIXED — The pass-13 contract/implementation mismatch remains resolved by the frozen exception policy (`data/canonical/config/deliverables_contract.json:20-21`). The changed implementation now additionally requires fixed-clock exceptions to fall on a calendar session date, so weekend/full-holiday clock matches become material (`scripts/build_dense_1s.py:161-170`, `scripts/build_dense_1s.py:222-248`); the added weekend maintenance-clock assertion passes (`scripts/tests/test_build_dense_1s.py:166-174`).

## Compliance assessment

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen contract and execution binding | PASS | The frozen contract declares the builder, tests, output artifacts, endpoint/exception rules, validations, and terminal labels (`data/canonical/config/deliverables_contract.json:1-46`). The audit packet binds the changed builder, tests, contract, and composite (`data/canonical/audit/audit_packet.json:1-12`). | Fresh preflight is CLEAR with 23 focused tests passing and composite `a54c8167d2c7314c4349bd2675e9b29e747ac560c1e9e71463b3068ae50fad67` (`data/canonical/audit/preflight.json:1-45`). | None. |
| Calendar closure exception scope | PASS | Fixed 15:15–15:30/16:00–17:00 candidates are retained only on dates present in the calendar schedule; generic exceptions are retained only on calendar-declared early-close dates. All other candidates count as unallowed and block (`scripts/build_dense_1s.py:161-170`, `scripts/build_dense_1s.py:207-248`). This matches the literal frozen policy (`data/canonical/config/deliverables_contract.json:20-21`). | Calendar tests cover weekends, Sunday reopen, Christmas, New Year, an early close, DST, and a delayed open (`scripts/tests/test_build_dense_1s.py:101-121`). Boundary tests prove isolated early-close preservation, contiguous rejection, weekend rejection at an ordinary time, and weekend rejection at the maintenance clock (`scripts/tests/test_build_dense_1s.py:143-174`). | None. |
| Materiality threshold and native-only preservation | PASS | Any contiguous exception run or more than 100 rows blocks; allowed exception seconds become singleton windows, so no synthetic closure neighbors are created (`scripts/build_dense_1s.py:239-264`). | Tests prove exactly 100 isolated rows pass, 101 block, and an allowed singleton is emitted unchanged with `is_fill=false` (`scripts/tests/test_build_dense_1s.py:177-190`). | None. |
| Validation, publication, manifest, and failure semantics | PASS | Boundary validation precedes candidate construction; output validation precedes atomic publication; failed paths emit the blocked terminal label and do not publish the canonical output. Manifest and boundary data include the contract-declared provenance and validation fields (`scripts/build_dense_1s.py:600-706`, `scripts/build_dense_1s.py:731-808`). | Focused tests cover parity/fill/YTD validation, independent coverage counters, source/year streaming, aggregation smoke, manifest-before-publication failure, candidate-validation failure, fallback, and CLI failure (`scripts/tests/test_build_dense_1s.py:193-615`). | None. |
| Materialized canonical output, final manifest, and boundary report | NOT APPLICABLE | Preflight records `source_inputs_read=false` and `canonical_output_written=false` (`data/canonical/audit/preflight.json:40-45`). | No full build was run for this composite. | Run the mandatory completion contract audit after materialization. |
| C4 selection/test-set discipline and promotion gates | NOT APPLICABLE | This is a canonical data build without selection or promotion (`data/canonical/config/deliverables_contract.json:1-46`). | Not applicable. | None. |
| D train/serve parity and model binding | NOT APPLICABLE | No trained/served model is in scope (`data/canonical/config/deliverables_contract.json:1-46`). | Not applicable. | None. |
| E backtest configuration, fills, and warmup | NOT APPLICABLE | No backtest is authorized by this contract (`data/canonical/config/deliverables_contract.json:1-46`). | Not applicable. | None. |

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"CLEAR","audit_type":"contract","auditor":"dense-contract-audit-pass15-2026-08-20","blocking":0,"warning":0,"note":0,"study":"canonical","audited_execution_composite_sha256":"a54c8167d2c7314c4349bd2675e9b29e747ac560c1e9e71463b3068ae50fad67"}
<!-- AUDIT_SUMMARY_V2_END -->

## Blocking verdict

CLEAR

The changed session-date filter and final tests conform to the frozen closure-exception policy, and no blocking or warning finding remains for pre-execution. Because this composite read no source input and produced no canonical output, the materialized deliverables still require the mandated completion contract audit after the full build.
