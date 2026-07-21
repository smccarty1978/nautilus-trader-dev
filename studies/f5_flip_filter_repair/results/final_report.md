F1/F2 POPULATION RECONCILIATION:
PASS

CANONICAL F2 ENTRY PARITY:
PASS

EXECUTION AUDIT:
PASS

CRITICAL VIOLATIONS REMAINING:
0

DIRECTION ATTRIBUTION:
PASS

RTH/ETH ATTRIBUTION:
PASS

F5 SCORE REPRODUCTION:
PASS* (documented exception: not bit-exact, see Section 6)

FROZEN F5 THRESHOLD:
0.15

VALIDATION EV LIFT:
+$1.35

DEVELOPMENT-TEST EV LIFT:
+$2.94

2025-H2 EV LIFT:
+$1.00

2026 EV LIFT:
-$0.50

COMBINED POST-TRAIN EV LIFT:
+$1.03

COMBINED PAIRED 95% CI:
(-$0.04, +$2.17)

TRADE RETENTION:
0.9799 (combined post-train)

TOP-DECILE RUNNER RETENTION:
0.9875 (combined post-train)

MATCHED RANDOM EMPIRICAL P-VALUE:
0.014 (combined post-train); 0.019 (dev-test); 0.673 (2026 alone)

BASELINE MAX DRAWDOWN:
$132,740.54 (combined post-train)

F5 MAX DRAWDOWN:
$127,782.54 (combined post-train)

THRESHOLD STABILITY:
MIXED

1S VS 5S SKIP DISAGREEMENT:
1.12% (2/179 sampled episodes)

F5 VERDICT:
CONDITIONAL

ORDER-FLOW REQUIREMENT:
NOT ESTABLISHED

NEXT STEP:
Deploy F5 only with an explicit 2026-regime monitor (rolling monthly lift + matched-random p-value) that would auto-suspend the filter if the negative 2026 pattern persists or worsens across two more months, since the aggregate "pass" is materially propped up by one anomalous month (2025-04) and a filter that is statistically indistinguishable from random skipping in the most recent evaluation year.

---

# F5 Flip Filter Repair Study — Final Report

Study directory: `studies/f5_flip_filter_repair/`
Source study (read-only, never modified): `studies/regime_sequence_chop_context/`

## 1. Artifact Inventory

All 21 required artifacts from the prior study were located and schema-audited (`results/artifact_inventory.json`, `results/artifact_schema_audit.parquet`) — 21/21 found, 0 missing. The prior study's `flip_context_atlas.parquet` (209,372 rows: 146,603 F1 + 62,769 F2) is the primary cached feature/outcome table reused throughout this repair; no raw 1-second feature reconstruction was rerun.

**Important pre-existing finding used throughout this report:** no serialized model object (`.pkl`/`.joblib`) exists anywhere in the prior study. `flip_model_manifest_F2.json` persists only the feature list and train-median imputation vector, not fitted coefficients — this shapes the Section 6 reproduction methodology.

## 2. F1/F2 Population Correction

The prior final report's headline "+$0.37 lift" figure was traced to a concrete code defect in `run_study.py`: `flip_policy_metrics.parquet` concatenates F1-test, F2-test, F1-secondary_oos, F2-secondary_oos metrics **without a `population` column**, and the final-report code does `df_policy_metrics[(subset=='test')&(policy=='F4')].iloc[0]` — which silently grabs the **first** matching row (F1, since F1 blocks are concatenated first), not F2. Reproducing this exact bug confirms: F1 F4-lift = +$0.372 (the erroneously reported number), while the true F2 F4-lift = +$0.122/eligible episode — matching the hypothesis in the task brief almost exactly.

**Repair:** `results/population_reconciliation.parquet` gives exact F1 and F2 counts per canonical period_role with an explicit `population` column in every downstream artifact. All primary economics in this report use F2 only.

| period_role | F1 | F2 |
|---|---|---|
| train | 110,503 | 47,122 |
| validation | 4,256 | 1,779 |
| dev_test | 6,650 | 3,006 |
| secondary_2025H2 | 16,260 | 6,905 |
| secondary_2026 | 8,934 | 3,957 |

(F2 counts above are pre-execution-violation-repair; see Section 4 for the repaired counts actually used in economics.)

## 3. Canonical F2 Entry Reconciliation

