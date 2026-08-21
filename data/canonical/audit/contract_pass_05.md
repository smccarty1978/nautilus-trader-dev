# Contract audit — NQ canonical dense 1-second build — pass 05

Reviewer identity: `dense-contract-audit-pass05-2026-08-20`.
Declared execution composite: `299c03a546a8ac6a21270b6bc0f730def2634f83de0e3aa24dbd0b0ca1f8ea07`.
Scope: frozen deliverables contract plus C4, D, and E; no causal theory assessed.

## Prior finding adjudication

- FIXED — pass 04 contained no unresolved finding; its three pass-03 findings remain fixed in the unchanged publication, fallback, validation, and test paths.

## Compliance table

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen contract and final execution binding | PASS | `data/canonical/config/deliverables_contract.json:1-57`; actual file hashes match `data/canonical/audit/audit_packet.json:2-8` at the declared composite | `preflight.json` is CLEAR, records `19 passed`, and states no source read/output write | — |
| Exact 16:00 and pre-regime 15:15 endpoint convention | FAIL | Contract authorizes exact 16:00 CT and pre-regime 15:15 CT at `data/canonical/config/deliverables_contract.json:16-21`; `scripts/build_dense_1s.py:121-133` adds one second to every `market_close`, including holiday early closes | `scripts/tests/test_build_dense_1s.py:101-107` explicitly expects two Thanksgiving seconds from 11:59:59 through 12:00:00 CT, proving the override is applied beyond the frozen endpoints | Add the terminal second only when the close is exactly 16:00 CT; keep other calendar closes half-open and restore the early-close assertion to one second. |
| Native fixed-boundary precheck and report | NOT VERIFIED | `scripts/build_dense_1s.py:143-179,526-530,588-595` scans all source batches, permits exact boundaries, rejects fixed-closure interiors, writes the declared report, and binds its result into the manifest | `scripts/tests/test_build_dense_1s.py:127-133` verifies 16:00/17:00 and a 16:15 interior only; no test proves pre-regime 15:15:00 is accepted and 15:15:01-15:29:59 is rejected | Add a 2021-06-25 native test containing 15:15:00 CT (PASS) and an interior timestamp such as 15:15:01 CT (FAIL). |
| 2021 pre/post aggregation samples | PASS | Default samples include `2021-06-25` and `2021-07-01` at `scripts/build_dense_1s.py:436-457`; all 5s/30s/1m results gate overall at lines 554-566 | Aggregation mechanics test at `scripts/tests/test_build_dense_1s.py:170-176`; preflight records the focused suite PASS | — |
| Source/schema, dense rows, validation, fallback, failure publication | PASS | Previously cleared paths remain at `scripts/build_dense_1s.py:69-103,182-605` | Preflight-bound focused suite is CLEAR | — |
| Materialized boundary report, output, and manifest contents | NOT APPLICABLE | No full build rerun occurred; preflight records `source_inputs_read=false` and `canonical_output_written=false` | Completion evidence awaits materialization | Run completion contract audit after the bounded build. |
| C4, D, E | NOT APPLICABLE | No selection/model-serving/backtest surface exists | n/a | — |

### BLOCKING: endpoint override extends beyond frozen close convention

Every early-close session receives an extra expected second at its calendar close.
For Thanksgiving, the focused test proves a 12:00:00 CT row is generated even
though the frozen override names only exact 16:00 CT and pre-regime 15:15 CT.
That row is inside the scheduled early-close interval but would pass coverage.

### BLOCKING: pre-regime native-boundary behavior not verified

The 15:15 endpoint/interior implementation appears structurally correct, but the
frozen endpoint decision has no direct source-precheck test. Under the audit rule,
untested contract code is `NOT VERIFIED` and cannot clear the build gate.

## Referred to lookahead-auditor

None.

## Blocking verdict

BLOCKED. The final composite is correctly bound and prior findings remain fixed,
but the endpoint override must be narrowed to its frozen times and the pre-regime
native 15:15 boundary precheck must receive direct deterministic evidence before
the full build reruns.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "contract", "auditor": "dense-contract-audit-pass05-2026-08-20", "blocking": 2, "warning": 0, "not_verified": 1, "note": 0, "study": "canonical", "audited_execution_composite_sha256": "299c03a546a8ac6a21270b6bc0f730def2634f83de0e3aa24dbd0b0ca1f8ea07"}
<!-- AUDIT_SUMMARY_V2_END -->
