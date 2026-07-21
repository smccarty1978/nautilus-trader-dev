# Trend Quality Emergence Curve

Capsule: 146,831 regimes (MAR-duration-skewed; fast-dying regimes under-represented).
IS HardStall hC thresholds: p33=0.044, p67=0.304

**Bar-mode caveat**: all entry simulations use O[:,k] entry / hold-to-flip exit, 1 lot, $4.06 commission. Expect ~$9-18/tr overstatement vs tick-mode. Use as opportunity landscape, not deployment-grade claim.

## A. Predictive Quality (hC AUC and decile spread by regime age)

hC from walk-forward KNN mapping (IS-only training, causally validated).
AUC computed on OOS 2025+2026 regimes alive at that age.
Top/bot decile = top/bottom 10% hC; rem-MFE = avg remaining MFE in ATR.

| Age | n alive | % of pop | AUC hC→runner | AUC hC→bad | top-dec rem-MFE | bot-dec rem-MFE | spread |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Bar 4 | 124,292 | 85% | 0.638 | 0.619 | 3.55 | 1.39 | 2.15 |
| Bar 6 | 104,298 | 71% | 0.704 | 0.665 | 4.30 | 1.24 | 3.05 |
| Bar 8 | 86,992 | 59% | 0.715 | 0.731 | 4.58 | 1.43 | 3.15 |
| Bar 10 | 72,934 | 50% | 0.705 | n/a | 5.01 | 1.57 | 3.44 |
| Bar 12 | 61,224 | 42% | 0.690 | n/a | 5.52 | 1.74 | 3.78 |
| Bar 15 | 46,854 | 32% | 0.680 | n/a | 6.18 | 2.53 | 3.65 |
| Bar 20 | 29,928 | 20% | 0.670 | n/a | 6.77 | 3.44 | 3.33 |

## B. Opportunity Decay (bar-4 entry baseline; averaged over surviving population)

mfe_consumed = max favourable excursion from bar-4 entry through bar k.
mfe_remaining = max favourable excursion from bar k+1 to flip.
mfe_total = max over all bars 4..flip per regime.
% remaining = avg(remaining) / avg(total).

| Age | n alive | mfe_total (ATR) | consumed (ATR) | remaining (ATR) | % remaining |
| --- | ---: | ---: | ---: | ---: | ---: |
| Bar 4 | 124,292 | 2.23 | 0.50 | 2.16 | 97% |
| Bar 6 | 104,298 | 2.61 | 1.04 | 2.43 | 93% |
| Bar 8 | 86,992 | 3.01 | 1.49 | 2.74 | 91% |
| Bar 10 | 72,934 | 3.41 | 1.92 | 3.05 | 90% |
| Bar 12 | 61,224 | 3.80 | 2.35 | 3.37 | 89% |
| Bar 15 | 46,854 | 4.41 | 2.98 | 3.90 | 88% |
| Bar 20 | 29,928 | 5.44 | 4.02 | 4.79 | 88% |

### Opportunity decay — OOS only (2025+2026)

| Age | n alive OOS | mfe_total | consumed | remaining | % remaining |
| --- | ---: | ---: | ---: | ---: | ---: |
| Bar 4 | 30,730 | 2.26 | 0.50 | 2.20 | 97% |
| Bar 6 | 25,873 | 2.64 | 1.03 | 2.46 | 93% |
| Bar 8 | 21,646 | 3.04 | 1.48 | 2.77 | 91% |
| Bar 10 | 18,200 | 3.43 | 1.92 | 3.08 | 90% |
| Bar 12 | 15,307 | 3.83 | 2.34 | 3.41 | 89% |
| Bar 15 | 11,736 | 4.44 | 2.97 | 3.94 | 89% |
| Bar 20 | 7,453 | 5.51 | 4.03 | 4.85 | 88% |

## C. Pullback State Analysis (OOS 2025+2026)

5 states: Healthy | HH-HardStall (stall bars with hC ≥ p67) | MH-HardStall (p33-p67) | LH-HardStall (<p33) | DETER.
reignition = P(new MFE peak within 5 bars past this age).
Entry sim (pnl†): causal — state observed at bar k close, enter bar k+1 open, 1 lot bar-mode.

### C.1  Bar 4 state snapshot

| State | n | bad% | runner% | rem-MFE (ATR) | pnl $/tr† | P(flip≤3) | P(flip≤5) | P(reignite) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Healthy | 15,579 | 33% | 48% | 2.94 | $-10 | 15% | 28% | 81% |
| LH-HardStall | 8 | 12% | 62% | 1.90 | $-543 | 12% | 12% | 38% |
| DETER | 12,604 | 50% | 27% | 1.73 | $-6 | 33% | 45% | 60% |
| **ALL** | 30,730 | 45% | 36% | 2.20 | $-9 | 30% | 41% | 66% |
†pnl = causal: enter bar k+1 open (state observed at bar k close), exit hold-to-flip. Bar-mode 1-lot.

  *2025: n=23,098  $/tr=$-3  runner=36%  bad=45%*
  *2026: n=7,632  $/tr=$-25  runner=35%  bad=46%*

