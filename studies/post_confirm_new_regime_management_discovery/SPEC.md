# Post-Confirmation New-Regime Management Discovery — Frozen Specification

**Study:** `post_confirm_new_regime_management_discovery`
**Status:** contract frozen 2026-07-28, before any policy is evaluated.
**Substrate:** `data/canonical/regime_complete_v1/` (REGIME-COMPLETE STORE ACCEPTED).
**Scope:** discovery scan. **Not** authorization for NautilusTrader validation.

---

## 0. Decision to inform

Whether model behavior during the **newly confirmed regime** supports a small
number of causal exit / breakeven / trailing / adaptive-stop policies that both

1. reduce losses among trades that confirm and later fail, and
2. preserve the large favorable excursions of trades that become runners.

Deliverable: **at most 3–5 structurally distinct candidates**, or a documented
negative.

**A candidate that removes losers by also removing most runners is not useful.**
Win rate is explicitly not the objective.

---

## 1. Feasibility findings that shape this study

Measured before any policy was designed. These are constraints, not results.

### 1.1 Score availability after confirmation

Top-2.5% population, 4,000 confirmed trades:

| Quantity | Value |
|---|---:|
| Post-confirmation score dispatches per trade | median **108** (p25 60, p75 200) |
| Trades with ≥1 score of any kind | **98.7%** |
| Trades with ≥1 **in-domain** warning score | **40.4%** |
| Trades with no dispatch at all | 0 |

Density is not the constraint. **Domain validity is.**

### 1.2 Why in-domain coverage is low

The in-domain predicate includes the established gate — age ≥ 120s,
MFE ≥ 1.0 ATR, ≥ 2 progress windows, retained ≥ 0.5. The new regime starts
fresh at the confirming flip, so it must re-earn that status. Across the store:

```text
regimes ever reaching in-domain          16,469 of 137,673   (12.0%)
regime start -> first in-domain score    p05 195s · p50 410s · p75 580s · max 5,820s
median regime duration                   540s
```

First in-domain score arrives at a median of 410s against a median regime life
of 540s. **The warning model qualifies only near the end of the new regime, if at
all.** This is the structural mechanism behind the prior finding that
opposing-model warnings were "usually late" — they are late by construction.

### 1.3 No model predicts continuation

Both frozen models predict a flip **away** from the regime they operate in. After
a fade SHORT confirms into a bearish regime, the model that becomes in-domain is
the bearish-fade model, predicting a *bullish* flip — precisely the event that
ends the trade.

There is therefore **no supporting-continuation score**, only a warning score.
Family A's "supporting score deteriorating" component is unimplementable as
written and is **dropped** (DECISION-2). Exact target semantics are recorded in
`artifacts/score_semantics.md` from the `repo-scout` audit.

---

## 2. Frozen decisions

| # | Decision | Authority |
|---|---|---|
| 1 | **Both score domains, reported separately.** Every policy is run twice: `in_domain_only` (contract-valid, ~40% coverage) and `all_scores` (≈99% coverage, out-of-domain flagged exploratory). The difference between the two is itself a finding. | user, 2026-07-28 |
| 2 | **Family A uses the opposing-model warning only.** No supporting-continuation component. | user, 2026-07-28 |
| 3 | Cost 2 ticks round-turn = 0.50 pts, charged per completed trade. | inherited |
| 4 | No position lockout; per-trade economics. Drawdown descriptive only, never presented as a deployable equity curve. | inherited |
| 5 | Flat at 15:00 CT. No overnight holding. | inherited |

Any policy result computed on `all_scores` carries
`uses_out_of_domain_scores = true` and may not be described as contract-valid.

---

## 3. Population contract

Inherited unchanged from the accepted survival analysis. **The entry rule is not
modified while studying post-confirmation management.**

```text
instrument    NQ, both directions
session       RTH-scored entries only
thresholds    top_1, top_2_5, top_5, top_10
eligibility   regime age at entry strictly > 600s (causal), first true
              qualifying crossing thereafter, one entry per regime
initial stop  1.0 ATR, ATR frozen at entry
pre-confirm   unchanged from baseline
study focus   trades surviving the initial stop and reaching the confirming flip
```

Lifecycle resolution uses the **corrected** resolver
(`engine.RegimeIndex.next_start_after`, `inclusive=True`), which handles regime
flips stamped at the entry second. The superseded strictly-after resolver may not
be used; it mis-resolved confirm and opposing exit for ~2% of trades.

### 3.1 Path adjacency

