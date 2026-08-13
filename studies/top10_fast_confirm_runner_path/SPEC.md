# Fast-Confirm Top-10 Post-Confirmation Runner Path — Frozen Specification

**Study:** `top10_fast_confirm_runner_path` · **Frozen:** 2026-08-10, before implementation.
**Substrate:** `data/canonical/regime_complete_v1/` + the frozen arm table
`studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet`
**Predecessor:** `top10_post_confirmation_mfe_monetization` (verdict **F**).

---

## 0. Objective

The broad post-confirmation study closed **F — NO ROBUST POST-CONFIRMATION MFE
MONETIZATION FOUND**. Its mechanism finding was that the model's P90 exhaustion
warning is real but arrives after a median **0.953 ATR** of giveback with only
**0.095 ATR** of MFE left, because *deterioration is the giveback*.

This study does not re-open that policy question. It asks a **structural** one:

> For an immediate Top-10 fade entry whose confirming flip arrives **within 120
> seconds** and **before the 1.00 ATR stop**, does the post-confirmation path
> carry causal information separating eventual **≥3 ATR** runners from eventual
> **<2 ATR** outcomes?

The deliverable is a *measurement of separation*, not an exit rule. Phase 12
(policy screen) is **conditional** and gated on an explicit numeric criterion
(§8), so "is there separation" cannot be answered by taste.

**Explicit non-goals.** No re-run of the P80/P90 policy study. No P80/P90
optimization. No model training. No large exit grid. No entry change. No
initial-stop optimization. No new threshold. 2026 untouched.

---

## 1. Frozen decisions (settled with the study owner before implementation)

| # | Decision | Resolution | Consequence |
|---|---|---|---|
| D1 | Does the 1.00 ATR stop stay live after confirmation for the **economic** baseline? | **Yes — stop stays live.** | Phase 0 reconciles to the accepted baseline (−0.0765/entry, pool 0.898/entry). 530 of the 2,340 fast trades remain `CONFIRMED_THEN_STOPPED`. Descriptive geometry (Phases 3–9) is measured on the **unconstrained** path regardless. |
| D2 | What starts the ≤120 s clock? | **`arm_top10_ns`** — the Top-10 crossing decision timestamp. | `seconds_to_confirm = (walk_a_confirm_ns − arm_top10_ns)/1e9`. The stored `walk_a_seconds_to_confirm` differs by up to 11 s and is **not** used; the count that would move under it is reported as a sensitivity line. |
| D3 | How are trades that already ended treated at a post-confirm landmark? | **Constant population, terminal carry-forward.** | All 2,340 fast trades appear at every landmark; ended trades carry their terminal state with `alive = false`. Alive-only is reported as a **secondary** column with per-landmark attrition. This is the direct fix for the survivorship structure that voided stream A in the predecessor. |

---

## 2. Frozen entry and lifecycle (inherited, not modifiable)

```text
entry            RTH only; regime age > 600 s; first true causal Top-10 crossing
                 from below; immediate fade entry
entry price      arm_price (checkpoint_reference_price), ATR arm_atr, both frozen
initial stop     1.00 ATR from entry, measured on completed 1s bar LOW/HIGH
confirming flip  walk_a_confirm_ns — the next regime start at or after entry in
                 the trade's own direction (derived, never a literal R+1 offset)
opposing flip    next regime start at or after entry in direction −d
natural exit     STOP-LIVE: first of 1 ATR stop / opposing flip / 15:00 CT
                 UNCONSTRAINED: first of opposing flip / 15:00 CT (no stop)
fills            a TRIGGER observed on a completed 1s bar (stop, or any Phase-12
                 policy trigger) fills at the FOLLOWING bar's open; the trigger
                 price is never credited.
                 A SCHEDULED terminal -- the opposing regime flip or the 15:00
                 forced-flat -- marks at that bar's own close, because it is not
                 a triggered decision. This is the predecessor's convention,
                 inherited unchanged, and is what makes the baseline reconcile
                 (-0.0765 vs accepted -0.0742; pool 0.898 vs 0.899).
session          RTH only, clamped to the entry's own session; no overnight stitch
cost             2 ticks round-turn = 0.50 points, charged once per trade
same-bar ties    resolved adversely, flagged, both bounds reported
normalisation    every excursion divided by the ENTRY ATR
```

Domain: NQ `*.v.0`, **2021–2025**, RTH. 2025 is **NOT** threshold-OOS (inherited
waiver `studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`). 2026 is
untouched.

---

## 3. Populations

```text
ORIGINAL ENTRIES      8,950   valid Top-10 arms          <- strategy denominator
CONFIRMED             4,705   terminal_label_full in
                              {CONFIRMED_THEN_STOPPED, FINAL_FLIP_EXIT_WINNER,
                               FINAL_FLIP_EXIT_LOSER, SESSION_EXIT}
STOPPED_BEFORE_CONFIRM 4,245
```

