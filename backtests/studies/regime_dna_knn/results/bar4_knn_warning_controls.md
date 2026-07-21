# KNN Warning — Timing & Same-MFE Controls + Continuation Atlas

Warned trades: 6,477. Three hard attacks on the deterioration warning.

## Control 1 — Same-trades, random-bar (timing vs selection)
Exit the EXACT warned trades at the warning bar vs a random bar drawn from the warning-bar distribution truncated to each trade's own life (per-trade feasible). Warned-trades-only PnL.

| Exit timing | avg/tr (warned trades) | 2025 | 2026 |
| --- | --- | --- | --- |
| at WARNING bar | $-92 | $-86 | $-107 |
| at RANDOM bar (8-seed) | $-51 | $-48 | $-59 |

→ Warning-bar exit ≈ / does not beat random-bar exit on the same trades by $-41/tr → **SELECTION only** (these trades are bad, exit anytime).

## Control 2 — Same-MFE-so-far matched (beyond pullback severity)
Match warning vs healthy states on (bars_alive, mfe_so_far ±0.25, mae_so_far ±0.25). Matched warning states: 6,172 (bins with ≥10 each). If warning STILL predicts worse forward at the SAME visible weakness, it sees beyond pullback severity.

| metric (matched) | WARNING | HEALTHY | warn/healthy |
| --- | --- | --- | --- |
| P(new high ≤3) | 35% | 65% | 0.54 |
| P(flip ≤3) | 36% | 20% | 1.80 |
| remaining MFE (ATR) | 1.47 | 1.80 | 0.81 |

→ At the SAME mfe/mae/age, warning P(new high) is 0.54× healthy → **KNN sees BEYOND pullback severity** (the warning adds info the visible weakness does not).

## Warning Continuation Atlas — opportunity vs direction (warning states)
| horizon | remaining MFE | remaining MAE | new-high % | flip % |
| --- | --- | --- | --- | --- |
| 1 bar | 0.47 | 0.48 | 14% | 17% |
| 2 bar | 0.69 | 0.64 | 27% | 28% |
| 3 bar | 0.85 | 0.72 | 34% | 36% |
| 5 bar | 1.07 | 0.84 | 43% | 48% |
| 10 bar | 1.39 | 0.93 | 49% | 68% |

**Opportunity-vs-direction read:** at h=1, new-high% = **14%** (opportunity) while flip% = **17%** (direction). Opportunity collapses BEFORE direction reverses — the warning marks an OPPORTUNITY-STATE change, not a reversal. This is a genuinely different signal from prior direction-focused studies.

## Verdict

Timing skill: NO (selection only) (warn-bar $-92 vs random-bar $-51). Beyond-pullback-severity: YES (same-mfe warning new-high 0.54× healthy).
> [!TIP]
> **The warning carries information BEYOND visible pullback severity** — matched on mfe/mae/age, warning states still die faster (fewer new highs, sooner flip). KNN is functioning as an **opportunity-state detector**, and opportunity collapses before direction reverses. This is the distinct thing the project has been chasing. Now scope order-flow ONLY as the exit/ignore arbiter on confirmed-warning states.