# Study Report — Long-Side Top-50 / Top-25 Pure-Flip Reduced-Feature Training

## Decision

**`LONG_TOP25_SIGNAL_STRONG_PRESERVATION`**

The **top 25 features alone** reproduce the long-side bullish-flip signal at full
strength. TOP25 passes every minimum-viable gate *and* every strong-preservation
gate against the TOP100 reference — and does so while being **4× smaller and
~14× cheaper to fit** (5.9 s vs 83.6 s). TOP50 also passes both gate sets, but
the briefed preference order selects the lighter set.

## Full comparison

Selection was on **2025 AUC only** (tie-break 2025 AP). TOP100 was **re-fit in
this same harness**, not transcribed, and reproduces the prior study's published
figures exactly (0.6682 / 0.6512) — so every row below is like-for-like.

| Set | Model | Train AUC | **2025 AUC** | **2026 AUC** | 2025 AP | 2026 AP | 2026 Brier | 2026 logloss | 2026 top-dec | 2026 lift | 2026 mono | Fit (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TOP100 | logreg | 0.6962 | 0.6660 | 0.6424 | 0.4139 | 0.4343 | 0.1912 | 0.5713 | 54.6% | 1.95× | 0.988 | 56.9 |
| TOP100 | **gbt** ← ref | 0.7322 | **0.6682** | **0.6512** | 0.4232 | 0.4401 | 0.1885 | 0.5619 | 53.7% | 1.91× | 0.988 | 83.6 |
| TOP50 | **logreg** ← sel | 0.6917 | 0.6706 | 0.6396 | 0.4176 | 0.4248 | 0.1916 | 0.5716 | 53.4% | 1.90× | 0.988 | 10.9 |
| TOP50 | gbt | 0.7244 | 0.6637 | 0.6462 | 0.4181 | 0.4341 | 0.1895 | 0.5647 | 54.0% | 1.93× | 1.000 | 39.0 |
| TOP25 | **logreg** ← sel | 0.6893 | **0.6729** | 0.6462 | 0.4249 | 0.4342 | 0.1901 | 0.5677 | 54.5% | 1.94× | 1.000 | **5.9** |
| TOP25 | gbt | 0.7150 | 0.6688 | 0.6500 | 0.4238 | 0.4364 | 0.1890 | 0.5634 | 54.5% | 1.94× | 1.000 | 23.6 |

2025 base positive rate 0.263; 2026 0.280. 2026 bottom-decile flip 13.3% (TOP25
logreg) against a 54.5% top decile.

**The best 2025 AUC of all six models is TOP25 logreg (0.6729) — it beats the
100-feature GBT.** This is not noise-mining: train AUC falls monotonically as
features are removed (0.7322 → 0.7150 GBT; 0.6962 → 0.6893 logreg) while dev AUC
*rises*, so the generalization gap collapses from **0.064** (TOP100 gbt) to
**0.016** (TOP25 logreg). The extra 75 features were contributing variance, not
signal.

## Gate results

| Gate | TOP50 (logreg) | TOP25 (logreg) |
|---|---|---|
| Minimum viable (6 checks) | **PASS** | **PASS** |
| Strong preservation vs TOP100 (5 checks) | **PASS** | **PASS** |
| Δ 2025 AUC vs TOP100 | +0.0024 | **+0.0047** |
| Δ 2026 AUC vs TOP100 | −0.0116 | −0.0050 |
| Δ 2025 top-decile flip | −0.8 pp | −0.3 pp |
| Δ 2026 top-decile flip | −0.3 pp | +0.8 pp |

2026 monthly AUC (all four months must exceed 0.60 for strong preservation):

| Model | 2026-01 | 2026-02 | 2026-03 | 2026-04 |
|---|---:|---:|---:|---:|
| TOP100 gbt | 0.630 | 0.684 | 0.642 | 0.641 |
| TOP50 logreg | 0.621 | 0.668 | 0.641 | 0.624 |
| **TOP25 logreg** | **0.629** | **0.671** | **0.643** | **0.641** |

TOP25 is month-for-month indistinguishable from the 100-feature model and is
*more* stable than TOP50 in every month.

## Answers to the 10 required questions

1. **Exact prefixes?** Yes, verified twice — in Phase 0 and re-asserted at fit
   time — and independently re-derived by the auditor from the raw ranked CSV.
   TOP25 ⊂ TOP50 ⊂ TOP100. Source `sha256 6c6ceba7…` and ordered-list
   `sha256 f2a6db0b…` both reproduced exactly. TOP50 `5a2b1a70…`, TOP25 `d601abe6…`.
2. **Both trained cleanly on strict-causal data?** Yes. No rebuild was needed —
   all six prepared years existed with exact row counts (682,952 / 163,397 /
   52,488) and the corrected convention re-verified independently: **min gap
   exactly 1,000,000,000 ns, zero rows at-or-after `observation_time`, all six
   years**. No NaN/imputation surprises; 0 object-dtype columns.
3. **TOP50 / TOP25 2025 AUC?** 0.6706 and **0.6729**.
4. **TOP50 / TOP25 2026 AUC?** 0.6396 and **0.6462**.
5. **Top-decile flip rates and lifts?** TOP50 50.3%/53.4% at 1.91×/1.90×;
   TOP25 50.9%/54.5% at 1.94×/1.94×. Decile monotonicity 1.00 in both years for
   TOP25 — no inversion.
6. **2026 monthly AUC stable?** Yes — TOP25 holds 0.629/0.671/0.643/0.641, all
   above the strict 0.60 floor, with the same February peak shape as TOP100.
7. **How much signal was lost vs TOP100?** Effectively none, and on the selection
   year it *gained*: **+0.0047 AUC on 2025, −0.0050 on 2026**. Both deltas are
   far inside the ±0.015 / ±0.020 tolerances and are smaller than the
   month-to-month spread within 2026 itself.
8. **Lightest acceptable candidate?** **TOP25** — 25 features, logistic
   regression, 5.9 s to fit. It is the smallest set tested and it passed the
   strongest gate, so no intermediate size needs evaluating.
9. **Which families remain load-bearing?** All three, but the balance shifts.
   In TOP25 the two `aligned_price_minus_center_{15m,5m}` features carry by far
   the largest coefficients (−0.380, −0.298 standardized) — center/slope is still
   the single most concentrated source of signal, exactly as on the short side.
   Price-level and ohlcv-delta both still contribute materially (aggregate
   |coef| 0.425 and 0.503 vs 0.736 for center/slope), led by
   `rolling_15m_high_signed_distance_atr` (+0.137), `price_change_points_60s`
   (+0.109) and `rth_elapsed_seconds` (+0.106). **No family can be dropped.**
   Notably, TOP25 contains only 6 of the 44 center features yet retains their
   full effect — the other 38 were largely redundant.
10. **Strong enough to move toward NT live-scoring parity?** **Yes — TOP25 is the
    right candidate**, with the scope caveat in the next section. Three reasons:
    it matches TOP100 on sealed 2026; a 25-feature linear model is dramatically
    easier to implement and verify in the NT event loop than a 100-feature GBT;
    and it **contains zero `TIMING_UNVERIFIED` features**.

## Two findings worth carrying forward

**TOP25 removes a disclosed provenance residual.** All three inherited
`TIMING_UNVERIFIED` features (`regime_first_half_vol`,
`regime_abs_delta_per_atr_moved`, `regime_price_change_atr`) rank outside the top
25; only one survives into TOP50. TOP100 and TOP50 carry that caveat forward,
**TOP25 does not.** Choosing TOP25 retires the residual instead of inheriting it.

**What was dropped and why it didn't hurt.** Of TOP100-GBT's 25
highest-permutation-importance features, only 8 are inside TOP25 (15 inside
TOP50), and TOP25 retains 68% of total importance mass. That understates the
result, because the discarded high-importance features are overwhelmingly
**redundant `_signed_distance_points` twins of retained `_signed_distance_atr`
features** (`rolling_15m_high_signed_distance_points`,
`prior_day_close_signed_distance_points`, `rolling_60m_high_signed_distance_points`,
`rolling_5m_open_signed_distance_points`, …) — the same quantity in raw points
rather than ATR units. Permutation importance splits credit across correlated
duplicates, so the mass figure reads as a loss where the information is actually
retained. That is the mechanism behind strong preservation at a quarter of the
feature count.

## Selection discipline — an honest note

The rule (2025 AUC, tie-break 2025 AP) selected **TOP25 logreg** (2025 0.6729)
over **TOP25 gbt** (2025 0.6688). On the sealed 2026 year, gbt was in fact
*better* (0.6500 vs 0.6462). We did **not** switch — doing so would be selecting
on the sealed test set, exactly the failure mode
`[[grid_tune_vs_validate_separation]]` warns about. Both variants pass every
gate, so the decision is unaffected; if a future study wants the GBT variant it
must justify that on 2025 or on new data, not on this 2026 result.

## Regime-level diagnostics (diagnostic only — not a gate)

| Model | Split | Regimes | Base flip | **Regime AUC** | Top-dec regime flip | top20 / top10 / top5 | FP regime rate | Missed-flip rate | Median lead (s) |
|---|---|---:|---:|---:|---:|---|---:|---:|---:|
| TOP100 gbt | 2025 | 1,578 | 82.3% | 0.504 | 88.6% | 84.8 / 88.6 / 88.6% | 6.5% | 89.2% | 40 |
| TOP100 gbt | 2026 | 488 | 86.3% | 0.471 | 85.7% | 86.7 / 85.7 / 92.0% | 10.4% | 90.0% | 45 |
| TOP50 logreg | 2026 | 488 | 86.3% | 0.469 | 89.8% | 90.8 / 89.8 / 88.0% | 7.5% | 89.5% | 40 |
| **TOP25 logreg** | 2025 | 1,578 | 82.3% | 0.510 | 86.1% | 82.9 / 86.1 / 92.4% | 7.9% | 89.5% | 40 |
| **TOP25 logreg** | 2026 | 488 | 86.3% | 0.462 | 89.8% | 88.8 / 89.8 / 88.0% | 7.5% | 89.5% | 35 |

**Regime-level AUC is ~0.50 — chance — for every model including TOP100.** The
reduction changes nothing here, and that is the single most important
qualification on this study. The model does **not** identify which bearish
regimes will flip (86% of them flip anyway; base rate ≈ top-decile rate). It
prices **when**, inside a regime, a flip is imminent — a within-regime **timing**
signal with ~35–45 s median lead. Any downstream gate must read the row-level
metric, not the regime-level one (`[[row_level_vs_entity_level_auc_rule]]`).

## Audit

An independent `lookahead-auditor` pass returned **0 CRITICAL / 1 WARNING /
2 NOTE**, verifying by independent recomputation from the raw artifacts (not the
implementer's logs): the prefix relationships and all three SHA-256 values; the
strict-causality gap directly from `attached_long_*.parquet` (min 1,000,000,000
ns, zero violations, six years); that all 115 prepared columns were enumerated
and none of the outcome/metadata columns appear in any feature list; that the
promoted prediction files are byte-identical to the TOP25-logreg candidate; that
`regime_start_ns` has zero overlap across the year splits; and that the headline
AUC/flip figures recompute exactly from the stored scores.

The **WARNING** was mine and it was real: `decide.py`'s "materially better"
tie-break compared TOP50 against TOP25 on **2026** AUC. That branch was
unreachable in this run (TOP25 passed the strong gate first), so the decision was
never affected — but it was a code path where the sealed year could have ranked
one feature set against another, which the brief forbids. **Remediated**: the
tie-break now uses 2025 AUC with 2025 AP, and `decide.py` was re-run (decision
unchanged). The pre-registered 2026 *pass/fail* thresholds remain, as the brief
mandates. The two NOTEs (a defensively over-broad `FORBIDDEN_IN_MATRIX` entry;
unused in-sample calibrated columns that no gate reads) were documented in place.

A confirmatory re-audit after remediation returned **0 CRITICAL / 0 WARNING /
1 NOTE**. The auditor re-read the remediated branch line-by-line and confirmed no
`2026_` key appears in the ranking expression, traced every remaining branch to
confirm the only surviving 2026 references are pre-registered pass/fail booleans
and a failure-narrative label choice (neither ranks TOP25 against TOP50), and
**re-ran `decide.py` itself from a clean shell** rather than trusting this
study's run — reproducing `LONG_TOP25_SIGNAL_STRONG_PRESERVATION` and
re-verifying that `final_decision.json` / `viability_gates.json` /
`model_metrics.csv` agree and that the promoted 2026 predictions remain
byte-identical to the TOP25-logreg candidate. The one residual NOTE (2025
`_cal_` diagnostic columns are in-sample for the calibrator) is informational and
read by no gate. **The mandatory audit gate is cleared at 0 CRITICAL.**

## Scope honesty

No NautilusTrader, no MBP-1, no surface rebuild, no trade economics, no
entry/stop/exit/threshold optimization — none were in scope. This study
establishes **feature-count reduction with preserved predictive quality only**.
2026 was opened solely for sealed evaluation and pre-registered gate checks, and
never for any fit, selection, hyperparameter, threshold, or calibration decision.
Predictive preservation is not evidence of monetizability
(`[[flip_score_entry_policy_weak_but_useful]]`).
