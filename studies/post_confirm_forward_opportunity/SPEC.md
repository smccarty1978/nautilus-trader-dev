# Post-Confirmation Forward Opportunity / Continuation Value — Frozen Specification

**Study:** `post_confirm_forward_opportunity` · **Frozen:** 2026-08-11, before implementation.
**Substrate:** `data/canonical/regime_complete_v1/` + the frozen arm table
`studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet`
**Predecessor:** `top10_fast_confirm_runner_path` (verdict **C**), which inherits from
`top10_post_confirmation_mfe_monetization` (verdict **F**).

---

## 1. Decision to inform

The predecessor closed with a specific, unresolved indictment:

> A uniformly random exit after confirmation beats the accepted natural exit by up
> to **+0.52 ATR/trade**. Median unconstrained capture is **0.000**, mean
> **−0.225**. The open question is no longer "which exit signal" but "why is the
> terminal exit worth less than a random one".

This study does **not** design an exit. It builds the missing prerequisite: a
**forward opportunity map**. The action it changes is whether the program spends
another cycle on exit architecture at all, and if so, on which architecture
family — direct liquidation, state-armed protection, or staged harvesting.

## 2. Hypothesis

> From a causal state observed after the confirming regime flip, there exists a
> **broad, year-stable, direction-stable** region in which the expected value of
> continuing to the accepted natural exit is materially **negative** relative to
> exiting now — identified without predicting the eventual MaxMFE.

**What kills the branch.** If `E[continue − exit_now]` is negative only in cells
that are (a) small, (b) year-unstable, (c) LONG/SHORT-divergent, or (d) populated
mainly by trades the 1.00 ATR stop has already taken, then the forward map
contains no actionable structure and the study returns **G**.

**Explicit non-goals.** No re-run of the predecessor's four policies. No entry
change. No initial-stop optimization. No threshold search or grid. No model
training. No new features. No recollection of the canonical store. 2026 untouched.

---

## 3. Frozen scope

```text
instrument     NQ, *.v.0 volume-continuous only
years          2021, 2022, 2023, 2024, 2025          (development)
2026           SEALED — MUST NOT be opened during this study
session        RTH only, [08:30, 15:00) CT, half-open; 15:00 is the forced flat
directions     LONG and SHORT, both reported separately everywhere
population     the 4,656 measurable confirmed trades of the accepted study
```

**Upstream artifacts consumed (read-only, never rewritten):**

| Input | Path | Causal status |
|---|---|---|
| Arm table | `studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet` | accepted; 8,950 valid Top-10 arms |
| 1s RTH path | `data/canonical/regime_complete_v1/canonical_regime_paths_all.parquet` | accepted, policy-free |
| Regime sequence | `data/canonical/regime_complete_v1/canonical_regimes_all.parquet` | accepted, policy-free |
| Model scores | `data/canonical/regime_complete_v1/canonical_regime_scores_all.parquet` | **EXPLORATORY_OUT_OF_DOMAIN** for the new regime |
| Prior engine | `studies/top10_fast_confirm_runner_path/implementation/engine.py::prepare` | audited clean, reused unchanged |
| Path engine | `studies/model_driven_entry_exit_discovery/implementation/engine.py` | audited clean, reused unchanged |

**Inherited disclosure.** 2025 is **NOT** threshold-OOS (waiver
`studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`). The Phase 13
model score is out of domain on the new regime. Both stay visible in every
headline comparison.

---

## 4. Frozen entry and lifecycle (inherited, not modifiable)

