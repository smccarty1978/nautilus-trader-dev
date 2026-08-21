# Contract audit — NQ canonical dense 1-second build — pass 11

Reviewer identity: `dense-contract-audit-pass11-2026-08-20`.
Declared execution composite: `1aedf099fd52886b85fa32eae0f80c492fc62cad3eb01a7b77ed7bf78fc1287a`.
Scope: frozen deliverables contract plus C4, D, and E; no causal theory assessed.

## Prior finding adjudication

- FIXED — `scripts/tests/test_build_dense_1s.py:227-233` now exercises `build_dense` and directly asserts that the generated result field serialized to the manifest includes `early closes`; the changed test hash is bound into the declared composite.

## Compliance table

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen contract and execution binding | PASS | `data/canonical/config/deliverables_contract.json:1-58`; actual hashes match `data/canonical/audit/audit_packet.json:2-8` at the declared composite | `preflight.json` is CLEAR, records `20 passed`, and states no source/output run | — |
| Runtime normal/holiday endpoint handling | PASS | `scripts/build_dense_1s.py:121-135` matches the frozen endpoint convention at `data/canonical/config/deliverables_contract.json:20` | Normal and Thanksgiving cases at `scripts/tests/test_build_dense_1s.py:79-81,101-107` | — |
| Generated manifest endpoint provenance | PASS | `scripts/build_dense_1s.py:611` states normal 16:00, calendar-provided early closes, pre-regime 15:15, and closure-after-boundary semantics | `scripts/tests/test_build_dense_1s.py:227-233` asserts the generated result field that is written to the manifest | — |
| Previously cleared exception policy, validations, fallback, publication | PASS | Bound implementation remains present | Preflight-bound suite is CLEAR | — |
| Materialized output/manifest/boundary report | NOT APPLICABLE | No canonical output or manifest exists; preflight records no source read/output write | Completion evidence awaits successful materialization | Run completion contract audit after the bounded build. |
| C4, D, E | NOT APPLICABLE | No selection/model-serving/backtest surface exists | n/a | — |

## Referred to lookahead-auditor

None.

## Blocking verdict

CLEAR. The pass-10 finding is fixed, manifest provenance now has direct focused
evidence, and no new blocking deliverables defect exists at composite
`1aedf099fd52886b85fa32eae0f80c492fc62cad3eb01a7b77ed7bf78fc1287a`.
Materialized artifacts remain subject to completion contract audit.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "dense-contract-audit-pass11-2026-08-20", "blocking": 0, "warning": 0, "not_verified": 0, "note": 0, "study": "canonical", "audited_execution_composite_sha256": "1aedf099fd52886b85fa32eae0f80c492fc62cad3eb01a7b77ed7bf78fc1287a"}
<!-- AUDIT_SUMMARY_V2_END -->
