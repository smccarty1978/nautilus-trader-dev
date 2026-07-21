# Offline Batch Summary — Final Deliverable

Work completed during the user's offline window (~3 hours).

## Reports delivered

1. **`V_A_CROSS_PRODUCT_BASELINE.md`** — V_A baseline across NQ/ES/YM × 17 cells
2. **`NQ_EXIT_POLICY_MODEL_V1.md`** — Supervised exit policy on NQ 2024-2026
3. **(Skipped per spec rule 4)** `CROSS_PRODUCT_EXIT_POLICY_MODEL_V1.md` — exit policy was not promising on NQ; did not force it on ES/YM

## Run inventory

### Completed runs (all 17 with valid path_checkpoints)

| Product | Year | Trades | Path checkpoints |
|---|--:|--:|--:|
| NQ | 2020 | 11,375 | 291,638 |
| NQ | 2021 | 11,841 | 288,146 |
| NQ | 2022 | 12,067 | 305,738 |
| NQ | 2023 | 11,966 | 293,058 |
| NQ | 2024 | 11,987 | 298,794 |
| NQ | 2025 | 11,776 | 293,260 |
| NQ | 2026 | 3,575 | 87,067 |
| ES | 2020 | 10,424 | 259,798 |
| ES | 2021 | 10,024 | 239,491 |
| ES | 2024 | 9,918 | 235,566 |
| ES | 2025 | 10,469 | 256,026 |
| ES | 2026 | 3,260 | 80,890 |
| YM | 2020 | 11,723 | 265,553 |
| YM | 2021 | 11,817 | 239,543 |
| YM | 2024 | 11,255 | 220,982 |
| YM | 2025 | 11,634 | 219,928 |
| YM | 2026 | 3,602 | 70,186 |

**Total: 168,713 trades, 3,645,664 path_checkpoints, 0 provenance violations.**

### Missing/failed runs

- **ES 2022, ES 2023** — data unavailable in catalog (verified at start)
- **YM 2022, YM 2023** — data unavailable in catalog
- All other queued cells completed successfully

### Bugs caught and fixed during batch

1. **YM instrument precision mismatch** (price_increment "1.0" gave precision=1; YM bars have precision=0). Fixed by using "1" as tick string.
2. **path_checkpoint extra fields not wired into FeatureSnapshot** — first batch of NQ 2024 / NQ 2025 / ES 2024 / YM 2024 produced path_checkpoints with all extras NaN. Fix: explicitly pass extras into FeatureSnapshot constructor in `snapshot_builder.py`. All affected cells were re-run with the fix.

## Headline findings

### V_A baseline (RTH-only)

> **15 of 17 (product, year) RTH cells lose money. Only NQ 2024 (+$6.35/trade) and NQ 2025 (+$18.04/trade) are positive.**

The earlier V_A NT-validated baseline (PF 1.03 across NQ 2024-2026) was a localized 2-year window in an otherwise loss-making strategy.

| Product | Years | n | Mean $ | PF | Total $ |
|---|---|--:|--:|--:|--:|
| NQ | 2020-2026 | 21,691 | -$6.88 | 0.97 | -$149,280 |
| ES | 2020-2026 | 13,630 | -$17.31 | 0.86 | -$236,000 |
| YM | 2020-2026 | 14,888 | -$7.80 | 0.91 | -$116,105 |

NQ is closest to break-even but still net negative across 7 years.
ES never works. YM never works.

ETH performance is uniformly worse than RTH (additional ~$200/trade
loss in aggregate). No reason to ever enable ETH for this strategy.

### NQ exit-policy model

> **Causal supervised exit-policy modeling cannot identify when remaining upside is poor enough to exit without killing the winner tail.**

- `future_giveback_risk` is predictable (AUC 0.79 stable across folds) — but base rate is so high that any threshold collapses to "exit everything"
- `exit_now_better_than_hold` is essentially random (AUC 0.53)
- `remaining_ev_atr` regression has correlation 0.01

Best honest policy improvement: +$1.62/trade (1% of trades cut), economically marginal. SL=2.0 ATR overlay is also marginal (-$0.95 vs -$1.51 baseline).