```text
entry            RTH only; regime age > 600 s; first true causal Top-10 crossing
                 from below; immediate fade entry
entry price      arm_price, ATR arm_atr, both frozen at entry
initial stop     1.00 ATR from entry, on a completed 1s bar LOW/HIGH
confirming flip  walk_a_confirm_ns — next regime start at or after entry in the
                 trade's own direction (derived, never a literal R+1 offset)
opposing flip    next regime start at or after entry in direction −d
NATURAL exit     STOP-LIVE:      first of 1 ATR stop / opposing flip / 15:00 CT
                 UNCONSTRAINED:  first of opposing flip / 15:00 CT (stop released)
fills            a TRIGGER on a completed 1s bar fills at the FOLLOWING bar's
                 open; the trigger price is never credited.
                 A SCHEDULED terminal (opposing flip, 15:00 flat) marks at that
                 bar's own close. Inherited unchanged — this is what makes the
                 baseline reconcile.
session          clamped to the entry's own session; no overnight stitching
cost             2 ticks round-turn = 0.50 points, charged once PER UNIT EXIT
same-bar ties    resolved adversely, flagged, optimistic bound reported
normalisation    every excursion divided by the ENTRY ATR
```

Populations (Phase 0 must reproduce all seven exactly):

```text
ORIGINAL ENTRIES        8,950     <- the strategy denominator, always
CONFIRMED               4,705
STOPPED_BEFORE_CONFIRM  4,245
MEASURABLE CONFIRMED    4,656     <- the PRIMARY population of this study
NON-MEASURABLE            49      SESSION_CLOSE_UNRESOLVED
giveback pool/entry     0.898
baseline net/entry     −0.0765
```

**No confirmation-speed restriction.** `confirmation_speed_s` and the four
predecessor cohorts (`FAST_0_60`, `FAST_61_120`, `SLOW_121_300`,
`VERY_SLOW_GT300`) are carried as **diagnostic columns only** and never filter a
primary table.

---

## 5. Causal contract

### D1 — The dual track (settled with the study owner, 2026-08-11)

The 1.00 ATR stop is the source of the predecessor's censoring trap. Its role is
split, and the split is load-bearing:

| Surface | Path used | Reason |
|---|---|---|
| Observation grid (Phase 1) | **UNCONSTRAINED** — runs to `unc_i` | An observation at a state the stop already closed still has a well-defined forward opportunity. Terminating the grid at the stop is the censored-population defect that understated required stop room 5× in a prior study. |
| Forward labels (Phases 3–9) | **UNCONSTRAINED** — barriers, forward MFE/MAE resolve to `unc_i` | The brief's NO-CENSORING rule verbatim: *"Do not let a hypothetical stop censor the forward opportunity labels."* |
| Continuation value (Phase 10) | **BOTH.** `cv_stop_live` is PRIMARY, `cv_unconstrained` secondary | The accepted economic baseline has the stop live. Continuing through a stop means eating the stop. |
| Architectures (if gate opens) | **STOP-LIVE only** | Any policy is evaluated inside the accepted contract, no exceptions. |

Every observation carries `alive_stop_live`. `cv_stop_live` is **null** where
`j > nat_i`, never imputed. Primary economic reporting is on the
stop-live-actionable subset, labelled `CONDITIONAL_ON_STILL_ALIVE`.

### D2 — Observation grid horizon (settled with the study owner, 2026-08-11)

Measured on the accepted panel, confirm→unconstrained-exit is median **540 s**,
p75 **1,020 s**, p90 **1,680 s**. The brief's +600 s cap would truncate over half
the population's lifetime, and disproportionately the ≥3 ATR runners that carry
the entire pool. Therefore:

```text
DENSE   every 15 s from confirm+15 s through min(unc_i, confirm+600 s)
        <- the PRIMARY reporting horizon; all Phase 3-13 tables use this
SPARSE  additional single observations at +900, +1200, +1800, +2400 s
        <- reported ONLY in results/extended_horizon.parquet, clearly separated,
           never pooled into a primary table
```

The brief's mandatory explicit observations (+30/60/90/120/180/300/600) are all
multiples of 15 s and are therefore members of the dense grid by construction.

An observation exists **only if the trade is alive on the unconstrained path**
(`0 <= j <= unc_i`). Ended trades produce no observation — a forward-opportunity
row with no forward path is meaningless. Attrition is instead accounted against
the **constant denominator of 4,656** in every time-indexed table:

```text
eligible   4,656 always
alive      trades with a valid j at this offset
terminal   4,656 − alive
attrition_pct
alive_stop_live
```

### D3 — Decision instant and what is readable

At observation offset `L`, let `j` = first bar with `ts >= confirm_ns + L·1e9`,
`ci` = confirmation bar. **Only bars `[0..j]` may be read for state.** All
forward labels read **strictly `(j..unc_i]`**. The boundary is enforced by
construction (suffix arrays are built from `j+1`) and verified by hard-truncation
replay (§9 gate 8).

Direction-normalised, entry-relative primitives (inherited):

```text
bar_hi[k]  = (high−entry)·d/atr          bar_lo[k]  = (low−entry)·d/atr
mark[k]    = (close−entry)·d/atr
run_mfe[k] = cummax(max(bar_hi,0))[k]    run_mae[k] = cummax(max(−bar_lo,0))[k]
```

### D4 — Causal state variables (Phase 2). Small by contract.

| Variable | Definition |
|---|---|
| `return_from_entry_atr` | `mark[j]` |
| `return_since_confirm_atr` | `mark[j] − mark[ci]` |
| `running_mfe_from_entry_atr` | `run_mfe[j]` |
| `running_mfe_since_confirm_atr` | `max(bar_hi[ci..j]) − mark[ci]` |
| `drawdown_from_running_max_atr` | `run_mfe[j] − mark[j]` |
| `retracement_fraction` | `drawdown / run_mfe[j]`, null if `run_mfe[j] < 0.10` |
| `seconds_since_last_favorable_extreme` | **ARMED**: `ts[j] − ts[e]`, `e` = last `k ∈ (ci..j]` with `bar_hi[k] > run_mfe[k−1]`. If no post-confirm extreme yet, anchored at `ci` with `stall_armed = false`. |
| `n_new_favorable_extremes_since_confirm` | count of such `k` |
| `favorable_progress_last_15/30/60s` | `run_mfe[j] − run_mfe[j_W]`, `j_W` = first bar with `ts >= ts[j] − W·1e9`; **null** if `ts[j] − confirm_ns < W·1e9`. Non-negative by construction. |
| `adverse_progress_last_15/30/60s` | `run_mae[j] − run_mae[j_W]`, same nulling. Non-negative by construction. |
| `mark_progress_last_15/30/60s` | `mark[j] − mark[j_W]`, same nulling. **SIGNED** — this is the progress axis of Phases 6/7. |
| `seconds_since_confirmation` | `L` |
| `seconds_to_session_close` | `(day_close_ns − ts[j])/1e9` |
| `confirmation_speed_s` | `(confirm_ns − entry_ns)/1e9` (diagnostic only) |

**Why the progress axis is `mark_progress_last_60s` and not
`favorable_progress_last_60s`.** Phases 6/7 require a *negative* progress bucket.
`favorable_progress` is a difference of a running maximum and is non-negative by
construction, so it cannot express "progress turned negative". The signed mark
progress is also the variable that produced the predecessor's central mechanism
(its `prog_mark_60s`). Both are carried; the signed one defines the axis.

**The armed stall convention is inherited and non-negotiable.** The raw clock
(anchored at `ci` regardless) fires on ~100% of trades and is degenerate; it is
carried as `secs_since_last_extreme_raw` for disclosure only.

### D5 — Retrospective labels. Never inputs.

`eventual_max_mfe_atr`, `runner_bucket` (R0 `<1`, R1 `1–2`, R2 `2–3`, R3 `≥3`),
tier flags `≥2/2.5/3/4`, all forward barrier outcomes, `forward_mfe_atr`,
`forward_mae_atr`, `continuation_value_atr`. These may appear only as outcomes
and never in a state variable or a trigger.

### D6 — Forward barrier races (Phase 3)

All barriers are relative to the **current price at the observation**,
`P_j = close[j]`, i.e. to `mark[j]` in normalised space. ATR is frozen at entry.

