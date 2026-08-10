# Top-10 Armed Entry Refinement — Frozen Specification

**Study:** `top10_armed_entry_refinement` · **Frozen:** 2026-08-10, before implementation.
**Substrate:** `data/canonical/regime_complete_v1/`
**Armed population:** frozen from `studies/armed_fade_score_path_progression/` — **8,950**

---

## 0. Objective

**Entry study only.** No exit optimization, no retraining, no feature or model
contract change, no large grid.

> After a true Top-10 crossing in a regime already >600s old, what is the
> **minimum additional causal evidence** that buys meaningfully higher
> confirmation probability without surrendering the economic advantage of being
> early?

We are **not** maximizing confirmation probability. A rule that lifts
confirmation 52% → 70% while giving away most of the move is not superior.

---

## 1. Frozen contract

```text
arm             the frozen Top-10 arm: regime age >600s, true in-domain Top-10
                crossing from below, direction-specific frozen threshold, prior
                scored in-domain observation exists and is below, first per
                regime, one arm per regime. 8,950 regimes, reproduced exactly.
candidate entry the first post-arm true score dispatch satisfying the rule
entry price     checkpoint_reference_price at that dispatch
ATR             atr_at_checkpoint at the CANDIDATE ENTRY, frozen for that trade
stop            1.0 ATR from the CANDIDATE entry price -- the arm's stop is NOT
                carried forward
confirm         next_start_after(entry_ns, direction, inclusive=True)
confirm price   the CLOSE of the 1s bar at the confirming flip
session         RTH only, forced flat 15:00 CT, window clamped to the entry session
cost            2 ticks round-turn = 0.50 points (secondary reporting only)
measurement     opens on the first 1s bar STRICTLY AFTER the entry timestamp
same-bar ties   resolved adversely, flagged, both bounds reported
```

### 1.1 The armed state does not expire on adverse price

An arm is a **state, not a position**. A 1 ATR adverse move before the trigger
costs nothing, and a later entry gets a better price — that is realistic and it
is part of what waiting buys.

The arm expires naturally at the regime's end, and this is **structurally
enforced**: post-arm score rows carry the *old* regime's `regime_id`, so no
trigger can fire at or after the confirming flip. No explicit cancel is needed.

**Fairness disclosure, mandatory.** Because there is no adverse invalidation,
a candidate can enter in cases where immediate Top-10 was already stopped out —
a free option the baseline does not have. Every candidate must therefore report
`pct_entries_after_arm_1atr_adverse`, and the report must discuss it wherever a
lift is claimed.

### 1.2 Intermediate levels are INTERPOLATED, not percentiles

The frozen calibration distribution **cannot be recovered**. Neither calibration
population reproduces from the canonical store — bullish 216,828 observed vs
171,334 in the contract, bearish 172,031 vs 163,397, and the bearish population
is named `BEARISH_2025_DEVELOPMENT_POPULATION`, a model-development artifact
predating the store. A true reconstructed Top-7.5 percentile is therefore
unavailable, and deriving one from the evaluation population is forbidden.

Family A instead uses **arithmetic interpolation between two already-frozen
contract values**, which introduces no new percentile claim and needs no
calibration data:

| Level | Bullish | Bearish |
|---|---:|---:|
| frozen `top_10` | 0.431672 | 0.445591 |
| **`INTERP_L1`** (⅓ of the way to Top-5) | **0.456684** | **0.466548** |
| **`INTERP_L2`** (midpoint) | **0.469190** | **0.477027** |
| frozen `top_5` | 0.506708 | 0.508462 |

These are labelled **INTERPOLATED RESEARCH LEVEL — NOT A PERCENTILE** everywhere
they appear. They are not thresholds, carry no calibration guarantee, and may
not be promoted to a contract.

---

## 2. Baselines — four, fixed, not discoveries

All measured **after arming**, from the arm's own regime:

```text
A  IMMEDIATE_TOP10   enter at the arm timestamp
B  FIRST_TOP5        first post-arm true observation >= frozen Top-5
C  FIRST_TOP2_5      first post-arm true observation >= frozen Top-2.5
D  FIRST_TOP1        first post-arm true observation >= frozen Top-1
```

### 2.1 The after-arming baselines reproduce the quoted figures exactly

