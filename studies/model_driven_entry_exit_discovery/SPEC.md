# Model-Driven Entry and Exit Discovery — Frozen Specification

**Study:** `model_driven_entry_exit_discovery`
**Status:** contract frozen 2026-07-27, before any policy is evaluated.
**Substrate:** `data/canonical/regime_complete_v1/` (REGIME-COMPLETE STORE ACCEPTED).

---

## 0. Objective and honesty constraint

Find a small number of causal, model-driven entry/exit policies reaching
**net expectancy ≥ +0.25 ATR per completed trade**.

This is a discovery funnel, not a parameter sweep. The deliverable is the top few
economically plausible *structures* with an explanation of why they work.

**The starting point is negative and is recorded here before any search runs**, so
that a marginal result cannot later be presented as success:

| Known policy (accepted artifacts) | Gross ATR expectancy |
|---|---:|
| Top-2.5% first signal → opposing-flip exit, no stop | **-0.067** |
| Top-2.5% first signal → 1.00 ATR stop → opposing-flip exit | **-0.097** |

Reaching +0.25 net therefore requires roughly a **+0.35 to +0.40 ATR swing**.

Where the headroom is, from the same artifacts: mean MFE 2.479 ATR against mean
giveback 2.546, median capture ratio ≈ -0.28, and **36.8% of trades stop before
confirmation with median MFE only 0.234** — fast failures that better entry
timing may avoid, and large unharvested excursion on the survivors.

**If no candidate credibly reaches +0.25 ATR net, the report says so.** A
manufactured winner is a worse outcome than a documented negative result.

---

## 1. Frozen execution assumptions

| Assumption | Value | Authority |
|---|---|---|
| Transaction cost | **2 ticks round-turn** = 0.50 pts = $10, charged per completed trade **and** per reentry | user, 2026-07-27 |
| Cost normalization | `0.50 / atr_at_entry` ATR per trade (per-trade, not median-ATR) | derived |
| Overlap | **No position lockout.** Long and short may overlap; multiple regimes may overlap. Per-trade expectancy. | user; matches accepted canonical contract |
| Session | Entries **RTH-only** (both models are unscored in ETH). **Forced flat at 15:00 CT.** | user |
| Instrument | NQ, $20/point, tick 0.25 pt | `run_nt.create_instrument` |
| Sizing | 1 contract, unlevered, no compounding | derived |

**Consequence of the forced 15:00 flat, stated explicitly:** every policy here is
intraday. This truncates MFE on the long winners that carried the accepted
baseline's expectancy, so results are **not** directly comparable to the -0.067 /
-0.097 figures above, which held through the opposing flip overnight. The report
recomputes the baseline under the intraday rule so the difference is attributable.

Drawdown is descriptive over the chronological trade sequence, not a tradeable
equity curve, because no lockout is enforced.

---

## 2. Data contract

Source, and nothing else:

```text
data/canonical/regime_complete_v1/canonical_regimes_all.parquet          137,673
data/canonical/regime_complete_v1/canonical_regime_scores_all.parquet 12,156,904
data/canonical/regime_complete_v1/canonical_regime_paths_all.parquet  61,543,945
data/canonical/regime_complete_v1/canonical_model_threshold_contracts.parquet  12
```

The legacy 5,836 selected-trade population is used **only** for backward parity.
It is never the primary population.

Regime engine: `studies.fable5_pre_flip_d10_reversal_entry.RegimeEngine`. No
substitution without a parity proof.

### 2.1 Eligibility

A checkpoint may create a candidate only if the model is **in domain**
(`bullish_in_domain` / `bearish_in_domain`), which already encodes direction,
the established gate, and RTH. Out-of-domain and ETH scores are exploratory and
may never qualify an entry.

Direction mapping, from the frozen fade contract:

```text
bullish model in-domain (bullish regime) -> SHORT
bearish model in-domain (bearish regime) -> LONG
```

---

## 3. Trade lifecycle — derived, never hard-coded

