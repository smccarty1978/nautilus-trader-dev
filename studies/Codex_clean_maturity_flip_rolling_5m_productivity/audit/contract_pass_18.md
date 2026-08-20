# Contract Pass 18

**Reviewer identity:** contract-checker-pass18-smccarty (distinct from any causal-audit identity used on this study)
**Study:** Codex_clean_maturity_flip_rolling_5m_productivity
**Scope:** C4, D, E, and the SPEC.md Deliverables Manifest (`docs/CAUSAL_CHECKLIST.md`).

## Adjudication of pass 17

Pass 17 (`audit/contract_pass_17.md`) recorded 0 CRITICAL / 0 WARNING — CLEAR, no findings raised. Nothing
to adjudicate.

## What changed since pass 17

Only `study.yaml`'s `execution.data_requirements.authorized_dates` field was added (5 dates,
2023-10-02..2023-10-06). Verified directly:

- `studies/Codex_clean_maturity_flip_rolling_5m_productivity/study.yaml:69-80` — the new field sits under
  the pre-existing `execution` block, alongside unchanged `runtime`, `strategy_class`, `progress_seconds`,
  `bounded`.
- `population`, `target`, `features` (`selection.mode: train_only`, `years: [2021,2022,2023]`,
  `forbidden_lineage`), `model.arms`, `chronology` (`train: [2021,2022,2023]`, `dev: [2024]`,
  `prohibited: [2025,2026]`), `stratification`, and `lineage` blocks are byte-identical to what pass 17
  audited — confirmed by full-file read, no other lines differ.
- `research_decision.yaml` (chronology, baseline, model_arms A/B/C, prohibited_changes,
  allowed_changes) is unchanged and matches `study.yaml`'s chronology exactly.

### Mechanism verification — `authorized_dates` is a narrowing-only execution bound

`backtests/nt_runtime/data_plan.py:22-82` (`resolve_authorized_dates`/`enforce_authorized_dates`):
- Returns `None` (no additional restriction) when the field is absent — pre-existing year-level chronology
  gates remain the sole authority for any study without it.
- When present, `enforce_authorized_dates` raises `UnauthorizedExecutionDomainError` unless **every** requested
  calendar day is in the declared list (line 75-81) — it can only shrink the runnable date domain within an
  already-chronology-authorized year, never expand it. There is no code path in this function or its caller
  that widens a year-level authorization.
- The design comment at lines 26-32 explicitly documents why this lives inside the existing free-form
  `data_requirements` field rather than a new top-level schema field: to keep the SHA-256 delta scoped to
  this study's own `spec_sha256`, not force every other study's `compiled_study.json` stale. Confirmed this is
  the same mechanism `studies/es_wick_imbalance_acceptance_v2/study.yaml:45` already uses.

### Recompiled artifact re-check

`studies/Codex_clean_maturity_flip_rolling_5m_productivity/compiled_study.json:88-157` — `chronology.train`
is `[2021,2022,2023]`, `dev` is `[2024]`, `prohibited` is `[2025,2026]` (unchanged); `execution.data_requirements
.authorized_dates` lists the same 5 October-2023 dates from `study.yaml`. All 5 dates fall inside the TRAIN
year 2023 — none touch the 2024 dev/OOS year or the 2025/2026 prohibited years. `selection_mode`,
`ranking_method`, `forbidden_lineage`, and `model.arms` in the compiled artifact are unchanged from what pass
17 audited.

`studies/Codex_clean_maturity_flip_rolling_5m_productivity/audit/preflight.json` — `status: CLEAR`,
`RESEARCH_DECISION_FIDELITY: PASSED`, `execution_composite_sha256:
278ae56d33371fbc15f2278834bdd8057d86a9863f3532fa616e123827c13b64` — matches the composite declared in this
pass's task instructions and this report's summary block.

### Deliverables Manifest / promotion-gate consistency

`SPEC.md`'s literal Deliverables Manifest (§"Deliverables Manifest", unchanged lines per pass 17's citation)
makes no reference to execution date scoping and did not need to — `authorized_dates` is an execution-time
smoke-run bound, not a deliverable, population, feature, or promotion-gate definition. No line in `SPEC.md`
or `research_decision.yaml` was touched by this change (confirmed: only `study.yaml` differs from the pass-17
tree). This study still has no `config/deliverables_contract.json` anywhere in the repo (confirmed absent at
repo root and at the study path); this was already adjudicated WITHDRAWN at pass 17 citing the pass-01/pass-12
literal-SPEC-manifest remediation — not re-raised here per the re-audit protocol (no re-raising an
already-adjudicated finding under new framing).

No real NT run, collection, fit, or score has occurred under this study (only the `_work/exploratory_*`
diagnostics from prior passes exist, all mode-stamped `EXPLORATORY — CONTRACT GATE BLOCKED`). Absence of
`artifacts/model_manifest.json`, `artifacts/score_manifest.json`, `artifacts/result_seal.json`,
`artifacts/promotion_gate.json`, `collection_manifest.json`, or any structural_coverage/frozen_top25 output
from a genuine run is correctly not a finding — the study is pre-execution and this pass's authorized change
is exactly the date-bound intended to scope an upcoming smoke run.

## New findings this pass

None. No new blocking or warning findings identified within C4/D/E/Deliverables-Manifest scope.

## Referred to lookahead-auditor

(none)

## Blocking verdict

CLEAR

The only change since pass 17 — `study.yaml`'s new `execution.data_requirements.authorized_dates` (5 dates,
2023-10-02..06) — is verified to be a narrowing-only execution-time bound implemented by the repo's standard
`resolve_authorized_dates`/`enforce_authorized_dates` mechanism, applied identically to
`studies/es_wick_imbalance_acceptance_v2`. All 5 dates fall inside the already-authorized TRAIN year 2023; the
OOS year 2024, the prohibited years 2025/2026, `forbidden_lineage`, feature selection mode, model arms, and
every other frozen research-contract element in `SPEC.md`/`research_decision.yaml`/`compiled_study.json` are
byte-identical to the pass-17-audited state. Research-decision fidelity re-ran PASSED and deterministic
preflight re-ran CLEAR with a composite hash matching this report's summary block. The Deliverables Manifest
remains internally consistent with the now-compiled study; no execution artifacts exist yet, correctly, since
this study remains pre-execution.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "contract-checker-pass18-smccarty", "blocking": 0, "warning": 0, "note": 0, "study": "Codex_clean_maturity_flip_rolling_5m_productivity", "audited_execution_composite_sha256": "278ae56d33371fbc15f2278834bdd8057d86a9863f3532fa616e123827c13b64"}
<!-- AUDIT_SUMMARY_V2_END -->
