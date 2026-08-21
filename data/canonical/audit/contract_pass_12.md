# Contract audit — NQ canonical dense 1-second build — pass 12

Reviewer identity: `dense-contract-audit-pass12-2026-08-20`.
Declared execution composite: `fdf1ceca11d110d287ffc4c18600d1f5a7f99a394c2c6a619dfd4278c2e770be`.
Scope: frozen deliverables contract plus C4, D, and E; no causal theory assessed.

## Prior finding adjudication

- FIXED — pass 11 contained no unresolved finding; the endpoint provenance assertion remains bound and passing.

## Compliance table

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen contract and execution binding | PASS | `data/canonical/config/deliverables_contract.json:1-58`; actual hashes match `data/canonical/audit/audit_packet.json:2-8` at the declared composite | `preflight.json` is CLEAR, records `21 passed`, and states no source/output run | — |
| Generic calendar closure precheck | FAIL | Frozen policy at `data/canonical/config/deliverables_contract.json:21` permits isolated nonmaterial native closure observations and blocks only contiguity or more than 100; `scripts/build_dense_1s.py:199-206` instead makes any `generic_closure_rows > 0` material | `scripts/tests/test_build_dense_1s.py:143-152` uses two contiguous post-early-close rows, which would already block under the frozen policy; no test covers one isolated generic closure row | Apply the same isolated/contiguous/100-row policy to all native closure observations, or explicitly refreeze the contract to declare every generic-calendar closure observation material; add a singleton generic-closure test. |
| Fixed 15:15/16:00 closure exceptions | PASS | `scripts/build_dense_1s.py:145-206,210-216` | `scripts/tests/test_build_dense_1s.py:127-168` | — |
| Boundary report and material failure label | PASS | Counts and verdict are written/gated at `scripts/build_dense_1s.py:563-570,628-635` | New generic-closure count and failure verdict are asserted at `scripts/tests/test_build_dense_1s.py:143-152` | — |
| Previously cleared deliverables, validations, fallback, publication | PASS | Bound implementation remains present | Preflight-bound suite is CLEAR | — |
| Materialized output/manifest/boundary report | NOT APPLICABLE | Current preflight records no source read/output write; no completion artifacts are supplied | Completion evidence awaits successful materialization | Run completion contract audit after the bounded build. |
| C4, D, E | NOT APPLICABLE | No selection/model-serving/backtest surface exists | n/a | — |

### BLOCKING: generic closure singleton contradicts frozen exception policy

A single isolated native row after a holiday early close produces
`generic_closure_rows == 1`, immediately fails boundary validation, and raises
`NATIVE_DATA_INSIDE_DECLARED_CLOSURE`. The frozen policy classifies an isolated
nonmaterial closure observation as preservable; the new test does not adjudicate
this case because its two rows are contiguous and material under either design.

## Referred to lookahead-auditor

None.

## Blocking verdict

BLOCKED. The generic calendar scan is implemented and tested, but its singleton
failure semantics contradict the frozen closure-exception policy. Resolve that
contract/implementation mismatch before the full build resumes.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "contract", "auditor": "dense-contract-audit-pass12-2026-08-20", "blocking": 1, "warning": 0, "not_verified": 0, "note": 0, "study": "canonical", "audited_execution_composite_sha256": "fdf1ceca11d110d287ffc4c18600d1f5a7f99a394c2c6a619dfd4278c2e770be"}
<!-- AUDIT_SUMMARY_V2_END -->
