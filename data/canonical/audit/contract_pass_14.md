# Dense canonical 1-second build contract audit — pass 14

## Prior finding adjudication

- FIXED — The frozen closure-exception policy now limits nonmaterial exceptions to isolated rows in the declared 15:15–15:30 and 16:00–17:00 closures and isolated same-day tails after a calendar-declared early close, while declaring weekend/full-holiday rows material (`data/canonical/config/deliverables_contract.json:20-21`). This matches the implementation’s early-close-date restriction and material-row decision (`scripts/build_dense_1s.py:161-169`, `scripts/build_dense_1s.py:225-248`) and the focused early-close/weekend tests (`scripts/tests/test_build_dense_1s.py:143-170`).

## Compliance assessment

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen contract and execution binding | PASS | The contract defines the output, validation, endpoint, closure-exception, manifest, boundary-report, and terminal-label obligations (`data/canonical/config/deliverables_contract.json:1-46`). The preflight and packet bind the audited builder, tests, contract, and composite (`data/canonical/audit/preflight.json:1-45`; `data/canonical/audit/audit_packet.json:1-35`). | Fresh deterministic preflight is CLEAR with 23 tests passing and composite `f3ea7799ca403e220809c2724162a44b0a5c58cc4e9c3fe2feaf103904a73d75` (`data/canonical/audit/preflight.json:1-45`). | None. |
| Closure-exception scope and materiality | PASS | Generic exceptions are restricted to timestamps after a declared early close on that same date; other generic closure rows contribute to the material blocker. More than 100 rows or any contiguous run also blocks (`scripts/build_dense_1s.py:161-169`, `scripts/build_dense_1s.py:225-248`). This implements the frozen policy literally (`data/canonical/config/deliverables_contract.json:21`). | Tests cover contiguous early-close rows blocking, an isolated early-close row passing, and an isolated weekend row blocking (`scripts/tests/test_build_dense_1s.py:143-170`). | None. |
| Native-only preservation and exception thresholds | PASS | Allowed exception windows are emitted without synthetic neighbors and retain native rows with `is_fill=false`; counts are recorded in the boundary report (`scripts/build_dense_1s.py:236-248`, `scripts/build_dense_1s.py:392-423`). | Focused tests cover the 100/101 threshold and native-only singleton emission (`scripts/tests/test_build_dense_1s.py:173-224`). | None. |
| Boundary report, failure semantics, and terminal labels | PASS | Boundary validation runs before publication, records exception/material counts, and failures route to the blocked terminal outcome without publishing canonical output (`scripts/build_dense_1s.py:520-608`, `scripts/build_dense_1s.py:731-808`). | The focused suite covers validator failures, manifest/publication failures, fallback behavior, and terminal outcomes (`scripts/tests/test_build_dense_1s.py:226-615`). | None. |
| Declared pre-execution deliverables | PASS | The builder implements the contract-declared manifest provenance, source/output metadata, schema/compression/row-group information, validations, calendar metadata, and deterministic CLI (`scripts/build_dense_1s.py:425-808`). | The 23-test suite exercises manifest content, validation, aggregation, calendar boundaries, publication ordering, and fallback (`data/canonical/audit/preflight.json:1-45`). | None. |
| Materialized canonical output, final manifest, and boundary report | NOT APPLICABLE | The audited preflight records `source_inputs_read=false` and `canonical_output_written=false`; this is a pre-execution audit (`data/canonical/audit/preflight.json:1-45`). | No full build was run for this pass. | Perform the required completion contract audit after the full build materializes deliverables. |
| C4 selection/test-set discipline and promotion gates | NOT APPLICABLE | This data-build contract has no model selection, promotion, or test-set workflow (`data/canonical/config/deliverables_contract.json:1-46`). | Not applicable. | None. |
| D train/serve parity and model artifact binding | NOT APPLICABLE | This builder produces canonical data, not a trained or served model (`data/canonical/config/deliverables_contract.json:1-46`). | Not applicable. | None. |
| E backtest configuration, fills, and warmup | NOT APPLICABLE | No backtest is authorized or performed by this build contract (`data/canonical/config/deliverables_contract.json:1-46`). | Not applicable. | None. |

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"CLEAR","audit_type":"contract","auditor":"dense-contract-audit-pass14-2026-08-20","blocking":0,"warning":0,"note":0,"study":"canonical","audited_execution_composite_sha256":"f3ea7799ca403e220809c2724162a44b0a5c58cc4e9c3fe2feaf103904a73d75"}
<!-- AUDIT_SUMMARY_V2_END -->

## Blocking verdict

CLEAR

The prior frozen-contract mismatch is fixed, and the implementation plus focused tests now directly enforce the declared narrowed exception policy. No blocking or warning finding remains for pre-execution. Materialized deliverables remain outside this pass because no source input was read and no canonical output was produced; they require the mandated completion contract audit after the full build.
