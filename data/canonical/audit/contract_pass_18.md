# Dense canonical 1-second build contract audit — pass 18

## Prior finding adjudication

- WITHDRAWN — The historical closure-conflict blocking requirement remains superseded by the frozen warning-only policy (`data/canonical/config/deliverables_contract.json:1-51`). Pass 17 raised no unresolved blocking or warning finding.

## Compliance assessment

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen contract and execution binding | PASS | The unchanged frozen contract requires synthetic OHLC at the previous canonical close, zero volume, `is_fill=true`, native preservation, conflict artifacts, global validation, and terminal labels (`data/canonical/config/deliverables_contract.json:1-51`). The packet binds the corrected builder, tests, and contract to composite `9cb1a928287548b7e4f2a3c8ca238cb379715368ea74586e57d679bb9dac07a5` (`data/canonical/audit/audit_packet.json:1-12`). | Fresh preflight is CLEAR with 25 focused tests passing (`data/canonical/audit/preflight.json:1-45`). | None. |
| Synthetic OHLC uses prior canonical close | PASS | `densify_window` constructs one carried-close array and uses it for all four synthetic OHLC fields; native matches still take their exact source values (`scripts/build_dense_1s.py:377-425`). State advances from the last native close and is retained across calendar closures (`scripts/build_dense_1s.py:426-429`, `scripts/build_dense_1s.py:590-623`). | The new regression test gives the prior native bar distinct O/H/L/C values and proves every synthetic OHLC value equals its close, not its open/high/low (`scripts/tests/test_build_dense_1s.py:59-68`). Existing tests cover multiple fills and reopen carry (`scripts/tests/test_build_dense_1s.py:43-56`, `scripts/tests/test_build_dense_1s.py:78-84`). | None. |
| Independent synthetic-fill validation | PASS | Candidate validation requires synthetic volume zero, flat OHLC, and synthetic close equal to the immediately preceding canonical close; violations block publication (`scripts/build_dense_1s.py:521-562`, `scripts/build_dense_1s.py:689-734`). | Validator tests exercise a valid densified candidate and require zero fill violations (`scripts/tests/test_build_dense_1s.py:223-231`); failed validation publication semantics remain directly tested (`scripts/tests/test_build_dense_1s.py:266-274`). | None. |
| Native preservation and warning-only conflicts | PASS | Native values are selected unchanged on matched timestamps; all out-of-calendar native timestamps become singleton windows, are counted as diagnostic warnings, and are written to the conflict CSV (`scripts/build_dense_1s.py:207-306`, `scripts/build_dense_1s.py:401-425`, `scripts/build_dense_1s.py:656-663`). | Focused tests cover exact native parity, early-close/weekend conflicts, 100/101 rows, singleton preservation, and CSV contents (`scripts/tests/test_build_dense_1s.py:71-75`, `scripts/tests/test_build_dense_1s.py:142-220`). | None. |
| Manifest, validation, publication, and terminal semantics | PASS | Required manifest fields, source hashes, calendar metadata, Parquet metadata, validations, and conflict artifact/count are assembled after candidate validation; manifest write precedes atomic publication; exceptions reach the blocked terminal label (`scripts/build_dense_1s.py:684-760`). | Focused tests cover coverage counters, year/source streaming, aggregation, candidate failure, partition fallback, manifest failure, and CLI failure (`scripts/tests/test_build_dense_1s.py:223-346`). | None. |
| Materialized output, manifest, boundary report, and conflict CSV | NOT APPLICABLE | Preflight records `source_inputs_read=false` and `canonical_output_written=false` (`data/canonical/audit/preflight.json:40-45`). | No full build was run for this composite. | Perform the mandatory completion contract audit after materialization. |
| C4 selection/test-set discipline and promotion gates | NOT APPLICABLE | This canonical data build has no selection or promotion workflow (`data/canonical/config/deliverables_contract.json:1-51`). | Not applicable. | None. |
| D train/serve parity and model binding | NOT APPLICABLE | No trained/served model is in scope (`data/canonical/config/deliverables_contract.json:1-51`). | Not applicable. | None. |
| E backtest configuration, fills, and warmup | NOT APPLICABLE | No backtest is authorized (`data/canonical/config/deliverables_contract.json:1-51`). | Not applicable. | None. |

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"CLEAR","audit_type":"contract","auditor":"dense-contract-audit-pass18-2026-08-20","blocking":0,"warning":0,"note":0,"study":"canonical","audited_execution_composite_sha256":"9cb1a928287548b7e4f2a3c8ca238cb379715368ea74586e57d679bb9dac07a5"}
<!-- AUDIT_SUMMARY_V2_END -->

## Blocking verdict

CLEAR

The synthetic-fill OHLC correction and its focused regression test now implement the frozen previous-canonical-close contract, while independent candidate validation remains publication-blocking. No contract-audit finding remains. Materialized artifacts still require the completion audit because this composite read no source inputs and published no canonical output.
