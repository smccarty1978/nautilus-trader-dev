# Contract-checker — Pass 1 (pre-execution)

Scope: deliverables/manifest/seal completeness, terminal-label
reachability, C4/D/E applicability.

## Scope confirmation (C4/D/E)

Confirmed N/A. SPEC §1.1 states explicitly "This study performs no
trade-lifecycle simulation — it is a join and stratified aggregation of two
already-closed, already-audited artifacts." §10 forbids any exit
rule/policy. No `BarType`, fill model, or backtest config appears anywhere
— E fully inapplicable. No model training/scoring/ONNX/encoding path — D
fully inapplicable. No walk-forward split or promotion gate — C4 fully
inapplicable.

## Findings

| # | Requirement | Verdict | Evidence | Remediation |
|---|---|---|---|---|
| 1 | §6 terminal-label reachability | WARNING | The `C5` condition text ("checked before Phase 12 is even needed") contradicts the evaluation-order summary line ("C1 → C3 → C2 → C4 → C5, checked last"). Two mutually exclusive statements about whether C5 is a pre-Phase-12 short-circuit or the final residual check. | State one evaluation order only. |
| 2 | §7 item 17 `primary_table.csv` | WARNING | Only a prose description, no explicit `population_definition`/`group` columns, while Phase 0 mandates every Phase 2-11/13 output carry `population_definition`. | Add explicit column list including `population_definition, group`. |
| 3 | §7 item 18 `opportunity_capture_summary.csv` | WARNING | Same gap as #2, on the other designated primary table. | Add explicit column list including `population_definition, group`. |
| 4 | Phase 11/Phase 12 bucket-name collision | WARNING | Phase 11's `runner_bucket`/`mfe_bucket` is built on retrospective `eventual_max_mfe_atr` (LABEL_ONLY, gate V-LABEL). Phase 12 separately reuses "the `<1/1-2/2-3/>=3` scheme" for `walk_a_mfe_to_confirm_atr` (confirmation-time-only, gate V-MATCH, stop condition 5). The shared informal name risks an implementer conflating the retrospective field with the confirmation-time stratum. | Give Phase 12's variable a distinct name (`confirm_mfe_bucket`); drop the "mfe_bucket" alias from Phase 11's text. |
| 5 | Phase 8 audit-scope coverage | WARNING | §9 exempts Phases 3/4/8/9/10 from fresh causal proof as "direct reads." But Phase 8 performs genuinely new derived logic — a boolean complement restricted to resolved observations — not a pure passthrough. A sign/restriction error here would silently invert `p_adverse_before_favorable_<pair>` with nothing catching it. | Add Phase 8's complement computation to lookahead-auditor's explicit scope, AND require `validate.py` to assert `p_adverse_before_favorable + p_favorable_before_adverse + p_unresolved == 1` per row/pair. |
| 6 | §8 stop conditions 4-5 | WARNING | Retrospective-field misuse / Phase-12 offset-column misuse are code-review/audit-time checks, not named to any automated `validate.py` gate the way conditions 1,2,6,7 are (V1/V2, V-SEALED). | Assign explicit gate names (extend V-LABEL/V-MATCH from §3.1) to stop conditions 4 and 5. |

## Notes (non-blocking)

- Item 11's `p_unresolved_<pair>` vs. the panel's native `_ambiguous` suffix
  — not shown to be the same concept, only assumed. Add one sentence
  confirming equivalence under the panel's D6 convention.
- Item 2 `transition_matrix.csv` — add one example row to the manifest
  entry (4 transition-cell rows, `n`∈{623,9,6,4018}, plus label columns).
- Phase 12's "time-of-day" bucket source timestamp not explicitly named
  (reasonably inferable as `walk_a_confirm_ns`, already in §1.1).

## Confirmed PASS

- C4/D/E applicability confirmed N/A.
- §7.1 Domain & completeness contract is concrete and gives exact
  reconciliation numbers.
- §8 stop conditions 1-2 are literal count/set-equality checks, consistent
  with "inherited by reference-reproduction."
- §9 audit-plan scope split matches `docs/CAUSAL_CHECKLIST.md`.
- §1.1 vs. phase column cross-check: all phase-referenced columns trace to
  a §1.1-listed source (minor note on time-of-day above).

## Blocking verdict

**BLOCKED** on pass 1 — 6 WARNINGs, 0 FAIL. Per `docs/CAUSAL_CHECKLIST.md`'s
severity table, WARNING blocks unless explicitly adjudicated in the SPEC.
All six are single-sentence-scale documentation fixes — no redesign
required.

## Pass 2 adjudication (resolved in SPEC.md before implementation)

- **#1 (C5 evaluation-order contradiction)**: FIXED. §6's summary line now
  states a single order matching the per-row conditions: C1 → C3 → C2 → C4 →
  C5, with C5 read last only if the pooled curves are already flat (removed
  the contradictory "checked before Phase 12" phrasing).
- **#2, #3 (missing column lists)**: FIXED. Items 17/18 now carry explicit
  column lists including `population_definition, group`.
- **#4 (bucket-name collision)**: FIXED. Phase 12's stratum renamed
  `confirm_mfe_bucket` throughout; Phase 11's text no longer aliases
  `mfe_bucket` as interchangeable with anything confirmation-time.
- **#5 (Phase 8 audit-scope + correctness gate)**: FIXED. §9's
  lookahead-auditor scope line now explicitly includes Phase 8's
  favorable/adverse complement logic; `validate.py`'s gate list (§3.1) gains
  a probability-sums-to-one check per race pair.
- **#6 (unnamed gates for stop conditions 4-5)**: FIXED. Stop conditions 4
  and 5 now reference `gate V-LABEL` and `gate V-MATCH` explicitly (already
  named in §3.1's ten-item table; cross-referenced from §8).
