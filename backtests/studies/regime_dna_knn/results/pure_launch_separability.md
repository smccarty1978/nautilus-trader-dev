# Pure Orderly Launch — Early Separability (Bar-3 info only)

Positives = Pure Orderly Launch (IS 3,393 / OOS 1,228). Features: Bar-1–3 health + pre-flip runway ONLY. Train IS 2021–24, evaluate OOS 2025–26. No KNN, no clustering. The question: AUC ~0.52 (unpredictable) vs ~0.70 (the conclusion changes).

## Univariate — P(Pure Launch | decile), IS, launch vs all non-launch
Base rate P(launch) = 3.1%. A feature separates if top/bottom deciles deviate strongly from base.

| Feature | D1 | D2 | D5 | D9 | D10 | span(max−min) |
| --- | --- | --- | --- | --- | --- | --- |
| early_mfe_expansion | 0.1% | 0.5% | 2.7% | 5.5% | 4.6% | 5.4pp |
| early_mae_peak | 4.7% | 5.4% | 3.4% | 0.1% | — | 5.3pp |
| early_health_ratio | 0.0% | 0.1% | 3.4% | 5.5% | 5.2% | 5.5pp |
| current_pullback_from_peak | 6.2% | 5.7% | 3.8% | 0.9% | 0.5% | 5.7pp |
| bar3_close_location | 1.8% | 2.1% | 3.4% | 5.1% | 3.8% | 3.3pp |
| pre5_efficiency | 3.0% | 2.8% | 3.3% | 3.1% | 2.9% | 0.5pp |
| pre5_compression | 2.5% | 2.7% | 3.1% | 3.4% | 3.2% | 0.8pp |
| pre5_velocity_ratio | 3.8% | 3.4% | 3.0% | 2.7% | 2.5% | 1.3pp |
| pre5_volume_acceleration | 2.7% | 2.8% | 3.0% | 3.2% | 2.7% | 0.8pp |

## Multivariate — AUC + precision @ top k% (OOS 2025–26)
### Negatives = ALL non-launch (deployment haystack)  (OOS positives 1228, negatives 35014, base rate 3.4%)
| Model | AUC | Prec@1% | Prec@5% | Prec@10% | Lift@1% |
| --- | --- | --- | --- | --- | --- |
| Logistic | **0.792** | 12.4% | 10.4% | 9.4% | 3.7x |
| LightGBM | **0.782** | 9.9% | 9.3% | 9.0% | 2.9x |

### Negatives = QuickFailure fakeouts only (easiest)  (OOS positives 1228, negatives 8051, base rate 13.2%)
| Model | AUC | Prec@1% | Prec@5% | Prec@10% | Lift@1% |
| --- | --- | --- | --- | --- | --- |
| Logistic | **0.978** | 96.7% | 93.7% | 85.5% | 7.3x |
| LightGBM | **0.978** | 95.7% | 93.5% | 86.3% | 7.2x |

## Verdict
> [!TIP]
> **CONCLUSION CHANGES — orderly launches ARE early-separable.** Best OOS AUC = 0.978. Bar-3 + pre-flip information meaningfully identifies the orderly launches. This reopens the price-action branch as an ENTRY filter — proceed to a costed, walk-forward, both-years money gate on the top-decile selections.
---

## CORRECTED VERDICT (after feature-group decomposition)

The headline AUC 0.79 (vs all) / 0.978 (vs QuickFailure) is **TAUTOLOGICAL, not predictive**:

| Feature group | AUC vs all | AUC vs QF |
| --- | --- | --- |
| **Pre-flip runway ONLY (causal at flip)** | **0.528** | 0.549 |
| Tautological subsets (flip_open_viol_b + early_mae) | 0.726 | 0.920 |
| Predictive-run (early_mfe + progression + close-loc) | 0.740 | 0.957 |
| Everything (drop MAE/violation) | 0.764 | 0.976 |

- **Pre-flip alone = AUC 0.528 (coin flip): orderly launches are NOT causally anticipatable at the flip.**
- The 0.79 is driven by bars-1–3 features that are SUBSETS of the 10-bar label (early_mae ⊂ MAE10≤0.75 gate; flip_open_violation_b ⊂ bars-1–5 gate; early_mfe ⊂ MFE10≥1.5). This is OBSERVING the launch's own first 3 bars, not predicting it.
- Precision @ top-1% = only **12.4%** (88% of best picks are non-launches) — not deployable.
- The early-health study already TRADED this filter (Version B: bars-1–3 health gate, enter bar 4) → **net-negative both years**. Separability does not monetize.

**CONCLUSION HOLDS.** Causal (pre-flip) separability is a coin flip; the high post-hoc AUC is the label including the early bars; the partial observation is low-precision and loses money. Price geometry recognizes state, it does not predict payoff.
