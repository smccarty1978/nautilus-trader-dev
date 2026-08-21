# ES/YM dense canonical 1-second completion contract audit — pass 20

## Prior finding adjudication

- FIXED — Pass 19 completed the separately declared NQ deliverables with no unresolved finding. That verdict does not authorize or bind ES/YM artifacts (`data/canonical/audit/contract_pass_19.md:1-33`).

### BLOCKING: ES and YM lack an authoritative deliverables contract

The only frozen contract identifies `nq_canonical_dense_1s_v1`, authorizes only symbol `NQ` from `data/raw/NQ_v0_1s_*.parquet`, and declares only NQ output, manifest, boundary-report, and conflict-CSV paths (`data/canonical/config/deliverables_contract.json:2-7`, `data/canonical/config/deliverables_contract.json:32-39`). It contains no ES/YM modes, symbols, source globs, or artifact paths. The materialized ES/YM filenames cannot be used to reconstruct audit authority. Consequently their counts, native parity, fills, hashes, conflict diagnostics, and aggregation evidence are out of contract scope and cannot receive a completion verdict.

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Authoritative ES/YM deliverables scope | FAIL | Frozen authority is explicitly NQ-only (`data/canonical/config/deliverables_contract.json:2-7`, `data/canonical/config/deliverables_contract.json:32-39`). | The shared builder tests do not create contractual authorization for ES/YM. | Freeze either symbol-specific ES and YM deliverables contracts or one parameterized multi-symbol contract that explicitly declares both source globs/symbols and every output/manifest/boundary/conflict path; bind the executed composite, then rerun completion audit. |
| ES/YM materialized artifact contents | NOT APPLICABLE | No applicable frozen ES/YM deliverables contract exists. | Supplied files are not sufficient to define their own acceptance scope. | Complete the contract remediation above. |
| C4, D, and E | NOT APPLICABLE | Contract authority is incomplete before these sections can apply; the requested artifacts are data builds rather than selection, model-serving, or backtest workflows. | Not applicable. | None. |

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"INCOMPLETE","audit_type":"contract","auditor":"dense-contract-audit-pass20-2026-08-20","blocking":1,"warning":0,"note":0,"study":"canonical","audited_execution_composite_sha256":"9cb1a928287548b7e4f2a3c8ca238cb379715368ea74586e57d679bb9dac07a5"}
<!-- AUDIT_SUMMARY_V2_END -->

## Blocking verdict

INCOMPLETE

The ES/YM completion review cannot proceed under a frozen contract that literally authorizes and declares only NQ. This is a specification-scope defect, not an implementation or materialized-data defect; no ES/YM artifact has been approved or rejected on content.
