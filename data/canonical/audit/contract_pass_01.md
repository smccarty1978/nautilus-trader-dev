# Contract audit — NQ canonical dense 1-second build — pass 01

Reviewer identity: `dense-contract-audit-pass01-2026-08-20`.

Assigned surface: `scripts/build_dense_1s.py` and
`scripts/tests/test_build_dense_1s.py`. Scope is deliverables-contract
completeness plus C4, D, and E from `docs/CAUSAL_CHECKLIST.md`; no causal theory
is assessed. The reviewer-declared surface composite is SHA256 over the two
ordered `path:file_sha256` records stated in `contract_status.json`. No official
execution manifest exists under `data/canonical/audit/`, so execution-manifest
binding is unavailable.

## Compliance table

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Authoritative deliverables contract exists before implementation/output review | FAIL | Required path `data/canonical/config/deliverables_contract.json` is absent; repository-wide file enumeration finds deliverables contracts only in unrelated study directories. Per the contract-checker rules, no implementation-derived substitute may define the expected artifacts. | The supplied passing command `python -m pytest scripts/tests/test_build_dense_1s.py -q` cannot establish compliance with an absent authoritative deliverables contract. | Add `data/canonical/config/deliverables_contract.json` that literally declares the authorized build mode and every required output/manifest artifact, schema/content requirement, validation result, aggregation-smoke result, and failure/terminal status. Then re-run this audit against a declared execution composite. |

### BLOCKING: authoritative deliverables contract absent

The audit cannot determine whether the builder, tests, manifest, validations,
failure semantics, or terminal labels satisfy the intended deliverable set
without reconstructing that set from the user request or implementation. That
reconstruction is explicitly prohibited. No further C4/D/E or implementation
review is permitted on this pass.

## Referred to lookahead-auditor

None.

## Blocking verdict

INCOMPLETE. The required authoritative deliverables contract is missing, so this
pass stops with the single blocking specification-completeness finding above.
The passing unit test evidence is retained as supplied evidence but cannot make
the pre-execution contract gate reviewable or clear.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "contract", "auditor": "dense-contract-audit-pass01-2026-08-20", "blocking": 1, "warning": 0, "note": 0, "study": "canonical", "audited_execution_composite_sha256": "dea3ef8c7fb621780095d9088effd74ca090e374a2536a609dbb8e37fcc90be3"}
<!-- AUDIT_SUMMARY_V2_END -->