No policy may reference literal `R+1` / `R+2` labels. For each entry the
lifecycle is derived at simulation time from the entry timestamp, trade
direction, and the regime sequence:

```text
direction_flip  = first regime start, strictly after entry, whose direction
                  == trade direction
opposing_exit   = first regime start, strictly after entry, whose direction
                  == -trade direction
session_close   = 15:00 CT on the entry's session
terminal        = min(policy exit, stop, opposing_exit, session_close)
```

Both are resolved by successor lookup on `regime_sequence_number`, which is dense
and globally monotonic in the consolidated store. A trade whose terminal cannot be
resolved inside the data is **censored** and excluded from expectancy, counted
separately.

---

## 4. Fill and ordering contract

Inherited from the accepted stop studies:

- Entry reference is `checkpoint_reference_price` at `checkpoint_decision_ns`.
  It is a mark, not an executable fill.
- A stop touch is detected from the completed 1s bar high/low. The exit fills at
  the **following** path bar's open. The trigger price is not credited.
- Where a stop and a regime event fall in the same second, ordering is
  **ambiguous**. Such trades are counted and reported under both a conservative
  bound (adverse event first) and an optimistic bound (favorable event first).
- A touch on the final available bar with no following open is **censored**.
- Returns within 0.125 NQ points of zero are flat.

MFE/MAE are directionally normalized by `atr_at_entry`. For a stopped trade,
excursion ends on the touch bar; its OHLC cannot reveal intrabar order.

---

## 5. Search funnel

Cartesian sweeps are forbidden. Three stages, each gated.

**Stage 1 — family screening.** ~3–5 representative settings per family. Purpose
is to find which families contain signal, not to locate an optimum.

Entry families: first qualifying observation · true threshold crossing ·
two-observation persistence · score acceleration / re-expansion · score peak
pullback re-expansion · bullish-bearish spread · within-regime score rank ·
regime-age and path-development conditioning.

Exit families: opposing-flip baseline · fixed ATR target · peak giveback ·
retained-MFE floor · score deterioration · model-triggered stop tightening ·
ATR trailing. Immediate opposing-model exit carries a **weak prior** — prior
evidence found it usually late.

**Stage 2 — local refinement.** Only the strongest few families advance. Test
nearby settings. **A candidate is rejected if its performance is an isolated
spike** rather than a plateau.

**Stage 3 — composites.** At most 3 entries × 3 exits × 2–3 stops × a small set
of reentry rules.

Reentry, tested at minimum: none · one after stop within the source regime ·
only after score resets below a lower threshold and re-crosses · short cooldown
in true score observations. Unlimited reentry is forbidden in discovery.

---

## 6. Split

| Period | Role |
|---|---|
| 2021–2023 | discovery |
| 2024 | candidate selection and local refinement |
| 2025 | final descriptive holdout |

**2025 is not independent OOS.** Both frozen threshold calibration populations are
calendar-2025, so every result using a percentile contract inherits
`full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json` and must carry the
disclosure. A finalist is never described as validated out-of-sample.

---

## 7. Success criteria

Primary: **net expectancy ≥ +0.25 ATR per completed trade.**

A finalist must **also** show:

```text
adequate sample size
stability across years
stability across long and short
nearby-parameter stability (a plateau, not a spike)
no dependence on a single month or on outlier trades
acceptable drawdown
limited censoring
limited same-bar ambiguity
```

Candidates in the **+0.15 to +0.25** band are preserved when substantially more
robust than a higher-EV alternative. **Highest mean EV alone never selects a
candidate.**

---

## 8. Mandatory validation, before any policy result is trusted

```text
reproduce the accepted 5,836 Top-2.5% population from this store
no duplicate candidate checkpoints
score cadence counts unique model observations only
no forward-filled second counts as a persistence observation
no feature or regime lookahead
reentry state resets correctly
no overlapping trades except as explicitly permitted
stop and exit ordering is deterministic
partition boundaries create no duplicate or missing flips
```

---

## 8a. Deliverables Manifest

Frozen before implementation. The completion gate checks this list literally;
anything not listed here cannot be demanded later.

