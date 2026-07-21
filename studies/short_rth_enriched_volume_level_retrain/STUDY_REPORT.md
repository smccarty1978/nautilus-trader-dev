# Study Report: Short-RTH Enriched Volume/Level Retrain

**Study directory:** `studies/short_rth_enriched_volume_level_retrain/`
**Final decision: `ENRICHED_RETRAIN_OVERFITS_2025`**

## Summary

Adding the 461 newly-accepted OHLCV volume/delta and price-level context
features measurably improves the model's ability to separate short-RTH
entry outcomes (AUC), and the best resulting policy beats the current W4
baseline decisively on 2025 dev data. But the improvement does not survive
sealed 2026: every one of the 8 (feature_set, model) combinations' own
best-on-2025 retention band goes **negative** on 2026, including the
overall winner. Keep the current W4 short-RTH Policy A baseline
(`[[short_rth_retrain_baseline_still_best]]`); do not promote any enriched
variant to NT schedule-driven validation.

## 1. Did the enriched features improve over the old feature set?

Yes, on every diagnostic measured, in both years:

| feature_set | model | 2025 AUC winner | 2026 AUC winner | 2025 AUC pre-stop | 2026 AUC pre-stop |
|---|---|--:|--:|--:|--:|
| F0 existing only | logreg | 0.5692 | 0.5454 | 0.5271 | 0.5123 |
| F0 existing only | gbt | 0.5781 | 0.5610 | 0.5314 | 0.5024 |
| F1 volume/delta only | logreg | 0.5713 | 0.5597 | 0.5636 | 0.5413 |
| F1 volume/delta only | gbt | 0.5795 | 0.5631 | 0.5675 | 0.5677 |
| F2 price-levels only | logreg | 0.5722 | 0.5476 | 0.5550 | 0.5396 |
| F2 price-levels only | gbt | 0.5772 | 0.5673 | 0.5689 | 0.5560 |
| **F3 combined** | **logreg** | 0.5719 | 0.5472 | 0.5626 | 0.5476 |
| **F3 combined** | **gbt** | **0.5816** | **0.5827** | **0.5797** | **0.5690** |

F3-gbt has the best AUC of all 8 combos, in **both** years, on **both**
target classes — including a 2026 AUC that is not just "not much worse"
than 2025 but slightly *higher* (0.5827 vs 0.5816), the strongest AUC-level
stability result in the whole grid. This AUC lift is real and durable. It
does not, however, translate into a durable economic edge (see §6-7).

## 2. Did volume/delta features add measurable signal?

Yes. F1 (existing + volume/delta) beats F0 (existing only) on every AUC
column, in both years, for both models — the largest single jump of any
feature addition (e.g. logreg pre-stop AUC: 0.527→0.564 in 2025,
0.512→0.541 in 2026). In the feature-family contribution table, volume/delta
features carry 64.2% of logreg's importance mass in F1 (vs 35.8% for the
149 existing features) and 39.1% in the combined F3 model — a real,
substantial, non-trivial contribution, not noise.

## 3. Did price-level context features add measurable signal?

Yes, similarly. F2 (existing + price-level) beats F0 on every AUC column in
both years for both models (e.g. gbt pre-stop AUC: 0.531→0.569 in 2025,
0.502→0.556 in 2026). Price-level features carry 61.3% of logreg's
importance mass in F2 and 40.0% in F3.

## 4. Did the combined model improve 2025?

Yes, decisively. The best 2025-selected combo (F3 combined, logistic
regression, 20% retention) beats Baseline A on all three available
comparator criteria:

| Metric | Selected (2025) | Baseline A (2025) |
|---|--:|--:|
| Trades | 1,243 | 650 |
| Net PnL | +$45,110 | +$15,366 |
| $/trade | **+$36.29** | +$23.64 |
| Profit factor | **1.241** | 1.129 (combined) |
| Max closed-trade DD | **$8,185** | $18,686 (combined) |
| Win rate | 39.98% | — |