### C.2  Bar 8 state snapshot

| State | n | bad% | runner% | rem-MFE (ATR) | pnl $/tr† | P(flip≤3) | P(flip≤5) | P(reignite) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Healthy | 3,609 | 5% | 71% | 3.95 | $-7 | 11% | 23% | 83% |
| HH-HardStall | 5,240 | 7% | 72% | 4.19 | $-12 | 13% | 25% | 69% |
| MH-HardStall | 4,303 | 15% | 54% | 2.88 | $+1 | 23% | 36% | 51% |
| LH-HardStall | 3,544 | 29% | 40% | 2.02 | $-13 | 38% | 51% | 31% |
| DETER | 3,178 | 28% | 21% | 1.33 | $-4 | 36% | 49% | 36% |
| **ALL** | 21,646 | 23% | 50% | 2.77 | $-7 | 29% | 41% | 51% |
†pnl = causal: enter bar k+1 open (state observed at bar k close), exit hold-to-flip. Bar-mode 1-lot.

  *2025: n=16,267  $/tr=$-1  runner=51%  bad=22%*
  *2026: n=5,379  $/tr=$-25  runner=49%  bad=23%*

### C.3  Bar 12 state snapshot

| State | n | bad% | runner% | rem-MFE (ATR) | pnl $/tr† | P(flip≤3) | P(flip≤5) | P(reignite) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Healthy | 1,564 | 0% | 82% | 4.90 | $-15 | 10% | 23% | 83% |
| HH-HardStall | 3,897 | 0% | 85% | 5.23 | $-12 | 13% | 25% | 70% |
| MH-HardStall | 3,655 | 0% | 69% | 3.58 | $+0 | 21% | 35% | 50% |
| LH-HardStall | 4,322 | 0% | 57% | 2.42 | $-9 | 38% | 50% | 28% |
| DETER | 536 | 0% | 19% | 1.14 | $-5 | 35% | 50% | 29% |
| **ALL** | 15,307 | 0% | 66% | 3.41 | $-8 | 30% | 42% | 47% |
†pnl = causal: enter bar k+1 open (state observed at bar k close), exit hold-to-flip. Bar-mode 1-lot.

  *2025: n=11,530  $/tr=$-1  runner=66%  bad=0%*
  *2026: n=3,777  $/tr=$-31  runner=65%  bad=0%*

### C.4  Bar 20 state snapshot

| State | n | bad% | runner% | rem-MFE (ATR) | pnl $/tr† | P(flip≤3) | P(flip≤5) | P(reignite) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Healthy | 359 | 0% | 96% | 5.99 | $-33 | 8% | 19% | 86% |
| HH-HardStall | 1,813 | 0% | 96% | 7.21 | $-2 | 12% | 25% | 72% |
| MH-HardStall | 2,017 | 0% | 88% | 5.52 | $+2 | 22% | 34% | 49% |
| LH-HardStall | 2,583 | 0% | 81% | 3.80 | $-7 | 36% | 47% | 27% |
| **ALL** | 7,453 | 0% | 87% | 4.85 | $-5 | 31% | 42% | 44% |
†pnl = causal: enter bar k+1 open (state observed at bar k close), exit hold-to-flip. Bar-mode 1-lot.

  *2025: n=5,622  $/tr=$+1  runner=87%  bad=0%*
  *2026: n=1,831  $/tr=$-21  runner=86%  bad=0%*

## D. Entry Simulation (bar-mode, 1 lot, OOS 2025/2026 separate)

Age entries: enter at O[:,k] (bar k open). No state conditioning.
State entries: enter at O[:,k_state+1] (bar after state observed).
Survivorship: each row's population is conditioned on regime surviving to entry bar.

| Entry | 2025 n | 2025 $/tr | 2026 n | 2026 $/tr | both>0? |
| --- | ---: | ---: | ---: | ---: | :---: |
| bar-4 baseline (bar-mode) | 23,098 | $-1 | 7,632 | $-26 | no |
| bar-4 NT fills (per contract) | 23,234 | $-9.4 | 7,763 | $-31.7 | no |
| bar-6 age entry | 19,444 | $-2 | 6,429 | $-23 | no |
| bar-8 age entry | 16,267 | $-1 | 5,379 | $-25 | no |
| bar-10 age entry | 13,678 | $-2 | 4,522 | $-26 | no |
| bar-12 age entry | 11,530 | $-2 | 3,777 | $-28 | no |
| bar-15 age entry | 8,858 | $-1 | 2,878 | $-30 | no |
| bar-20 age entry | 5,622 | $+2 | 1,831 | $-28 | no |
| | | | | | |
| first HH-HardStall (enter next bar) | 12,702 | $-2 | 4,164 | $-26 | no |
  *(avg first-HH-HS bar: 7.5; 37% of regimes have a HH-HardStall before bar 29)*