**Primary:** `FAST_CONFIRM_120` = CONFIRMED ∧ `seconds_to_confirm ≤ 120`.
The "before the 1 ATR stop" clause of the brief is *definitionally* the CONFIRMED
label — a trade stopped first is `STOPPED_BEFORE_CONFIRM`. This is stated so the
condition is not silently double-counted.

**Diagnostic cohorts** (descriptive only, cutoff NOT optimized):
`FAST_0_60` · `FAST_61_120` · `SLOW_121_300` · `VERY_SLOW_GT300`.

Every economic result is reported **per FAST_CONFIRM trade** *and* **per ORIGINAL
Top-10 entry (8,950)**. The strategy-level denominator is always 8,950.

---

## 4. Causal state variables (Phase 5) — the contract that makes this study valid

At landmark `L ∈ {5,10,15,20,30,45,60,90,120,180}` seconds after `confirm_ns`,
let `j` = first bar with `ts ≥ confirm_ns + L·1e9`, `ci` = confirmation bar.
**Only bars `[0..j]` may be read.** Definitions, entry-relative and
direction-normalised:

```text
bar_hi[k]  = (high−entry)·d/atr        favorable extreme of bar k
bar_lo[k]  = (low −entry)·d/atr        adverse extreme of bar k
mark[k]    = (close−entry)·d/atr
run_mfe[k] = cummax(max(bar_hi,0))[k]
```

| Variable | Definition |
|---|---|
| `ret_from_entry` | `mark[j]` |
| `ret_since_confirm` | `mark[j] − mark[ci]` |
| `run_mfe_entry` | `run_mfe[j]` |
| `mfe_since_confirm` | `max(bar_hi[ci..j]) − mark[ci]` |
| `dd_from_run_max` | `run_mfe[j] − mark[j]` |
| `retrace_frac` | `dd_from_run_max / run_mfe[j]`, null if `run_mfe[j] < 0.10` |
| `made_new_extreme` | any `k ∈ (ci..j]` with `bar_hi[k] > run_mfe[k−1]` |
| `secs_since_last_extreme` | `ts[j] − ts[last such k]`, else measured from `ci` |
| `n_new_extremes` | count of such `k` |
| `prog_mfe_15/30/60s` | `run_mfe[j] − run_mfe[j_W]`, `j_W` = first bar with `ts ≥ ts[j] − W·1e9`; null if `ts[j] − confirm_ns < W·1e9` |
| `prog_mark_15/30/60s` | same on `mark` |
| `alive` | `j ≤ unconstrained terminal index` (D3 carry-forward flag) |
| `alive_stop_live` | `j ≤ stop-live terminal index` (secondary) |

**Retrospective outcome labels** — permitted ONLY as labels, never as inputs:
`eventual_max_mfe_atr` = `max(run_mfe)` over the **unconstrained** window from
original entry; runner tiers `R0 <1.0`, `R1 1.0–2.0`, `R2 2.0–3.0`, `R3 ≥3.0`.

---

## 5. Phase plan

| Phase | Content | Population |
|---|---|---|
| 0 | Reconcile 8,950 / 4,705 / 4,245, the 49 non-measurable confirmed trades, baseline −0.0765 and pool 0.898 per entry | all |
| 1 | Define and size `FAST_CONFIRM_120` + 4 diagnostic cohorts; n, %, LONG/SHORT, year | confirmed |
| 2 | Entry→confirm economics (secs, return, MFE, MAE, capture); mean/median/p25/p75/p90, all cohorts | confirmed |
| 3 | Post-confirmation opportunity: additional MFE, eventual MaxMFE, secs to MaxMFE, natural return, giveback, capture, **fraction of eventual MaxMFE already achieved at confirmation** | fast + cohorts |
| 4 | Retrospective runner buckets R0–R3 and tiers ≥2/≥2.5/≥3/≥4 with natural-exit economics | fast |
| 5 | The 10 causal landmarks × §4 variables | fast |
| 6 | ≥3 ATR vs <2 ATR (and ≥2.5 vs <2) landmark-state contrast | fast |
| 7 | First-giveback geometry at 0.25/0.50/0.75/1.00 ATR | fast |
| 8 | Stall geometry at 15/30/45/60/90/120 s without a new favorable extreme (first stall of each length per trade) | fast |
| 9 | 3×3 progress × drawdown matrix at 30/60/120 s (progress terciles of the fast cohort, frozen bins) | fast |
| 10 | Raw causal new-regime model score at the same landmarks — **EXPLORATORY_OUT_OF_DOMAIN** | fast |
| 11 | Single-variable discrimination: AUC + monotonic bucket tables, ≥3 ATR vs <2 ATR | fast |
| 12 | **CONDITIONAL** ≤4 policies + mandatory runner destruction + count-matched placebo | fast |