> **Amendment, 2026-08-10.** This section originally asserted that the brief's
> quoted returns came from the independent first-qualifying populations and that
> after-arming entries would return ~30% less. **That was wrong**, and the error
> is recorded rather than overwritten. It came from comparing against the armed
> study's *uncensored* confirm population (which includes trades that hit the
> stop before confirming, dragging the median down), not its censored one.
>
> Measured after arming on the censored population — confirm strictly before the
> 1 ATR stop, the same bound the quoted rates use — the baselines reproduce the
> brief exactly:
>
> | Baseline | P(confirm) | quoted | median return | quoted |
> |---|---:|---:|---:|---:|
> | IMMEDIATE_TOP10 | 0.520 | 52.1% | +0.854 | +0.85 |
> | FIRST_TOP5 | 0.589 | 59.0% | +0.655 | +0.66 |
> | FIRST_TOP2_5 | 0.648 | 64.8% | +0.475 | +0.48 |
> | FIRST_TOP1 | 0.731 | 73.1% | +0.295 | +0.30 |
>
> There is one frontier, not two, and no reference row set is needed. This
> agreement is also a strong parity check on the armed window (§1.1): it only
> holds once the arm is allowed to survive an adverse move.

---

## 3. Candidate families — hard cap 8 discovered

Nominated **from Phase 1/2 evidence**, not in advance. Structurally distinct, not
a Cartesian grid. Family E (fast progression) is nominated **only if** Phase 2
shows timing carries information; if the cap is reached by better-supported
families, its omission must be stated with the reason.

| Family | Concept | At most |
|---|---|---|
| A | intermediate interpolated level | 2 levels |
| B | Top-10 persistence, consecutive true dispatches | 2 counts |
| C | score progression above the arm score | 2 increments |
| D | retreat then re-expansion to a new post-arm high | 2 retreat defs (0.03 / 0.05, both already used in accepted work) |
| E | fast progression to a deeper level | only if Phase 2 supports it; coarse quartiles |
| F | one hybrid, only if both components independently matter | 1 |

---

## 4. Metrics

### 4.1 Both denominators are first-class

Only ~7,371 of 8,950 arms ever reach Top-5, so a conditional rate flatters
selective triggers. The primary tradeoff table carries **both**:

```text
P(confirm | entered)          conditional -- comparable to the quoted baselines
confirmed_per_100_arms        throughput -- (entries/arms) x P(confirm | entered)
```

A rule entering 30% of arms at 70% confirmation yields **21** confirmed trades
per 100 arms; immediate Top-10 at 52% on 100% of arms yields **52**. Both numbers
must be visible or the frontier is misread.

### 4.2 Per candidate

```text
POPULATION      arms · eligible entries · pct_arms_entered · n
COST OF WAITING median/mean seconds arm->entry;
                SIGNED price move arm->entry in ARM ATR (waiting sometimes gains
                a better price), p25/p75/p90;
                pct_entries_after_arm_1atr_adverse   (SPEC 1.1)
CONFIRMATION    pct confirm before 1 ATR stop · pct stopped · session unresolved
ENTRY->CONFIRM  return / MFE / MAE at the confirming flip bar close, in the
                CANDIDATE's own frozen ATR; seconds; pct positive; pct >= 0.25 /
                0.50 / 0.75 / 1.00 ATR
EFFICIENCY      delta-P(confirm) per ATR sacrificed; per second waited
                -- descriptive only, never a single composite selection metric
```

Excursions for the *cost of waiting* are normalised by the **arm** ATR so
candidates are commensurable; trade metrics use the **candidate's own** ATR.

---

## 5. Phases

**1 — descriptive score path after arm.** SUCCESS (confirm before 1 ATR from the
*arm*) / FAILURE / SESSION. True dispatches only. Level, delta from arm, running
max, drawdown from max, slope over 10/20/30/60s where real dispatches bracket the
interval (**no interpolation across gaps**), consecutive counts, time to each
level, retreat, re-expansion, recrossings, max score before terminal.

