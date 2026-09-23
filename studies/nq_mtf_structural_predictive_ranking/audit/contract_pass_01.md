audit_type: contract
study: nq_mtf_structural_predictive_ranking
auditor: contract-checker (pass 01)
audited_execution_composite_sha256: 6ced7ced583a3a877a451a373b2350edc7807db3471005b74c7e1cdb1c9a924a

Scope note: `_work/controller/audit_packet_contract.json` is absent; used
`audit_packet_causal.json` for packet shape/identity per the task instruction. No
`config/deliverables_contract.json` exists for this study and it has not reached a collect/fit
run this session (no `runs/`, no model artifacts, no freeze receipt) — deliverable-existence
checks (item 5) are therefore N/A this pass; nothing to flag as premature.

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Split: fit 2023 only, 2024 scored once after freeze | PASS | `study.yaml:470-474` `validation.tuning_years:[2023]`, `final_train_validation_years:[]`; identical in `compiled_plan.json:1730-1738`; `year_role_table` (compiled_plan.json:1739-1752) has no 2024 entry at all, so 2024 carries no fit or eval role yet | causal packet `model.validation.year_role_table` matches | none |
| `final_train_validation_years: []` reflected (explicit owner decision) | PASS | `study.yaml:474`; `compiled_plan.json:1731` | packet `model.validation.final_train_validation_years:[]` | Record this decision explicitly in `research_decision.yaml` (currently only the old `[2024]` mechanism text at line 29 exists — see FAIL below) |
| Frozen 78-column feature surface + order | PASS | `study.yaml:391-469` (78 entries, `&id001`) byte-identical in order to `compiled_plan.json:1628-1707` and arm `full` (`compiled_plan.json:1434-1513`) | n/a (static compile) | none |
| Four arms: full, direction_only, mtf_state_only, geometry_no_direction | WARNING | `compiled_plan.json:1517-1538`: `direction_only` and `mtf_state_only` declare the **identical** 4-column feature list `[dir_1m, dir_5m, dir_15m, dir_1h]`. `research_decision.yaml:42` calls for `exact_MTF_state_only (16-cell categorical)` — a joint encoding of the 4 directions, not a duplicate of `direction_only`'s raw columns | none (arms not yet fit) | Encode `mtf_state_only` as one categorical joint-state column (16 levels) per the decision doc, or strike the duplicate control before fitting — as declared, any 2023 delta between these two arms is dead by construction (same features, same fixed hyperparams, same `random_state:42` ⇒ deterministically identical fit) |
| Cell t0, fixed hyperparams, `search_space: none` | PASS | `compiled_plan.json:1618-1626` (`t0`, `checkpoint_index:0`); `params` block lines 1710-1719 all fixed; `search_space: {}` line 1721 | packet `model.params`/no search block | none |
| Target A only this session; B–E not declared | PASS | `study.yaml:568-570` and `compiled_plan.json:1722-1729` declare only `A_win: terminal_gross_pnl_atr > 0`; no `targets:` list, no B/C/D/E expr anywhere in study.yaml or compiled_plan.json | grep for `fav_2p00`/`fav_3p00`/`fav_5p00`/`adv_2p00` as *model* targets: none found (those ids only exist as pre-existing outcome-kernel barrier arms, not model targets) | none |
| Partition provenance: original identity + re-attestation | PASS | `artifacts/partition_reattestation.json` records, per partition, `recorded.plan_sha256` (2023: `4e7538b4…`, 2024: `c408c4d9…`), `recorded.candidates_sha256`/`observations_sha256`, `composite_seal_hash`, plus `current.*`, `closure_delta` (membership_identical, composite hashes), `equivalence_proof` (bounded-replay byte equality, both `candidates_sha256`/`observations_sha256` match, `rows` match), and `authorization_equivalence` (`year_roles_identical: true`, only `study_id`/`study_path` differ) | verdict `REUSABLE_BY_CLOSURE_ATTESTATION` both years | none |
| Installed partition manifests still carry original atlas plan_sha256 | PASS | `_work/controller/partitions/train/2023/manifest.json:15` `plan_sha256: 4e7538b459db82aef27bda64ae4a800c563d022156b09945227ab5d5bd580372`; `.../2024/manifest.json:15` `plan_sha256: c408c4d9fe81a36136d614e6e47f71f002e6c5377915fbca846b2abee7824679` — both match the requested `4e7538b4`/`c408c4d9` exactly, and their `candidates_sha256`/`observations_sha256` match the reattestation's `recorded` block byte-for-byte | n/a | none — confirms no re-collection or rewrite occurred |
| TRAIN/OOS/prohibited disjoint; 2025/2026 untouched; no `mode: score`; no analysis block declared | PASS | `artifacts/experiment_authorization.json`: `train_years:[2023,2024]`, `oos_years:[]`, `prohibited_years:[2025,2026]` — disjoint; `study.yaml` `model.mode: train` (line 380); no `analysis:` key anywhere in `study.yaml`; no `runs/` directory exists (nothing executed) | tests 158/0 pass per causal packet `tests.status: PASS` | none |
| Deliverables sequencing (2023 dev metrics → freeze receipt → single 2024 score) | N/A this pass | No `runs/`, no `train_experiment_freeze.json`, no model artifact exists yet — this session produced only governance/plan artifacts | n/a | Re-check on the next pass once a fit is attempted; do not allow a 2024 scoring call before a freeze receipt exists |
| `research_decision.yaml` status field current | FAIL | `research_decision.yaml:4` still reads `status: BLOCKED_REUSE_AND_TARGET` and its `blockers_found_pre_fit` block (lines 79-116) is presented as open, but `study.yaml`/`compiled_plan.json` (target `A_win` declared) and `artifacts/partition_reattestation.json` (`REUSABLE_BY_CLOSURE_ATTESTATION`) show both B1 (replay-closure reuse) and B2 (no trainable label) were in fact resolved this same session (`artifacts/reuse_and_target_blockers.json` records the pre-resolution state; git log shows `b5bc1a2f model.target derived from collected columns + partition re-attestation` merged after it). The authoritative decision contract was never updated to say so | none | Append a short "Phase A resume 2" block to `research_decision.yaml` recording `status: <new>`, the target-derivation mechanism, and the re-attestation verdict, so the authoritative file matches the artifacts it governs |
| `CAPABILITY_GAP_HANDOFF.json` currency | WARNING | File still declares `state: BLOCKED_ON_CAPABILITY_GAP`, `no_work_performed` (all null) and `next_session: platform chore... fresh study session compiles this study` — stale: the capability landed on `main` (`ff47868d`) and this same worktree already compiled the plan, reattested both partitions, and declared the target | none | Regenerate or delete this handoff file (or add a superseding entry) so a future session/agent does not re-open a gap that is already closed |

