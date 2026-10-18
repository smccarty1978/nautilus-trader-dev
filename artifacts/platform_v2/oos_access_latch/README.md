# chore/oos_access_latch: remediation evidence (G1 / G2 from the HV1 synthetic proof)

| Defect | Before (HV1 proof, 723a0b75) | After (7f13e4d9 + the lazy-identity fix) |
|---|---|---|
| G1 / N2: thresholds loosened after OOS | Re-sealed, re-froze, re-collected OOS; class flipped to VALIDATED; first-access manifests overwritten | Controller BLOCKED at `seal`: `OOS_IDENTITY_CONFLICT` (plan, analysis spec and seal changed); OOS evidence byte-identical |
| G1: treatment redefined after OOS | Accepted | BLOCKED at `seal`: `OOS_IDENTITY_CONFLICT` |
| G1: OOS years widened after OOS | Refused by the stale authorization (untyped) | BLOCKED at `seal`: `OOS_IDENTITY_CONFLICT` (authorization, year_roles) |
| G2 / N8: TRAIN-year row in the OOS partition, manifest hashes recomputed | Analysed as `[2031]` | After pinning: `OOS_EVIDENCE_ALTERED`. During collection: `OOS_RECONCILE_FAILED: rows outside the primary year` (lifecycle tests) |
| Pre-OOS amendment (resealed) | Accepted | Still accepted (no record before the first opening) |
| Resume / repeat analysis under the same identity | n/a | OK, with no re-collection and evidence unchanged |

## Evidence

- `controller_proof/`: the real `V2StudyController`, synthetic golden fixture (TRAIN 2029–2030, OOS 2031), `--shared` clone of 7f13e4d9.
  - Phases p0, p1 and p2 (Architecture B: install + reattest, both partitions `REUSABLE_BY_AUTHORIZATION_ATTESTATION`, shadow `IDENTICAL`, closed) passed in-run.
  - p3L ran to `STUDY_CLOSED`. The in-run assertion failed on a harness defect: it read the failure packet, not `oos_access_refusal.json`. The same assertions re-applied to the recorded evidence are in `p3L_verdict.json` and **PASS** (9/9). Harness fixed.
- `research_workflow/tests/test_oos_access_latch.py`: 18 lifecycle-level tests, all passing.
  - First opening recorded before any held-out bar is read.
  - Repeat analysis triggers no collection.
  - Resume after interruption keeps the original record.
  - Threshold and treatment amendments refused at seal, freeze, analyze and oos.
  - A forged reseal cannot reset the latch.
  - An interrupted opening cannot resume under another plan.
  - OOS-year change refused; unauthorized year refused.
  - Deleted manifest, deleted partition or re-collected bytes: `OOS_EVIDENCE_ALTERED`, with no re-collection.
  - Deleted record: `OOS_ACCESS_RECORD_MISSING`; tampered record: `OOS_ACCESS_RECORD_CORRUPT`.
  - Partition defects (TRAIN-year row, duplicate key, candidate/observation key mismatch): `OOS_RECONCILE_FAILED`, evidence never pinned.
  - Two **processes** racing the opening gate (5 rounds each, conflicting and identical identities): exactly one `FIRST_OPENING`; the other gets `OOS_IDENTITY_CONFLICT` or `RESUMED`.
- `test_delta_targeted.json`: lifecycle_v2, replay_closure, reconcile_bounded_memory (byte-identical `reconcile.json`), model_target_and_reattest, oos_analysis_lineage, chronology_windows, declarative_analysis, experiment, redteam chronology / model authority / packet F, and the latch tests: **171/171 passed, 0 NEW**. The baseline reports `BASELINE_COMMIT_MISMATCH`; with zero failures, nothing needed classification.
- `contract_review.md`: contract-checker, spec items 1–10 PASS, 0 CRITICAL.
  - One WARNING: the legacy non-declared OOS scoring branch relies on the single gate at the top of `analyze()`. With no dev years it reads no partitions.
- Capability registry: `research cap generate --check`, 233 entries, 0 broken.
- Broad pre-merge gate (`test_delta_broad.json`, at 7f13e4d9): 2,608 ran, 2,516 passed, 65 failed. The committed baseline is stale (`BASELINE_COMMIT_MISMATCH`), so all 65 were labelled NEW. Each failing id was therefore re-run on the merge base, 8404c72e (`broad_triage.json`).
  - **61 fail identically on main.** They predate this branch.
  - **4 were caused by this branch** (`test_multi_arm_modeling`). `freeze()` and `analyze()` derived the OOS identity unconditionally and raised `KeyError('instruments')` on minimal plans.
    - Fix: the identity is derived only once an access record exists (`_oos_check`).
    - 3 of the 4 tests score hand-written OOS partitions that have no governed opening. The gate now refuses those, as intended, so these tests stub `_oos_analysis_gate` test-locally. The gate itself is covered here.
    - Re-verified by the targeted gate after the fix (`test_delta_targeted_postfix.json`, 195/195).
- **Final broad gate at a56cfe8d** (`test_delta_broad_final.json`): 2,608 ran, 2,520 passed, 61 failed. These are exactly the 61 that fail on main 8404c72e, so **0 failures are attributable** to this branch. The failure baseline was not updated.

## Limits (stated, not hidden)

- Deleting the record, the completion record **and** the partitions together is not detectable locally. The record and completion live in `artifacts/` (git-tracked), so it is detectable from history.
- The concurrency claim covers the opening gate (an `O_EXCL` create). Two controllers on one study are separately refused by the existing run lock (`STUDY_RUN_ALREADY_LIVE`); that lock was not re-tested here.
- Concurrent writers of the same OOS partition after an identical-identity opening are excluded by that run lock, not by the latch.
- No unclosed study with OOS partitions exists in any worktree (directory existence checked, contents not read), so the latch breaks no in-flight study.
