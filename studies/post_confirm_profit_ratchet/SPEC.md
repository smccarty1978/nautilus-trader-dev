# Post-Confirmation Profit-Ratchet Feasibility — Frozen Specification

**Study:** `post_confirm_profit_ratchet` · **Frozen:** 2026-08-11, before implementation.
**Substrate:** `data/canonical/regime_complete_v1/` + the frozen arm table
`studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet`
**Predecessor:** `post_confirm_forward_opportunity` (verdict **E**), which inherits from
`top10_fast_confirm_runner_path` (verdict **C**) and
`top10_post_confirmation_mfe_monetization` (verdict **F**).

---

## 1. Decision to inform

The predecessor closed with a two-part result that this study is the direct
consequence of:

> **PRICE STATE HAS FORWARD INFORMATION BUT NOT ENOUGH FOR ECONOMIC ACTION.**
> `P(next +0.50 ATR rung)` is **0.79–0.81 at every achieved rung**, spanning only
> 0.756–0.851 across all 30 rung × year cells — a genuinely memoryless ladder.
> Median MAE before the next rung is **0.30–0.36 ATR**. But *harvesting* on that
> ladder is worth at most **+0.0050 ATR/original entry** (0.56% of the pool) and
> is negative at rungs ≤ 2.5.

Harvesting failed because it surrenders the continuation the ladder promises. The
untested alternative is **protection**: keep the whole position, and change the
*payoff function* by placing a floor under achieved profit. The economic question
is entirely different from the one already answered.

The action this study changes is whether the program builds a rung-armed
protective-stop architecture, or closes the post-confirmation exit line for good.

## 2. Hypothesis

> Because `P(next rung) ≈ 0.80` while `mean peak-to-terminal giveback ≈ 2.14 ATR`,
> there exists a stop distance `D` at which the adverse excursion *required* by
> successful continuation is materially **smaller** than the giveback *suffered*
> by failed continuation — so that a stop armed at an achieved rung preserves
> ≥ 90% of successful next-rung transitions while recovering a material share of
> the accepted **0.89808 ATR/original-entry** giveback pool.

**What kills the branch.** If the post-rung adverse-excursion distributions of
successful and failed continuation **overlap** — which they will if the giveback
that kills a failed trade is indistinguishable, in its first `D` ATR, from the
retracement a successful runner routinely absorbs — then no stop distance can
separate them, and any apparent economic gain is loss-containment paid for with
right-tail destruction. That is verdict **E**, `PROFIT_RATCHET_NOT_SUPPORTED`.

**Explicit non-goals (from the brief, binding).** No model-score thresholds. No
P80/P90 exits. No stall thresholds. No progress thresholds. No new ML classifier.
No optimisation of rung locations. No optimisation of trailing-stop distances
beyond the frozen diagnostic grid. No 2026. No conditioning of descriptive MAE on
survival of the existing 1.00 ATR stop. No use of eventual MaxMFE to decide when
the stop arms. No selection of a "best" rule on pooled PnL. No entry change. No
new data collection.

---

## 3. Frozen scope

```text
instrument     NQ, *.v.0 volume-continuous only
years          2021, 2022, 2023, 2024, 2025          (development)
2026           SEALED — MUST NOT be opened during this study
session        RTH only, [08:30, 15:00) CT, half-open; 15:00 is the forced flat
directions     LONG and SHORT, both reported separately everywhere
population     the 4,656 measurable confirmed trades of the accepted study
denominator    8,950 original Top-10 entries, always, in every economic table
```

**Upstream artifacts consumed (read-only, never rewritten):**

| Input | Path | Causal status |
|---|---|---|
| Arm table | `studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet` | accepted; 8,950 valid Top-10 arms |
| Confirmed population | `studies/top10_fast_confirm_runner_path/implementation/build.py::confirmed_population` | accepted; 4,705 rows; imported, never re-derived |
| Trade window | `studies/top10_fast_confirm_runner_path/implementation/engine.py::prepare` | audited clean, reused **unchanged** |
| Forward machinery | `studies/post_confirm_forward_opportunity/implementation/engine.py::TradeForward` | audited clean, reused **unchanged** |
| Rung lineage | `studies/post_confirm_forward_opportunity/results/harvest_panel.parquet` | accepted; Phase 0 reconciles against it |
| 1s RTH path | `data/canonical/regime_complete_v1/canonical_regime_paths_all.parquet` | accepted, policy-free |
| Regime sequence | `data/canonical/regime_complete_v1/canonical_regimes_all.parquet` | accepted, policy-free |