```text
first favorable touch of +f   first k ∈ (j..unc_i] with bar_hi[k] >= mark[j] + f
first adverse  touch of −a    first k ∈ (j..unc_i] with bar_lo[k] <= mark[j] − a
favorable levels  0.25 0.50 0.75 1.00 1.50
adverse   levels  0.25 0.50 0.75 1.00
```

Race resolution:

```text
t_f < 0 and t_a < 0   -> UNRESOLVED   (reported separately, never as adverse)
t_f valid, t_f < t_a  -> FAVORABLE
t_a valid, t_a < t_f  -> ADVERSE
t_f == t_a            -> AMBIGUOUS -> counted ADVERSE for economic reporting;
                         the optimistic bound (counted favorable) is reported
                         as a mandatory sensitivity on every race table
```

The ten reported pairs, frozen, no expansion:
`+0.25/−0.25 · +0.50/−0.25 · +0.50/−0.50 · +0.75/−0.25 · +0.75/−0.50 ·
+1.00/−0.50 · +1.00/−0.75 · +1.50/−0.50 · +1.50/−0.75 · +1.50/−1.00`

### D7 — Exit-now fill convention (Phase 10)

An observation at bar `j` is a decision on a **completed** bar and therefore
fills at bar `j+1`'s **open**. Two quantities are carried and both are reported:

```text
exit_now_mark_atr   mark[j]                  the barrier reference price
exit_now_fill_atr   realise(j, next_open)    the ECONOMIC number
```

`continuation_value_atr = natural_exit_return − exit_now_fill_atr`, both measured
from the original entry in ATR. **Costs cancel** — one round turn is charged
either way on a single unit — so continuation value is a gross difference. This
is stated so the cost treatment cannot be mistaken for a favour to the active
side. Phase 12 harvesting is the one place a second round turn is charged, and it
is charged explicitly per unit.

### D8 — Dependence. Repeated observations are not independent trades.

- Every table reports **`n_obs` and `n_unique_trades`**, without exception.
- Year and LONG/SHORT stability is assessed at **trade level**: within each
  state bucket, a trade contributes its **first** observation entering that
  bucket (one row per trade per bucket — the "state transition" definition),
  and the slice statistic is computed over those rows.
- No p-value is quoted from pooled observations. Where an interval is given it
  is a **trade-clustered** bootstrap (resample trades, 1,000 draws, seed 20260811).

### D9 — Load-bearing rules from `docs/CAUSAL_CHECKLIST.md`

`A1` (decision-time snap), `B4` (no negative shift / future read), `C1–C3`
(population containment, censoring, matched comparison), `F` (label horizon
strictly after decision), `H4` (fill never priced at the trigger level).

---

## 6. Deliverables Manifest (frozen; the completion gate checks this list literally)