Phase 10 reads the **last true dispatch at or before** the landmark. Carry-forward
is used for *reading a level* and is flagged; it is never counted as a crossing.

---

## 6. Deliverables Manifest (frozen; the completion gate checks this list literally)

| # | Path | Type | Required contents |
|---|---|---|---|
| 1 | `results/population_reconciliation.parquet` | table | `quantity, observed, accepted, delta, passed` |
| 2 | `results/confirm_speed_cohorts.parquet` | table | `cohort, n, pct_of_confirmed, pct_of_entries, n_long, n_short, n_2021..n_2025` |
| 3 | `results/confirmation_geometry.parquet` | table | `cohort, metric, mean, median, p25, p75, p90, n` |
| 4 | `results/post_confirm_opportunity.parquet` | table | same shape, post-confirm metrics incl. `frac_maxmfe_at_confirm` |
| 5 | `results/runner_buckets.parquet` | table | `bucket, n, pct, natural_return_atr, giveback_atr, capture, max_mfe` |
| 6 | `results/time_landmark_states.parquet` | table | one row per trade × landmark, all §4 variables + `alive`, `runner_bucket` |
| 7 | `results/giveback_geometry.parquet` | table | `level_atr, n, pct_reaching, mfe_at_event, eventual_max_mfe, remaining_mfe, p_new_extreme, p_add_025/050/100, p_ge_2/2_5/3` |
| 8 | `results/stall_geometry.parquet` | table | `stall_s, n, pct_reaching, ret, mfe, dd, additional_mfe, p_new_extreme, p_ge_2/2_5/3` |
| 9 | `results/progress_retracement_matrix.parquet` | table | `landmark_s, progress_bin, dd_bin, n, additional_mfe, p_ge_2, p_ge_3, natural_return` |
| 10 | `results/single_variable_discrimination.parquet` | table | `landmark_s, variable, population, n_pos, n_neg, auc, auc_abs_lift, bucket_table_monotonic, years_consistent` |
| 11 | `results/model_context.parquet` | table | `landmark_s, metric, mean, median, p25, p75, p90, auc` — labelled EXPLORATORY_OUT_OF_DOMAIN |
| 12 | `results/validation_report.json` | json | the 15 gates of §9, `all_passed` |
| 13 | `results/summary.json` | json | headline answers to the 14 report questions + final classification |
| 14 | `results/partition_manifest.json` | json | input paths, row counts, frozen constants, disclosures |
| 15 | `SPEC.md` · `README.md` · `REPORT.md` | docs | REPORT answers Q1–Q14 and ends with exactly one label |
| 16 | `audit/status.json` · `audit/contract_status.json` · `audit/lint.json` | json | machine-readable audit verdicts |
| 17 | *(conditional)* `results/policy_results.parquet`, `results/runner_destruction.parquet` | table | only if §8 gate opens; else `summary.json` records `phase12_ran = false` |

CSV mirrors are required for #1–#5, #7–#11 (report-critical tables). #6 is
per-trade × landmark (23,400 rows) and is parquet-only by design.

### Terminal decision labels — every label reachable

| Label | Condition |
|---|---|
| **A** FAST CONFIRM IDENTIFIES A SUPERIOR RUNNER POPULATION AND CAUSAL EXIT SEPARATION | fast cohort materially better than slow (Phase 2/3 + §8 cohort test) **and** §8 separation gate opens |
| **B** SUPERIOR POPULATION BUT NO USEFUL EXIT SEPARATION | cohort test passes, separation gate closed |
| **C** CONFIRMATION SPEED NOT ECONOMICALLY INFORMATIVE, BUT POST-CONFIRM PATH IS | cohort test fails, separation gate opens |
| **D** PRICE PROGRESS / GIVEBACK PROVIDES A BOUNDED EXIT CANDIDATE | separation gate opens **and** Phase 12 yields ≥1 policy that is net-positive per original entry, preserves ≥50% of ≥3 ATR runners, beats its count-matched placebo, and is stable across ≥4 of 5 years |
| **E** RAW MODEL SCORE ADDS EXPLORATORY INFORMATION BEYOND PRICE PATH | Phase 10 score variable clears the §8 AUC bar while every price variable fails it |
| **F** NO CAUSAL POST-CONFIRM PATH SEPARATION FOUND | cohort test fails **and** separation gate closed |
| **G** RESULT INVALID / CONTRACT FAILURE | any CRITICAL audit finding, or Phase 0 reconciliation fails |

---

## 7. Domain & completeness contract