Model scores (`canonical_regime_scores_all.parquet`) are **not consumed by this
study at all**. The brief forbids score thresholds; the cheapest way to honour
that is not to open the file.

**Inherited disclosure.** 2025 is **NOT** threshold-OOS (waiver
`studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`). This is carried
verbatim into every headline comparison. 2025 is **not** described as OOS anywhere.

## 4. Frozen entry, lifecycle and economics (inherited, not modifiable)

```text
entry            RTH only; regime age > 600 s; first true causal Top-10 crossing
                 from below; immediate fade entry
entry price      arm_price, ATR arm_atr, both FROZEN AT ENTRY. Every excursion in
                 this study is divided by that entry ATR and by nothing else.
initial stop     1.00 ATR from entry, on a completed 1s bar LOW/HIGH
confirming flip  walk_a_confirm_ns — next regime start at or after entry in the
                 trade's own direction
opposing flip    next regime start at or after entry in direction −d
NATURAL exit     STOP-LIVE:      first of 1 ATR stop / opposing flip / 15:00 CT
                 UNCONSTRAINED:  first of opposing flip / 15:00 CT (stop released)
fills            a TRIGGER on a completed 1s bar fills at the FOLLOWING bar's
                 OPEN; the trigger price is NEVER credited (checklist H4).
                 A SCHEDULED terminal (opposing flip, 15:00 flat) marks at that
                 bar's own close. Inherited unchanged.
session          clamped to the entry's own session; no overnight stitching
cost             2 ticks round-turn = 0.50 points, charged once PER UNIT EXIT
same-bar ties    resolved ADVERSELY, flagged, optimistic bound reported
```

Populations (Phase 0 must reproduce all seven **exactly**):

```text
ORIGINAL ENTRIES        8,950
CONFIRMED               4,705
STOPPED_BEFORE_CONFIRM  4,245
MEASURABLE CONFIRMED    4,656     <- the PRIMARY population
NON-MEASURABLE             49     SESSION_CLOSE_UNRESOLVED
giveback pool/entry     0.89808   (tolerance 0.005)
baseline net/entry     −0.07653   (tolerance 0.005)
```

---

## 5. Causal contract

### D1 — The dual track (inherited from the predecessor's D1, unchanged)

| Surface | Path | Reason |
|---|---|---|
| Rung events, Phases 1–4 descriptive geometry | **UNCONSTRAINED** (`unc_i`) | The brief forbids conditioning descriptive MAE on survival of the 1.00 ATR stop. Terminating the geometry at the stop is the censored-population defect that understated required stop room 5× in a prior study. |
| Phase 5 stop-survival frontier | **UNCONSTRAINED** | The frontier answers "would a stop of distance `D` have survived this path", which is undefined if a different stop already ended the path. |
| Phases 6–7 ratchet economics | **STOP-LIVE** (`nat_i`) | Any policy is evaluated inside the accepted economic contract, no exceptions. The baseline is the accepted natural management. |

Every rung event carries `stop_live_reachable`. A rung first reached **after** the
trade's 1.00 ATR stop already fired (`r > nat_i`, ≈ 2.4% of rung events in the
accepted lineage) is **descriptively valid** and **economically inert**: it appears
in Phases 1–5 and is held at baseline with zero delta in Phases 6–7. The count is
reported, never silently dropped.

### D2 — The rung event. Two bases; both computed; primary is POST_CONFIRM.

Let `run_mfe[k] = cummax(max(bar_hi,0))[k]` be the entry-anchored running
favorable excursion (inherited primitive), `ci` the confirmation bar index, and
`unc_i` the unconstrained terminal.

```text
r_entry(X)  = first k in [0, unc_i] with bar_hi[k] >= X       (identical to the
              first k with run_mfe[k] >= X, since run_mfe is a cummax of bar_hi)

FROM_ENTRY   rung index = r_entry(X)              LINEAGE basis (secondary)
POST_CONFIRM rung index = max(r_entry(X), ci)     PRIMARY basis
```

**Why POST_CONFIRM clamps rather than re-touches.** 58.4% of 1.0 ATR rungs and
26.1% of 1.5 ATR rungs are first touched before the confirming flip. Requiring a
*fresh* post-confirmation touch of `X` would demand that price retrace below `X`
and come back — deleting most of the population and, worse, selecting on a
retracement, which is the exact variable under study. At the confirmation bar the
running MFE is already causally known, so a live rule arms immediately. Clamping
preserves trade membership exactly and moves only the arming *timestamp*.

