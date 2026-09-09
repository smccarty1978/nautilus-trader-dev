# AUDIT BRIEF 005_contract_audit_f4bffac6 -- CONTRACT audit, pass 01, study `rehearsal_checkpoint_norm`

You are `contract-checker` (owns C4, D, E + deliverables, lifecycle state, model-integrity declarations). This brief is the SMALLEST packet sufficient to verify the changed executable surface.
Read it, then the audit packet it names, then your role file. Do NOT re-discover the repository.

## 1. Facts the deterministic gates already proved (do not re-derive; cite them)

- audited execution composite (declare exactly this): `73db2ed0f21316e4c0a5b04790a37910824f37dc67d964a30d020c39dc6b75f7`
- plan_sha256 `50c8e6667a90124b06d78c7a1c1981ec67c741d4c7f1d1c0cbc93ef7fad16de3`  spec_sha256 `3af9393f69cc0ff384ba3bd2248a88ec713be074465eb29be11b382c24804945`  closure files 115 (hash v2)
- preflight: CLEAR (8/8 required checks PASSED; leaked_outcome_columns=[]; composite 73db2ed0f213)
- readiness: PASS (R1_NQ=pass, R8_host_boundary_lint=pass, R5_binding_proof=pass, R3_session_table=pass, R9_closure_current=pass, R10_zero_study_python=pass; composite 73db2ed0f213)
- tests: PASS 137 passed / 0 failed @ composite 73db2ed0f213 (6 files)
- controller: STATUS=OK state=NEEDS_CONTRACT_AUDIT stage=contract_audit blocker=None; fingerprints execution_composite=73db2ed0f213 current=73db2ed0f213 plan=50c8e6667a90 spec=3af9393f69cc
- worktree `C:\Users\Scott McCarty\Projects\Nautilus Trader-rehearsal_checkpoint_norm` branch `study/rehearsal_checkpoint_norm` @ `5ae67a7d7a7fc3d3365091b59ae00330348f136b`; dirty paths: 2 (listed in the packet; all under studies/ unless noted)
- experiment_authorization.json: {"train_years": [2023], "oos_years": [2024], "prohibited_years": [2020, 2021, 2022, 2025, 2026]}
- audit/status.json: verdict=CLEAR auditor=`lookahead-auditor:004_causal_audit_300a825d` composite 73db2ed0f213 (critical 0 / warning 0 / note 2)

Deliverables declared for the stages that already ran (mechanical existence check). A V2 study has no per-study `config/deliverables_contract.json` (that is the V1 artifact): `packet.deliverables_by_stage` IS the contract, so its absence is not a finding:

| stage | deliverable | present | bytes |
|---|---|---|---|
| compile | `compiled_plan.json` | yes | 50604 |
| prepare | `audit/frozen_execution_manifest.json` | yes | 24787 |
| prepare | `artifacts/experiment_authorization.json` | yes | 436 |
| readiness | `audit/readiness.json` | yes | 1413 |
| preflight | `audit/preflight.json` | yes | 1022 |
| tests | `_work/controller/test_summary.json` | yes | 1889 |

## 2. Audit packet = the compiled semantic contract (primary surface)

- `C:\Users\Scott McCarty\Projects\Nautilus Trader-rehearsal_checkpoint_norm\studies\rehearsal_checkpoint_norm\_work\controller\audit_packet_contract.json` (17705 bytes, sha256 `d8bc4939304eddd6340111f9e8fd43bb7d273fb89549a0a009b376027e9b07ab`, packet_version 2)
- Its `instructions` field describes the MANUAL flow (audit/pass_NN.md + `research audit ingest`); under the supervisor the report path and result card in your worker packet take precedence. Never write under studies/<id>/.
- `packet.closure.stages` lists every closure file per stage; `audit/frozen_execution_manifest.json` carries the per-file hashes. Open it only to verify a membership claim -- never compute closure membership yourself (Python is not on your allowlist).

## 3. Executable surface: what changed

