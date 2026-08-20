# Contract audit — NQ canonical dense 1-second build — pass 06

Reviewer identity: `dense-contract-audit-pass06-2026-08-20`.
Declared execution composite: `52e7179b890012f47d368cb9cbcedf59d4308b8e85d5a49fb26d5faa438ee46c`.
Scope: frozen deliverables contract plus C4, D, and E; no causal theory assessed.

## Prior finding adjudication

- FIXED — normal-close endpoint extension is now limited to 16:00 CT at `scripts/build_dense_1s.py:121-127`; Thanksgiving early close remains half-open and is asserted as one second at `scripts/tests/test_build_dense_1s.py:101-107`.
- FIXED — pre-regime native 15:15:00 acceptance and 15:15:01 rejection are directly tested at `scripts/tests/test_build_dense_1s.py:127-138` against `scripts/build_dense_1s.py:145-180`.

## Compliance table

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen contract and execution binding | PASS | `data/canonical/config/deliverables_contract.json:1-57`; actual hashes match `data/canonical/audit/audit_packet.json:2-8` at the declared composite | `preflight.json` is CLEAR, records `19 passed`, and states no source read/output write | — |
| Exact normal 16:00 endpoint; generic holiday early close | PASS | `scripts/build_dense_1s.py:121-127` applies `+1s` only to a 16:00 CT close | Normal boundary at `scripts/tests/test_build_dense_1s.py:79-81`; Thanksgiving early close at lines 101-107 | — |
| Pre-regime 15:15 endpoint and interior halt | PASS | `scripts/build_dense_1s.py:130-135,145-180` includes exact 15:15:00, rejects 15:15:01-15:29:59, scans every source batch, and gates boundary PASS | `scripts/tests/test_build_dense_1s.py:72-76,127-138` covers expected windows plus native acceptance/rejection | — |
| Boundary-report deliverable and manifest evidence | PASS | Declared at `data/canonical/config/deliverables_contract.json:29-38`; written/gated at `scripts/build_dense_1s.py:526-530`; override and report are bound into result at lines 588-595 | Focused boundary tests pass in preflight | — |
| 2021 pre/post aggregation smoke | PASS | Defaults include `2021-06-25` and `2021-07-01` at `scripts/build_dense_1s.py:436-457`; all 5s/30s/1m results gate overall | Aggregation mechanics at `scripts/tests/test_build_dense_1s.py:179-185`; preflight records suite PASS | — |
| Previously cleared deliverables, validations, fallback, publication, terminal labels | PASS | Bound implementation paths remain present in `scripts/build_dense_1s.py` | Preflight-bound suite is CLEAR | — |
| Materialized boundary report, output, and manifest contents | NOT APPLICABLE | No full build occurred; preflight records `source_inputs_read=false`, `canonical_output_written=false` | Completion evidence awaits materialization | Run completion contract audit after the bounded build. |
| C4, D, E | NOT APPLICABLE | No selection/model-serving/backtest surface exists | n/a | — |

### NOTE: exact-minute calendar assumption

The normal-close predicate at `scripts/build_dense_1s.py:125-126` checks hour and
minute, not `second == 0`. The authorized `CME_Equity` schedule supplies exact
minute boundaries in the tested evidence, so this does not block; adding an exact
second check would make the frozen `16:00:00` invariant structural.

## Referred to lookahead-auditor

None.

## Blocking verdict

CLEAR. Both pass-05 blockers are fixed, the endpoint convention and native
boundary precheck have direct deterministic evidence, and no new blocking
deliverables defect exists at composite
`52e7179b890012f47d368cb9cbcedf59d4308b8e85d5a49fb26d5faa438ee46c`.
Materialized artifacts remain subject to completion contract audit.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "dense-contract-audit-pass06-2026-08-20", "blocking": 0, "warning": 0, "not_verified": 0, "note": 1, "study": "canonical", "audited_execution_composite_sha256": "52e7179b890012f47d368cb9cbcedf59d4308b8e85d5a49fb26d5faa438ee46c"}
<!-- AUDIT_SUMMARY_V2_END -->
