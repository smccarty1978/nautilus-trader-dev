# Dense canonical 1-second build contract audit — pass 17

## Prior finding adjudication

- WITHDRAWN — The former closure-conflict blocking requirement remains superseded by the amended frozen warning-only policy (`data/canonical/config/deliverables_contract.json:1-51`). Pass 16 raised no unresolved blocking or warning finding.

## Compliance assessment

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen contract and execution binding | PASS | The amended contract declares authoritative native preservation, diagnostic calendar conflicts, required conflict CSV and manifest fields, validations, and terminal labels (`data/canonical/config/deliverables_contract.json:1-51`). The packet binds the vectorized builder, tests, and contract to composite `13548ca206fb15af9016b16dcf2af669360c90edda43be6cacb6df9cba01b9f7` (`data/canonical/audit/audit_packet.json:1-12`). | Fresh preflight is CLEAR with 24 focused tests passing (`data/canonical/audit/preflight.json:1-45`). | None. |
| Vectorized conflict CSV scan | PASS | Conflict timestamps are normalized to unique sorted `int64` values; each streamed Parquet batch uses `np.isin`, then writes every matching native OHLCV row with UTC/CT timestamps and `CALENDAR_CONFLICT_NATIVE_PRESENT` (`scripts/build_dense_1s.py:271-306`). The change preserves streaming and CSV contents. | The focused CSV test exercises the vectorized path and verifies row count, conflict label, and native price (`scripts/tests/test_build_dense_1s.py:198-205`). | None. |
| Warning-only conflict inventory and native preservation | PASS | All native timestamps outside generic calendar windows are counted as conflicts, boundary validation remains `PASS`, and every conflict is added as a one-second singleton output window without synthetic neighbors (`scripts/build_dense_1s.py:207-268`). Conflict counts do not enter the publication-blocking predicate (`scripts/build_dense_1s.py:681-697`). | Tests cover contiguous, 100/101-row, early-close, weekend, and maintenance-clock conflicts as nonblocking; singleton output remains native with `is_fill=false` (`scripts/tests/test_build_dense_1s.py:127-195`). | None. |
| Declared conflict artifact and manifest binding | PASS | The build always writes the output-derived conflict CSV and records its path and row count in the manifest result before validated publication (`scripts/build_dense_1s.py:653-660`, `scripts/build_dense_1s.py:698-736`). | Conflict artifact creation is directly tested; publication/failure ordering remains covered by focused build tests (`scripts/tests/test_build_dense_1s.py:198-205`, `scripts/tests/test_build_dense_1s.py:251-300`). | None. |
| Global output validation and terminal semantics | PASS | Native parity, fill validity, chronology, duplicates, expected coverage, YTD limit, immutable-source hashes, and aggregation smoke gate publication; all exceptions route to the blocked terminal label (`scripts/build_dense_1s.py:458-574`, `scripts/build_dense_1s.py:681-757`). | Focused tests cover validators, aggregation, fallback, failed candidate validation, manifest failure, and CLI failure (`scripts/tests/test_build_dense_1s.py:208-331`). | None. |
| Materialized output, manifest, boundary report, and conflict CSV | NOT APPLICABLE | Preflight records `source_inputs_read=false` and `canonical_output_written=false` (`data/canonical/audit/preflight.json:40-45`). | No full build was run for this composite. | Perform the mandatory completion contract audit after materialization. |
| C4 selection/test-set discipline and promotion gates | NOT APPLICABLE | This canonical data build has no selection or promotion workflow (`data/canonical/config/deliverables_contract.json:1-51`). | Not applicable. | None. |
| D train/serve parity and model binding | NOT APPLICABLE | No trained/served model is in scope (`data/canonical/config/deliverables_contract.json:1-51`). | Not applicable. | None. |
| E backtest configuration, fills, and warmup | NOT APPLICABLE | No backtest is authorized (`data/canonical/config/deliverables_contract.json:1-51`). | Not applicable. | None. |

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"CLEAR","audit_type":"contract","auditor":"dense-contract-audit-pass17-2026-08-20","blocking":0,"warning":0,"note":0,"study":"canonical","audited_execution_composite_sha256":"13548ca206fb15af9016b16dcf2af669360c90edda43be6cacb6df9cba01b9f7"}
<!-- AUDIT_SUMMARY_V2_END -->

## Blocking verdict

CLEAR

The vectorized conflict scan preserves the amended warning-only conflict and native-row deliverables contract, with direct focused test evidence. Runtime conflict warnings are declared diagnostics rather than audit findings. Materialized artifacts remain completion-audit scope because no source input was read and no canonical output was published for this composite.
