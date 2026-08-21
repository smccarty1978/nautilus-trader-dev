# Contract audit — NQ canonical dense 1-second build — pass 10

Reviewer identity: `dense-contract-audit-pass10-2026-08-20`.
Declared execution composite: `648213e59d53f566cd0bfff206bad0c5d59e9ed06d07edec659b03c8a887ce21`.
Scope: frozen deliverables contract plus C4, D, and E; no causal theory assessed.

## Prior finding adjudication

- NOT FIXED — `scripts/build_dense_1s.py:611` now states normal 16:00, calendar-provided early-close, and pre-regime 15:15 boundaries correctly, but the required direct manifest assertion was not added: `scripts/tests/test_build_dense_1s.py` is byte-identical to pass 09 and contains no `project_nq_endpoint_override` assertion.

## Compliance table

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen contract and execution binding | PASS | `data/canonical/config/deliverables_contract.json:1-58`; actual hashes match `data/canonical/audit/audit_packet.json:2-8` at the declared composite | `preflight.json` is CLEAR and records `20 passed` with no source/output run | — |
| Runtime normal/holiday endpoint handling | PASS | `scripts/build_dense_1s.py:121-135` matches `data/canonical/config/deliverables_contract.json:20` | Normal and Thanksgiving endpoint tests at `scripts/tests/test_build_dense_1s.py:79-81,101-107` | — |
| Generated manifest endpoint-policy disclosure | NOT VERIFIED | `scripts/build_dense_1s.py:611` now appears textually consistent with the frozen convention | No test reads the build result/manifest and asserts `project_nq_endpoint_override`; the test file hash is unchanged from pass 09 | Add the direct manifest/result assertion required by pass 09. |
| Previously cleared exception policy, validations, fallback, publication | PASS | Bound implementation remains present | Preflight-bound suite is CLEAR | — |
| Materialized output/manifest/boundary report | NOT APPLICABLE | No canonical output or manifest exists; current preflight records no source read/output write | Completion evidence awaits successful materialization | Run completion contract audit after the bounded build. |
| C4, D, E | NOT APPLICABLE | No selection/model-serving/backtest surface exists | n/a | — |

### BLOCKING: manifest endpoint provenance remains unverified

The literal mismatch is corrected, but no relevant test authenticates the
deliverable field. The audit rules require correct-looking untested contract code
to remain `NOT VERIFIED`, so the original pass-09 finding is not fixed as a whole.

## Referred to lookahead-auditor

None.

## Blocking verdict

BLOCKED. Add the direct manifest/result assertion for the corrected endpoint
provenance string, refresh the composite, and re-audit before the full build.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "contract", "auditor": "dense-contract-audit-pass10-2026-08-20", "blocking": 1, "warning": 0, "not_verified": 1, "note": 0, "study": "canonical", "audited_execution_composite_sha256": "648213e59d53f566cd0bfff206bad0c5d59e9ed06d07edec659b03c8a887ce21"}
<!-- AUDIT_SUMMARY_V2_END -->
