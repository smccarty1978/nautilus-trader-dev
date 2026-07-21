# V_A Cross-Product Baseline — Collector V2

V_A reference (1m HH/LL + momentum confirm, hold to opposing 1m
regime flip close) run through Collector V2 across NQ / ES / YM and
all available years. Causal feature timing enforced by registry
audit on every snapshot — **0 provenance violations across 17
cells, ~168K trades, ~3.6M path checkpoints.**

**Cost model**: $5 commission + 1-tick exit slip per product
(NQ=$5, ES=$12.50, YM=$5).

## Headline finding

> **V_A is structurally negative on every product, every year,
> every session — except NQ 2024-2025 RTH.**
>
> The prior +$58K aggregate result on NQ 2024-2026 was driven by
> 2 favorable years (2024-2025) on one product (NQ) in one
> session (RTH). Extending to 5 products × 5+ years × both
> sessions reveals **15 of 17 (product, year) cells are negative
> in RTH** and the cumulative 7-year cross-product portfolio
> would have lost ~$2M trading 1 contract per product.

## 1. Per-cell results — RTH ONLY (matches prior baselines)

This is the real picture. Each cell is one (product, year) RTH
session. Cells with positive mean **bolded**.

| Product | Year | n | WR | Mean $ | PF | Total $ | Max DD |
|---|--:|--:|--:|--:|--:|--:|--:|
| ES | 2020 | 3,325 | 32.6% | $-23.76 | 0.80 | -$79,012 | — |
| ES | 2021 | 3,186 | 30.6% | $-18.90 | 0.79 | -$60,230 | — |
| ES | 2024 | 3,024 | 31.6% | $-14.26 | 0.87 | -$43,120 | — |
| ES | 2025 | 3,148 | 33.0% | $-9.43 | 0.94 | -$29,678 | — |
| ES | 2026 | 947 | 32.1% | $-25.30 | 0.85 | -$23,960 | — |
| NQ | 2020 | 3,571 | 35.7% | $-9.57 | 0.94 | -$34,170 | — |
| NQ | 2021 | 3,548 | 33.2% | $-22.02 | 0.86 | -$78,130 | — |
| NQ | 2022 | 3,465 | 34.2% | $-15.82 | 0.94 | -$54,805 | — |
| NQ | 2023 | 3,448 | 34.3% | $-13.28 | 0.92 | -$45,780 | — |
| **NQ** | **2024** | **3,343** | **35.2%** | **+$6.35** | **1.03** | **+$21,220** | — |
| **NQ** | **2025** | **3,310** | **34.2%** | **+$18.04** | **1.07** | **+$59,720** | — |
| NQ | 2026 | 1,006 | 35.1% | $-17.23 | 0.94 | -$17,335 | — |
| YM | 2020 | 3,483 | 34.2% | $-8.92 | 0.90 | -$31,065 | — |
| YM | 2021 | 3,558 | 30.4% | $-11.67 | 0.82 | -$41,535 | — |
| YM | 2024 | 3,374 | 33.2% | $-4.48 | 0.94 | -$15,105 | — |
| YM | 2025 | 3,416 | 32.1% | $-4.24 | 0.96 | -$14,475 | — |
| YM | 2026 | 1,057 | 31.0% | $-13.17 | 0.88 | -$13,925 | — |

**Positive cells: 2 of 17 (NQ 2024, NQ 2025).**

## 2. By product — RTH

| Product | Years | n | WR | Mean $ | PF | Total $ |
|---|---|--:|--:|--:|--:|--:|
| NQ | 2020-2026 (7 years) | 21,691 | 34.5% | $-6.88 | 0.97 | -$149,280 |
| ES | 2020-2026 (5 years) | 13,630 | 32.0% | $-17.31 | 0.86 | -$236,000 |
| YM | 2020-2026 (5 years) | 14,888 | 32.4% | $-7.80 | 0.91 | -$116,105 |

NQ is the closest to break-even, ES is the worst, YM is in between.

## 3. By session

| Session | n | WR | Mean $ | PF | Total $ |
|---|--:|--:|--:|--:|--:|
| RTH | 50,209 | 33.2% | $-9.99 | 0.93 | -$501,385 |
| ETH | 118,504 | 28.8% | $-12.74 | 0.82 | -$1,509,845 |
| ALL | 168,713 | 30.1% | $-11.92 | 0.87 | -$2,011,230 |

**Both sessions are losing.** ETH is worse per-trade AND has 2.4× the trade count, so ETH dominates the loss column.

## 4. Product × session matrix

| Product | Session | n | WR | Mean $ | PF | Total $ |
|---|---|--:|--:|--:|--:|--:|
| NQ | RTH | 21,691 | 34.5% | $-6.88 | 0.97 | -$149,280 |
| NQ | ETH | 52,896 | 30.7% | $-10.53 | 0.89 | -$557,025 |
| ES | RTH | 13,630 | 32.0% | $-17.31 | 0.86 | -$236,000 |
| ES | ETH | 30,465 | 27.7% | $-18.38 | 0.73 | -$559,825 |
| YM | RTH | 14,888 | 32.4% | $-7.80 | 0.91 | -$116,105 |
| YM | ETH | 35,143 | 27.0% | $-11.18 | 0.75 | -$392,995 |

**NQ RTH is the closest to viable (PF 0.97). Every other cell is materially worse.**