| # | Path | Type | Required contents |
|---|---|---|---|
| 1 | `results/population_reconciliation.parquet` | table | `quantity, observed, accepted, delta, tolerance, passed` |
| 2 | `results/observation_panel.parquet` | table | one row per (trade × dense offset); all D4 state vars, all D6 race outcomes, forward excursion, `alive_stop_live`, `cv_*`, bucket assignments |
| 3 | `results/forward_barrier_races.parquet` | table | `population, slice_kind, slice, pair, n_obs, n_unique_trades, p_favorable, p_adverse, p_unresolved, p_ambiguous, p_favorable_optimistic` |
| 4 | `results/forward_excursion.parquet` | table | `population, slice_kind, slice, metric, n_obs, n_unique_trades, mean, median, p25, p75, p90` for `forward_mfe/mae/net`, `time_to_forward_mfe/mae` |
| 5 | `results/stall_continuation.parquet` | table | `slice_kind, slice, stall_bucket, n_obs, n_unique_trades, fwd_mfe_median/mean, fwd_mae_median, p_up025_b_dn025, p_up050_b_dn025, p_up050_b_dn050, p_up100_b_dn050, natural_exit_ret_from_now, p_another_extreme` |
| 6 | `results/progress_continuation.parquet` | table | same metric set, keyed by `progress_var, progress_bucket` |
| 7 | `results/progress_stall_matrix.parquet` | table | `slice_kind, slice, progress_bucket, stall_bucket, n_obs, n_unique_trades, fwd_mfe, fwd_mae, p_up050_b_dn050, p_up100_b_dn050, natural_exit_ret_from_now, p_another_extreme` |
| 8 | `results/mfe_state_continuation.parquet` | table | stall analysis within `mfe_bucket ∈ {<1, 1-2, 2-3, >=3}` |
| 9 | `results/drawdown_state_continuation.parquet` | table | drawdown buckets `{<0.25, 0.25-0.50, 0.50-0.75, >=0.75}`, plain and crossed with stall |
| 10 | `results/exit_now_continuation_value.parquet` | table | `basis, slice_kind, slice, bucket_kind, bucket, n_obs, n_unique_trades, mean_cv, median_cv, p25_cv, p75_cv, pct_cv_negative, ci_lo, ci_hi` (trade-clustered) |
| 11 | `results/placebo_diagnosis.parquet` | table | `slice_kind, slice, n_trades, mean_random, mean_fixed_horizon, mean_opposing_flip, mean_maxmfe, d_random_minus_flip, d_maxmfe_minus_random, d_maxmfe_minus_flip, secs_maxmfe_to_terminal, giveback_after_max` |
| 12 | `results/harvest_geometry.parquet` | table | `rung_atr, n_trades, pct_achieved, p_next_050, p_next_100, mae_before_next_median/p75/p90, secs_to_next_median, blended_ret_variant_a/b/c, full_size_ret` |
| 13 | `results/extended_horizon.parquet` | table | the sparse +900…+2400 s observations, D2, clearly separated |
| 14 | `results/model_additivity.parquet` | table | *(optional, cheap)* `progress_bucket, stall_bucket, score_half, n_obs, n_unique_trades, p_up050_b_dn050, p_up100_b_dn050, mean_cv, n_null` — **EXPLORATORY_OUT_OF_DOMAIN** |
| 15 | `results/decision_gate.parquet` | table | the 8 §8 conditions × candidate region, `condition, value, threshold, passed` |
| 16 | `results/validation_report.json` | json | the 14 gates of §9, `all_passed` |
| 17 | `results/summary.json` | json | headline answers to the 16 report questions + final classification |
| 18 | `results/partition_manifest.json` | json | input paths, row counts, frozen constants, disclosures |
| 19 | `SPEC.md` · `README.md` · `REPORT.md` | docs | REPORT answers Q1–Q16 and ends with exactly one label |
| 20 | `audit/lint.json` · `audit/status.json` · `audit/contract_status.json` | json | machine-readable audit verdicts |
| 21 | *(conditional)* `results/architecture_results.parquet`, `results/runner_destruction.parquet` | table | only if the §8 gate opens; else `summary.json` records `gate_open = false` and `architectures_ran = false` |

CSV mirrors are required for #1, #3–#13, #15 (report-critical tables). #2 is the
per-observation panel and is parquet-only by design.

### Terminal decision labels — every label reachable

