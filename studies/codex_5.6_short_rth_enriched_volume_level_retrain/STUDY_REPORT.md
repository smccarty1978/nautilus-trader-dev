# Enriched short-RTH retrain

## Executive summary

Decision: `ENRICHED_RETRAIN_CLIPS_WINNERS`. Selected schedule: `F3__logistic__rband0.2`. The enriched retrain passed all five frozen 2025 selection checks but failed sealed 2026 and clipped more baseline winners than its exact stop savings. Keep the current W4 Policy A; do not promote this retrain.

This is a 1-second-OHLC research analysis of accepted, precomputed NT-derived Policy-A labels; it is not NT-native executable validation.

## Selected economics

| Split | Trades | Net PnL | PnL/trade | PF | Max DD |
|---|---:|---:|---:|---:|---:|
| 2025 selection | 1247 | 46706.93 | 37.46 | 1.254 | 7953.42 |
| 2026 sealed | 380 | -3242.93 | -8.53 | 0.954 | 16154.95 |

Baselines: A = 872 trades / $22,250 / $25.52 per trade / PF 1.129 / DD $18,686; B = 807 / $27,013 / $33.47 / PF 1.174 / DD $14,331; C NT benchmark = 807 / $23,270 / $28.84 / PF 1.149 / DD $15,000; D prior retrain selected GBT 35% and failed 2026 at -$10,970.

## Findings

- The frozen 2025 choice was F3 (combined volume/delta and price-level features), logistic regression, 20% qualifying-score retention.
- Sealed 2026 produced $-3242.93 total and $-8.53 per trade with PF 0.954; it did not survive the net, per-trade, PF, or monthly gates.
- Exact matched attribution found $13247.14 of stop savings but $29662.68 of clipped winners.
- Survival gates: `{"monthly_abs_share": true, "monthly_positive_share": true, "monthly_worst_25pct": false, "net_positive": false, "pertrade_90pct": false, "pf_90pct": false, "positive_month_concentration": false, "stop_savings_gate": true, "winner_clipping_exact": false}`.
- The fixed-807 overlay remains not applicable because that schedule lacks complete trade-level PnL/outcome semantics for exact keep/drop/move/add attribution.

## Decision

`ENRICHED_RETRAIN_CLIPS_WINNERS`

Do not promote to NT schedule validation. Keep the current W4 Policy A.

## Recovery provenance

The sealed computation completed and wrote all machine-readable outputs. A report-only NumPy-boolean formatting error prevented the original Markdown and manifest writes. This finalizer verified the unchanged runner hash against the 2025 seal, exact selected-schedule identity, required table row counts, selected 2025/2026 economic rows, and the 2026 trade count/PnL before writing this report. It did not refit, rescore, reselect, or reopen the 2026 input.