Canonical source: `collectors/collector_v2/results/v_a_v0_nodelay_{2024,2025,2026}/trades.parquet` (the repo's current no-delay V_A confirmed-entry collector). F2's entry rule (HH/LL vs. flip bar + directional close, decision_ts) was independently verified against `collectors/collector_v2/strategy.py` and matches.

Two real findings emerged, both documented in `results/population_report.md`:
- **Timing convention:** V_A's `entry_ts` lands 1-7s after the minute boundary F2 uses (V_A fills on the bar whose own processing follows the 1m close; F2 fills on the bar starting at the boundary). Matched with 5s tolerance; RTH price-diff distribution is symmetric around a median of exactly $0.00 (std ~2.1pts) — ordinary market noise, not a bug.
- **Session-scope mismatch:** the canonical V_A collector is ~99.3% RTH / 0.7% ETH as currently deployed, while F2 trades the full ~23h session. Restricting the reconciliation to F2's own RTH subset (the only subset with real canonical coverage) gives **99.18% match rate, 96.91% price match** → **CANONICAL F2 ENTRY PARITY: PASS**. This is reported as a scope difference in the canonical collector, not a defect in F2.

## 4. Execution-Violation Root Causes and Repairs

The prior `execution_audit.parquet` reported 64 boundary violations (`observation_time > ep_end_time`), all in F2 (F1 had zero). Independent re-detection confirms 64, all classified `decision_after_terminal_time`.

**Root cause:** `build_flip_atlas.py` selects the F2 confirmation bar as `df_1m_list[idx+1]` — literally "the next row in the bar array" — not "the next row within a wall-clock tolerance." When the underlying 1m-bar sequence has a gap (CME maintenance break, weekend/holiday closure, thin-liquidity gap), `idx+1`'s close timestamp can land after the episode's fixed 30-minute timeout, or even after the opposing-flip timestamp found by the same ungapped forward scan. Observed gap distribution: min 31 min, up to 52.3 hours.

**Repair:** all 64 episodes excluded from the eligible population (`repair = exclude_episode_from_eligible_population`). A separate, non-critical defect was also found and repaired: 125 F2 episodes (86 train / 4 val / 6 dev-test / 29 secondary) have null `entry_price`/`exit_price`/`pnl_base` because the forward 1s replay slice ran past the end of that calendar year's raw file (year-boundary censoring) — excluded from economics, documented as `missing_replay_bar`, not a boundary violation.

Post-repair assertion battery: **`critical_execution_violations_remaining = 0`**. Full detail in `results/execution_violation_details.parquet` / `execution_violation_report.md`.

## 5. Direction and Session Metadata Repair

**Direction:** was null for 100% of train/val/test F2 rows (partially null in secondary_oos) in the cached atlas — traced to `run_study.py`'s incremental year-cache logic (`if flip_atlas_path.exists(): skip already-processed years`), which means the currently-cached atlas is a **mix of feature-computation runs from different points in the code's history**, some predating a `direction` fix. Repair: rebuilt 100% from the canonical `regime` column, which has zero nulls in F2 and matches every pre-existing non-null `direction` value exactly (100% agreement wherever both existed). `missing_direction = 0` post-repair.

**RTH/ETH:** the prior segment code (`"RTH" if get_session_start(ts).value != ts else "ETH"`) compares a session-start timestamp to the observation timestamp for exact equality — true for essentially zero rows, so it labeled ~100% RTH / 0% ETH. Repair: rebuilt using the project-canonical RTH window (08:30–15:00 America/Chicago, `CLAUDE.md`), DST-aware via `tz_convert` on the tz-aware UTC timestamp. Result: 28.7% RTH / 71.3% ETH, consistent with NQ's ~23h trading day. `missing_session = 0` post-repair.

Full detail: `results/rebuilt_episode_metadata.parquet`, `results/metadata_audit.json`.

## 6. Frozen-Model and Score Reproduction

No `.pkl`/`.joblib` exists for the frozen `ridge_log_fail` model, so "reproduction" means refitting the identical `Pipeline(StandardScaler, LogisticRegression(C=0.1, l2))` on the identical unrepaired F2 train split with identical feature order (verified against `flip_model_manifest_F2.json`), which is deterministic given fixed data.

Result: **not bit-exact**. 78/149 train-median features differ slightly (max |diff| 0.0116), mean |score diff| ≈ 0.0011, and 159/62,769 (0.25%) skip-flag disagreements at threshold 0.15. This independently corroborates the Section 5 finding: the cached atlas mixes feature-computation runs across code versions, so the exact rows that produced the frozen manifest's medians cannot be re-derived from today's cache without rerunning the full raw pipeline (out of scope — this is provenance drift, not corruption).

**Exception invoked** (documented prior provenance issue, not a defect introduced by this repair): all downstream economics in Sections 7-16 use the **cached** `ridge_log_fail_prob` column — the actually-frozen, actually-deployed score — not the refit. Full detail: `results/f5_score_reproduction.parquet`, `results/f5_model_reproduction_audit.json`.

## 7. Validation Results (Jan-Feb 2025)

Eligible: **1,775** (2 execution violations + 2 censored excluded from the prior table's 1,779). Skipped: 28 (1.58%). Retention: 98.42%. **Paired EV lift: +$1.35/eligible**, matching the task brief's hypothesis (+$1.35) almost exactly post-repair. Paired bootstrap (10k iter): mean +$1.34, 95% CI (-$0.78, +$3.42), P(lift>0)=89.5%. Matched-random empirical p=0.140 (does not clear the ≤0.10 strong-pass bar).

## 8. Development-Test Results (Mar-May 2025)

Eligible: **3,000** (1 violation + 5 censored excluded from 3,006). Skipped: 52. Retention: 98.27%. **Paired EV lift: +$2.94/eligible**, total benefit +$8,830 — both match the task brief's hypothesis almost exactly. Bootstrap: mean +$2.97, 95% CI (+$0.47, +$5.67), P(lift>0)=99.1%. Matched-random p=0.019 (clears strong-pass bar).

**Caveat (see Section 11):** $5,993 of this $8,830 (68%) is concentrated in April 2025 alone; March and May contribute much smaller, more ordinary amounts (+$2,310 and +$526).

## 9. 2025-H2 Results (Jun-Dec 2025, separately reported)

Eligible: **6,887**. Skipped: 174 (2.53%). Retention: 97.47%. Paired EV lift: **+$1.00/eligible**, total benefit +$6,861. Bootstrap: mean +$1.01, 95% CI (-$0.59, +$2.85), P(lift>0)=88.8%. Matched-random p=0.092 (marginally clears the ≤0.10 bar).

## 10. 2026 Results (Jan 1 - Apr 29 2026, separately reported, NOT pooled with 2025-H2)

Eligible: **3,946**. Skipped: 59 (1.50%). Retention: 98.50%. Paired EV lift: **-$0.50/eligible**, total change -$1,990. Bootstrap: mean -$0.50, 95% CI (-$3.03, +$1.57) — spans zero. P(lift>0)=36.1%. **Matched-random p=0.673 — F5 is statistically indistinguishable from a matched-random skip in 2026.**

This is the single most important repaired finding: the prior study's pooled `secondary_oos` (Jun 2025-Apr 2026, ev lift +$0.45) **hid a real regime split** — every individual 2026 month (Jan, Feb, Mar, Apr) shows a flat-to-negative lift (-$0.01, -$0.80, -$0.08, -$1.26 respectively; see Section 11), not one bad month but a persistent four-month pattern.

## 11. Monthly Stability

16 months evaluated (`results/f5_monthly_metrics.parquet`), Jan 2025 - Apr 2026. Positive in 10/16 months, negative in 6/16. Two concentration patterns stand out:
- **April 2025 is an outlier**: +$6.07/eligible, dwarfing every other month (next highest is Dec 2025 at +$3.45). It alone drives 68% of the celebrated dev-test total benefit.
- **All four 2026 months are flat-to-negative**, a consistent regime pattern rather than one-month noise.

## 12. Skipped-Trade Economics

`results/f5_skipped_trade_economics.parquet`: across all four eval periods, skipped episodes are heavily loss-skewed (majority losers, profit factor of skipped trades well below 1.0 in validation/dev-test/2025-H2, but not in 2026 — consistent with the 2026 regime shift). Full winner/loser counts and largest-skipped-trade figures are in the parquet.

## 13. Paired Uncertainty

10,000-iteration paired bootstrap + 20,000-iteration exact sign-flip permutation per period, `results/f5_paired_bootstrap.parquet` / `f5_uncertainty_summary.parquet`. Combined post-train: mean +$1.04, 95% CI (-$0.04, +$2.17) — nearly excludes zero but does not, P(lift>0)=97.0%, P(lift≥$1)=52.4%, P(lift≥$2)=4.6%.

## 14. Long/Short and RTH/ETH Segmentation

`results/f5_segment_results.parquet` (combined post-train):

| segment | eligible | paired lift | total benefit |
|---|---|---|---|
| LONG | 7,904 | +$0.09 | +$724 |
| SHORT | 7,704 | +$2.00 | +$15,370 |
| RTH | 4,404 | +$2.84 | +$12,504 |
| ETH | 11,204 | +$0.32 | +$3,590 |
| RTH_LONG | 2,253 | +$1.84 | +$4,142 |
| RTH_SHORT | 2,151 | +$3.89 | +$8,361 |
| ETH_LONG | 5,651 | **-$0.60** | **-$3,418** |
| ETH_SHORT | 5,553 | +$1.26 | +$7,008 |

Nearly all of the aggregate benefit comes from SHORT and RTH episodes; ETH_LONG is net-negative under F5 (the filter actively hurts that segment). This directional/session asymmetry echoes a pre-existing finding in this repo's memory (`long_short_asymmetry_hmm_s3`) that shorts systematically outperform longs in related models.

## 15. Runner Preservation

`results/f5_runner_retention.parquet`, combined post-train: top-10% retention 98.75%, top-5% 98.87%, top-1% 98.95% — all comfortably clear the ≥95% target. Only 10 top-decile runners were skipped combined post-train (mean skipped-runner PnL $637, max $1,130) — small dollar cost relative to the ~$16K total benefit.

## 16. Drawdown Effects

Sign convention: positive cumulative PnL is favorable; drawdown = running-peak minus current cumulative PnL (≥0, larger = worse). Combined post-train: baseline max DD $132,741 → F5 max DD $127,783, an improvement of $4,958. Mixed at the period level: validation and 2025-H2 improve ($1,668 and $1,586 respectively), but dev-test and 2026 both get *slightly worse* (-$194 and -$1,555) — F5's skips are not always drawdown-reducing locally, and combined-period improvement is driven mostly by 2025-H2. Chronological equity path: `results/f5_equity_episode_path.parquet`; episodes most responsible for the combined drawdown difference: `results/f5_drawdown_causing_skips.parquet`.

## 17. Matched-Random Controls

1,000 seeds per period, matched exactly per-stratum (month × session × direction × entry-delay-bucket × ATR-bucket) to F5's real skip distribution (`results/matched_random_skip_controls.parquet` / `_summary.parquet`).

| period | F5 real lift | random mean | random p5-p95 | empirical p |
|---|---|---|---|---|
| validation | +1.35 | -0.42 | (-3.95, 1.99) | 0.140 |
| dev_test | +2.94 | -0.30 | (-4.15, 2.52) | **0.019** |
| secondary_2025H2 | +1.00 | +0.21 | (-0.77, 1.22) | 0.092 |
| secondary_2026 | -0.50 | -0.13 | (-1.77, 1.31) | **0.673** |
| combined_post_train | +1.03 | -0.10 | (-1.26, 0.74) | **0.014** |

F5 clearly beats matched-random on aggregate (combined p=0.014) and in dev-test, but is statistically indistinguishable from random in validation (p=0.14) and — most importantly — in 2026 alone (p=0.673), where the "skill" essentially vanishes.

## 18. Threshold Sensitivity (diagnostic only — 0.15 remains the frozen primary)

`results/f5_threshold_sensitivity.parquet`, grid {0.10, 0.125, 0.15, 0.175, 0.20} plus score-rank top-{1,2,3,5}%. Per-period classification is mostly `mixed_unstable`: e.g. secondary_2026's lift swings from +$7.42 (thr=0.10, retention 51%) to -$1.16 (thr=0.125) to -$0.50 (thr=0.15) to +$0.14 (thr=0.175) — a sign-flipping, non-monotonic pattern typical of a threshold sitting in a noisy region rather than a stable plateau. combined_post_train alone is monotonic (lift shrinks toward zero as threshold rises and fewer trades are skipped — expected mechanically). **Overall: MIXED**, not a stable plateau.

## 19. Feature-Family Ablations

`results/f5_feature_family_ablations.parquet`, refit on cached F2 features, evaluated on validation at equivalent retention (98.42%). **Context that qualifies every number below: the full frozen model's own validation AUC is only 0.522** (barely above chance) — this is a weak classifier whose economic value comes from removing a small number of very bad outlier trades, not from broad discriminative skill.

The task brief's prior observation ("removing 5-minute center features may improve classification while 15/30/60m and sequence features carry more signal") is **NOT confirmed**: removing `median_center_5m` makes AUC slightly *worse* (0.522→0.513) and cuts economic lift from +$1.35 to +$0.55 — the 5m family carries real, not redundant, signal. `regime_counts` removal also hurts (AUC 0.522→0.509, lift → +$0.89). Several sequence-geometry ablations (`overlap_retracement`, `12_regime_sequence`) show the *largest* lift degradation, suggesting sequence-overlap features are doing more economic work than the median-center families, opposite to the prior claim's framing.

## 20. 1s-vs-5s Sensitivity Reconciliation

`results/center_sampling_sensitivity.parquet` / `center_sampling_reconciliation.md`. The prior contradiction ("<0.05 points" vs "~1.25 points") was never fully specified (feature/unit/horizon/population/normalization/median-vs-mean/pooling all unstated). Reconciled on a 179-episode deterministic stratified sample (period_role × session × ATR-bucket):

| horizon | median \|diff\| pts | mean \|diff\| pts | p95 \|diff\| pts | mean \|diff\| ATR |
|---|---|---|---|---|
| 5m | 0.125 | 0.253 | 0.638 | 0.027 |
| 15m | 0.125 | 0.166 | 0.500 | 0.020 |
| 30m | 0.125 | 0.163 | 0.500 | 0.019 |
| 60m | 0.000 | 0.140 | 0.500 | 0.018 |

Neither prior claim is reproduced exactly; the true median sits close to (slightly above) the "<0.05" claim and far below the "~1.25" claim — likely a pooled-vs-per-horizon or median-vs-mean confusion in the original reporting. **Score/skip impact: 2/179 (1.12%) skip-flag disagreements** when the three `aligned_price_minus_center_{5,15,30}m` features are perturbed to their 5s-sampled values and rescored through the frozen model — small but nonzero.

## 21. Decision Against Predeclared Rules

- Validation lift positive: **yes** (+$1.35)
- Dev-test lift ≥ +$2: **yes** (+$2.94, but 68% concentrated in one month — Section 11)
- 2025-H2 lift positive: **yes** (+$1.00)
- 2026 lift positive: **no** (-$0.50, but CI spans zero and matched-random p=0.673 — statistically flat, not "materially negative")
- Combined lift range: **+$1.03**, inside the conditional-pass band [+$0.50, +$2.00]
- Combined paired CI: **includes zero** ((-$0.04, +$2.17))
- Top-decile runner retention: **98.75%**, clears ≥95%
- Matched-random combined p=0.014 (clears ≤0.10); but validation (0.140) and 2026 (0.673) do not
- Critical execution/provenance violations: **0**
- F2 canonical parity: **PASS**
- Threshold sensitivity: **mixed**, not a stable plateau

This profile does not meet **strong pass** (2026 is not positive, and threshold sensitivity is not stable). It matches **conditional pass**: validation and dev-test positive, 2025-H2 positive with 2026 approximately neutral (not materially negative — CI includes zero, matched-random indistinguishable from noise), combined lift in the [+$0.50, +$2.00] band, runner retention clears 95%, matched-random directionally favors F5 in aggregate, and the combined CI includes zero.

**F5 VERDICT: CONDITIONAL.**

## 22. Recommended Next Step

Do not deploy F5 unconditionally. The aggregate "pass" rests on (a) an April-2025 outlier month contributing most of the celebrated dev-test result and (b) a 2026 evaluation year in which the filter is statistically indistinguishable from randomly skipping the same number of trades. Before any live use: deploy with a rolling monthly monitor (lift + matched-random p-value) that auto-suspends the filter if the 2026-style flat/negative pattern persists or worsens across two more months. Do not pursue order-flow/microstructure features yet (`ORDER-FLOW REQUIREMENT: NOT ESTABLISHED`) — the frozen F5 model's own validation AUC (0.522) shows almost no OHLCV-derived skill to begin with, and the economics are driven by removing a small negative tail (skip rate ~2%), not by broad predictive power; the priority is confirming temporal stability of the existing signal, not adding data sources to a signal that may not be real.
