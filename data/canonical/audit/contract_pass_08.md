# Contract audit — NQ canonical dense 1-second build — pass 08

Reviewer identity: `dense-contract-audit-pass08-2026-08-20`.
Declared execution composite: `619e4317b141386acdfa21c474336965b0fac695f3631265a2318661703eeb9d`.
Scope: frozen deliverables contract plus C4, D, and E; no causal theory assessed.

## Prior finding adjudication

- FIXED — the pass-07 closure-exception evidence gap is closed by `scripts/tests/test_build_dense_1s.py:143-156`: exactly 100 isolated interior rows pass, a noncontiguous 101st row fails, and an allowed singleton is emitted as native-only without neighboring closure windows.
- NOT FIXED (nonblocking NOTE) — the previously disclosed exact-minute calendar assumption is unchanged and remains nonblocking for the authorized `CME_Equity` schedule.

## Compliance table

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen contract and execution binding | PASS | `data/canonical/config/deliverables_contract.json:1-58`; actual hashes match `data/canonical/audit/audit_packet.json:2-8` at the declared composite | `preflight.json` is CLEAR, records `20 passed`, and states no source read/output write | — |
| Isolated/contiguous and 100/101 closure classification | PASS | `scripts/build_dense_1s.py:35,145-190` sorts all fixed-closure interior timestamps and blocks adjacency or a count greater than 100 | `scripts/tests/test_build_dense_1s.py:127-150` proves singleton and exactly-100 acceptance, contiguous rejection, and noncontiguous-101 rejection | — |
| Native-only singleton with no synthetic closure fills | PASS | `scripts/build_dense_1s.py:194-200,552-575` adds only one-second native exception windows to the writer path | `scripts/tests/test_build_dense_1s.py:151-156` asserts the exact singleton window, `is_fill=false`, and unchanged native volume; absence of neighboring windows proves no closure fill generation | — |
| Boundary report, manifest counts, and material failure label | PASS | `scripts/build_dense_1s.py:547-554,612-623` writes exception count/timestamps into the boundary report and manifest and blocks material data with `NATIVE_DATA_INSIDE_DECLARED_CLOSURE` | Policy classification tests pass in the bound preflight suite | — |
| Previously cleared deliverables, validations, fallback, publication | PASS | Bound implementation remains present | Preflight-bound suite is CLEAR | — |
| Materialized report/output/manifest | NOT APPLICABLE | No full build occurred; preflight records no source read or canonical output write | Completion evidence awaits materialization | Run completion contract audit after the bounded build. |
| C4, D, E | NOT APPLICABLE | No selection/model-serving/backtest surface exists | n/a | — |

## Referred to lookahead-auditor

None.

## Blocking verdict

CLEAR. The pass-07 finding is fixed, the complete native closure-exception policy
has direct deterministic evidence, and no new blocking deliverables defect exists
at composite `619e4317b141386acdfa21c474336965b0fac695f3631265a2318661703eeb9d`.
Materialized artifacts remain subject to completion contract audit.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "dense-contract-audit-pass08-2026-08-20", "blocking": 0, "warning": 0, "not_verified": 0, "note": 0, "study": "canonical", "audited_execution_composite_sha256": "619e4317b141386acdfa21c474336965b0fac695f3631265a2318661703eeb9d"}
<!-- AUDIT_SUMMARY_V2_END -->