Every rung event is stratified, and **every Phase 2–7 table carries the split**:

```text
ARM_FRESH        r_entry(X) >= ci   rung first earned at or after confirmation
ARM_AT_CONFIRM   r_entry(X) <  ci   rung already banked when the flip confirmed
```

`ARM_FRESH`-only variants of every primary table are emitted, so the strict
reading of "post-confirmation only" is answerable without re-running the study.

**The already-met trap.** For a `POST_CONFIRM` event, `run_mfe[r]` may already
exceed the target `X + step` (an `ARM_AT_CONFIRM` trade banked 1.6 ATR before the
flip, so the 1.0-rung's +0.50 target is met at arming). Such a row is flagged
`target_already_met_at_arm` and is **excluded from every transition and MAE
distribution** — its required adverse excursion is zero by construction, not by
evidence. This is the *"a running extremum mechanically contains an eventual
extremum"* defect, and it inflated an AUC by 0.05–0.09 in a prior study. The
excluded count is reported per rung, per basis, per stratum.

Frozen rung set — **not optimisable**:

```text
X in {1.0, 1.5, 2.0, 2.5, 3.0, 4.0} ATR
```

### D3 — What may be read at the rung

At rung bar `r`, state reads bars `[0..r]` only. Every transition label, adverse
excursion and policy outcome reads **strictly `(r..unc_i]`**, built from suffix
arrays that begin at `r+1`. No array in the implementation spans the boundary.
Eventual MaxMFE, runner bucket and terminal return are **retrospective labels**
and may never enter an arming condition — the brief states this explicitly
("do not use eventual MaxMFE to decide when the stop arms") and it is enforced by
construction: the arming index is a function of `bar_hi[:r+1]` alone.

### D4 — The two adverse-excursion measures. They are not interchangeable.

For a rung event at `r` and an end bar `t` (the target touch, or `unc_i` on
failure), over `k ∈ (r, t]`:

```text
retrace_below_rung_atr  =  X − min(bar_lo[r+1 : t+1])
        the drawdown below the RUNG LEVEL. Drives STATIC protection (Phase 7A).
        May be NEGATIVE, meaning price never returned to the rung level. Reported
        raw; never floored, because the left tail is the finding.

mae_from_hwm_atr        =  max over k of ( run_mfe[k−1] − bar_lo[k] )
        the maximum drawdown from the CAUSAL running high-water mark. Drives the
        HIGH-WATER RATCHET (Phase 7B). Non-negative by construction.
        This is the brief's `mae_from_rung_before_target_atr`.
```

`run_mfe[k−1]` — the high-water mark through the **previous completed bar** — is
used deliberately and is load-bearing twice over. It is *causal* (a stop can only
ratchet on information from a completed bar) and it is *adverse* (a bar that both
sets a new high and breaches the old stop level is counted as stopped). Using
`run_mfe[k]` would let the bar's own high raise the stop before its own low tests
it, which is a same-bar look-ahead.

**Exact correspondence to the frontier (load-bearing).** A high-water ratchet of
distance `D` armed at `r` survives to `t` **iff** `mae_from_hwm_atr < D`. A static
floor at `X − D` survives to `t` **iff** `retrace_below_rung_atr < D`. Phase 5's
survival percentages are therefore the empirical CDFs of the Phase 2 statistics,
and §9 gate 7 asserts the two agree to the row.

### D5 — Same-bar collisions

The window `(r, t]` **includes** bar `t`, the bar on which the target is touched.
If that bar's low also breaches the stop, intra-second ordering is unknowable from
OHLC and the economic reading is **stopped** (adverse). The **optimistic bound**,
computed over `(r, t)` — excluding the target bar's low — is a mandatory column on
every survival and frontier table, never a substitute for the adverse number.

### D6 — Transition classification

For rung `X` and step ∈ {0.50, 1.00}, with target `Y = X + step`:

```text
t = first k in (r, unc_i] with bar_hi[k] >= Y

SUCCESS   t exists                    (and not target_already_met_at_arm)
FAIL      t does not exist before unc_i
```

Failure is reported with its cause, because a session-close terminal is a
censoring event and a flip terminal is not:

```text
pct_fail_terminal_opposing_flip
pct_fail_terminal_session_close     <- the p_unresolved analogue; mandatory
```

A resolved-only failure rate (excluding session-close terminals) accompanies every
headline `P(next rung)` figure.

### D7 — The protective architectures. Frozen before economics.

Arming is always at the rung bar `r`; the order is live from bar `r+1` onward, and
the earliest possible fill is bar `r+2`'s open. Four architectures, no more:

| Code | Arming | Stop level on bar `k > r` |
|---|---|---|
| `STATIC` | once, at the first touch of `X` | `X − D`, constant |
| `HWM` | once, at the first touch of `X` | `run_mfe[k−1] − D`, non-decreasing |
| `LADDER_STATIC` | re-arms at **every** rung crossed | `max over rungs X' ≤ run_mfe[k−1] of (X' − D)` |
| `LADDER_HWM` | re-arms at every rung crossed | identical to `HWM` from the first rung armed — retained only to prove that identity, and reported once |

`LADDER_HWM` is mathematically identical to `HWM` armed at the lowest rung the
trade reaches, because a high-water stop already advances continuously. It is
computed and asserted equal (§9 gate 8) rather than reported as a separate
architecture, so the master table cannot imply a distinction that does not exist.

**Interaction with the accepted 1.00 ATR stop.** The effective stop is
`max(−1.00, architecture_level)` and it **never loosens**. Every level in the
frozen grid is ≥ `1.0 − 1.25 = −0.25` ATR, so an armed architecture always
dominates the initial stop; before arming, the 1.00 ATR stop is the only stop.
The policy terminal is therefore
`min(first architecture trigger after r, opposing flip, 15:00 CT)`.

Frozen diagnostic stop grid — **not optimisable**:

```text
D in {0.25, 0.375, 0.50, 0.625, 0.75, 1.00, 1.25} ATR
```

### D8 — Mandatory placebos. Non-negotiable on this line.

This program has **four times** mistaken "acting earlier than a bad exit" for an
edge, and the accepted natural exit is known to be worth *less than a random one*.
No economic number in this study is reported without its controls:

| Control | Definition | Isolates |
|---|---|---|
| `P_BLIND` | identical architecture and `D`, armed at an offset drawn uniformly from the frozen dense grid `{15,30,…,600}s` after confirmation instead of at the rung. If the offset lands past `nat_i`, no arming — the trade is held at baseline, exactly as a live rule would experience it. 20 draws, seed 20260811. | whether the **rung** is the right trigger, vs. any tighter stop being better |
| `P_UNCOND` | identical architecture and `D`, armed at the confirmation bar for **every** measurable confirmed trade, no rung condition. Deterministic. | whether the rung condition adds anything over "just tighten the stop after confirmation" |
| `P_UNIFORM` | armed at an index drawn uniformly from `[ci, nat_i)`. **Uses the realised lifetime — a benchmark, never a rule.** 20 draws, same seed. | how much of any "edge" is knowledge of how long the trade lives |

`P_BLIND` and `P_UNCOND` are causally implementable and are the ones the decision
gate reads. `P_UNIFORM` is diagnostic only and is labelled `FUTURE_INFORMATION`
wherever it appears. The length-blind control exists because a placebo drawn over
the *realised* lifetime is itself look-ahead — it inverted an accepted study's
headline in this repository once already.

### D9 — Runner destruction. Defined before any economics are computed.

Tiers `T ∈ {2.0, 2.5, 3.0, 4.0, 5.0}` on `eventual_max_mfe_atr` (unconstrained,
retrospective). For each `(X, D, architecture)` and each tier, over participants:

```text
runner_survival_T     % of trades whose unconstrained path reaches T ATR MFE that
                      are STILL IN THE TRADE when T is first touched
runner_cut_T          % of those trades whose policy exit precedes their baseline
                      terminal AND returns less than baseline
runner_delta_T        mean (policy − baseline) return on that tier, in ATR
runner_pnl_retained_T sum(policy return) / sum(baseline return) on that tier
```

`runner_survival_T` is the master table's runner column. An architecture that
improves the mean by destroying the right tail is rejected by gate condition 6
regardless of its pooled delta.

### D10 — Dependence and stability

- Every table reports **`n_trades`** and, where rung events are pooled across
  rungs, `n_unique_trades`. A trade contributing to five rung populations is five
  rows and one trade, and both numbers are visible.
- Year and LONG/SHORT stability is assessed at **trade level** within each
  `(X, D, architecture)` cell.
- Intervals are **trade-clustered bootstraps** (resample trades with replacement,
  1,000 draws, seed 20260811). No p-value is quoted from pooled rung events.

### D11 — Load-bearing checklist rules

`A1` (decision-time snap), `B4` (no negative shift / future read), `C1–C3`
(population containment, censoring, matched comparison), `F` (label horizon
strictly after decision), `H4` (fill never priced at the trigger level).

### D12 — The duration confound in Phase 4. Disclosed and controlled.

A SUCCESS trade's adverse-excursion window ends at the target touch; a FAIL
trade's window runs to the terminal. **Longer window ⇒ larger observed MAE,
mechanically.** Any AUC computed on the raw windows is inflated by trade duration
and is not evidence of separation — this is the *"path-shape classes are
confounded with trade duration"* defect, recorded in this repository's memory.

Phase 4 therefore reports **three** numbers for every rung and every step, and the
raw one is never quoted alone:

```text
auc_raw            SUCCESS vs FAIL on the full post-rung windows. DISCLOSED AS
                   DURATION-CONFOUNDED in the column name and in every caption.
auc_horizon_matched  for each SUCCESS with time-to-target τ, each FAIL's MAE is
                   recomputed over the SAME τ seconds after its own rung
                   (truncated window). Matched by τ decile. THE PRIMARY NUMBER.
auc_frontier       the separation actually available to a stop: the AUC implied by
                   the Phase 5 survival curves, which evaluate both classes over
                   their whole paths and are immune to the confound.
```

---

## 6. Deliverables Manifest (frozen; the completion gate checks this list literally)

| # | Path | Type | Required contents |
|---|---|---|---|
| 1 | `results/population_reconciliation.parquet` | table | `quantity, observed, accepted, delta, tolerance, passed` — the seven §4 quantities plus the six accepted `P(next +0.50)` ladder values |
| 2 | `results/rung_events.parquet` | table | one row per (trade × rung × basis); `trade_id/regime_id, year, side, rung_atr, basis, stratum, rung_ts, rung_idx, rung_price, rung_overshoot_atr, entry_price, entry_atr, confirmation_ts, stop_live_reachable, nat_terminal_ts, nat_terminal_return_atr, unc_terminal_ts, unc_terminal_return_atr, unc_terminal_kind, eventual_max_mfe_atr, runner_bucket, target_already_met_at_arm_050/100` |
| 3 | `results/rung_achievement.csv/.parquet` | table | **Phase 1 headline** — per rung × basis × stratum × slice: `n_achieving, pct_of_measurable_confirmed, pct_of_original_8950, pct_arm_fresh, pct_stop_live_reachable, median_overshoot_atr` |
| 4 | `results/rung_transitions.parquet` | table | one row per (rung event × step ∈ {0.50, 1.00}); `outcome ∈ {SUCCESS, FAIL, ALREADY_MET}`, `secs_to_target, retrace_below_rung_atr, mae_from_hwm_atr` (+ optimistic-bound variants), `fail_terminal_kind`, all Phase 3 failure geometry |
| 5 | `results/success_mae_distribution.csv/.parquet` | table | **Phase 2 headline** — per rung × step × measure × slice (`POOLED/YEAR/SIDE/STRATUM`): `n, mean, median, p25, p50, p75, p80, p85, p90, p95, p99` |
| 6 | `results/failure_geometry.csv/.parquet` | table | **Phase 3** — per rung × slice: `max_additional_mfe_after_rung, mae_from_hwm_to_terminal, giveback_hwm_to_terminal, secs_rung_to_terminal, pct_another_favorable_extreme, natural_terminal_return, stop_live_terminal_outcome` — mean/median/p75/p90 each |
| 7 | `results/overlap.csv/.parquet` | table | **Phase 4** — per rung × step × slice: `median_diff, p75_diff, p90_diff, auc_raw_DURATION_CONFOUNDED, auc_horizon_matched, auc_frontier, ci_lo, ci_hi, year_stable_n, side_stable` |
| 8 | `results/stop_survival_frontier.csv/.parquet` | table | **Phase 5** — per rung × D × slice: `pct_success_050_surviving, pct_success_100_surviving` (+ optimistic bounds), `pct_fail_050_stopped, giveback_prevented_mean/median, realized_return_if_stopped_mean/median, secs_stop_before_natural_terminal_median` |
| 9 | `results/preservation_frontier.csv/.parquet` | table | per rung × step: the `D` achieving ≥95% / ≥90% / ≥85% success preservation, by interpolation on the frozen grid, with the failure-side consequence at each |
| 10 | `results/ratchet_economics.parquet` | table | one row per (trade × rung × D × architecture): `baseline_return_atr, policy_return_atr, delta_atr, policy_exit_kind, policy_exit_ts, participated` |
| 11 | `results/ratchet_summary.csv/.parquet` | table | **Phase 6/7** — per rung × D × architecture × slice: `n_achieving, delta_per_achieving_trade, delta_per_confirmed_trade, delta_per_original_entry, pct_giveback_pool_recovered, absolute_net_per_original_entry, delta_P_BLIND, delta_P_UNCOND, delta_P_UNIFORM_FUTURE_INFO, edge_over_blind, edge_over_uncond, beats_blind, beats_uncond, ci_lo, ci_hi` |
| 12 | `results/runner_destruction.csv/.parquet` | table | per rung × D × architecture × tier ∈ {2.0,2.5,3.0,4.0,5.0}: the four D9 metrics, plus the same four for `P_BLIND` |
| 13 | `results/static_vs_ratchet.csv/.parquet` | table | **Phase 7** — `STATIC` vs `HWM` head-to-head on identical `(X, D)` cells, with the `LADDER_STATIC` column and the `LADDER_HWM ≡ HWM` assertion result |
| 14 | `results/master_tradeoff.csv/.parquet` | table | **THE MOST IMPORTANT TABLE.** `rung, stop_D, architecture, n_achieving, success_050_survival, failure_stop_rate, giveback_prevented, runner_survival_3atr, delta_per_original_entry, pct_giveback_pool_recovered, absolute_net_per_original_entry, edge_over_blind, years_positive_of_5, both_sides_positive`. Sorted by `rung, stop_D, architecture` — **conceptually, never by performance** |
| 15 | `results/stability.csv/.parquet` | table | **Phase 9** — every candidate cell × {2021,2022,2023,2024,2025} × {LONG,SHORT}, trade-level |
| 16 | `results/path_examples.csv` + `results/path_examples.parquet` | table | **Phase 8** — the six mandated categories, selected by explicit frozen quantile rules (§8), with the causal bar-by-bar path of each |
| 17 | `results/decision_gate.csv/.parquet` | table | the 7 §8 conditions × candidate cell, `condition, value, threshold, passed`, plus `gate_open` |
| 18 | `results/validation_report.json` | json | the 16 gates of §9, `all_passed` |
| 19 | `results/summary.json` | json | headline answers to the 8 §10 questions + final classification |
| 20 | `results/partition_manifest.json` | json | input paths, row counts, frozen constants, seeds, disclosures |
| 21 | `SPEC.md` · `README.md` · `REPORT.md` | docs | REPORT answers Q1–Q8 of §10 and ends with exactly one label |
| 22 | `audit/lint.json` · `audit/status.json` · `audit/contract_status.json` | json | machine-readable audit verdicts, `critical: 0` required |

CSV mirrors are required for #1, #3, #5–#9, #11–#17. #2, #4 and #10 are
per-event panels and are parquet-only by design.

### Terminal decision labels — every label reachable, routing explicit

| Label | Condition |
|---|---|
| **A** PROFIT RATCHET SUPPORTED | §8 gate opens for at least one `(X, D)` cell in **both** the `STATIC` and `HWM` architectures |
| **B** STATIC PROFIT FLOOR SUPPORTED, TRAILING RATCHET NOT | gate opens for `STATIC` (or `LADDER_STATIC`) only |
| **C** TRAILING RATCHET SUPPORTED, STATIC FLOOR NOT | gate opens for `HWM` only |
| **D** GEOMETRY SEPARATES BUT ECONOMICS DO NOT | some `(X, D)` clears preservation ≥ 90% **and** a material failed-transition giveback reduction (gate conditions 1–2), but **no** cell clears the full gate |
| **E** PROFIT_RATCHET_NOT_SUPPORTED | no cell clears conditions 1–2; successful and failed continuation paths overlap too heavily for any stop distance to separate them |
| **H** RESULT INVALID / CONTRACT FAILURE | any surviving audit CRITICAL, or Phase 0 reconciliation fails |

Routing is total: every gate outcome maps to exactly one label, and D is reachable
whenever the gate closes with geometry intact. (The predecessor shipped a SPEC in
which label C was unreachable; that defect is not repeated here.)

---

## 7. Domain & completeness contract

- **Partition grid:** 5 calendar years × 2 sides = **10 partitions**, enumerated
  `entry_year ∈ {2021..2025}` × `side ∈ {LONG, SHORT}`. All 10 must be non-empty.
- **Cell grid completeness:** 6 rungs × 7 stop distances × 3 reported
  architectures (`STATIC`, `HWM`, `LADDER_STATIC`) = **126 cells**, every one
  emitted in `master_tradeoff`. A cell with `n_achieving = 0` is **retained with a
  flag**, never dropped.
- **Basis/stratum completeness:** 2 bases × 2 strata × 6 rungs = 24 combinations
  in `rung_achievement`; all emitted, zero-count cells flagged.
- **Transition completeness:** every rung event yields exactly 2 rows in
  `rung_transitions` (step 0.50 and 1.00) with a non-null `outcome` in
  `{SUCCESS, FAIL, ALREADY_MET}`. `n_rung_events × 2 == n_transition_rows` is a
  hard assertion.
- **Boundary convention:** America/Chicago; RTH `[08:30, 15:00)` CT; windows
  clamped to the entry's own session index range; no overnight stitching.
- **Nulls are never imputed.** A missing quantile (`n < 20` in a slice) is emitted
  as null with the count visible, never carried forward or interpolated.
- **Global validation:** all 16 gates of §9 pass.

---

## 8. Stop conditions, path-example selection, and the decision gate

**Abort (emit H) if:** Phase 0 fails to reproduce 8,950 / 4,705 / 4,245 / 4,656 /
49; or the pool and baseline miss the accepted values by > 0.005 ATR/entry; or the
`FROM_ENTRY` basis fails to reproduce the accepted `P(next +0.50)` ladder
(0.8070 / 0.8008 / 0.7920 / 0.8149 / 0.8008 / 0.8042) within 0.002; or any of the
10 partitions is empty; or any audit CRITICAL survives.

**If a defect is found that changes the accepted predecessor population or
economics, execution STOPS and the defect is reported. Lineage is never silently
repaired.**

### Path-example selection rules (Phase 8), frozen before results

Selected mechanically from `rung_transitions` at rung `X = 2.0`, step 0.50,
architecture `HWM`, `D = 0.50`, `basis = POST_CONFIRM`; three trades per category,
taken at the 25th/50th/75th percentile *of the ranking variable within the
category*, seed-free and deterministic:

```text
1 SUCCESS, tiny retracement        SUCCESS_050 with mae_from_hwm in the bottom decile
2 SUCCESS, large retracement       SUCCESS_050 with mae_from_hwm in the top decile
3 FAIL caught well by the ratchet  FAIL_050, stopped by D, giveback_prevented top quartile
4 FAIL not helped by the ratchet   FAIL_050, stopped by D, giveback_prevented bottom quartile
5 >=3 ATR runner destroyed         eventual_max_mfe >= 3, runner_survival_3atr = false
6 >=3 ATR runner preserved         eventual_max_mfe >= 3, survived D = 1.25 but not D = 0.375
```

### The decision gate (Phase 10). Machine-evaluated.

A **candidate cell** is one `(rung X, stop distance D, architecture)` triple on the
frozen grid. No unions, no interpolated thresholds, no post-hoc regions.
Architectures run for all 126 cells regardless; the gate decides what may be
*claimed*, not what is computed.

```text
1 PRESERVATION    >= 90% of SUCCESS_050 transitions survive D (adverse convention)
2 GIVEBACK        mean giveback prevented on FAIL_050 paths >= 0.50 ATR, and the
                  failed-transition stop rate is >= 25%
3 ECONOMICS       delta per ORIGINAL entry > 0 after accepted costs, AND the cell
                  beats BOTH causal placebos (edge_over_blind > 0 and
                  edge_over_uncond > 0), AND the trade-clustered CI lower bound
                  on delta per original entry is > 0
4 YEAR            delta per original entry >= 0 in at least 4 of 5 years
5 DIRECTION       delta per original entry > 0 for BOTH long and short; neither
                  side worse than -0.02 ATR/entry
6 TAIL            runner_survival_3atr >= 80% AND runner_pnl_retained_3.0 >= 0.90
7 NOT-ARTIFACT    the cell's edge is not explained by future information: its
                  delta exceeds P_UNIFORM's delta, or P_UNIFORM's own delta is
                  <= 0; and >= 60% of participants are stop_live_reachable
```

**Condition 3 is a DELTA test, per the study owner's frozen decision.** A cell may
pass while the strategy remains net-negative overall — that is the legitimate
"the ratchet works, the entry is the problem" outcome. To make that impossible to
hide, `absolute_net_per_original_entry` is a **mandatory column in every economic
table including the master table**, and the REPORT states the absolute net of any
passing cell in the same sentence as its delta.

**If the gate stays closed:** the study stops and returns **D** or **E** by the §6
routing. No policy is manufactured, no threshold is searched, no fifth
architecture is invented.

---

## 9. Validation gates (all 16 must pass)

```text
 1 8,950 / 4,705 / 4,245 / 4,656 / 49 reproduced exactly
 2 pool 0.89808 and baseline -0.07653 per original entry reproduced (tol 0.005)
 3 the FROM_ENTRY basis reproduces the accepted P(next +0.50) ladder to 0.002 at
   all six rungs, and the accepted median pre-rung MAE band 0.30-0.36 ATR
 4 2026 never read: no input path or filter admits entry_year 2026, asserted at
   the source before any walk
 5 no overnight stitching; every rung event, target touch and policy exit lies
   inside the entry's own RTH session
 6 every POST_CONFIRM rung event satisfies rung_ts >= confirm_ns, and every
   FROM_ENTRY event satisfies rung_idx == first bar with bar_hi >= X
 7 the Phase 5 survival percentages equal the empirical CDF of the Phase 2
   statistics to the row: pct_success_surviving(D) == mean(mae_from_hwm < D) for
   HWM and mean(retrace_below_rung < D) for STATIC, exactly
 8 LADDER_HWM produces a bit-identical exit index to HWM armed at the lowest rung
   reached, on every trade (the D7 identity assertion)
 9 no policy exit is priced at its own trigger level: every triggered exit fills
   at the FOLLOWING bar's open (H4), verified on a sample of >= 500 exits
10 forward labels strictly after the rung bar: suffix arrays built from r+1,
   verified by HARD-TRUNCATED replay of >= 250 trades and >= 2,500 rung events
   from the raw 1s parquet, >= 6 quantities each, 0 mismatches
11 same-bar collisions counted, resolved adversely, optimistic bound reported on
   every survival and frontier table
12 target_already_met_at_arm rows are excluded from every MAE and transition
   distribution, and their count is reported per rung/basis/stratum
13 the horizon-matched AUC is computed on truncated FAIL windows and is the
   number quoted; auc_raw carries DURATION_CONFOUNDED in its column name
14 placebos are causally implementable where the gate reads them: P_BLIND draws a
   GRID OFFSET not an index and its support does not depend on realised lifetime;
   P_UNIFORM is labelled FUTURE_INFORMATION everywhere it appears
15 repeated rung events are not treated as independent trades: every pooled table
   carries n_unique_trades, and all year/side stability is trade-level (D10)
16 causal_lint exits 0; lookahead-auditor and contract-checker both report
   critical = 0
```

Any CRITICAL finding blocks conclusions and forces label **H**.

## 10. Questions the REPORT must answer in plain English

1. Once we have earned +1 / +1.5 / +2 / +2.5 / +3 / +4 ATR, how much retracement
   do trades that successfully continue actually require?
2. What stop distance preserves 90%, 95% and 85% of successful next-rung
   transitions?
3. Are failed next-rung transitions meaningfully distinguishable by their adverse
   excursion — after the duration confound is removed?
4. Can a profit floor eliminate substantial giveback without sacrificing the
   right-tail runners?
5. Is STATIC protection better than a moving HIGH-WATER ratchet?
6. At what achieved-MFE level, if any, does protection become economically
   justified?
7. How much of the accepted ~0.898 ATR/original-entry giveback pool can actually
   be recovered?
8. Can we change the PAYOFF FUNCTION enough that we no longer need to predict the
   exact end of the regime?

## 11. Audit plan

- Pre-execution: `python scripts/causal_lint.py --study studies/post_confirm_profit_ratchet --json studies/post_confirm_profit_ratchet/audit/lint.json` must exit 0
- Pre-execution: `lookahead-auditor` on §5 (the causal contract) before the first full run
- Completion: `lookahead-auditor` + `contract-checker`; `audit/status.json` and
  `audit/contract_status.json` must both show `critical: 0`
</content>