| Label | Condition |
|---|---|
| **A** CONTINUATION VALUE HAS A ROBUST NEGATIVE REGION — EXIT ARCHITECTURE WARRANTED | §8 gate opens **and** a direct continuation-value exit architecture is net-positive per original entry, beats its matched placebo, and preserves ≥50% of ≥3 ATR runners |
| **B** CONTINUATION VALUE SUPPORTS STATE-ARMED PROTECTION, NOT DIRECT EXIT | gate opens; the armed architecture clears the bar in A while the direct exit does not |
| **C** STAGED HARVESTING IS BETTER SUPPORTED THAN TERMINAL EXIT TIMING | Phase 12 rung geometry shows `P(next +0.5 rung) ≥ 0.55` at ≥3 consecutive rungs with bounded pre-rung MAE, **and** the harvest architecture beats both the baseline and the placebo while the timing architectures do not |
| **D** OPPOSING FLIP IS STRUCTURALLY LATE, BUT NO CAUSAL REPLACEMENT STATE FOUND | Phase 11 confirms large positive `random − opposing_flip` **and** no causal state region clears §8 |
| **E** PRICE STATE HAS FORWARD INFORMATION BUT NOT ENOUGH FOR ECONOMIC ACTION | forward barrier/continuation-value structure is real and monotone, but §8 fails on breadth, year, direction, or actionability |
| **F** RAW MODEL SCORE ADDS MATERIAL EXPLORATORY INFORMATION | Phase 13 score split moves `p_up050_b_dn050` by ≥0.05 or `mean_cv` by ≥0.15 ATR **within** matched progress×stall cells, in ≥4/5 years, while price state alone fails §8 |
| **G** NO ROBUST FORWARD-OPPORTUNITY STRUCTURE FOUND | none of the above; forward opportunity is flat or noise-dominated across the state space |
| **H** RESULT INVALID / CONTRACT FAILURE | any surviving audit CRITICAL, or Phase 0 reconciliation fails |

---

## 7. Domain & completeness contract

- **Partition grid:** 5 calendar years × 2 sides = **10 partitions**, enumerated
  `entry_year ∈ {2021..2025}` × `side ∈ {LONG, SHORT}`. All 10 must be non-empty.
- **Observation grid completeness:** the dense offsets are exactly
  `{15, 30, …, 600}` (40 offsets). Every offset must have `alive > 0`. The
  per-offset attrition table must be present for all 40 with the constant 4,656
  denominator.
- **Bucket grid completeness:** stall buckets (7), progress buckets (5 fixed),
  progress×stall cells (3×4 = 12), MFE buckets (4), drawdown buckets (4). Every
  cell is emitted; a cell with `n_obs = 0` is **retained with a flag**, never
  dropped. A zero-count cell in the 12-cell progress×stall map is a reportable
  condition, not a silent gap.
- **Boundary convention:** America/Chicago; RTH `[08:30, 15:00)` CT; windows
  clamped to the entry's own session index range; no overnight stitching.
- **Missing dispatch (Phase 13):** an observation with no true model dispatch at
  or before it yields `score = null`, counted as `n_null`, **never imputed**.
  Carry-forward reads a level only; a crossing is never inferred from it.
- **Global validation:** all 14 gates of §9 pass; `n_unique_trades` in the
  observation panel ≤ 4,656; every primary table carries both `n_obs` and
  `n_unique_trades`.

---

## 8. Stop conditions and the decision gate

**Abort (emit H) if:** Phase 0 fails to reproduce 8,950 / 4,705 / 4,245 / 4,656 /
49; or the pool and baseline miss the accepted values by > 0.005 ATR/entry; or any
of the 10 partitions is empty; or any audit CRITICAL survives.

**The decision gate (Phase 14).** Machine-evaluated, written to
`results/decision_gate.parquet`. A **candidate region** is a union of contiguous
buckets on one of the frozen axes (stall, progress, progress×stall, MFE-crossed,
drawdown-crossed). Architectures run **only if a single candidate region clears
all eight**:

```text
1 BREADTH-ECON   mean cv_stop_live <= -0.10 ATR on the region
2 GEOMETRY       P(+0.50 before -0.50) <= 0.45 on the region
3 BREADTH-SIZE   region covers >= 10% of stop-live-alive observations
                 AND >= 15% of unique trades contribute an observation in it
4 YEAR           mean cv_stop_live < 0 in >= 4 of 5 years (trade-level, D8)
5 DIRECTION      mean cv_stop_live < 0 for BOTH long and short (trade-level)
6 ACTIONABLE     >= 60% of region observations have alive_stop_live = true, and
                 the region's median observation is >= 30 s before the trade's
                 own stop-live terminal
7 NOT-ALREADY-DEAD  <= 40% of the region's unique trades have their stop-live
                 terminal within 15 s after their first observation in the region
8 TAIL-BOUNDED   <= 35% of the region's unique trades are eventual >= 3 ATR
                 runners AND those runners' mean cv_stop_live is > -0.50 ATR
```

