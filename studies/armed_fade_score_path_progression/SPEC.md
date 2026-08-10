# Armed Fade Score-Path Progression and MAE-to-Flip — Frozen Specification

**Study:** `armed_fade_score_path_progression`
**Substrate:** `data/canonical/regime_complete_v1/` (REGIME-COMPLETE STORE ACCEPTED)
**Predecessor:** `studies/model_driven_entry_exit_discovery/` (sealed `DISCOVERY_NEGATIVE`)
**Frozen:** before implementation. Nothing below may be changed by a result.

---

## 0. Objective and honesty constraint

Study how the fade-model score evolves **after** a regime older than 600 seconds
first crosses the Top-10% threshold, and quantify the adverse excursion that
successful flips actually require.

Two questions, in order of priority:

> **Q1.** Can Top-10 be treated as an early warning that *arms* the setup, while
> subsequent score progression identifies the subset likely to actually flip
> before consuming too much of the available move?

> **Q2.** For the trades that do successfully flip, how much adverse ATR must be
> tolerated while waiting for confirmation?

**This is a score-path and path-risk discovery study.** It is not a trading
policy optimization. No parameter in this SPEC is tuned against an outcome. The
candidate entry concepts in §11 are hypotheses that must be reported with their
sample size and risk profile; none may be designated a production winner.

**Honesty constraint.** The predecessor study found 0 of 65 entry configurations
and 0 of 18 exit configurations net-positive against these frozen models. This
study inherits that prior. A path structure that looks informative here is a
*structural* finding about score dynamics, not evidence of a monetizable edge,
unless it is accompanied by the economics to support that claim.

---

## 1. Frozen execution assumptions

```text
instrument            NQ, *.v.0 volume-continuous only
session               RTH entries only; forced flat 15:00 CT
bar granularity       1s path bars for all excursion measurement
score cadence         true model dispatches only (nominal 5s, real gaps retained)
cost                  2 ticks round-turn = 0.50 points, charged per completed trade
flat band             |return| < 0.125 points is reported flat
stop                  1.0 ATR adverse excursion
ATR                   frozen at the decision timestamp of the entry in question
```

Costs are reported but never optimized against. §8 success criteria are stated
in probability and ATR terms, not PnL.

---

## 2. Data contract

| Source | Role |
|---|---|
| `canonical_regime_scores_all.parquet` | true model dispatches; 12,156,904 rows, **2,205,823 in-domain** (all RTH) |
| `canonical_regime_paths_all.parquet` | 1s OHLC path; 61,543,945 rows |
| `canonical_regimes_all.parquet` | 137,673 regimes, starts and directions |
| `canonical_model_threshold_contracts.parquet` | frozen percentile thresholds |

Reused without modification from
`studies/model_driven_entry_exit_discovery/implementation/`:
`engine.MarketData`, `engine.RegimeIndex`, `engine.load_market`,
`engine.load_regimes`, `candidates.THRESHOLDS`, `candidates.load_scored`.

### 2.1 Carry-forward exclusion is structural

Carried-forward score copies live on **path** rows
(`is_carried_forward`, `last_bullish_probability`), never on score rows. The
score table contains one row per true dispatch. Therefore no persistence,
progression, or observation count in this study can be contaminated by a
forward-filled second. This is verified, not assumed (§9 gate 2).

### 2.1a An unscored dispatch is not an observation

Roughly 8% of in-domain dispatches (177,429 of 2,205,823) carry a **null
probability**: the dispatch happened, but a frozen feature was incomplete and
the model declined to score. These rows are dropped from the observation stream
before any rule reads it.

They are not observations, for two independent reasons. **Causally**, a null is
not evidence of "below threshold" — if the model declined to score at T−5s, the
last thing a live trader saw was the score at T−10s, and that is the correct
predecessor for a crossing test. **Numerically**, `to_numpy()` renders a null as
NaN and NaN propagates through `np.maximum.accumulate`, so one unscored dispatch
inside a post-arm window would silently corrupt that regime's peak, drawdown,
and shape class rather than failing loudly.

Dropping them does not disturb the §9 gate 1 parity target: the first-qualifying
rule compares `probability >= threshold`, which already excludes nulls, so the
accepted counts are unchanged.

### 2.2 Direction and model are one-to-one