## Referred to lookahead-auditor
None — no new look-ahead theory found beyond what SPEC/`research_decision.yaml` already names.

## Blocking verdict

**BLOCKED.**

The compiled plan is faithful to `research_decision.yaml`'s split, frozen 78-column surface and
order, fixed hyperparameters, single Target A, and the `final_train_validation_years: []`
owner decision; partition provenance for both 2023 and 2024 is fully documented and the
installed manifests prove no re-collection occurred. However: (1) the `mtf_state_only` control
arm is byte-identical to `direction_only` rather than the declared 16-cell joint-categorical
encoding, which would make any 2023 arm-delta between them structurally dead rather than
informative and needs a fix before any fit is run; and (2) `research_decision.yaml`, the
authoritative decision document, has not been updated to reflect that both of its own recorded
blockers (B1 replay-closure reuse, B2 no trainable label) are now resolved on disk — a
governance-currency defect independent of the arm bug. Neither finding blocks on causal
grounds; both should be closed before a fit is attempted.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "contract", "audited_execution_composite_sha256": "6ced7ced583a3a877a451a373b2350edc7807db3471005b74c7e1cdb1c9a924a", "auditor": "contract-checker-pass01", "critical": 0, "note": 0, "study": "nq_mtf_structural_predictive_ranking", "verdict": "BLOCKED", "warning": 3}
<!-- AUDIT_SUMMARY_V2_END -->
