# Contract audit — NQ canonical dense 1-second build — pass 13

Reviewer identity: `dense-contract-audit-pass13-2026-08-20`.
Declared execution composite: `b758e232caf7feb06893706fad977773dae46fbbf44ba4161112923b4ea329a0`.
Scope: frozen deliverables contract plus C4, D, and E; no causal theory assessed.

## Prior finding adjudication

- NOT FIXED — the post-early-close singleton path is corrected, but the frozen exception-policy file is byte-identical to pass 12 and still does not limit isolated exceptions to early-close tails; `scripts/tests/test_build_dense_1s.py:166-170` proves a single weekend closure observation is now blocked.

## Compliance table

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen contract and execution binding | PASS | Actual hashes match `data/canonical/audit/audit_packet.json:2-8` at the declared composite | `preflight.json` is CLEAR, records `23 passed`, and states no source/output run | — |
| Early-close singleton exception | PASS | `scripts/build_dense_1s.py:153-169,221-248` classifies isolated rows in early-close tails under the exception threshold | `scripts/tests/test_build_dense_1s.py:143-163` proves two contiguous rows block and one isolated row passes | — |
| Frozen generic closure-exception scope | FAIL | `data/canonical/config/deliverables_contract.json:21` remains unchanged: isolated nonmaterial native closure observations are preserved, with contiguity or `>100` named material. `scripts/build_dense_1s.py:225-242` additionally makes any generic candidate outside an early-close date material via `generic_unallowed_rows > 0` | `scripts/tests/test_build_dense_1s.py:166-170` explicitly proves one isolated weekend observation fails | Either apply the isolated/contiguous/100 policy to every closure observation, or refreeze the contract to state that only same-day early-close tails may be nonmaterial and weekends/full holidays are always material. |
| Fixed 15:15/16:00 exceptions and manifest boundary counts | PASS | `scripts/build_dense_1s.py:145-252,606-612,671-677` | Bound policy suite passes | — |
| Previously cleared deliverables, validations, fallback, publication | PASS | Bound implementation remains present | Preflight-bound suite is CLEAR | — |
| Materialized output/manifest/boundary report | NOT APPLICABLE | No completion artifacts are supplied; preflight records no source/output run | Completion evidence awaits materialization | Run completion contract audit after the bounded build. |
| C4, D, E | NOT APPLICABLE | No selection/model-serving/backtest surface exists | n/a | — |

### BLOCKING: generic singleton narrowing is absent from frozen contract

The implementation now defines a new material category—any isolated weekend or
full-holiday closure observation—but the frozen policy does not. Because the
contract hash is unchanged, the original pass-12 scope mismatch remains rather
than being resolved by the early-close singleton test.

## Referred to lookahead-auditor

None.

## Blocking verdict

BLOCKED. The early-close case is repaired, but the implementation's narrowed
exception scope must be explicitly frozen or removed before the full build.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "contract", "auditor": "dense-contract-audit-pass13-2026-08-20", "blocking": 1, "warning": 0, "not_verified": 0, "note": 0, "study": "canonical", "audited_execution_composite_sha256": "b758e232caf7feb06893706fad977773dae46fbbf44ba4161112923b4ea329a0"}
<!-- AUDIT_SUMMARY_V2_END -->
