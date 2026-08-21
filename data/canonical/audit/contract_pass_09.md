# Contract audit — NQ canonical dense 1-second build — pass 09

Reviewer identity: `dense-contract-audit-pass09-2026-08-20`.
Declared execution composite: `8234eb620c18f24875d903def642b9aeff75f7f06fa7a2daffb6b4d3b34fa13c`.
Scope: frozen deliverables contract plus C4, D, and E; no causal theory assessed.

## Prior finding adjudication

- FIXED — pass 08 had no blocking or warning finding; the closure-exception policy remains directly tested and unchanged.
- WITHDRAWN — the prior nonblocking exact-minute predicate assumption no longer applies because `expected_windows` now includes every calendar-declared close boundary without an hour/minute predicate.

## Compliance table

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen contract and execution binding | PASS | `data/canonical/config/deliverables_contract.json:1-58`; actual hashes match `data/canonical/audit/audit_packet.json:2-8` at the declared composite | `preflight.json` is CLEAR, records `20 passed`, and states no source read/output write | — |
| Normal and holiday session-close boundary seconds | PASS | Contract includes every declared close boundary at `data/canonical/config/deliverables_contract.json:16-22`; `scripts/build_dense_1s.py:121-135` includes exactly one boundary second and begins closures afterward | `scripts/tests/test_build_dense_1s.py:79-81,101-107` covers normal maintenance and Thanksgiving early close; preflight suite passes | — |
| Generated manifest endpoint-policy disclosure | FAIL | `scripts/build_dense_1s.py:611` emits `project_nq_endpoint_override` stating only exact 16:00 and pre-regime 15:15 are valid, contradicting the frozen inclusion of calendar-provided early closes at `data/canonical/config/deliverables_contract.json:20` | No test asserts that the manifest disclosure equals the frozen endpoint convention | Update the manifest string to include all calendar-declared session-close boundaries and add a direct assertion. |
| Native closure exception policy and boundary evidence | PASS | `scripts/build_dense_1s.py:145-200,546-553,611-619` | `scripts/tests/test_build_dense_1s.py:127-156`; preflight records PASS | — |
| Previously cleared validations, fallback, publication, terminal labels | PASS | Bound implementation remains present | Preflight-bound suite is CLEAR | — |
| Materialized output/manifest/boundary report | NOT APPLICABLE | Prior full build stopped before canonical publication; canonical Parquet and manifest do not exist, and current preflight records no output write | Completion evidence awaits successful materialization | Run completion contract audit after the bounded build. |
| C4, D, E | NOT APPLICABLE | No selection/model-serving/backtest surface exists | n/a | — |

### WARNING: manifest misstates frozen endpoint convention

Row generation now follows the contract, but a successful build would publish a
manifest claiming a narrower endpoint policy than the one that produced the data.
This is a real deliverable-content defect, though it does not alter generated rows.

## Referred to lookahead-auditor

None.

## Blocking verdict

BLOCKED. Runtime endpoint handling is fixed, but the unwaived manifest warning
must be corrected before the full build reruns so the canonical artifact's own
provenance accurately states the frozen endpoint convention.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "contract", "auditor": "dense-contract-audit-pass09-2026-08-20", "blocking": 0, "warning": 1, "not_verified": 0, "note": 0, "study": "canonical", "audited_execution_composite_sha256": "8234eb620c18f24875d903def642b9aeff75f7f06fa7a2daffb6b4d3b34fa13c"}
<!-- AUDIT_SUMMARY_V2_END -->
