# Dense canonical 1-second build contract audit — pass 16

## Prior finding adjudication

- WITHDRAWN — The former requirement to block material native/calendar closure conflicts was removed by the amended frozen authority. Pass 15 had no unresolved finding; the current warning-only policy is assessed below against the new composite (`data/canonical/config/deliverables_contract.json:1-51`).

## Compliance assessment

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen contract and execution binding | PASS | The amended contract declares authoritative native preservation, warning-only calendar conflicts, the conflict CSV, manifest fields, validations, and terminal labels (`data/canonical/config/deliverables_contract.json:1-51`). The audit packet binds all three audited surfaces to composite `a9128d01ceebc7cd5c03c6a57fbbd36cf3ee19862472162b49605fb8847d208e` (`data/canonical/audit/audit_packet.json:1-12`). | Fresh preflight is CLEAR with 24 focused tests passing (`data/canonical/audit/preflight.json:1-45`). | None. |
| Native/calendar conflicts are warning-only | PASS | Every timestamp outside the expected calendar windows is inventoried; `calendar_conflict_status` is `WARNING` when present, while boundary validation remains `PASS` (`scripts/build_dense_1s.py:207-258`). Conflict count is not a publication blocker (`scripts/build_dense_1s.py:681-697`). | Tests prove contiguous, 100-row, 101-row, early-close, and weekend conflicts all remain nonblocking and are counted/reported (`scripts/tests/test_build_dense_1s.py:127-190`). | None. |
| Preserve every authoritative native conflict row | PASS | All outside-window native timestamps are passed to `add_native_exception_windows`, which adds one-second singleton windows without synthetic neighbors; candidate validation compares output native values against all sources (`scripts/build_dense_1s.py:249-268`, `scripts/build_dense_1s.py:653-681`; `scripts/build_dense_1s.py:510-574`). | Tests prove singleton output retains native `is_fill=false`/volume and native parity is zero-mismatch (`scripts/tests/test_build_dense_1s.py:181-195`, `scripts/tests/test_build_dense_1s.py:208-216`). | None. |
| Required calendar-conflict CSV | PASS | The streaming CSV writer emits UTC/CT timestamps, year, native OHLCV, classification, and `CALENDAR_CONFLICT_NATIVE_PRESENT`; the build always writes the artifact and records its path/count (`scripts/build_dense_1s.py:271-306`, `scripts/build_dense_1s.py:653-660`, `scripts/build_dense_1s.py:698-727`). | A focused test writes a real conflict CSV and verifies the conflict label and native price (`scripts/tests/test_build_dense_1s.py:198-205`). | None. |
| No synthetic closure rows and strict output validation | PASS | Only singleton native conflict windows are added; expected-coverage, native-parity, fill-validity, chronology, duplication, YTD, source-hash, and aggregation checks gate publication (`scripts/build_dense_1s.py:262-268`, `scripts/build_dense_1s.py:458-574`, `scripts/build_dense_1s.py:681-736`). | Tests cover fill behavior, calendar cases, validation counters, aggregation smoke, failed validation, fallback, and manifest-write failure (`scripts/tests/test_build_dense_1s.py:43-121`, `scripts/tests/test_build_dense_1s.py:208-300`). | None. |
| Materialized output, manifest, boundary report, and conflict CSV | NOT APPLICABLE | Preflight records `source_inputs_read=false` and `canonical_output_written=false` (`data/canonical/audit/preflight.json:40-45`). | No full build was run for this composite. | Perform the mandatory completion contract audit after materialization. |
| C4 selection/test-set discipline and promotion gates | NOT APPLICABLE | This is a canonical data build without selection or promotion (`data/canonical/config/deliverables_contract.json:1-51`). | Not applicable. | None. |
| D train/serve parity and model binding | NOT APPLICABLE | No trained/served model is in scope (`data/canonical/config/deliverables_contract.json:1-51`). | Not applicable. | None. |
| E backtest configuration, fills, and warmup | NOT APPLICABLE | No backtest is authorized (`data/canonical/config/deliverables_contract.json:1-51`). | Not applicable. | None. |

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"CLEAR","audit_type":"contract","auditor":"dense-contract-audit-pass16-2026-08-20","blocking":0,"warning":0,"note":0,"study":"canonical","audited_execution_composite_sha256":"a9128d01ceebc7cd5c03c6a57fbbd36cf3ee19862472162b49605fb8847d208e"}
<!-- AUDIT_SUMMARY_V2_END -->

## Blocking verdict

CLEAR

The amended implementation and focused tests conform to the frozen warning-only calendar-conflict policy and required conflict CSV contract. Runtime `CALENDAR_CONFLICT_NATIVE_PRESENT` warnings are declared diagnostics, not audit findings. Materialized artifacts remain completion-audit scope because this composite read no source inputs and published no canonical output.