- **Partition grid:** 5 calendar years × 2 sides = **10 partitions**, enumerated
  `entry_year ∈ {2021..2025}` × `side ∈ {LONG, SHORT}`. All 10 must be non-empty.
- **Boundary convention:** America/Chicago; RTH session is the half-open interval
  `[08:30, 15:00)` CT; the 15:00 boundary is the forced-flat instant. Windows are
  clamped to the entry's own session index range — no overnight stitching.
- **Zero-row partition:** retained with a flag and reported; it does not silently
  vanish. A zero-row partition is a **stop condition** (§8).
- **Missing dispatch:** the score table holds one row per true dispatch. A
  landmark with no dispatch at or before it yields `score = null`, recorded
  explicitly in `model_context.parquet` as `n_null`; never imputed.
- **Global validation:** the 15 gates of §9 must all pass, `sum(cohort n) = 4,705`,
  and `FAST_0_60 + FAST_61_120 = FAST_CONFIRM_120` exactly.

---

## 8. Stop conditions and the conditional gate

**Abort (emit G) if:** Phase 0 fails to reproduce 8,950 / 4,705 / 4,245; or the
baseline and pool miss the accepted values by >0.005 ATR/entry; or any partition
is empty; or any audit CRITICAL survives.

**Cohort test (decides A/B vs C/F).** FAST_CONFIRM_120 counts as an economically
superior population only if it beats SLOW_CONFIRM (>120 s) on **both** mean
natural net ATR/trade **and** P(eventual MaxMFE ≥3 ATR), in **≥4 of 5 years**.

**Separation gate (decides whether Phase 12 runs) — frozen numeric criterion.**

> **AMENDMENT 2026-08-10, after implementation, before any policy was written.**
> The gate is judged on the **`undetermined`** population — trades with
> `run_mfe_entry < 2.0` at the landmark — not on the constant population.
> Reason: `eventual MaxMFE ≥ run_mfe_entry` by construction, so a trade already
> showing ≥2.0 ATR of running MFE *cannot* belong to the `<2 ATR` class and is a
> guaranteed positive. Those trades are 6.8 / 9.5 / 17.7% of the labelled set at
> 30/60/120 s and **100% of them are positives**, confirming the containment.
> Scoring them measures the definition of MaxMFE, not the path.
> This is a **tightening** of the original criterion. The gate opens under both
> the original and the amended population, so the amendment cannot have
> manufactured the verdict; both counts are reported in `summary.json`.

It opens only if, for at least one single variable at one of the 30/60/120 s
landmarks, on the **undetermined population**:

```text
|AUC − 0.5| >= 0.10                                   (>=3 ATR vs <2 ATR)
AND the quintile bucket table is monotonic in the outcome rate
AND the same sign of separation holds in >= 4 of 5 years
```

If the gate stays closed, the study **stops** and returns
`NO CAUSAL POST-CONFIRM PATH SEPARATION FOUND`. No policy is tested.

**If Phase 12 runs:** ≤4 policies, thresholds read off broad descriptive
plateaus only (no grid, no threshold search). Each policy is accompanied by
(a) the **mandatory** runner-destruction table at ≥2/≥2.5/≥3/≥4 ATR, and (b) a
**count-matched random-exit placebo** — non-negotiable on this research line,
which has twice mistaken "exiting earlier than a bad exit" for an edge.

---

## 9. Validation gates (all 15 must pass)

```text
 1 8,950 original Top-10 entries reproduced exactly
 2 4,705 confirmed reproduced exactly
 3 the 49 non-measurable confirmed trades reconciled and enumerated
 4 giveback pool ~0.898 and baseline ~-0.0765 per original entry reproduced
 5 <=120 s classification derived exactly from causal timestamps (D2), with the
   stored-field sensitivity count reported
 6 every FAST_CONFIRM trade's confirming flip strictly precedes its stop
 7 all post-confirm landmarks strictly after confirm_ns
 8 no overnight stitching; session containment
 9 no future extreme in any causal state variable (index bound j enforced)
10 future MaxMFE used only as a retrospective label
11 same-bar ambiguities identified and resolved adversely
12 >= 200 trades independently replayed from raw 1s (landmark state + fill)
13 causal_lint clean
14 lookahead-auditor: pre-execution AND completion, critical = 0
15 contract-checker against this frozen SPEC, critical = 0
```

Any CRITICAL finding blocks conclusions and forces label **G**.

## 10. Audit plan

- Pre-execution: `python scripts/causal_lint.py --study studies/top10_fast_confirm_runner_path`
- Pre-execution: `lookahead-auditor` on §2/§4 (the causal contract) before first full run
- Completion: `lookahead-auditor` + `contract-checker`; `audit/status.json` and
  `audit/contract_status.json` must both show `critical: 0`
