# contract-checker — pass 1 — armed_fade_score_path_progression

**Date:** 2026-08-09 · **Verdict: CLEAR** · 0 blocking · 2 warning/note · 1 pending · 1 not verified

Scope: SPEC.md §9a Deliverables Manifest, terminal decision labels, §9b
domain/completeness contract, C4/D/E, §9 validation gates. Causality
(A, B, C1–C3, F, G, H) is out of scope — `lookahead-auditor` cleared it through
pass 2 (`audit/status.json`, verdict PASS, 0 CRITICAL, 0 WARNING).

> Authored by the `contract-checker` agent and persisted by the main session,
> which has the Write tool the agent lacks. The compliance table is verbatim;
> the remediation section at the end was added afterwards.

## Referred to lookahead-auditor

(none)

## Compliance table

| Requirement | Verdict | Evidence | Smallest remediation |
|---|---|---|---|
| Manifest #1 `SPEC.md` | PASS | present, frozen, matches §9a table | — |
| Manifest #2 `README.md` | PASS | reproduce steps, module map, runtime notes present | — |
| Manifest #3 `REPORT.md` | **PENDING** | not yet written (in progress per task) | write per SPEC §10/10a |
| Manifest #4 `armed_regime_score_paths.parquet` | PASS | exists; gates 4–7 operate on columns matching the §6 field names (`arm_top10_ns`, `walk_a_*`, `walk_b_*_<level>`, `shape_class_0_03/0_05`) | — |
| Manifest #5 `threshold_progression_funnel.json` | PASS | pooled/direction/year stages with `p_confirm` and incremental lift | — |
| Manifest #6 `mae_to_confirm_by_level.json` | PASS | `uncensored` + `censored_1atr` per level, survival thresholds at 0.25/0.50/0.75/1.00 ATR; gate 6 independently recomputes MAE, 0/400 mismatches | — |
| Manifest #6b `remaining_opportunity.json` | PASS | pooled/direction/year breakdowns present | — |
| Manifest #6c `shape_diagnostics.json` | PASS | both retreat blocks, 5 classes, `depth_cross_tab` | — |
| Manifest #7 `progression_speed.json` | PASS | pooled/direction/year keys present | — |
| Manifest #8 `persistence_diagnostics.json` | PASS | pooled/direction/year keys present | — |
| Manifest #9 `reexpansion_diagnostics.json` | PASS | r = 0.03 and 0.05, both comparators | — |
| Manifest #10 `validation_report.json` | PASS | all 8 gates with `passed`, top-level `all_passed` | — |
| Manifest #11 `entry_confirmation_candidates.json` | PASS | 5 candidates, each with n, `p_confirm`, MAE median, remaining return, time-to-confirm, direction + year splits | — |
| Manifest #12 `partition_manifest.json` | PASS | cost, years, levels, walks, thresholds, code hashes, overlap disclosure | — |
| Manifest #13 `audit/status.json` | PASS | lookahead-auditor verdict PASS, 0 critical | — |
| Manifest #14 `audit/contract_status.json` | PASS (self) | this pass's own output | — |
| Terminal decision labels, reachability | **NOT VERIFIED** | criteria are computable from existing artifacts; no label assigned yet because REPORT.md is unwritten | re-check when REPORT.md exists |
| §9b instrument (NQ, `*.v.0`) | PASS | substrate is the accepted `regime_complete_v1` store | — |
| §9b years 2021–2025 | PASS | `_assert_arming_population_is_complete` raises on any partial slice; manifest years = [2021…2025] | — |
| §9b RTH only | PASS | gate 5 `session_containment`, 0 violations | — |
| §9b regime age > 600s | PASS | gate 3 `all_regime_age_gt_600s` true, `min_regime_age_s` = 605.0 | — |
| §9b four frozen levels | PASS | `LEVELS` matches; thresholds imported unmodified from `candidates.THRESHOLDS` | — |
| §9b two walks, never pooled | PASS | separate `walk_a_*` / `walk_b_*_<level>` column sets; every results file names its walk; gate 4 asserts Top-10 agreement (0 disagreements) | — |
| §9b two retreat definitions, no third | PASS | `RETREAT_DEFINITIONS = (0.03, 0.05)`; artifacts emit only those blocks | — |
| §9b censoring counted, not imputed | PASS | uncensored (n = 8,725) and censored (n = 4,656) reported as separate counted populations | — |
| §9b ambiguity counted, both bounds | PASS | `ambiguous`, `confirm_reached_censored` (adverse) and `..._optimistic`; gate 4 `ambiguous_same_bar` = 0 | — |
| C4 walk-forward / selection seals | PASS | thresholds frozen from a prior sealed study, never fit on this population; gate 1 authenticates the arm population by independent as-of-join reconciliation | — |
| C4 promotion gate implements every frozen check | PASS | `validate.py`'s 8 functions map 1:1 to SPEC §9; gate 8 reads machine-readable JSON only, never prose | — |
| D — threshold not derived from evaluation population | PASS | `THRESHOLDS` imported unmodified from the predecessor study | — |
| D — 2025 overlap disclosure | **WARNING** | disclosure text present in SPEC §2.4, README, and `partition_manifest.json`, but the cited `THRESHOLD_OVERLAP_WAIVER.json` does not exist inside this study | add the file or fix the citation |
| E — backtest config (cost, stop, fills) | PASS | `STOP_ATR = 1.0`; `COST_POINTS`/`FLAT_POINTS` from the accepted engine; `_exit_price` fills at next-bar open, never the trigger | — |
| §9 gate 1 `lifecycle_parity` | PASS (see CC-2) | independent as-of-join reconciliation, `excluded_unexplained` = 0 | — |
| §9 gate 2 `true_dispatch_cadence` | PASS | — | — |
| §9 gate 3 `arm_definition` | PASS | independent predecessor recovery via as-of join, a distinct code path from `arm_population`'s shift | — |
| §9 gate 4 `event_ordering` | PASS | 0 violations across 8 checks | — |
| §9 gate 5 `session_containment` | PASS | 0 violations | — |
| §9 gate 6 `mae_independent_recompute` | PASS | separate code path reading raw parquet, 0/400 mismatches | — |
| §9 gate 7 `assertions` | PASS | 0 violations | — |
| §9 gate 8 `audit_gates` | PASS (logic) | reads `lint.json`, `status.json`, `contract_status.json` machine-readably; the `passed: false` at pass time is solely this file's absence | re-run `validate` after this file is written |