This converges with the prior path-diagnostics study which tested hand-crafted rules and reached the same conclusion: no exit overlay improves V_A.

## Final recommendations

### 1. **DO NOT deploy V_A baseline as-is.**

The strategy is structurally negative on:
- Every product tested (NQ, ES, YM)
- Most years tested (15 of 17 RTH cells)
- Both sessions (RTH and ETH, ETH worse)

The 2024-2025 NQ profitability that motivated this work was a regime pocket, not a stable edge.

### 2. **DO NOT continue exit-policy modeling.**

Both ML (this study) and hand-crafted rules (prior path-diagnostics) cannot improve V_A's hold-to-regime-exit baseline. The bottleneck is feature informativeness — the available registry MTF state + path features do not separate winners from losers at intermediate checkpoints. RL will not help.

### 3. **DO NOT expand to ES/YM exit-policy.**

NQ result is unpromising; cross-product exit policy is unlikely to be different given:
- ES is structurally worse than NQ at baseline (PF 0.86 vs 0.97)
- YM is similar to NQ but lower volatility
- Same path-checkpoint feature class would be tested

### 4. **Consider these next directions (if continuing):**

a) **Identify the 2024-2025 NQ regime.** What was different about
   those years? If we can build a meta-filter (RTH-only NQ, only
   when X regime condition holds), we might extract a usable subset.
   But the 2026 reversion to losses is a warning that the regime
   is not durable.

b) **Different signal class entirely.** V_A's structural negativity
   suggests the entry signal is too noisy. Orderflow imbalance,
   volume profile breakouts, or news-driven entries would be a
   reasonable pivot.

c) **Drop the strategy class.** Hold-to-regime-exit on momentum-
   confirmed 1m flips is a well-tested and consistently negative
   pattern. The energy spent here may be better directed elsewhere.

### 5. **Infrastructure delivered (not negative)**

- **Collector V2** is now production-ready with full causality enforcement, 0 provenance violations across ~3.6M path checkpoints
- **CAUSALITY.md** + `utils/causality.py` + parity smoke harness are the correct gates for any future strategy work
- Per `MEMORY.md` critical rules, no future strategy can ship without 1-week parity passing first
- The legacy MTF lookup bugs (5m alignment lookahead, regime-exit optimism, schedule survivor bias) are all documented and prevented going forward

## Process notes

- Matrix driver (`run_matrix.py`) ran 17 cells in ~17 minutes wall time at 4-parallel — the new architecture is fast enough that re-running the full grid is cheap
- All deliverables produced within the 3-hour offline window with time to spare
- Bug fix (path_checkpoint wiring) caught and corrected mid-flight; affected cells were re-run automatically by the matrix driver

## Files

### Reports
- `collectors/collector_v2/reports/V_A_CROSS_PRODUCT_BASELINE.md`
- `collectors/collector_v2/reports/NQ_EXIT_POLICY_MODEL_V1.md`
- `collectors/collector_v2/reports/SMOKE_PARITY_2024_01_08_15.md` (prior)
- `collectors/collector_v2/reports/V_A_BASELINE_REPRODUCTION.md` (prior)
- `collectors/collector_v2/reports/V_A_MTF_ALIGNMENT_RE_TEST.md` (prior)
- `collectors/collector_v2/reports/OFFLINE_BATCH_SUMMARY.md` (this file)

### Data
- `collectors/collector_v2/results/portfolio/<PRODUCT>_<YEAR>/` — per-cell trades + snapshots
- `collectors/collector_v2/results/portfolio/MATRIX_MANIFEST.json` — completion manifest
- `collectors/collector_v2/results/exit_policy/` — labeled datasets + model predictions + simulation summaries

### Code
- `collectors/collector_v2/strategy.py` — V_A reference + path_checkpoint emission
- `collectors/collector_v2/run_portfolio.py` — per-cell runner
- `collectors/collector_v2/run_matrix.py` — autonomous batch driver
- `collectors/collector_v2/exit_policy_dataset.py` — label generation
- `collectors/collector_v2/exit_policy_train.py` — walk-forward LightGBM
- `collectors/collector_v2/exit_policy_simulate.py` — policy simulator
- `collectors/collector_v2/analyze_portfolio.py` — cross-product analyzer