Every combo's own best-2025 band also beat F0's best-2025 band (F0 logreg
100%: −$6.32/tr; F0 gbt 50%: −$3.87/tr — both negative even on their own
best 2025 selection) — the enriched feature sets are not just better on
AUC, they are the *only* feature sets whose 2025-selected policy is
profitable at all.

## 5. Did the improvement survive sealed 2026?

**No.** The selected combo goes negative:

| Metric | Selected (2026) | Baseline A (2026) |
|---|--:|--:|
| Trades | 378 | 222 |
| Net PnL | **−$1,177** | +$6,884 |
| $/trade | **−$3.11** | +$31.01 |
| Profit factor | **0.983** | — |
| Win rate | 36.51% | — |

And this is not an idiosyncrasy of the selected combo — **all 8** combos'
own best-2025 band go negative on 2026 (range: −$3.11/tr to −$43.86/tr; see
`results/feature_set_comparison.csv`). The AUC improvement from §1 is real,
but AUC-level separation is not the same thing as durable PnL discrimination
— consistent with this project's standing finding
(`[[rl_expanded_dynamic_closed]]`).

## 6. Did the model avoid pre-alignment stops without clipping too many opposing-flip winners?

**No — filtering itself was net negative**, and a closer look at the
attribution numbers reveals *why* the 2025 result looked good anyway. Going
from 100%-retention (no filtering, 1,678 trades, net −$10,613 — identical
by construction to the raw candidate-basis-independent population, since at
100% retention every model reduces to "first checkpoint in the regime,"
regardless of score) down to the selected 20% band (1,243 trades, net
+$45,110):