One-second path advancement requires **temporal adjacency**. A stored row that is
not the next second is not treated as the next second. Session boundaries,
missing seconds, weekends, holidays, and partition boundaries follow the
established causal path contract. Session containment is asserted, not assumed.

---

## 4. Baseline

The sole comparator, evaluated on **exactly the same entries** as every candidate:

```text
1.0 ATR initial stop
no post-confirmation modification
exit at next opposing regime flip
otherwise flat at 15:00 CT
```

Preserved outcome labels:

```text
1  stopped before confirmation
2  confirmed, then stopped
3  reached regime-flip exit, profitable
4  reached regime-flip exit, losing
5  session exit
```

Management concentrates on classes 2–4; full-population effects are reported
regardless.

---

## 5. Candidate families

Coarse, interpretable settings. **No Cartesian grid.**

| Family | Mechanism | Bounded settings |
|---|---|---|
| **A** | Opposing-model warning → immediate exit | crossing at top_10 / top_5 / top_2_5 · 2-dispatch persistence · adverse acceleration |
| **B** | Warning **arms** a breakeven stop | stop at entry · entry ± 1 tick |
| **C** | Warning **tightens** the stop | to entry · to a fraction of ATR behind price · to confirmation-bar structural extreme |
| **D** | Warning **arms** a trail | fixed ATR trail · MFE giveback fraction, each armed only after a minimum MFE |
| **E** | Immediate exit at the confirming-flip bar close | diagnostic benchmark, not a candidate |
| **F** | ≤2 hybrids | warning **and** minimum MFE · fast confirmation **and** warning |

**Family E is a measurement**, not a policy: it bounds how much PnL exists at
confirmation and therefore the maximum value obtainable by eliminating all
post-confirmation risk.

### 5.1 Mandatory mechanics

- A model condition may be evaluated **only at a true score dispatch**, never on
  a carried-forward second.
- **Arming is not triggering.** A breakeven or trail that arms must remain open
  until a later *price* observation reaches the stop. An unarmed condition is a
  no-op. Enforced by V-shaped regression fixtures.
- Stop evaluation uses completed 1s HIGH/LOW; fills use the established
  next-bar-open convention; the trigger price is never credited.
- Simultaneous stop and signal-exit resolve conservatively (adverse first) and
  are counted as ambiguous.
- No structure point may be used before the bar forming it has completed.
- No censored or unresolved trade may enter summary statistics silently.

---

## 6. Confirmation speed

Treated as a conditioning variable because eventual losers confirmed *faster* in
the prior study. Buckets are **threshold-specific and discovery-period derived**:

```text
fast    <= threshold-specific median
normal  median .. p75
slow    > p75
```

Cutoffs are not optimized. **At most one confirmation-speed interaction may enter
the shortlist**, and only on monotonic evidence.

---

## 7. Split

| Period | Role |
|---|---|
| 2021–2023 | discovery |
| 2024 | refinement / selection check |
| 2025 | descriptive holdout |

No rule family may be invented after inspecting 2024 or 2025. Both frozen
threshold calibration populations are calendar-2025, so every threshold-based
result carries `overlaps_evaluation_window = true` and inherits
`full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`. **2025 is never
described as threshold-out-of-sample.**

If diagnostics are too sparse per threshold, discovery may pool thresholds, but
results are always reported threshold-specific afterward.

---

## 8. Required diagnostics — run before any policy is designed

At the confirming-flip bar close, comparing baseline classes 2, 3, and 4, per
entry threshold: new-regime opposing score · score change entry→confirmation ·
score change over the first true post-confirm dispatches · max and min score
within 15 / 30 / 60 / 120s · first threshold reached after confirmation · time to
adverse warning · warning persistence · confirmation speed · return and MFE at
confirmation · post-confirmation MFE and MAE.

Candidates are nominated **from these diagnostics**, not by enumeration.

---

## 9. Selection criteria

Maximum discovery expectancy never selects a candidate. Required per candidate:

**Full population** — trades · gross and net expectancy · total PnL · win rate ·
profit factor · descriptive sequence drawdown · year and direction stability.

**Confirmed trades** — expectancy given confirmation · mean/median
post-confirmation PnL · confirmed-then-stopped rate · flip-exit winner and loser
counts · session-exit counts.

**Loss mitigation vs baseline** — mean and median loss reduction among baseline
confirmed losers · p90/p95 adverse-loss reduction · share of full-stop losers
avoided · average PnL saved per affected loser.

**Runner preservation vs baseline** — share of baseline winners retained · share
exited early · share exited before 1 / 2 / 3 ATR MFE · retained MFE ratio ·
retained realized-PnL ratio · runner false-positive exit rate · average
opportunity cost per prematurely exited winner.