| # | Path | Type | Required contents |
|---|---|---|---|
| 1 | `results/validation_report.json` | json | all eight SPEC 8 gates, each with `passed`, plus `all_passed` |
| 2 | `results/stage1_entries.json` | json | one row per entry family x threshold: family, threshold, resolved, net_atr, gross_atr, win_rate, mfe_mean, max_drawdown_atr |
| 3 | `results/stage1_exits.json` | json | one row per exit setting, same metric set |
| 4 | `results/stage3_composite.json` | json | `screen` (all composites, discovery) and `carried` (top 6 x 3 periods) |
| 5 | `results/partition_manifest.json` | json | cost assumption, split years, family and threshold inventory, code hashes |
| 6 | `REPORT.md` | report | the ten sections the study request enumerates, ending in one verdict |
| 7 | `audit/status.json` | json | lookahead-auditor machine-readable verdict |
| 8 | `audit/contract_status.json` | json | contract-checker machine-readable verdict |

Every finalist row reported in item 6 must carry: entry rule, exit rule, stop
rule, reentry rule, trade count, gross and net ATR expectancy, win rate, average
win, average loss, median, MFE, MAE, capture ratio, max drawdown, year
breakdown, direction breakdown, threshold breakdown, censored count, ambiguous
count, share of PnL from the best calendar month, and share of PnL from the
largest 1% of trades.

### Terminal decision labels

Every label is reachable through the real workflow.

| Label | Condition |
|---|---|
| `DISCOVERY_TARGET_MET` | at least one policy reaches net >= +0.25 ATR and passes every SPEC 7 robustness criterion |
| `DISCOVERY_LOWER_EV_CANDIDATE` | no policy reaches +0.25, but at least one in the +0.15 to +0.25 band passes every SPEC 7 criterion |
| `DISCOVERY_NEGATIVE` | no policy reaches +0.15 net, and the search executed every family SPEC 5 names with all SPEC 8 gates passing |
| `DISCOVERY_INCONCLUSIVE` | a SPEC 8 gate fails, or a SPEC 5 family was not executed, so absence of a candidate cannot be distinguished from absence of a search |

`DISCOVERY_NEGATIVE` and `DISCOVERY_INCONCLUSIVE` are deliberately separated:
the first is a result, the second is an admission. A study that has not run
every promised family may only emit the second.

## 8b. Domain and completeness contract

| Dimension | Domain | Completeness rule |
|---|---|---|
| Instrument | NQ only | any other symbol is out of scope, not missing data |
| Years | 2021-2025 | 2026 forbidden; a missing year is a defect, not a gap |
| Session | RTH entries only | ETH checkpoints exist but are never in-domain, by frozen model contract |
| Entry families | the 11 in `candidates.FAMILIES` | every family SPEC 5 names must appear here or the verdict is INCONCLUSIVE |
| Thresholds | the 6 frozen contracts | no interpolation, no new percentile |
| Censoring | counted, never imputed | a censored trade is excluded from expectancy and reported separately |
| Ambiguity | counted, both bounds reported | same-second stop/regime collisions resolved adversely for the conservative bound |

---

## 9. Reporting

Per finalist: exact entry / exit / stop / reentry rule · trade count · gross and
net ATR expectancy · win rate · average win and loss · median · MFE · MAE ·
capture ratio · max drawdown · year, direction, and threshold breakdowns ·
censored count · ambiguous count · share of PnL from the best month · share from
the largest 1% of trades.

Finalist table: **at most five policies**, each classified

```text
REJECT | DIAGNOSTIC ONLY | PROMISING | ADVANCE TO EVENT-DRIVEN VALIDATION
```

---

## 10. Non-goals

No retraining, no feature changes, no regime redefinition, no threshold derived
from evaluation outcomes, no 2026 data, no modification of
`data/canonical/regime_complete_v1/` or the accepted `full_trade_path_builder/`
artifacts, no unlimited reentry, no Cartesian grid, and no finalist selected on
mean EV alone.