**2 — separation.** At 5/10/15/20/30/45/60s from arm, SUCCESS vs FAILURE on each
feature: distributions, effect size (Cliff's delta), and AUC. **Does a useful
trigger exist before first Top-5?**

**3 — nominate** ≤8 candidates from that evidence.

**4 — trade path evaluation** per §4.

**5 — frontier.** Pareto on (confirmation probability, median return at
confirmation). Dominated = another candidate has ≥ both with similar or larger n.
Report throughput alongside; a candidate on the conditional frontier may be
dominated on throughput.

**6 — stability.** Pooled / LONG / SHORT / 2021–2025.

**7 — shortlist.** ≤3 finalists, each `ADVANCE` / `DIAGNOSTIC_ONLY` / `REJECT`.
`ADVANCE` requires all of: materially better confirmation than immediate Top-10;
materially more remaining move than Top-5 or Top-2.5; not dominated on the
frontier; stable across years; not one-directional; adequate n; no audit blocker.

---

## 6. Deliverables Manifest

| # | Path |
|---|---|
| 1 | `SPEC.md` |
| 2 | `README.md` |
| 3 | `REPORT.md` — the eleven report questions, then exactly one §7 label |
| 4 | `results/armed_score_path_diagnostics.parquet` |
| 5 | `results/success_failure_separation.parquet` |
| 6 | `results/candidate_entries.parquet` |
| 7 | `results/candidate_trade_metrics.parquet` |
| 8 | `results/confirmation_move_frontier.parquet` |
| 9 | `results/year_direction_stability.parquet` |
| 10 | `results/finalist_shortlist.json` |
| 11 | `results/validation_report.json` |
| 12 | `results/partition_manifest.json` |
| 13 | `audit/lint.json`, `audit/status.json`, `audit/contract_status.json` |

Parquet deliverables are gitignored per repo protocol; CSV mirrors are committed
for the small tabular ones so the evidence is version-controlled.

## 7. Final classification

Exactly one. All reachable.

| Label | Condition |
|---|---|
| **A** `IMMEDIATE TOP-10 REMAINS THE BEST EARLY ENTRY` | no candidate is non-dominated against immediate Top-10 on the conditional frontier, or every lift is erased by throughput |
| **B** `TOP-10 SHOULD ARM; SIMPLE PERSISTENCE IMPROVES ENTRY` | a Family B candidate is non-dominated and stable, and beats Families A/C/D |
| **C** `TOP-10 SHOULD ARM; INTERMEDIATE SCORE PROGRESSION IMPROVES ENTRY` | a Family A or C candidate is non-dominated and stable, and beats B/D |
| **D** `TOP-10 SHOULD ARM; RETREAT / RE-EXPANSION IMPROVES ENTRY` | a Family D candidate is non-dominated and stable, and beats A/B/C |
| **E** `MULTIPLE ARMED TRIGGERS WARRANT BOUNDED LIFECYCLE VALIDATION` | two or more structurally distinct candidates are non-dominated and stable |
| **F** `NO RELIABLE ARMED ENTRY IMPROVEMENT FOUND` | candidates separate but none survives stability, throughput or the free-option disclosure |
| **G** `RESULT INVALID / CONTRACT FAILURE` | a §8 gate fails |

## 8. Validation

```text
 1  armed population == 8,950 exactly
 2  immediate Top-10 baseline confirmation reproduces the accepted result
 3  triggers use TRUE score dispatches only
 4  the prior qualifying observation is within the same regime
 5  no carried-forward score counted as persistence
 6  candidate entry ns >= arm ns, and strictly inside the armed regime
 7  each candidate trade uses its OWN frozen ATR
 8  measurement opens strictly after the entry timestamp
 9  confirmation / stop ordering deterministic; same-bar ties adverse
10  no overnight stitching; session containment
11  deterministic replay of >= 200 candidate trades via an independent code path
12  causal_lint · lookahead-auditor · contract-checker
```

Pre-execution `causal_lint` + `lookahead-auditor` on the new entry-selection
logic before the first full run.

## 9. Domain and non-goals

NQ `*.v.0`, 2021–2025, RTH only. **2025 is NOT threshold-OOS** — inherited
overlap waiver `studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`;
it may not be described as clean OOS. 2026 untouched.

No exit optimization, no retraining, no model-contract change, no percentile
grid, no parameter sweep, no recollection, and no promotion of an interpolated
level to a threshold contract.

**Explicitly out of scope, preserved for a later study:** the post-confirmation
exit hypothesis (Top-10 warning against the NEW regime arming exit protection,
stop tightening relative to confirmation close / entry / favorable extreme, which
percentile sits nearest maximum MFE). None of it is tested here. Note the raw
post-confirmation score is causal but **largely out of domain** under the current
frozen contract (0.0%/0.0%/1.6%/16.4% contract-valid at 60/120/180/300s), so any
future use stays exploratory unless a purpose-built domain model is validated.
