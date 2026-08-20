# Dense canonical 1-second build completion contract audit — pass 19

## Prior finding adjudication

- WITHDRAWN — The historical closure-conflict blocking requirement remains superseded by the frozen diagnostic-warning policy. Pass 18 raised no unresolved blocking or warning finding (`data/canonical/config/deliverables_contract.json:20-21`, `data/canonical/config/deliverables_contract.json:48-51`).

## Compliance assessment

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Materialized deliverables and composite binding | PASS | The single Parquet, manifest, boundary report, and conflict CSV all exist at the exact declared paths (`data/canonical/config/deliverables_contract.json:32-43`). Manifest cleaner hash `b3968669…` equals the audited builder hash for composite `9cb1a928…` (`data/canonical/NQ_dense_1s_2016_2026.manifest.json:2-10`; `data/canonical/audit/audit_packet.json:1-12`). | Preflight for the bound composite is CLEAR with 25 tests (`data/canonical/audit/preflight.json:1-45`). | None. |
| Source immutability and output hash | PASS | Manifest records 11 source files with sizes, counts, ranges, and matching before/after SHA256 values, plus `source_hashes_unchanged=true` (`data/canonical/NQ_dense_1s_2016_2026.manifest.json:11-112`). Independent completion hashing matched the published output SHA256 `bb6bc610…` and all 11 current source hashes to their recorded values (`data/canonical/NQ_dense_1s_2016_2026.manifest.json:9-112`). | Build tests cover immutable-source and publication failure semantics (`scripts/tests/test_build_dense_1s.py:266-315`). | None. |
| Counts, schema, compression, and row groups | PASS | Manifest reconciles 111,274,121 native + 106,911,484 fills = 218,185,605 total (`data/canonical/NQ_dense_1s_2016_2026.manifest.json:113-118`). Independent Parquet metadata inspection found exactly 218,185,605 rows, 58,006 row groups, maximum group size 82,801, ZSTD on every column, and non-null boolean `is_fill`, matching recorded metadata (`data/canonical/NQ_dense_1s_2016_2026.manifest.json:68590-68598`). | Focused tests cover schema/native preservation, dense counts, and Parquet fallback (`scripts/tests/test_build_dense_1s.py:43-84`, `scripts/tests/test_build_dense_1s.py:276-297`). | None. |
| Global coverage, native parity, and fill validity | PASS | Sealed validation evidence reports expected=actual=218,185,605; zero coverage mismatches, missing seconds, synthetic closure rows, duplicates, out-of-order rows, fill violations, native mismatches, and YTD overruns. All 111,274,121 native rows were compared (`data/canonical/NQ_dense_1s_2016_2026.manifest.json:68599-68614`). Published output hash matches the validated candidate. First/last Parquet statistics independently match `2016-01-03 23:00:00Z` and `2026-04-29 23:59:59Z`. | Tests directly cover native parity, prior-close OHLC fills, coverage counters, and YTD validation (`scripts/tests/test_build_dense_1s.py:43-84`, `scripts/tests/test_build_dense_1s.py:223-246`). | None. |
| Calendar conflicts remain diagnostic-only | PASS | Boundary report and embedded manifest object agree on 53,970 native conflicts, `calendar_conflict_status=WARNING`, and `boundary_validation=PASS` (`data/canonical/NQ_dense_1s_2016_2026.boundary_validation.json:14476-68450`). CSV inspection found exactly 53,970 data rows, the required header, and `CALENDAR_CONFLICT_NATIVE_PRESENT` on every row (`data/canonical/NQ_dense_1s_2016_2026_calendar_conflicts.csv:1-53971`). | Focused tests cover conflict counting, nonblocking behavior, native singleton preservation, and CSV contents (`scripts/tests/test_build_dense_1s.py:142-220`). | None. |
| Aggregation and terminal acceptance | PASS | Manifest reports 5s, 30s, and 1m aggregation smoke all `PASS`, source hashes `PASS`, and overall `PASS` (`data/canonical/NQ_dense_1s_2016_2026.manifest.json:68614-68620`). | Normal aggregation smoke is directly tested (`scripts/tests/test_build_dense_1s.py:257-263`). | None. |
| C4, D, and E | NOT APPLICABLE | This deliverable is a canonical data build with no selection/promotion, trained/served model, or backtest (`data/canonical/config/deliverables_contract.json:1-51`). | Not applicable. | None. |

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"CLEAR","audit_type":"contract","auditor":"dense-contract-audit-pass19-2026-08-20","blocking":0,"warning":0,"note":0,"study":"canonical","audited_execution_composite_sha256":"9cb1a928287548b7e4f2a3c8ca238cb379715368ea74586e57d679bb9dac07a5"}
<!-- AUDIT_SUMMARY_V2_END -->

## Blocking verdict

CLEAR

All contract-declared completion artifacts exist and reconcile with the frozen contract, audited composite, physical Parquet/CSV metadata, current source hashes, and sealed validation evidence. The 53,970 calendar conflicts are the contract-declared diagnostic warnings and do not constitute an audit warning or publication blocker.
