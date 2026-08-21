# Contract audit — NQ canonical dense 1-second build — pass 03

Reviewer identity: `dense-contract-audit-pass03-2026-08-20`.
Declared execution composite: `f367df219d206e38c60a1879457c13391838936ffcf6822cdcc957dbb43ed8ad`.
Scope: frozen deliverables contract plus C4, D, and E; no causal theory assessed.

## Prior finding adjudication

- FIXED — failed validation no longer publishes the canonical path: `scripts/build_dense_1s.py:495-543`; `scripts/tests/test_build_dense_1s.py:135-142` proves the validation-failure case.
- NOT FIXED — terminal catch/fallback exists at `scripts/build_dense_1s.py:487-494,558-564`, but a fallback records no triggering failure and sets required `output_sha256` to null at lines 452-460, 515-517; the fallback contract remains incomplete.
- NOT FIXED — `ytd_overrun_rows` and tests were added, but coverage counters are not independent/correct and frozen delayed/special-open plus year/source-boundary evidence remains absent; details below.

## Compliance table

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen contract/preflight/composite binding | PASS | `data/canonical/config/deliverables_contract.json:1-55`; `data/canonical/audit/audit_packet.json:2-8` | `preflight.json` records lint/compile clear and `14 passed` without source reads/output writes | — |
| Source/schema, dense rows, ordering, streaming single-file path | PASS | `scripts/build_dense_1s.py:69-103,139-256,416-449` | `scripts/tests/test_build_dense_1s.py:42-97` | — |
| Validation-failure candidate isolation | PASS | `scripts/build_dense_1s.py:495-543` | `scripts/tests/test_build_dense_1s.py:135-142` | — |
| Conditional partition fallback deliverable contents | FAIL | Contract requires documented fallback and `output_sha256` at `data/canonical/config/deliverables_contract.json:35,38-42`; directory fallback returns `output_sha256: None` and does not retain the caught exception at `scripts/build_dense_1s.py:452-460,487-494,512-536` | Fallback test checks only format/path existence at `scripts/tests/test_build_dense_1s.py:145-164` | Record the fallback reason and a deterministic SHA256 binding the ordered partition files; assert both in the test. |
| Independent missing/closure validation | FAIL | Positional comparison at `scripts/build_dense_1s.py:301-337` treats every shifted expected row as both missing and closed | Direct audit counterexample: expected `[0,1,2]`, actual `[0,2]` reports missing `2`, closure rows `1`; truth is missing `1`, closure rows `0`. Existing test only exercises the all-zero case at `scripts/tests/test_build_dense_1s.py:115-123` | Compare ordered timestamp sets/streams with a merge-style walk and test missing-only, closure-only, and substitution cases. |
| All frozen schedule and boundary evidence | NOT VERIFIED | Contract requires delayed/special opens and year/source boundaries at `data/canonical/config/deliverables_contract.json:20,43-47` | Added test covers weekend, Sunday, Christmas, New Year, Thanksgiving early close, and DST at `scripts/tests/test_build_dense_1s.py:100-106`; no delayed/special-open or multi-source/year-boundary test exists | Add focused delayed/special-open and chronological multi-source/year-boundary tests. |
| Atomic publication of output plus required manifest | FAIL | Canonical output is renamed at `scripts/build_dense_1s.py:543` before manifest directory/write at lines 544-545; a manifest write failure exits through the blocked label while leaving canonical output present | No manifest-write-failure test | Stage the manifest first and publish the output/manifest as one recoverable commit protocol; test injected manifest-write failure leaves no canonical output. |
| C4, D2-D4, E | NOT APPLICABLE | No selection/model-serving/backtest surface | n/a | — |

### BLOCKING: partition fallback contract remains incomplete

The fallback is executable, but its manifest cannot authenticate the logical
output and does not document why fallback was required. Pass-02 finding 2 is
therefore not fixed as a whole.

### BLOCKING: frozen validation evidence remains incomplete

The missing/closure counters produce false findings on a basic missing-only
series, while two frozen schedule/boundary cases remain untested. Pass-02 finding
3 remains not fixed.

### BLOCKING: canonical output can survive manifest publication failure

After successful candidate validation, a manifest filesystem failure occurs
after the canonical rename. The CLI reports blocked, but a canonical-named output
without its required manifest remains available to downstream consumers.

## Referred to lookahead-auditor

None.

## Blocking verdict

BLOCKED. Candidate validation isolation is fixed, but fallback authentication,
validation correctness/completeness, and output-plus-manifest publication must
be remediated before reading source data or producing the canonical deliverable.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "contract", "auditor": "dense-contract-audit-pass03-2026-08-20", "blocking": 3, "warning": 0, "not_verified": 1, "note": 0, "study": "canonical", "audited_execution_composite_sha256": "f367df219d206e38c60a1879457c13391838936ffcf6822cdcc957dbb43ed8ad"}
<!-- AUDIT_SUMMARY_V2_END -->