- closure per stage: audit 1, collection 100, lifecycle 12, modeling 5, oos 6, outcome 4, replay 92; composite `73db2ed0f213`
- first pass of this kind under the supervisor: no prior manifest snapshot; the surface is the full closure named in the packet
- closure files the STUDY BRANCH changed against `main`: none (the platform under audit is main's)
- Every other closure file is unchanged since the last audit / since main and needs NO re-read. Open a source file only for a claim the packet cannot prove, and cite `file:line`.

## 4. Prior findings to adjudicate FIRST (pass 01)

- none: this is pass 01. Adjudication table not required.

## 5. Your checklist subset (verbatim from docs/CAUSAL_CHECKLIST.md; `lookahead-auditor` owns the rest -- refer, never report)

## C. Label construction

- **C4.** *(contract-checker scope)* Walk-forward validation does not refit on
  data overlapping the test window; selection seals authenticate their own
  selected result; promotion gates implement every frozen check.

## D. Train/serve skew *(contract-checker scope)*

- **D1.** Features computed offline match features computed live in the
  strategy's `on_bar`.
- **D2.** Filter cascades are trained on the *post-filter* distribution.
- **D3.** ONNX exports were made from the same model object whose features were
  validated.
- **D4.** Categorical encodings, missing-value imputation and feature ordering
  are deterministic and identical between train and serve.

## E. Backtest configuration *(contract-checker scope)*

- **E1.** Bar subscriptions in the strategy match the bar type produced by the
  data client.
- **E2.** `BarAggregation` and `PriceType` in `BarType` strings match the data
  being loaded.
- **E3.** Simulated venue uses an appropriate fill model — `LIMIT` orders do not
  auto-fill at signal price.
- **E4.** Order submission inside `on_bar` does not assume the bar that just
  closed is also the bar at which entry happens — entry occurs at the **next**
  bar's open.
- **E5.** Initial bar warmup for indicators is respected.

## Severity definitions

| Severity | Meaning | Gate effect |
|---|---|---|
| `CRITICAL` | Demonstrated defect that changes results, or an unenforced invariant the study's conclusion depends on | Blocks |
| `WARNING` | Real defect that does not change the headline result, or an enforced-in-practice-but-not-in-code invariant | Blocks unless explicitly adjudicated in the SPEC |
| `NOTE` | Disclosure, hygiene, or inherited upstream limitation | Does not block |

A finding is `CRITICAL` only if you can state a concrete failure path. "This is
not independently validated" is a `WARNING` unless you can show the validation
would fail.

## 6. docs/RESEARCH_WORKFLOW.md section 6.2 -- which model-integrity controls are gates, diagnostics, recommendations

### 6.2 Model integrity — gate, diagnostic, or recommendation

Be precise about which of the three a control actually is.

**Implemented hard gates** (fail closed, inside the lifecycle):

| Control | Where |
|---|---|
| Declared feature contract == produced surface; an **all-null column is refused under either null policy** | `scripts/check_feature_surface.py`, in `OutputManager.persist_collection` and re-derived in `scripts/validate_smoke.py` |
| Forward-outcome columns may not enter a fit matrix or a frozen feature set | `forward_outcomes/guard.py` via `modeling.fit_models` and `freeze_train_artifacts` (§10) |
| Outcome columns in `X` rejected at fit time | `research/analysis/modeling.fit_model` (`SchemaSurplus`) |
| TRAIN and DEV may not appear in one fit | `fit_model` (`PartitionMixing`) |
| Refuses to fit without partition provenance | `fit_model` (`PartitionProvenanceMissing`) — a missing `_partition` column is not evidence of a single partition |
| Threshold freeze requires TRAIN-only scores, records `derivation_population` | `research/analysis/modeling.freeze_threshold` |
| Declared arms must request features the collection provides | `resolve_arms` (`SchemaMissing`) |
| Model/feature-order binding, binary classes, `predict_proba` | `scripts/check_model_binding.py` |
| `train_test_split(shuffle=True)` on temporal data | `causal_lint.py` rule C3, CRITICAL |
| Degenerate slice surfaces a caveat, not a silent single group | `research/analysis/slices.py`, `reporting.py` |

**Available diagnostics** (real, but not unconditional gates): see §11 diagnostics table.

**Recommended integrity checks** — the study performs and reports these; they are **not**
mechanically enforced, and must not be described as gates:

- every declared feature is populated where its semantics require a value
- every required feature has variance on the fitted population
- each arm has the feature surface it claims — two arms with identical
  `fit_identity_sha256` / `prediction_identity` mean the added block is dead
- score surfaces are nondegenerate; frozen thresholds and deciles are nondegenerate
- a shuffled-label run behaves near chance when performed
- temporal validation is chronological
- suspiciously strong single-feature power triggers inspection before it is reported

A study reporting an arm delta must state which of these it verified. An unverified delta is a
hypothesis, not a result.

---

## 7. Bounded procedure (mandatory)

1. Do not reopen unchanged files. Section 3 names what changed; everything else was audited at the prior composite or is main's platform.
2. Use packet references first: streams/visibility, trackers, outcome kernel, chronology, closure membership, deliverables all come from the packet and this brief.
3. Inspect source only for a claim the packet cannot prove (state flow, callback order, a write site). Read the smallest range; cite `file:line`.
4. Stop when every rule id in section 5 is under `Clean checks`, a finding, or `Not applicable`. Then write the report and the result card.
5. No speculative architecture findings. A finding needs a concrete failure path (CRITICAL) or a real defect (WARNING); hygiene is a NOTE.
6. Do NOT read WORKFLOW.md, AGENTS.md, docs/RESEARCH_WORKFLOW.md, docs/CAUSAL_CHECKLIST.md, PLATFORM_STATE.json or compiled_plan.json: this brief carries the subset you need. compiled_plan.json only for a specific field the packet omits.
7. Do not run Python (`python -c`, heredocs), PowerShell variable assignments or recursive listings: the read-only allowlist denies them and every denial costs a turn. The only commands you need are `python scripts/research.py study result ...` and, if useful, `git diff`/`git log`/`git status`.
8. Keep `--notes` / `--next-action` free of `;`, `|`, `&`, `>` characters (compound commands are refused by the allowlist); keep them under 300 characters.
9. Report budget: causal 1,500 words / contract 1,000 words. Write the report to `C:\Users\Scott McCarty\.nt_research\supervisor\rehearsal_checkpoint_norm\results\005_contract_audit_f4bffac6.report.md` and declare auditor `contract-checker:005_contract_audit_f4bffac6`.