## 5. By year (RTH-only aggregate across products)

| Year | Products | n | WR | Mean $ | PF | Total $ |
|---|---|--:|--:|--:|--:|--:|
| 2020 | NQ+ES+YM | 10,379 | 34.1% | $-13.65 | 0.88 | -$144,247 |
| 2021 | NQ+ES+YM | 10,292 | 31.4% | $-17.46 | 0.83 | -$179,895 |
| 2022 | NQ only | 3,465 | 34.2% | $-15.82 | 0.94 | -$54,805 |
| 2023 | NQ only | 3,448 | 34.3% | $-13.28 | 0.92 | -$45,780 |
| 2024 | NQ+ES+YM | 9,741 | 33.4% | $-12.32 | 0.91 | -$120,005 |
| **2025** | **NQ+ES+YM** | **9,874** | **33.1%** | **+$1.55** | **1.01** | **+$15,567** |
| 2026 | NQ+ES+YM | 3,010 | 32.7% | $-18.36 | 0.89 | -$55,220 |

**2025 is the ONLY positive cross-product year — and only by +$1.55/trade ($15.6K total) carried by NQ 2025's +$60K offsetting ES/YM losses.**

## 6. Combined portfolio curve (1 contract per product, RTH-only)

| Year | NQ | ES | YM | TOTAL_PORTFOLIO |
|---|--:|--:|--:|--:|
| 2020 | -$34,170 | -$79,012 | -$31,065 | -$144,247 |
| 2021 | -$78,130 | -$60,230 | -$41,535 | -$179,895 |
| 2022 | -$54,805 | (n/a) | (n/a) | -$54,805 |
| 2023 | -$45,780 | (n/a) | (n/a) | -$45,780 |
| 2024 | -$15,105 (YM) +$21,220 (NQ) | -$43,120 | (folded above) | -$120,005 |

Cumulative running 7-year portfolio (RTH-only, 1 contract each):
**~-$501,385 total** (includes ES/YM gap years 2022-2023 where only NQ traded).

The portfolio curve is essentially monotone-down with a single positive year (2025).

## 7. Yearly return correlation (RTH per product)

Computed on years all three products traded (2020, 2021, 2024, 2025, 2026):

| | NQ | ES | YM |
|---|---|---|---|
| NQ | 1.00 | 0.07 | 0.31 |
| ES | 0.07 | 1.00 | 0.95 |
| YM | 0.31 | 0.95 | 1.00 |

ES and YM are highly correlated (0.95) — they move together. NQ is roughly uncorrelated with both. So a "diversified" 3-product portfolio actually concentrates in ES+YM exposure.

## 8. Provenance

**0 violations across all 17 (product, year) cells × 4 timeframes
× ~3.6M path checkpoints + ~340K regime/bar1 snapshots.**

The registry guarantees `last_<tf>_close_ts <= decision_ts` on
every snapshot row. Verified via `provenance_check()` on each cell.

## 9. Verdict

### Does V_A generalize to ES/YM?

**No.** V_A is structurally negative on ES and YM in every year tested (10 cells, all losing).

### Does V_A generalize across years on NQ?

**Partially.** NQ RTH:
- 2020-2023: 4 consecutive losing years (-$9 to -$22/trade)
- 2024-2025: 2 winning years (+$6 to +$18/trade)
- 2026: back to losing (-$17/trade)

NQ 2024-2025 was a localized profitable window in an otherwise loss-making strategy. The earlier "V_A NT-validated baseline" reports (PF 1.03 to 1.07) reflected only 2024-2025 + partial 2026 — they understated the strategy's true breadth.

### Per-product all-year RTH totals

- **ES**: -$236,000 across 13,630 trades (5 years) — PF 0.86
- **NQ**: -$149,280 across 21,691 trades (7 years) — PF 0.97
- **YM**: -$116,105 across 14,888 trades (5 years) — PF 0.91

### Recommendation: **DO NOT DEPLOY V_A as-is**

The strategy is structurally loss-making across products and years.
The 2024-2025 NQ window was a local pocket, not a stable edge.
ES and YM are **never** profitable.

The momentum-confirm regime-exit pattern works only within a
narrow regime that the strategy itself cannot detect.

Possible next directions (NOT in scope for this report):
- **Regime detection**: build a meta-filter that identifies when
  the V_A regime is "live" vs "dead" — only trade NQ during 2024-
  2025-like conditions
- **Different signal class**: V_A's edge is too narrow; a different
  entry signal may show broader generalization
- **Drop session-agnostic approach**: ETH is consistently worse;
  RTH-only at minimum eliminates 75% of losses

The path-diagnostics study (`PATH_DIAGNOSTICS_REPORT.md`) and the
exit-policy study (`NQ_EXIT_POLICY_MODEL_V1.md`) both confirm that
no exit overlay improves baseline economics — the issue is entry
selection, not exit management.

## Files

Per-cell raw data: `collectors/collector_v2/results/portfolio/<PRODUCT>_<YEAR>/`
- `trades.parquet`
- `snapshots.parquet` (regime_flip + bar1_check + path_checkpoint)
- `diag.json`

Manifest: `collectors/collector_v2/results/portfolio/MATRIX_MANIFEST.json`
Driver log: `collectors/collector_v2/results/portfolio/MATRIX_DRIVER.log`
