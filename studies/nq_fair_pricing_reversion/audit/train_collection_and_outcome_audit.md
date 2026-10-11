# nq_fair_pricing_reversion — TRAIN collection and outcome audit

**Correction of `c9bb2cb2`.** That version had mangled identifiers and amounts, an unsupported stop-masking claim and an incorrect durability claim. It also omitted the frozen identities. All are corrected below; §7 lists every change. No sealed contract file, plan, authorization, outcome definition, population or collected TRAIN result is modified by this correction.

## 0. Frozen execution identity
| | SHA-256 |
|---|---|
| Plan (`plan_sha256`) | `9b9b80c640aff865546e9000a8bbed5d5b0ffc4050aece8606f9dec8a442c5cb` |
| Execution composite | `dad232b5150ed7b50e230579cc7068e4ff11ff1166ddffde975b1a1a2860595e` |
| Dataset (`NQ_1S_V2_GLOBEX`, logical digest) | `9e7aecb7a2910b4402a6cb4f34cc2f6deb5df19d0e889b2c696cf4f844292c64` |
| Composite seal hash | `b80487723b4f6ff3b6475f7482307c7fe00aab2aa5050fe9e6a902dc971bbbf3` |
| Experiment authorization | `8d6fd75c7b1f87a8505c39db363a528d2d35792def089750a22effdccfacbf8e` (TRAIN 2021–2023, OOS 2024, prohibited 2025–2026) |

Checked 2026-10-11, read-only, against the V2 controller's own freshness predicates. The current closure recomputes to the frozen composite. Compile through seal are all fresh. The collection, reconcile and merge receipts are current for this plan.

## 1. Collection integrity
The full 2021–2023 TRAIN population is reconciled.
- 69,369 candidates over 772 sessions: 23,088 in 2021, 23,196 in 2022 and 23,085 in 2023.
- Every arm satisfies positive + negative + censored = total.
- The merged artifact equals the three partitions row for row. `_work/controller/reconcile.json` reports `passed: true` and `rows: 69369`, and it cites the dataset digest above.
- Merged file hashes:
  - `candidates.parquet` `606a4f4cc126e3300bd8c840259df86a5aeefb9267742355a309129b96ba5873`
  - `observations.parquet` `f1a15a18c33bb3c00698cc9fe49c656b8e2befe6e6aac3611f61096aab2a591e`
- On 2026-10-11 all 29 entries in `train_evidence/artifact_manifest.json` were re-hashed and match. That includes the 20 files under `_work/controller/`: partitions, merged outputs, receipts, manifests and replay traces.

## 2. Outcome semantics and cadence
- Barriers resolve causally on completed `nq_1m` bars.
- `research_workflow/grammar/compiler.py:1260` binds `outcome.stream` to the population cadence stream (`completed_1m`).
- `OutcomeSpec` (`research_workflow/grammar/spec.py:173-214`) has no stream field.
- Every barrier arm is evaluated against its own target and stop (`arm_good[i]`, `arm_bad[i]` in `research_workflow/host/outcomes.py:481-613`).
- The four recovery milestones m25–m100 are declared without an adverse barrier (`adverse_points: null`, `adverse_atr: 0`), so their stop is `±inf` by design.
- `tp38_sl25` (target 38 pts, stop 25 pts) and `anchor_sl25` (stop 25 pts) each carry their own stop. No barrier is shared between arms.

## 3. Bounded 1m vs 1s outcome parity
A governed 1s replay ran 2,427 candidates over 27 sessions. `outcome.stream` was overridden in memory only.
- Candidate identity, signal membership, entry prices and barrier levels are all preserved.
- There are 0 target↔stop reversals and 0 censoring changes.
- Labels changed only for rows the 1m run had censored as `AMBIGUOUS_SAME_BAR_TOUCH`: all 31 tp38 rows and 29 anchor rows.
- A1∩A2 has no tp38 ambiguous rows.

Details are in `train_evidence/OUTCOME_CONTRACT_AUDIT.md`. The per-candidate tables are now committed in `train_evidence/` (§5). Their hashes equal those already recorded in `train_evidence/evidence.json`.

## 4. 2023-10-12 cross-check (descriptive only)
This concerns the A1∩A2 short candidate with decision bar 10:16 ET. Its candidate row has `displacement_signal = 1`, `bos_signal = 1` and direction −1.

**Frozen TRAIN label:** in `observations.parquet`, `tp38_sl25` is `POSITIVE` with `resolution_seconds = 1740`, which resolves at 10:45:00 ET. A POSITIVE barrier label means the kernel saw this arm's own target before this arm's own stop.