`bullish_in_domain & bearish_in_domain` is true for **0 rows**. The fade contract
maps the bullish model in-domain to a **SHORT** fade and the bearish model
in-domain to a **LONG** fade. "By direction" and "by model" are therefore the
same partition; the study reports it once and states the equivalence rather than
duplicating tables.

### 2.3 Frozen thresholds

Direction-specific, from `candidates.THRESHOLDS`, never derived from this
study's population:

| Level | Bullish model (SHORT fade) | Bearish model (LONG fade) |
|---|---|---|
| `top_10` | 0.43167249785595935 | 0.44559149246408103 |
| `top_5` | 0.5067081427626979 | 0.5084619230529974 |
| `top_2_5` | 0.5697449423968936 | 0.5641320087327389 |
| `top_1` | 0.6412279079940403 | 0.6306416772425602 |

### 2.4 Threshold overlap disclosure

Both frozen calibration populations are calendar-2025 and overlap the evaluation
window. **2025 is not threshold-out-of-sample** and may not be reported as such.

The canonical waiver is
[`studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`](../full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json)
— the path carried in the `waiver_artifact` column of
`canonical_model_threshold_contracts.parquet` for all six percentiles. This
study inherits it; it does not fork a local copy, because a second waiver file
would be a second thing to keep in sync with the store.

---

## 3. The arm event

```text
arm = the first true crossing of Top-10 from below,
      at a checkpoint whose regime age already exceeds 600 seconds
```

Formally: the first in-domain dispatch in a regime where

```text
probability >= top_10 threshold (direction-specific)
AND the immediately preceding in-domain dispatch in the same regime did NOT qualify
AND seconds_from_regime_start > 600
```

A score already at or above Top-10 when the regime crosses 600s of age is **not**
an arm. A new crossing from below is required.

The preceding dispatch used for the from-below test may itself lie before the
600s boundary; the age filter applies to the crossing dispatch only.

**A regime whose first in-domain dispatch already qualifies is not armed.** With
no predecessor there is no observed crossing, and accepting it would assert a
rise from below on zero evidence. This is distinct from "the predecessor did not
qualify" and must not be collapsed into it by a `fill_value` default.

**Arming runs on the full 2021–2025 population, always.** The from-below test
reads each regime's predecessor dispatch, so filtering years before arming would
drop that predecessor at every year boundary and manufacture phantom crossings.
Year breakdowns are produced by slicing the finished event table, never by
slicing the input.

**One arm per regime.** Later re-crossings within the same regime are recorded in
the shape diagnostics but do not create a second armed row.

**Expected population:** a strict subset of the 8,988 first-qualifying-after-600s
regimes in the accepted `regime_lifecycle_600s.json`, reconciled to zero
unexplained exclusions in §9 gate 1.

> **Amendment, 2026-08-09.** This section originally froze the expectation at
> **8,953 armed regimes / 35-regime delta**, estimated before implementation.
> Two subsequent corrections tightened the rule — rejecting regimes with no
> predecessor dispatch, and dropping unscored dispatches from the observation
> stream (§2.1a) — giving **8,950 armed regimes / 38-regime delta (22
> predecessor already qualified + 16 no predecessor)**. The estimate is recorded
> here rather than overwritten. Gate 1 was always written to reconcile the delta
> to *exactly zero unexplained* rather than to a hardcoded count, which is the
> stronger invariant and is why it caught the unscored-dispatch defect instead
> of absorbing it.

---

## 4. Level reach, measured post-arm only

For each armed regime, the first-reach timestamp of Top-5 / Top-2.5 / Top-1 is
the first true dispatch **at or after the arm dispatch** whose probability meets
that level's direction-specific threshold.

A level touched earlier in the regime, before the arm, does not count. The
regime must reach it again post-arm.

**Level reach is session-gated.** A regime may span the overnight boundary, so a
post-arm dispatch can land in the *next* RTH session. A level counts as reached
only if its dispatch falls inside the arm's own session. Counting a next-session
dispatch as "waited for Top-5" would be dishonest: under the frozen 15:00 CT
flat you were out of the market in between, so there was no position to wait
with.

**Multi-level crossing on one dispatch.** If a single dispatch jumps two or more
levels, every level crossed receives that same causal timestamp and the elapsed
time between them is 0. Threshold sequence timestamps are therefore
non-decreasing, never strictly increasing (§9 gate 7).

---

## 5. Two walks, reported separately and never mixed

The study runs two independent path simulations. Every result artifact and every
report table states which walk it came from. **They are never pooled.**