**Path efficiency** — return and MFE at trigger · post-trigger MFE · giveback
avoided · giveback caused · confirmation→trigger and trigger→exit times.

**Concentration** — largest single-trade and largest-1% contribution · best-year
share · long vs short · consistency across top_1/2.5/5/10 · nearby-setting
stability · bootstrap CIs where practical.

A candidate does not advance if its benefit is dominated by a handful of trades
or by one year.

### 9.1 Frontier table

| Candidate | Net EV change | Confirm-loser loss saved | Baseline winners retained | Runner MFE retained | Full-stop rate | Premature-exit cost |
|---|---|---|---|---|---|---|

The decision is not collapsed into a single score.

### 9.2 Labels

`ADVANCE` · `DIAGNOSTIC_ONLY` · `REJECT`

`ADVANCE` requires a causal mechanism, reproducible implementation, materially
reduced confirmed-loser damage, acceptable runner retention, no single-year or
outlier dependence, and at least directional stability across 2024 and 2025
under the threshold-overlap limitation.

**Being least-negative is not grounds to advance.**

---

## 10. Deliverables Manifest

Frozen before implementation. The completion gate checks this list literally.

| # | Path | Type | Required contents |
|---|---|---|---|
| 1 | `artifacts/score_semantics.md` | doc | repo-scout mapping: targets, domains, availability, out-of-domain contract |
| 2 | `artifacts/population_manifest.json` | json | frozen entry population per threshold, counts, code and store hashes |
| 3 | `artifacts/baseline_ledger.parquet` | table | one row per baseline trade: ids, timestamps, outcome class, PnL, MFE, MAE |
| 4 | `artifacts/candidate_ledgers/<name>.parquet` | table | same schema per candidate, plus trigger timestamp and armed/triggered flags |
| 5 | `artifacts/diagnostics.json` | json | section 8 diagnostics by threshold and baseline outcome class |
| 6 | `artifacts/frontier.json` | json | the section 9.1 table, both score domains |
| 7 | `artifacts/validation_report.json` | json | every section 11 gate with `passed`, plus `all_passed` |
| 8 | `artifacts/baseline_reconciliation.json` | json | before/after agreement with the accepted survival analysis |
| 9 | `REPORT.md` | report | answers the ten final questions; ends in exactly one verdict |
| 10 | `audit/status.json`, `audit/contract_status.json` | json | both gate verdicts |

### Terminal labels

| Label | Condition |
|---|---|
| `MANAGEMENT_CANDIDATES_ADVANCE` | ≥1 candidate meets every §9.2 ADVANCE condition |
| `MANAGEMENT_DIAGNOSTIC_ONLY` | no candidate advances, but ≥1 shows a reproducible structural effect worth preserving |
| `MANAGEMENT_NEGATIVE` | no candidate reduces confirmed-loser damage without unacceptable runner loss, **and** every §5 family ran with all §11 gates passing |
| `MANAGEMENT_INCONCLUSIVE` | a §11 gate fails, or a §5 family was not executed |

`MANAGEMENT_NEGATIVE` and `MANAGEMENT_INCONCLUSIVE` are distinct: the first is a
result, the second an admission. A study that skipped a family may emit only the
second.

---

## 11. Validation — required before any result is trusted

```text
true model-dispatch timing
no same-timestamp score used before availability
confirmation timestamp handling
adverse score crossing
warning persistence counts true dispatches only
stop arming versus stop triggering
V-shaped breakeven path
trailing updates use only prior/current causal information
session boundary and missing-second handling
temporal adjacency of path advancement
simultaneous stop and signal-exit ordering
baseline reconciles with the accepted survival analysis
```

Order: tests → `causal_lint` → `lookahead-auditor` → `contract-checker` → fix all
CRITICAL/BLOCKED → regenerate results → `contract-checker` pass 2 → **only then**
finalize `REPORT.md`.

**The report may not be written as accepted evidence before both gates pass.**

### 11.1 Prior-study reconciliation

The same-timestamp lifecycle defect has already been fixed and the
`model_driven_entry_exit_discovery` study fully regenerated and restated
(commit `3399101`, verdict `DISCOVERY_NEGATIVE`). That prior report is current,
not superseded. This study inherits the corrected resolver.

---

## 12. Non-goals

No modification of the canonical collector or store. No retraining, no feature
changes, no regime redefinition, no new threshold. No entry-rule changes. No
Cartesian grid. No parameter tuning to production precision. No overnight
holding. No 2026 data. No candidate advanced on expectancy alone.