- The **435 regimes removed** by filtering would, at their *original*
  (100%-band) entry, have contributed **+$74,817** — filtering them out cost
  more than it saved (105 pre-alignment stops avoided, +$34,446 saved, vs.
  124 opposing-flip winners removed, −$89,470 lost; net **−$55,024** on this
  comparison alone, per `results/manifest.json`'s `failure_attribution`).
- That means the **1,243 kept regimes**, at whatever entry the 100%-band
  policy would have given them, must have been sitting at roughly
  **−$85,430** (net_2025_100% − removed_regimes_pnl = −$10,613 − $74,817).
  Their *actual* 2025 result under the 20%-band policy was **+$45,110** — a
  swing of **+$130,540** on the exact same 1,243 regimes, driven entirely by
  which checkpoint *within* the regime got selected as the entry (527 of 554
  kept-and-fixed-807 trades moved to a different entry timestamp than the
  original, per the Layer 3 overlay).

This is the same "entry timing dominates entry filtering" pattern this
project has already established independently
(`[[w4_symmetric_bracket_race]]`, the prior retrain study's Layer 3 finding)
— now reproduced *within* this study's own Layer 2 policy across retention
bands, not just against the external fixed-807 comparator. It is the most
plausible explanation for why the 2025 result doesn't generalize: a
retention-band cutoff that happens to land on a favorable entry-timing shift
in one year has no reason to land on a favorable one in the next.

## 7. Is any model strong enough to promote to NT schedule-driven validation?

**No.** No combo passes the selection gate's sealed-2026 checks (net PnL
positive, $/trade and PF not materially worse than baseline). The gate
correctly returns `test_2026_positive: false` for the selected combo, and
inspection of the full 8-combo comparison table confirms this is universal,
not specific to the selected combo.

## 8. If not, should we keep the current W4 short-RTH Policy A baseline?

**Yes.** Baseline A (+$25.52/tr combined, PF 1.129) remains the best
available short-RTH entry policy. This is the third retrain attempt on this
population to reach the same conclusion by a different route — the original
149-feature retrain (`[[short_rth_retrain_baseline_still_best]]`, GBT@35%,
2025 +$4.75/tr → 2026 −$32.36/tr) and this 461-feature-enriched retrain both
overfit to 2025 despite very different feature sets and (for this study) a
richer, outcome-aware 5-class objective. The consistent failure mode across
both studies — and the entry-timing-dominance mechanism identified in §6 —
points at the underlying limitation being about **which checkpoint within a
regime to enter**, not which features describe the checkpoint. Proceed with
Phase 2 live-W4 NT validation on the frozen Baseline A / Policy A contract
instead of any retrained variant.

## Audit

`audit/audit.md`: **PASS, 0 CRITICAL** (1 WARNING — model-checkpoint cache
key doesn't hash input data, a risk for future re-runs, not an active
defect in this completed run; 3 NOTEs — documentation drift only, now
corrected in `SPEC.md`). Confirms `ENRICHED_RETRAIN_OVERFITS_2025` is a
genuine finding, not a look-ahead artifact: retention-band cutoffs are
computed from 2025 only and applied unchanged to 2026; the
imputer/scaler/models are fit on train only; `select_best()` never touches
2026 data; no feature set contains a provenance, name, or post-entry
outcome column.

## Selection gate detail

```text
criteria_2025 (>=2 of 3 required):
  per_trade_beats_baseline_a:       True  ($36.29 vs $23.64)
  profit_factor_beats_baseline_a:   True  (1.241 vs 1.129)
  max_dd_better_than_baseline_a:    True  ($8,185 vs $18,686)
  -> dev_2025_improves_over_baseline_a: True (3/3)

test_2026_positive:                        False (-$3.11/tr)
test_2026_not_materially_worse_than_baseline: False
monthly_shape_ok:                          True (top-1 month share 16.3% in 2025, 48.2% in 2026)
clips_winners:                             True (net_stop_savings_minus_winner_clipping < 0, both years)

-> DECISION: ENRICHED_RETRAIN_OVERFITS_2025
   (2025 improves + 2026 fails takes priority over the clips_winners check,
   per SPEC's decision-tree ordering.)
```

Note on gate scope: Baseline A publishes only per-trade/profit-factor/max-DD
as reusable constants project-wide — no split-year pre-alignment-stop-rate
or opposing-flip-PnL constant for Baseline A exists upstream. The "at least
two of five" 2025 check is therefore evaluated on the three criteria with a
real comparator number; pre-alignment-stop-rate and opposing-flip-PnL are
reported instead as within-model before/after attribution (§6), which is
what the SPEC's separate stop-savings-vs-winner-clipping comparison actually
calls for.

## Primary caveats

1. **Entry-timing dominance (§6)** is the dominant driver of both the 2025
   result and its 2026 failure — not feature quality per se. A future study
   aimed at *when within a regime* to enter (not *which* regime, and not
   *which features describe it*) is more likely to find a durable edge than
   further feature-set iteration on this same entry-selection framing.
2. **GBT permutation importance ran single-threaded (`n_jobs=1`)** after a
   Windows-specific joblib multiprocessing resource ceiling
   (`WinError 1450`) crashed the original `n_jobs=-1` run on the largest
   (695-feature) combo. This only affects computation cost, not correctness
   — the resulting importances are identical in expectation, verified by
   the fact that all 7 already-completed combos reproduced byte-for-byte
   identical diagnostics across the crashed and rerun attempts (same random
   seed, deterministic fit).
3. **F3-gbt has the best and most stable AUC of the whole grid** (§1) but is
   not the combo the 2025-only selection discipline picked (that was
   F3-logreg, by the SPEC's fixed per-trade/PF tie-break rule) — AUC
   stability and 2025 economic-selection are measuring different things by
   design, and the SPEC's rule intentionally does not let 2026 information
   (where F3-gbt's AUC stability shows up) influence the selection.
4. Model-checkpoint caching (`_work/checkpoints/*.pkl`) has no
   upstream-data hash (audit WARNING D4) — safe for this run, but must be
   manually cleared before any future re-run on corrected upstream data.

## Next bounded study to test information content

Not applicable in the original sense (that question belonged to the
feature-foundation study, already answered there). For this retrain's own
finding: a bounded study isolating **entry-timing-within-regime** as the
sole variable (holding feature set and filtering logic fixed) — e.g.,
comparing "first eligible checkpoint" vs. "latest eligible checkpoint before
timeout" vs. a small number of fixed-offset checkpoints — would directly
test the §6 mechanism without conflating it with feature selection, and
would clarify whether the entry-timing effect is exploitable prospectively
or only visible in hindsight (matching `[[w4_symmetric_bracket_race]]`'s
open question).
