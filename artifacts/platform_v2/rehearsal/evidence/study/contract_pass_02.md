# CONTRACT AUDIT pass 02 — `rehearsal_checkpoint_norm`

auditor `contract-checker:owner-pass02-20f45ea6` · composite `73db2ed0f21316e4c0a5b04790a37910824f37dc67d964a30d020c39dc6b75f7` (confirmed from `audit/frozen_execution_manifest.json:121`, unchanged since pass 01) · repair commit `3b63ccd2` · spec `a20e2be9efe2` (moved from `3af9393f69cc`) · plan `9eb2ff0d6e63` (moved from `50c8e6667a90`)

Gate facts unchanged and re-cited, not re-derived: preflight CLEAR, readiness PASS, tests 137/0, causal audit CLEAR at the same composite. Note: `_work/controller/audit_packet_contract.json` on disk still carries the **pre-repair** `plan_sha256 50c8e6667a90…` and `model.validation` block — it was not regenerated after `3b63ccd2`. Findings below are adjudicated against the current `research_decision.yaml`, `SPEC.md`, `study.yaml` (all read post-repair), not against that stale packet.

## Adjudication of pass-01 findings

- **CRITICAL-1 (treatment variable absent from compiled contract) — FIXED.** `research_decision.yaml:3-19` now carries the RATIFIED DEVIATION note and a SINGLE-ARM `research_question` naming exactly the three surviving instances; `structural_max_expansion_checkpoint_atr` is declared WITHDRAWN and its question left OPEN, not answered. `SPEC.md:5-21` mirrors this verbatim. `study.yaml:7,26-30` matches. The deviation is now ratified at the top-precedence document, not only `study.yaml`.
- **WARNING-2 (terminal vocabulary blind to the scope loss) — FIXED.** `research_decision.yaml:28-29` / `SPEC.md:117-118`: `REHEARSAL_COMPLETE` now requires the fitted feature surface be EXACTLY the three ratified instances (named), and `REHEARSAL_INCOMPLETE` fires on a surface mismatch or on any report claiming the withdrawn contrast. `SPEC.md:157-164` additionally requires phase D to report the fitted surface explicitly.
- **WARNING-3 (selection protocol with no candidate set) — FIXED.** `study.yaml:48-54` has no `validation:` block; the comment records why (single fit, fixed params, `WARNING-3` cited by name). `compiled_plan.json` per the repair report resolves `model.validation: null`. I did not re-open `compiled_plan.json` to re-verify this single field beyond the repair worker's cited bounded-check output (`STATUS: COMPILED`, `model.validation: null`), which is consistent with `study.yaml`'s absence of the block — this is corroboration, not independent re-derivation, and is noted as such.
- **NOTE-1 (censoring disclosure) — FIXED.** `SPEC.md:157` adds `excluded.rows_non_binary_label` to the required phase-D report.
- **NOTE-2 (unreachable GAP censor reason)** — WITHDRAWN as a pass-02 item; unchanged, benign, already disclosed in pass 01. Carries forward unaltered.
- **NOTE-3 (analyze deliverable list under-describes the two artifacts)** — known packet-completeness observation per this pass's brief; not re-litigated.

## New findings

None. The repair swept all four pass-01 findings at the correct precedence level, and no new C4/D/E defect is introduced by the diff (`git show 3b63ccd2` touches only `research_decision.yaml`, `SPEC.md`, `study.yaml`, `compiled_plan.json` — no execution-closure file).

## Verification detail

- Chronology unchanged and re-confirmed from `study.yaml:43-47`: TRAIN `[2023]`, DEV `[2024]`, prohibited `[2020,2021,2022,2025,2026]`, `authorized_dates: ['2023-03-01']` (inside TRAIN), no `chronology.windows`. Disjoint; matches `experiment_authorization.json` cited in the brief.
- C4: with `model.validation` removed there is no selection protocol left to authenticate a selected result — C4's selection-seal clause is now `NOT APPLICABLE` rather than the pass-01 `WARNING`. Single deterministic fit (`random_state: 42`, `n_jobs: 1`, `deterministic: true`) with fixed hyperparameters is not a walk-forward/selection scheme, so the "does not refit on test-overlapping data" clause is satisfied by construction (train 2023 only, dev 2024 never fit).
- D: TRAIN/OOS separation unaffected by the repair (chronology block untouched); repair commit is study-contract-only per its own diff description, execution composite unchanged confirms no closure file moved.
- E: no backtest orders/fills in this collection-only rehearsal (unchanged from pass 01, `NOT APPLICABLE`).

## Not applicable

Same set as pass 01: D1, D3, E3/E4, seal freshness / TRAIN-freeze-before-OOS / `derivation_population` / `forward_outcome_manifest.json` (all post-date this pre-execution audit), per-study `config/deliverables_contract.json` (V1 artifact).

## Referred to lookahead-auditor

Nothing new.

## Blocking verdict

**CLEAR.** All four pass-01 findings are fixed at the document that actually binds (`research_decision.yaml` and `SPEC.md`, not `study.yaml` alone): the treatment-variable removal is now ratified at top precedence with the checkpoint-ATR question left explicitly OPEN, `REHEARSAL_COMPLETE`/`REHEARSAL_INCOMPLETE` now cover the exact feature surface, the inert selection protocol was dropped rather than left dangling, and the phase-D censoring disclosure requirement was added. The execution composite is unchanged and every deterministic gate (preflight, readiness, tests, causal audit) remains passing at it. One hygiene item for the record, not a finding: `_work/controller/audit_packet_contract.json` is stale (still shows the pre-repair plan hash and the dropped `model.validation` block) — it should be regenerated before seal so a future reader does not trust it over the source documents.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "contract-checker:owner-pass02-20f45ea6", "critical": 0, "warning": 0, "note": 1, "study": "rehearsal_checkpoint_norm", "audited_execution_composite_sha256": "73db2ed0f21316e4c0a5b04790a37910824f37dc67d964a30d020c39dc6b75f7"}
<!-- AUDIT_SUMMARY_V2_END -->
