# NQ/ES/YM dense canonical 1-second completion contract audit — pass 21

## Prior finding adjudication

- FIXED — `authorized_variants` now explicitly declares NQ, ES, and YM source globs, symbols, and exact Parquet/manifest/boundary/conflict paths (`data/canonical/config/deliverables_contract.json:12-36`). This supplies the authority missing in pass 20.

## Compliance assessment

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Variant authority and composite binding | PASS | All three variants are explicitly declared (`data/canonical/config/deliverables_contract.json:12-36`). Each manifest cleaner hash equals audited builder hash `b3968669…`; packet binds that builder, tests, and amended contract to composite `f6a07659…` (`data/canonical/audit/audit_packet.json:1-12`). | Fresh preflight is CLEAR with 25 tests (`data/canonical/audit/preflight.json:1-45`). | None. |
| Physical outputs and source immutability | PASS | Independent SHA256 checks matched all three published outputs and all 33 current source files to their manifest hashes; every before/after source pair also matches. NQ records source integrity and range at `data/canonical/NQ_dense_1s_2016_2026.manifest.json:11-114`; ES at `data/canonical/ES_dense_1s_2016_2026.manifest.json:11-114`; YM at `data/canonical/YM_dense_1s_2016_2026.manifest.json:11-114`. | Immutable-source/publication behavior is covered by focused tests (`scripts/tests/test_build_dense_1s.py:266-315`). | None. |
| Counts, schema, compression, and row groups | PASS | NQ reconciles 111,274,121 native + 106,911,484 fills = 218,185,605 (`data/canonical/NQ_dense_1s_2016_2026.manifest.json:115-117`); ES 103,735,591 + 114,443,786 = 218,179,377 (`data/canonical/ES_dense_1s_2016_2026.manifest.json:115-117`); YM 73,630,462 + 144,531,225 = 218,161,687 (`data/canonical/YM_dense_1s_2016_2026.manifest.json:115-117`). Physical metadata matches each count/range and records non-null boolean `is_fill`, ZSTD throughout, and maximum row groups 82,801 ≤ 250,000; manifest metadata is at NQ `:68590-68598`, ES `:63081-63089`, YM `:39549-39557`. | Schema, native preservation, fills, and fallback are directly tested (`scripts/tests/test_build_dense_1s.py:43-84`, `scripts/tests/test_build_dense_1s.py:276-297`). | None. |
| Native parity, fills, chronology, coverage, and YTD | PASS | Every variant reports expected=actual, zero coverage mismatch, missing expected seconds, synthetic closure rows, duplicates, out-of-order rows, fill violations, native mismatches, and YTD overruns; every native row was compared. NQ evidence: `data/canonical/NQ_dense_1s_2016_2026.manifest.json:68599-68614`; ES: `data/canonical/ES_dense_1s_2016_2026.manifest.json:63090-63105`; YM: `data/canonical/YM_dense_1s_2016_2026.manifest.json:39558-39573`. Matching physical output hashes bind those validations to the published files. | Focused tests cover prior-close OHLC, native parity, coverage counters, chronology, and YTD (`scripts/tests/test_build_dense_1s.py:43-84`, `scripts/tests/test_build_dense_1s.py:223-254`). | None. |
| Conflict diagnostics | PASS | Boundary reports exactly match embedded manifest objects and report PASS with diagnostic WARNING: NQ 53,970 (`data/canonical/NQ_dense_1s_2016_2026.boundary_validation.json:14476-68450`), ES 47,742 (`data/canonical/ES_dense_1s_2016_2026.boundary_validation.json:15195-62941`), YM 30,055 (`data/canonical/YM_dense_1s_2016_2026.boundary_validation.json:9350-39409`). CSVs contain exactly those row counts, required headers, and only `CALENDAR_CONFLICT_NATIVE_PRESENT` labels (`data/canonical/NQ_dense_1s_2016_2026_calendar_conflicts.csv:1-53971`; `data/canonical/ES_dense_1s_2016_2026_calendar_conflicts.csv:1-47743`; `data/canonical/YM_dense_1s_2016_2026_calendar_conflicts.csv:1-30056`). | Conflict inventory/preservation/CSV tests pass (`scripts/tests/test_build_dense_1s.py:142-220`). | None. |
| Aggregation and overall acceptance | PASS | NQ, ES, and YM each record 5s/30s/1m PASS and overall PASS (NQ `data/canonical/NQ_dense_1s_2016_2026.manifest.json:68615-68620`; ES `data/canonical/ES_dense_1s_2016_2026.manifest.json:63106-63111`; YM `data/canonical/YM_dense_1s_2016_2026.manifest.json:39574-39579`). | Normal aggregation smoke is tested (`scripts/tests/test_build_dense_1s.py:257-263`). | None. |
| C4, D, and E | NOT APPLICABLE | These are canonical data builds without selection/promotion, trained/served models, or backtests. | Not applicable. | None. |

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"CLEAR","audit_type":"contract","auditor":"dense-contract-audit-pass21-2026-08-20","blocking":0,"warning":0,"note":0,"study":"canonical","audited_execution_composite_sha256":"f6a07659c8d620b9348e757aa2d9eb7a23fece98eefb60c32ca42258e46928e9"}
<!-- AUDIT_SUMMARY_V2_END -->

## Blocking verdict

CLEAR

The pass-20 authority gap is fixed. NQ remains bound, and all declared NQ/ES/YM completion artifacts reconcile with their manifests, physical metadata, current hashes, conflict diagnostics, and frozen acceptance checks. No blocking or warning audit finding remains.