**Ungoverned native execution, consistent but not adopted.** `audit/native_nt_execution/trades_20231012_A1_A2_SHORT_ONLY.csv` is classified in §6.
- Short entry at 15,441.50 at 10:16:00 ET.
- Target fill at 15,403.50 at 10:44:58 ET, +38.00 points.
- Its stop is entry + 25.00 = 15,466.50 (`EXECUTION_ASSUMPTIONS.md` §3).

**Withdrawn.** The earlier version claimed that a 10:27 ET high of 15,461.00 breached an "adverse stop" at 15,448.50, and that "shared recovery arms" masked it. That claim has no supporting evidence.
- The frozen label is POSITIVE, which is consistent with the native target execution.
- 15,448.50 is not a 25-point stop from the native entry, and 15,461.00 is below the native stop of 15,466.50.
- The kernel shares no stop between arms (§2).

2023-10-12 is not one of the 27 parity sessions, so the frozen kernel's own entry price for this row is not in committed evidence. It is not asserted here.

No outcome-kernel defect is indicated.

The earlier version's 2023-10-30 paragraph ("Trade #12" / "Signal #13") described the same ungoverned native execution. It is withdrawn as unvalidated and not adopted.

## 5. Retained evidence and durability
- **Committed in `c9bb2cb2` (on `origin/study/nq_fair_pricing_reversion`):** the sealed contract and the descriptive evidence in `audit/train_evidence/`.
- **Committed with this correction** (force-added past the global `*.csv` ignore, as in `da34311f`):

  | file | SHA-256 |
  |---|---|
  | `train_evidence/parity_candidates.csv` | `6541b76e4be384b3e4cc93446e432e3c9b3a40d4188428858fb016d032169878` |
  | `train_evidence/ambiguous_candidates.csv` | `eb54832e23024e6be81c65f5ee979cba4eedaa4084e8cefb1d5bee63fad9707d` |

  - Provenance: the bounded 1s parity replay in §3, run in Claude session `d3759a78-419b-4494-8051-925b4e364252`.
  - The session's scratchpad originals are byte-identical.
  - They are committed byte-exact (CRLF), staged with `-c core.autocrlf=false`, so the committed blobs carry the hashes above.
- **Local only, not durably backed up:** the TRAIN partitions, merged artifacts, controller receipts and manifests under `_work/controller/`.
  - They are gitignored by design and exist only on this machine's disk.
  - Their hashes are recorded in `train_evidence/artifact_manifest.json`, but a hash manifest is not a backup.
  - If lost, they can only be recovered by deterministic re-collection under the frozen identity, with the manifest hashes as the acceptance check.
  - No archive has been made: no approved archive destination exists.

## 6. Ungoverned post-seal artifacts (not adopted)
After the TRAIN merge, the previous owner (antigravity) left the files below in this worktree.

**Classification: UNAUTHORIZED / NOT VALIDATED / NOT APPROVED FOR PROMOTION.**
- None of them is committed, and none is cited as study evidence.
- None was executed or adopted in this correction.
- They were preserved in place, without deletion or modification.

Hashes recorded 2026-10-11:

| path (repo-relative) | SHA-256 |
|---|---|
| `scripts/analyze_mechanism_findings.py` | `7fcfb64eb6a7be573126270aa2b132dd862d91655d6ee364bf41d862770a42fd` |
| `scripts/compute_mechanism_discovery.py` | `a4fa7680ec66b387d0c862b96c629b1c802c5e3cc1aeed3ca67ea00e5d601a37` |
| `scripts/pilot_entry_discovery.py` | `8ade6b3883dac32e516978205142047902c20e31e6c693da02ddc0189baacf26` |
| `scripts/repair_mechanism_inference.py` | `44a7343b833d42e9e3d386bacc5ae55214aeae4fd7e69e38950667a9d810f999` |
| `scripts/run_native_nt_validation.py` | `6fb96a1723bc963af13327a4f2255cb7d0ee80a4649719135e7f4b8b8aa4dc3a` |
| `scripts/run_train_nt_validation.py` | `8047203fcd0c2d5b92f197d88c2bfe953dcd5e21a6abe669b18771326edee6a0` |
| `…/artifacts/train_scientific_analysis.json` | `620e50286f2d4d607f5b5166c8c7252d8d9997b24e6298a998bafc869325d2d6` |
| `…/audit/mechanism_discovery/dev_evaluation_frozen_contract.json` | `cec6823e3bf9f2ab1ecd2e0ecf00a19d9e935e2845bc62d4e6370a527c53a181` |
| `…/audit/mechanism_discovery/mechanism_study_packet.json` | `28888edbec5b07dae5f51b0674c7ce8b0980edbf38e234ba3f4577f047730b6a` |
| `…/audit/mechanism_discovery/pilot_entry_discovery_oct2023.json` | `e5c9e6d32ce5f31a9803211fcf98899971c1bb565d6a672cb7f3616848e74d64` |
| `…/audit/mechanism_discovery/repaired_decision_packet.json` | `f1a1ea7e78f5a34373189180898e1f08a2d16b19d1ba3a3aad9c850aa326a5c6` |
| `…/audit/native_nt_execution/EXECUTION_ASSUMPTIONS.md` | `8dc913d973dc43ff23fc341d437ee7007b4c2f0e13eddfb98597f772fbb84072` |
| `…/audit/native_nt_execution/events_20231012_A1_A2_SHORT_ONLY.json` | `bd3e462882c9a1f330ba43ce060e88248171a79a56d2329050b6f6c1656e43e6` |
| `…/audit/native_nt_execution/final_acceptance_summary.json` | `b770b64e28c7798c020b31e6befad6ccaf778f7b39b15de5a73c13d256b6a958` |
| `…/audit/native_nt_execution/october_smoke_summary.json` | `c7169fe4949d488859769b36dfc8403a7e84b691a343b02f3c7d75a94a12d21c` |
| `…/audit/native_nt_execution/order_events_20231012_A1_A2_SHORT_ONLY.json` | `b38d0d476ef6c21c3fde7def3ce907d3efe90a80cf03e216c8451288215f3a05` |
| `…/audit/native_nt_execution/position_events_20231012_A1_A2_SHORT_ONLY.json` | `6175b7af4004feef1a7712fac2d173584d9285fdffcae9ae68ddc76844fbaf7f` |
| `…/audit/train_execution/2021/summary_2021.json` | `4993bb8c9799db8f74de6e317d033b38876e1c0db26914f07072c6cd03eacd32` |
| `…/audit/train_execution/2022/summary_2022.json` | `844855b82ba0ce16a42242d80663673330589b1e310bae16f5d0ba4011961fc0` |
| `…/audit/train_execution/2023/summary_2023.json` | `365a07b04bb9671ea9d40384f224aaafdff0c264fe2803dff60dc2945c4a295a` |
| `…/audit/train_execution/train_execution_manifest.json` | `5be0043a1d786de167f88bb1413f9262b20cffc5b6b690dee15b1166c42922b3` |

The same directories also hold gitignored files, which are not hashed here:
- `audit/mechanism_discovery/augmented_trajectories.parquet`;
- 8 CSVs in `audit/native_nt_execution/`;
- 18 CSVs in `audit/train_execution/<year>/`.

`dev_evaluation_frozen_contract.json` declares 2024 as a "DEV" evaluation year with a self-assigned status of `SEALED_PRE_EXECUTION`.
- The experiment authorization makes 2024 the OOS year.
- That contract is not authorized and has no governed standing.
- No 2024 output exists anywhere under this study directory.

The platform has no sanctioned quarantine or classification mechanism for unowned study artifacts. The six `scripts/*.py` files therefore keep the controller at `WORKTREE_CONTAMINATION`. The controller auto-owns `studies/nq_fair_pricing_reversion/`, so the study-directory items do not trip it.
- `--owned-path` is documented for intentional local edits by the owner. It was not used to declare these files owned.
- No ignore rule was added.

## 7. Corrections to `c9bb2cb2`
- `reconcile.json`, `nq_1m` and `research_workflow` were mangled by shell escaping. They are restored.
- The prices in §3 were corrupted by dollar-sign escaping. The 2023-10-12 discussion is rewritten in §4.
- The "shared recovery arms masked an adverse stop" claim is withdrawn as unsupported.
- The 2023-10-30 native-execution paragraph is withdrawn because it rested on an unvalidated, ungoverned artifact.
- The durability statement was wrong. `_work/controller/` is local only and not backed up.
- The frozen identities were missing. They are added in §0.

## 8. Technical debt
- The seal pins the raw-byte hashes of `audit/status.json` (`8fbde36b…`) and `audit/contract_status.json` (`6196bb6d…`).
  - These hashes match only the CRLF working copies.
  - The committed blobs are LF (`ea359974…`, `89c28547…`) under `core.autocrlf=true`, so the seal verifies only on a CRLF checkout.
- This is tracked for a separately authorized chore. This correction makes no `.gitattributes` change and no reseal.