| first HH-HardStall + slope>0 | 8,832 | $-3 | 2,859 | $-22 | no |

### State-conditioned entry at bar 8 (enter bar 8 open when in state at bar 7 close)

| State at bar 7 | n OOS | 2025 $/tr | 2026 $/tr | both>0? |
| --- | ---: | ---: | ---: | :---: |
| Healthy | 4,704 | $-4 | $-23 | no |
| HH-HardStall | 5,440 | $-2 | $-24 | no |
| MH-HardStall | 4,426 | $+4 | $-36 | no |
| LH-HardStall | 2,586 | $-6 | $-32 | no |
| DETER | 4,490 | $-0 | $-14 | no |
| ALL | 21,646 | $-1 | $-25 | no |

## E. 5-Point Conclusion

Full-pop avg total MFE (bar-4 entry, OOS): **2.26 ATR**  | NT per-contract baseline: 2025 $-9/tr, 2026 $-32/tr

### 1. Earliest age where trend quality is statistically observable

**Bar 6** — AUC jumps from 0.638 (bar 4) to 0.704 at bar 6 for runner prediction. By bar 8 runner AUC = 0.715, bad AUC = 0.731. Top-vs-bottom decile MFE spread reaches 3.1 ATR at bar 8 (vs 2.2 at bar 4). State-level composition at bar 8 is dramatic: Healthy/HH-HardStall = 71-72% runner, 5-7% bad; LH-HardStall/DETER = 21-40% runner, 28-29% bad. **Statistical separability: bar 6. Practically strong: bar 8.**

### 2. Earliest age where trend quality is economically useful

**Never, based on this data.** Every unconditional age entry (bars 6/8/10/12/15/20) is negative in 2026 (−$14 to −$30/tr). Every state-conditioned bar-8 entry is negative in 2026 (−$14 to −$36/tr). First HH-HardStall entry: 2025 −$2, 2026 −$26. Even at bar 20 (87% runner rate, 0% bad): 2025 +$2, 2026 −$28. **Composition is informative. Expectancy is not.**

### 3. Remaining opportunity at the statistically observable age (bar 8)

At bar 8 (OOS): avg remaining MFE = **2.77 ATR** (122% of total MFE). Surviving population = **70%** of bar-4-alive regimes — positively selected (longer/stronger regimes). At bar 12: 3.41 ATR (151%) — 50% alive. At bar 20: 4.85 ATR (215%) — 24% alive. Opportunity does NOT decay — it appears to grow because survivorship selects stronger regimes. But the remaining-MFE is the MAX excursion, not the expected hold-to-flip PnL. The actual expectancy (hold-to-flip from entry) stays flat near −$25 regardless of entry age.

### 4. Whether a pullback-entry framework is more viable than regime-birth entry

**No — the composition gain is real; the expectancy gain is not.** At bar 8, HH-HardStall state has: bad=7%, runner=72%, rem-MFE=4.19 ATR. vs the bar-4 full population: bad=45%, runner=36%, rem-MFE=2.20 ATR. Dramatic composition improvement. But the causal bar-8 entry (state seen at bar 7, enter bar 8 open) for HH-HardStall regimes: 2025 −$2/tr, 2026 −$24/tr — essentially identical to unconditional bar-8 entry (−$1/−$25). The state separation exists in future-outcome space, not in the tradeable next-bar direction. **Pullback framework: composition artifact confirmed, same conclusion as [[regime_health_decay_no_leadtime_1m]].**

### 5. Whether the trend-quality thesis is monetizable after costs

**NO. Trend quality is measurable but not monetizable with OHLCV inputs.** Summary: (a) hC separates regimes well (AUC 0.71-0.73) — real signal. (b) High-quality regimes genuinely have more remaining MFE and higher runner rates. (c) But entering any of them at any age from 4 to 20 yields the same approximate expectancy: roughly −$1 to −$30/tr depending on year, regardless of state, timing, or composition filter. The pattern is identical to the earlier finding that pullback severity predicts recovery odds but is monetarily inert — price has already incorporated the quality signal into the current close. **The opportunity MFE is real; capturing it requires a non-OHLCV trigger (order flow, book, footprint) to identify the favorable resolution direction within the already-established trend.** Without that, trend quality is a descriptive feature, not a tradeable edge.

---

**OVERALL VERDICT: Trend-quality thesis CLOSED for OHLCV-only inputs.** This study represents the final angle of the regime-flip signal class: regime birth (V_A), bar-3 prediction (Model B / BadShort KNN), per-bar health monitoring (hC KNN), pullback states (HH-HardStall), and now delayed entry at each regime age. All angles confirm the same ceiling. Next viable direction: order-flow / book data on this same regime population.