## Assumptions true in observed data but not structurally enforced

- The "35-regime delta" in SPEC §3 is descriptive prose, not enforced by any
  assertion. Gate 1 enforces reconciliation-to-zero-unexplained instead, which is
  the stronger and correct invariant (see CC-2).
- The waiver file's *content* was not independently checked against this study's
  threshold years, because the file is absent from this study (see CC-1). The
  disclosure text itself is consistent wherever it appears.

## Blocking verdict

**CLEAR.** 0 blocking findings. CC-1 (waiver citation) and CC-2 (stale SPEC prose
count) are disclosure and hygiene issues that change no measurement. REPORT.md is
correctly pending, not a violation. Gate 8's `all_passed: false` is a byproduct of
this audit's own output not existing yet, not a defect in the gate's logic.

---

## Remediation applied after this pass (main session, 2026-08-09)

- **CC-1 RESOLVED.** `canonical_model_threshold_contracts.parquet` carries
  `waiver_artifact = studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`
  for all six percentiles, so that file is the canonical waiver and a local copy
  would be a second thing to keep in sync with the store. SPEC §2.4 and README now
  cite the full path and state that this study inherits rather than forks it.
- **CC-2 RESOLVED.** SPEC §3 now carries a dated amendment preserving the original
  pre-implementation estimate (8,953 / 35) alongside the reconciled figures
  (8,950 / 38), and naming the two corrections that moved it.
- **CC-3 / CC-4 remain open for pass 2.** REPORT.md now exists and assigns
  `ARMED SCORE PROGRESSION SUPPORTS REFINEMENT`; its structure and label
  assignment have not yet been checked against SPEC §9a/§10.