### 5.1 Walk A — arm-anchored lifecycle

One lifecycle per armed regime. The reference price and ATR are frozen at the
Top-10 arm dispatch. The walk terminates at the first of:

```text
confirming regime flip
1.0 ATR adverse excursion from the arm reference price
15:00 CT session close
```

Deeper levels are **conditioning milestones**: a level counts as reached only if
its first-reach dispatch occurs at or before the terminal event. Walk A answers
"does Top-10 function as an arm, and does subsequent progression sort the
survivors?" Its funnel is nested and path-dependent by construction.

### 5.2 Walk B — per-level independent hypothetical entries

For each level a regime reaches post-arm (including Top-10 itself), an
independent hypothetical entry with its **own** reference price
(`checkpoint_reference_price` at that level's first-reach dispatch), its **own**
ATR (`atr_at_checkpoint` at that dispatch), and its **own** 1.0 ATR stop.

A regime whose Walk A lifecycle stopped may still contribute a Walk B entry at a
deeper level, provided that level was reached before the session close. Walk B
answers "what would entering at Top-5 instead of Top-10 have cost and gained?"
and is the basis for the opportunity-cost comparison in §11.

### 5.3 Measurement conventions, both walks

```text
entry reference price   checkpoint_reference_price at the decision dispatch
ATR                     atr_at_checkpoint at the decision dispatch
path window             begins at the first 1s bar strictly after the decision ns
excursion               MAE/MFE from bar HIGH/LOW, running maximum, ATR-normalized
confirming flip         RegimeIndex.next_start_after(ts, direction, inclusive=True)
```

`inclusive=True` is mandatory. A regime flip stamped at second T is knowable only
after a decision made at T under the project's 1s-before-1m dispatch convention.
The superseded strictly-after resolver mis-resolved ~2% of trades and may not be
used.

**Session containment.** Only RTH bars are loaded, so consecutive array indices
jump the overnight gap. Every window is clamped to the arm's own session via the
`day_close_ns` boundary. No path may traverse a session boundary (§9 gate 5).

**Same-bar ambiguity.** A 1s bar that satisfies both the stop and the confirming
flip is not resolvable from OHLC. It resolves **adversely** (stop wins) for the
conservative bound, is flagged `ambiguous`, and both bounds are reported.

---

## 6. Score-path event table

One row per armed regime, written to `results/armed_regime_score_paths.parquet`.

**Identity and arm**
```text
regime_id · direction · model_id · entry_year
regime_start_ns · arm_top10_ns · regime_age_at_arm_s
arm_score · arm_price · arm_atr
```

**Level reach** (repeated for `top5`, `top2_5`, `top1`)
```text
<level>_reached · <level>_ns · score_at_<level> · price_at_<level> · atr_at_<level>
seconds_top10_to_<level>
seconds_top5_to_top2_5 · seconds_top2_5_to_top1
true_score_observations_to_<level>
```

**Walk A terminal**
```text
confirm_reached · confirm_ns · seconds_top10_to_confirm
stop_before_confirm · stop_ns
session_close_unresolved
terminal_label · ambiguous
true_score_observations_to_confirm
```

**Score-path aggregates**
```text
max_score_before_terminal · min_score_after_arm
score_drawdown_from_arm · score_drawdown_from_peak
n_true_observations_post_arm · median_dispatch_gap_s
shape_class_0_03 · shape_class_0_05
```

**Walk A excursion** — one set, always measured from the arm. Deeper levels
subset the population; they never move the measurement origin.
```text
walk_a_mae_to_confirm_atr · walk_a_mfe_to_confirm_atr · walk_a_return_at_confirm_atr
walk_a_confirm_reached_uncensored · walk_a_confirm_reached_censored
walk_a_stop_before_confirm · walk_a_terminal_label · walk_a_terminal_label_full
walk_a_gross_atr · walk_a_net_atr
```

**Walk B excursion** — one set per level reached, each measured from its own
first-reach dispatch, suffixed `_<level>` for `top10`, `top5`, `top2_5`, `top1`.
```text
walk_b_mae_to_confirm_atr_<level> · walk_b_mfe_to_confirm_atr_<level>
walk_b_return_at_confirm_atr_<level>
walk_b_confirm_reached_uncensored_<level> · walk_b_confirm_reached_censored_<level>
walk_b_stop_before_confirm_<level> · walk_b_terminal_label_<level>
walk_b_gross_atr_<level> · walk_b_net_atr_<level>
progress_atr_at_<level>
```

`walk_b_*_top10` and `walk_a_*` are the same measurement by construction, since
the arm is the Top-10 entry. They are emitted under both names so each walk's
artifacts are self-contained, and gate 4 asserts they agree.

---

## 7. Score-path shape taxonomy

Descriptive classification, computed at **two** fixed retreat definitions,
absolute probability decline of **0.03** and **0.05**. Both are reported. Neither
is optimized, and no third value may be introduced.

Evaluated in the order below; **the first match wins**, so every armed regime
receives exactly one class per retreat definition. The order runs
most-specific-first precisely so that no class is unreachable — evaluating
`RETREAT_NO_RECOVERY` before `OSCILLATING` would starve the latter, since every
oscillating path also contains a retreat.

| # | Class | Definition |
|---|---|---|
| 1 | `TOP10_ONLY` | never reaches Top-5 before the terminal event |
| 2 | `OSCILLATING` | >= 2 distinct retreat-then-new-high cycles post-arm |
| 3 | `RETREAT_REEXPANSION` | exactly one retreat >= r from a post-arm peak, then later exceeds that peak |
| 4 | `RETREAT_NO_RECOVERY` | retreats >= r from a post-arm peak and never sets a new post-arm high |
| 5 | `MONOTONIC_PROGRESS` | reaches at least Top-5 post-arm with no retreat >= r |

Because precedence collapses information, the raw components are emitted
alongside the class so any cross-tabulation remains derivable:
`had_retreat_r`, `had_reexpansion_r`, `n_retreat_cycles_r`, `band_changes`,
`reached_top5`. Depth (`TOP10_ONLY`) and shape are orthogonal; the report
cross-tabs them rather than relying on precedence alone.

The threshold band of an observation is its count of levels met (0–4). A band
change is any post-arm dispatch whose band differs from the previous dispatch's.
`band_changes` is **emitted and cross-tabbed but excluded from the class test**:
a single retreat-and-recovery through one band already produces three band
changes, so folding it into `OSCILLATING` as a disjunct swallows
`RETREAT_REEXPANSION` almost entirely. Band traversal measures depth, not
oscillation. The report answers "does repeated threshold crossing behave
differently" from the `band_changes` cross-tab rather than from the class.

---

## 8. Analyses and their required outputs

Each is reported **pooled, by direction, and by year** (2021–2025). Per §2.2,
"by model" is the direction breakdown and is not duplicated.

### 8.1 Threshold progression funnel — Walk A

Stages `armed Top-10 -> Top-5 -> Top-2.5 -> Top-1 -> confirmed`, each with

```text
n · pct of armed population · confirmation probability
stop-before-confirm probability · session-close rate
median seconds to confirmation · median remaining return to confirmation
median MAE to confirmation
```

plus the conditional probabilities and incremental lift

```text
P(confirm | Top-10 armed) · P(confirm | Top-5) · P(confirm | Top-2.5) · P(confirm | Top-1)
P(confirm|Top-5) - P(confirm|Top-10)
P(confirm|Top-2.5) - P(confirm|Top-5)
P(confirm|Top-1) - P(confirm|Top-2.5)
```

### 8.2 MAE-to-confirm — two populations, side by side

**This is mandatory and is the study's second central question.**

Reported at every level (Top-10 arm, Top-5, Top-2.5, Top-1) in **both** forms:

| Population | Definition | Purpose |
|---|---|---|
| `uncensored` | every regime reaching the confirming flip before session close, **no stop applied** | the true stop-room requirement |
| `censored_1atr` | only regimes confirming before a 1.0 ATR adverse excursion | matches the Walk A survivor population |

For each: `n · mean · median · p25 · p50 · p75 · p90 · p95 · max`.

Plus survival thresholds — the share of successful confirmations whose
MAE-to-confirm stays within

```text
0.25 ATR · 0.50 ATR · 0.75 ATR · 1.00 ATR
```

**The censored population is bounded above by 1.0 ATR by construction**, so its
1.00-ATR survival row is 100% and its p90/p95 are truncation artifacts, not
measurements. The report must say so wherever the censored table appears. The
answer to Q2 is read from the **uncensored** distribution.

MAE-to-confirm is measured from the hypothetical entry timestamp through the
confirming-flip bar, normalized by the ATR frozen at that hypothetical entry. It
is never mixed with full-trade MAE after confirmation.

### 8.3 Remaining opportunity — Walk B

For confirmed entries at each level: `MFE_to_confirm_atr` and
`return_at_confirm_atr`, reported as `mean · median · p25 · p75 · p90`, gross and
net. This quantifies the trade-off that earlier levels buy more remaining move at
lower confirmation probability.

### 8.4 Progression speed

Within-level quartiles of elapsed time, computed on this study's population
because they are descriptive, not tuned. Quartiles of `Top-10 -> Top-5`,
`Top-10 -> Top-2.5`, `Top-10 -> Top-1`. Per quartile:

```text
confirmation rate · stop-before-confirm rate
median MAE to confirm · median return at confirm · median MFE to confirm
```

The question is whether rapid escalation is more reliable, less reliable, or
simply later in the price move — the third possibility is distinguished by
reporting `current_progress_atr` at the level dispatch alongside.

### 8.5 Persistence

True dispatches only. Compare 1 / 2 / 3 consecutive observations at or above
Top-10, and 2 / 3 consecutive at or above Top-5 where sample permits.
"Consecutive" means consecutive true dispatches with no gap cap; the observed
dispatch-gap distribution is reported alongside so the result is interpretable.
Per cell: `confirmation probability · median MAE to confirm · median return at
confirm · median time to confirm · n`. **No persistence grid beyond these five
cells.**

### 8.6 Re-expansion

Post-arm: score sets a local peak, retreats >= r, later exceeds that peak.
Reported at r = 0.03 and r = 0.05 against the `no retreat` and
`retreat without recovery` comparators. Per cell: `n · confirmation rate ·
stop-before-confirm rate · median MAE to confirm · median return at confirm ·
median seconds from re-expansion to confirmation`.

This is a diagnostic. It may not be presented as a validated entry rule.

### 8.7 Terminal outcome labels

The primary Walk A split is `CONFIRMED` vs `STOPPED_BEFORE_CONFIRM`. Losers are
never collapsed into one ambiguous bucket. The full label set, retained for
post-confirmation descriptive context:

```text
STOPPED_BEFORE_CONFIRM · CONFIRMED_THEN_STOPPED
FINAL_FLIP_EXIT_WINNER · FINAL_FLIP_EXIT_LOSER · SESSION_EXIT
```

---

## 9. Mandatory validation, before any result is trusted

Written machine-readable to `results/validation_report.json`, each gate carrying
`passed`, plus a top-level `all_passed`.

```text
 1  lifecycle_parity        reproduce first-qualifying >600s counts exactly:
                            top_1 3,415 · top_2_5 5,823 · top_5 7,396 · top_10 8,988
                            and reconcile the arm-population delta (expected 8,953 at top_10)
 2  true_dispatch_cadence   no carried-forward 1s row counted as a score observation
 3  arm_definition          first post-600s crossing from below only; one arm per regime
 4  event_ordering          stop / confirm / session ordering deterministic and reproducible
 5  session_containment     no path traverses a session boundary
 6  mae_independent_recompute
                            MAE-to-confirm recomputed by a separate code path on a
                            deterministic sample of >= 100 confirmed trades per level
                            where sample permits; 0 mismatches beyond float tolerance
 7  assertions              confirm_ns >= hypothetical entry ns
                            censored MAE_to_confirm <= 1.0 ATR
                            threshold sequence timestamps non-decreasing
                            multi-level same-dispatch crossings share one timestamp
 8  audit_gates             causal_lint clean; lookahead-auditor and contract-checker CLEAR
```

Gate 8 includes a **pre-execution** `causal_lint` + `lookahead-auditor` pass on
the new causal and matching logic, before the first full run.

---

## 9a. Deliverables Manifest

Frozen before implementation. The completion gate checks this list literally;
anything not listed here cannot be demanded later.

| # | Path | Type | Required contents |
|---|---|---|---|
| 1 | `SPEC.md` | spec | this document |
| 2 | `README.md` | doc | how to reproduce, module map, runtime |
| 3 | `REPORT.md` | report | the nine sections of §10, ending in exactly one §10a verdict and the required closing list |
| 4 | `results/armed_regime_score_paths.parquet` | parquet | the §6 event table, one row per armed regime |
| 5 | `results/threshold_progression_funnel.json` | json | §8.1, pooled + by direction + by year, with incremental lift |
| 6 | `results/mae_to_confirm_by_level.json` | json | §8.2, `uncensored` and `censored_1atr` blocks per level, with survival thresholds |
| 6b | `results/remaining_opportunity.json` | json | §8.3 MFE and return to confirm per level, gross and net |
| 6c | `results/shape_diagnostics.json` | json | §7 class counts and outcomes at r = 0.03 and 0.05, with the depth cross-tab |
| 7 | `results/progression_speed.json` | json | §8.4 quartile cells |
| 8 | `results/persistence_diagnostics.json` | json | §8.5 five cells plus dispatch-gap distribution |
| 9 | `results/reexpansion_diagnostics.json` | json | §8.6 at r = 0.03 and 0.05 with both comparators |
| 10 | `results/validation_report.json` | json | all eight §9 gates with `passed`, plus `all_passed` |
| 11 | `results/entry_confirmation_candidates.json` | json | at most five hypotheses, each with the §11 metric set |
| 12 | `results/partition_manifest.json` | json | cost assumption, years, level inventory, walk definitions, code hashes |
| 13 | `audit/status.json` | json | lookahead-auditor machine-readable verdict |
| 14 | `audit/contract_status.json` | json | contract-checker machine-readable verdict |

### Terminal decision labels

Every label is reachable through the real workflow.

| Label | Condition |
|---|---|
| `ARMED SCORE PROGRESSION SUPPORTS REFINEMENT` | all §9 gates pass **and** at least one deeper level lifts confirmation probability over the Top-10 arm by >= 10 absolute points while retaining positive median remaining return to confirmation, stable in sign across both directions and >= 4 of 5 years |
| `ARMED SCORE PROGRESSION IS MIXED` | all §9 gates pass, progression measurably changes confirmation probability, but the lift fails the direction or year stability requirement, or is bought entirely with remaining return |
| `NO USEFUL ARMED PROGRESSION FOUND` | all §9 gates pass and no deeper level lifts confirmation probability by >= 5 absolute points over the Top-10 arm |
| `RESULTS NOT VALID` | any §9 gate fails, so the absence of a finding cannot be distinguished from the absence of a valid measurement |

`NO USEFUL ARMED PROGRESSION FOUND` and `RESULTS NOT VALID` are deliberately
separated: the first is a result, the second is an admission.

## 9b. Domain and completeness contract

| Dimension | Domain | Completeness rule |
|---|---|---|
| Instrument | NQ only, `*.v.0` | any other symbol is out of scope, not missing data |
| Years | 2021–2025 | 2026 forbidden; a missing year is a defect, not a gap |
| Session | RTH only | ETH checkpoints exist but are never in-domain, by frozen model contract |
| Regime age | > 600s at the arm dispatch | younger regimes are out of scope, not missing |
| Levels | the 4 frozen contracts Top-10 / 5 / 2.5 / 1 | no interpolation, no new percentile, no threshold derived from this population |
| Walks | exactly the two in §5 | results from the two are never pooled |
| Retreat definitions | exactly 0.03 and 0.05 | no third value |
| Censoring | counted, never imputed | reported separately, excluded from uncensored distributions |
| Ambiguity | counted, both bounds reported | same-second stop/confirm collisions resolved adversely for the conservative bound |

---

## 10. Required report structure

```text
1  Executive summary
2  Top-10 arm funnel
3  Risk required to survive  (MAE-to-confirm, all four levels, both populations)
4  Remaining opportunity      (MFE and return to confirm, all four levels)
5  Score-path shape
6  Progression speed
7  Persistence
8  Direction and year stability
9  Candidate entry concepts   (at most five, hypotheses only)
```

## 10a. Final verdict

Exactly one label from §9a, followed by:

```text
best early-warning level
best confirmation level
MAE required by 90% of successful flips
MAE required by 95% of successful flips
largest opportunity-cost tradeoff from waiting
most promising score-path hypothesis
```

---

## 11. Candidate entry concepts

At most **five**, each reported with

```text
sample size · confirmation probability · median MAE to confirm
median remaining return to confirm · median time to confirm
direction split · year split
```

Hypotheses only. No production winner is designated, no policy is optimized, and
none may be labelled ADVANCE without a separate study.

---

## 12. Non-goals

No retraining, no feature changes, no regime redefinition, no threshold derived
from evaluation outcomes, no 2026 data, no modification of
`data/canonical/regime_complete_v1/` or any accepted upstream artifact, no
trading-policy grid search, no net-PnL optimization, no reentry simulation, and
no finalist selected on mean EV.
