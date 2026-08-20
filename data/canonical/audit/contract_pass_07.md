# Contract audit — NQ canonical dense 1-second build — pass 07

Reviewer identity: `dense-contract-audit-pass07-2026-08-20`.
Declared execution composite: `eab5e388ae688eff8aa1875b916254056017109a68c83d9881cbec806bd0a888`.
Scope: frozen deliverables contract plus C4, D, and E; no causal theory assessed.

## Prior finding adjudication

- FIXED — pass 06 had no blocking or warning finding; both pass-05 endpoint findings remain fixed in `scripts/build_dense_1s.py:121-180` and their focused tests.
- NOT FIXED (nonblocking NOTE) — the 16:00 predicate still relies on the authorized calendar's exact-minute close values; this does not affect the new exception-policy verdict.

## Compliance table

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen contract and execution binding | PASS | `data/canonical/config/deliverables_contract.json:1-58`; actual hashes match `data/canonical/audit/audit_packet.json:2-8` at the declared composite | `preflight.json` is CLEAR, records `19 passed`, and states no source read/output write | — |
| Isolated-versus-contiguous native closure classification | PASS | `scripts/build_dense_1s.py:145-190` scans all source batches, sorts interior timestamps, and blocks adjacent one-second observations | `scripts/tests/test_build_dense_1s.py:127-140` covers one allowed interior observation and a two-second contiguous rejection in both closure regimes | — |
| More-than-100 noncontiguous material threshold | NOT VERIFIED | `scripts/build_dense_1s.py:35,185-190` appears to implement the frozen `>100` threshold | No focused test constructs 100 isolated observations (allowed) and 101 isolated observations (blocked) | Add deterministic 100/101 noncontiguous boundary tests. |
| Native-only singleton preservation with no closure fills | NOT VERIFIED | `scripts/build_dense_1s.py:194-200,547-575` adds a one-second exception window and routes it through the normal native-preserving writer; manifest boundary counts are emitted at lines 612-619 | No test invokes `add_native_exception_windows` or builds/validates an allowed closure singleton to assert exact native parity, `is_fill=false`, and no neighboring synthetic closure rows | Add a focused exception-window or small build integration test asserting the singleton row and absence of closure fills. |
| Blocking label and boundary-report/manifest contents | PASS | Material policy raises `NATIVE_DATA_INSIDE_DECLARED_CLOSURE` at `scripts/build_dense_1s.py:547-551`; report and manifest carry counts/timestamps at lines 548-554, 612-619 | Contiguous material rejection is exercised at `scripts/tests/test_build_dense_1s.py:127-140`; preflight suite passes | — |
| Previously cleared deliverables, validation, fallback, publication | PASS | Bound implementation remains present | Preflight-bound suite is CLEAR | — |
| Materialized report/output/manifest | NOT APPLICABLE | No full build occurred; preflight records no source read or canonical output write | Completion evidence awaits materialization | Run completion contract audit after the bounded build. |
| C4, D, E | NOT APPLICABLE | No selection/model-serving/backtest surface exists | n/a | — |

### BLOCKING: native closure exception policy is not fully verified

The new contract's two decisive edge cases lack direct evidence: the independent
`>100` material threshold, and actual preservation of an allowed singleton as a
native-only row without synthetic closure neighbors. The code appears consistent,
but untested contract behavior is `NOT VERIFIED` and cannot clear pre-execution.

## Referred to lookahead-auditor

None.

## Blocking verdict

BLOCKED. The bound implementation covers the declared classification and
manifest paths, but focused tests must authenticate both the 100/101 threshold
and native-only singleton materialization before the full build runs.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "contract", "auditor": "dense-contract-audit-pass07-2026-08-20", "blocking": 1, "warning": 0, "not_verified": 2, "note": 0, "study": "canonical", "audited_execution_composite_sha256": "eab5e388ae688eff8aa1875b916254056017109a68c83d9881cbec806bd0a888"}
<!-- AUDIT_SUMMARY_V2_END -->