Conditions 6–8 are the direct fix for the predecessor's failure mode: its signal
region was 40.5% already-stopped trades, and its giveback policies cut 70% of the
≥3 ATR tail.

**If the gate opens:** at most **THREE** qualitatively different architectures —
`A_CONTINUATION_EXIT`, `B_STATE_ARMED_PROTECTION`, `C_PARTIAL_HARVEST`. Thresholds
are read off broad descriptive plateaus only. No grid. No threshold search. Each
carries, mandatorily:

- a **count-and-timing-matched random-exit placebo** (20 draws/trade, seed
  20260811, uniform over the trade's actionable post-confirm window, causal
  next-bar-open fill) — non-negotiable on this line, which has three times
  mistaken "exiting earlier than a bad exit" for an edge;
- the **runner-destruction table** at ≥2 / ≥2.5 / ≥3 / ≥4 ATR with opportunity
  cost and the placebo's own cut rate;
- Δ ATR per confirmed trade **and** per original Top-10 entry (denominator 8,950);
- giveback recovered %, confirmed losers improved %;
- year and LONG/SHORT slices.

**If the gate stays closed:** the study stops at Phase 13 and returns the
appropriate descriptive label (D, E, F, or G). No policy is manufactured.

---

## 9. Validation gates (all 14 must pass)

> **AMENDMENT 2026-08-11, after the verdict was determined, in response to
> contract-checker NOTE N1.** A **fifteenth** gate,
> `domain_completeness_partitions_and_offsets`, was added: it asserts the 10-cell
> year × side grid against an explicit expected set and asserts all 40 dense
> offsets are present with `alive > 0`. §7 completeness was previously *inferred*
> from the fact that no slice came back empty, which would have hidden a genuinely
> empty partition. This is a **tightening** — it can only make the gate set harder
> to pass, and it passes. Recorded here rather than edited in silently.

```text
 1 8,950 / 4,705 / 4,245 / 4,656 / 49 reproduced exactly
 2 pool 0.898 and baseline -0.0765 per original entry reproduced (tol 0.005)
 3 2026 never read: no input path or filter admits entry_year 2026
 4 no overnight stitching; every observation and terminal inside the entry's
   own RTH session
 5 every observation strictly after confirm_ns
 6 every observation strictly at or before the UNCONSTRAINED terminal
 7 forward labels strictly after the observation bar (suffix built from j+1)
 8 >= 250 trades and >= 2,500 observation states independently replayed from the
   raw 1s parquet on HARD-TRUNCATED arrays, >= 6 state variables + >= 2 forward
   labels, 0 mismatches
 9 natural exit reconciled from every observation: the natural-exit return read
   at an observation equals the trade-level natural return, for all observations
10 barrier collisions resolved adversely, counted, optimistic bound reported
11 random-exit placebo cannot select its exit using future information: draws are
   index-uniform and outcome-blind; the length-blind fixed-horizon placebo is
   reported alongside and its support does not depend on the realised lifetime
12 repeated observations are not treated as independent: every primary table
   carries n_unique_trades, and all year/direction stability is trade-level (D8)
13 causal_lint exits 0
14 lookahead-auditor (pre-execution AND completion) and contract-checker both
   report critical = 0
```

Any CRITICAL finding blocks conclusions and forces label **H**.

## 10. Audit plan

- Pre-execution: `python scripts/causal_lint.py --study studies/post_confirm_forward_opportunity --json studies/post_confirm_forward_opportunity/audit/lint.json` must exit 0
- Pre-execution: `lookahead-auditor` on §5 (the causal contract) before the first full run
- Completion: `lookahead-auditor` + `contract-checker`; `audit/status.json` and
  `audit/contract_status.json` must both show `critical: 0`
