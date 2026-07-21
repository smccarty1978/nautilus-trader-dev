# Raw-Flip / Bar1 Survivor & Add-On Expectancy Study

V0_regime probe. NQ `NQ.v.0` 2021-2024 warmed. A=110,507, B=47,068. Forward economics measured PURELY from each survivor state forward to the regime exit (no pre-state credit). Costs: progress adds = limit (0 entry slip); time/path adds = market (0.5 tick); exit 0.5 tick; $5 RT/contract.

## 1. Forward expectancy table (ranked by NET future EV)

### Forward expectancy by survivor state — Population A (n=110,507)

| Survivor State | Count | % Orig | Future EV gross $ | Future EV NET $ | Reach+1 | Reach+2 | Reach+3 | Top 10% $ | Bottom 10% $ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| reach_0p25 | 94,837 | 86% | +0.9 | -6.6 | 62% | 40% | 27% | +799 | -484 |
| reach_0p50 | 83,792 | 76% | +0.0 | -7.5 | 63% | 41% | 28% | +814 | -500 |
| reach_1p50 | 52,740 | 48% | -0.5 | -8.0 | 66% | 45% | 31% | +866 | -546 |
| reach_1p00 | 65,966 | 60% | -0.5 | -8.0 | 65% | 43% | 30% | +842 | -528 |
| reach_0p75 | 74,235 | 67% | -0.7 | -8.2 | 64% | 42% | 29% | +828 | -517 |
| alive_180 | 93,550 | 85% | -0.9 | -10.9 | 55% | 36% | 24% | +731 | -427 |
| no5s_opp_90 | 20,797 | 19% | -1.0 | -11.0 | 62% | 42% | 28% | +831 | -529 |
| alive_90 | 108,230 | 98% | -1.4 | -11.4 | 55% | 35% | 23% | +717 | -429 |
| alive_120 | 101,515 | 92% | -1.5 | -11.5 | 56% | 36% | 24% | +730 | -429 |
| mfe_gt_mae | 53,156 | 48% | -2.3 | -12.3 | 60% | 40% | 27% | +793 | -486 |
| alive_60 | 108,271 | 98% | -2.4 | -12.4 | 57% | 36% | 24% | +737 | -443 |
| alive_30 | 110,471 | 100% | -2.6 | -12.6 | 57% | 37% | 25% | +745 | -451 |
| pos_path_eff | 51,415 | 47% | -2.7 | -12.7 | 61% | 40% | 27% | +801 | -497 |
| gate_pass | 50,532 | 46% | -3.4 | -13.4 | 61% | 40% | 27% | +771 | -487 |

### Forward expectancy by survivor state — Population B (n=47,068)

| Survivor State | Count | % Orig | Future EV gross $ | Future EV NET $ | Reach+1 | Reach+2 | Reach+3 | Top 10% $ | Bottom 10% $ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| no5s_opp_90 | 6,517 | 14% | +11.0 | +1.0 | 65% | 44% | 30% | +970 | -562 |
| reach_0p25 | 40,614 | 86% | +1.7 | -5.8 | 64% | 42% | 28% | +847 | -518 |
| reach_0p50 | 36,100 | 77% | +1.4 | -6.1 | 64% | 43% | 29% | +860 | -528 |
| reach_0p75 | 32,215 | 68% | +1.0 | -6.5 | 65% | 43% | 30% | +871 | -538 |
| reach_1p00 | 28,769 | 61% | +0.6 | -6.9 | 66% | 44% | 30% | +883 | -552 |
| reach_1p50 | 23,262 | 49% | -1.2 | -8.7 | 66% | 45% | 31% | +901 | -574 |
| pos_path_eff | 21,622 | 46% | +0.6 | -9.4 | 63% | 42% | 28% | +866 | -530 |
| alive_90 | 46,346 | 98% | -0.5 | -10.5 | 57% | 37% | 25% | +777 | -463 |
| alive_120 | 44,235 | 94% | -0.8 | -10.8 | 57% | 37% | 25% | +775 | -467 |
| gate_pass | 20,370 | 43% | -0.8 | -10.8 | 63% | 42% | 28% | +834 | -519 |
| alive_180 | 41,479 | 88% | -0.9 | -10.9 | 57% | 37% | 24% | +777 | -459 |
| alive_30 | 47,065 | 100% | -1.8 | -11.8 | 60% | 39% | 26% | +799 | -489 |
| alive_60 | 46,350 | 98% | -2.1 | -12.1 | 59% | 38% | 25% | +790 | -486 |
| mfe_gt_mae | 21,908 | 47% | -2.3 | -12.3 | 62% | 41% | 28% | +834 | -521 |

## 2. Add-on simulation (3 risk variants)

### Add-on simulation — Population A (probe=1 V0 contract; add=1 contract)

Net $/trade is over ALL entries (add only on reached trades). Fixed-2 baseline (2 probes) = -18.2 $/tr, PF 0.92.

| Add Rule | Variant | add net/add $ | TOTAL net/trade $ | PF | win% | avg contracts | max DD |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A_+0.5ATR | indep stop -0.75 | -5.7 | -13.4 | 0.91 | 26% | 1.76 | -1,543,690 |
| A_+0.5ATR | protect@regime | -7.5 | -14.7 | 0.92 | 28% | 1.76 | -1,689,706 |
| A_+0.5ATR | BE | -5.7 | -13.4 | 0.88 | 30% | 1.76 | -1,497,033 |
| B_+1.0ATR | indep stop -0.75 | -7.8 | -13.7 | 0.90 | 24% | 1.60 | -1,564,202 |
| B_+1.0ATR | protect@regime | -8.0 | -13.9 | 0.92 | 25% | 1.60 | -1,595,951 |
| B_+1.0ATR | BE | -5.9 | -12.6 | 0.88 | 30% | 1.60 | -1,413,305 |
| C_gate_pass | indep stop -0.75 | -11.8 | -14.5 | 0.89 | 28% | 1.46 | -1,644,353 |
| C_gate_pass | protect@regime | -13.4 | -15.2 | 0.90 | 29% | 1.46 | -1,743,825 |
| C_gate_pass | BE | -10.0 | -13.7 | 0.88 | 30% | 1.46 | -1,525,375 |
| D_no5s_opp_90 | indep stop -0.75 | -11.0 | -11.2 | 0.91 | 29% | 1.19 | -1,268,787 |
| D_no5s_opp_90 | protect@regime | -11.0 | -11.2 | 0.91 | 30% | 1.19 | -1,273,865 |
| D_no5s_opp_90 | BE | -10.0 | -11.0 | 0.90 | 31% | 1.19 | -1,238,575 |
| E_mfe_gt_mae | indep stop -0.75 | -11.0 | -14.4 | 0.89 | 28% | 1.48 | -1,623,341 |
| E_mfe_gt_mae | protect@regime | -12.3 | -15.0 | 0.91 | 29% | 1.48 | -1,706,970 |
| E_mfe_gt_mae | BE | -10.0 | -13.9 | 0.87 | 30% | 1.48 | -1,550,455 |

### Add-on simulation — Population B (probe=1 V0 contract; add=1 contract)

Net $/trade is over ALL entries (add only on reached trades). Fixed-2 baseline (2 probes) = -20.9 $/tr, PF 0.91.

| Add Rule | Variant | add net/add $ | TOTAL net/trade $ | PF | win% | avg contracts | max DD |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A_+0.5ATR | indep stop -0.75 | -6.3 | -15.3 | 0.91 | 26% | 1.77 | -811,569 |
| A_+0.5ATR | protect@regime | -6.1 | -15.2 | 0.93 | 29% | 1.77 | -829,332 |
| A_+0.5ATR | BE | -6.4 | -15.4 | 0.87 | 31% | 1.77 | -761,489 |
| B_+1.0ATR | indep stop -0.75 | -9.7 | -16.4 | 0.89 | 24% | 1.61 | -845,104 |
| B_+1.0ATR | protect@regime | -6.9 | -14.7 | 0.92 | 26% | 1.61 | -802,122 |
| B_+1.0ATR | BE | -6.4 | -14.4 | 0.88 | 31% | 1.61 | -720,945 |
| C_gate_pass | indep stop -0.75 | -13.1 | -16.1 | 0.89 | 29% | 1.43 | -816,660 |
| C_gate_pass | protect@regime | -10.8 | -15.1 | 0.91 | 30% | 1.43 | -806,235 |
| C_gate_pass | BE | -10.0 | -14.8 | 0.88 | 32% | 1.43 | -737,678 |
| D_no5s_opp_90 | indep stop -0.75 | -5.4 | -11.2 | 0.91 | 31% | 1.14 | -592,491 |
| D_no5s_opp_90 | protect@regime | +1.0 | -10.3 | 0.92 | 31% | 1.14 | -563,620 |
| D_no5s_opp_90 | BE | -10.0 | -11.8 | 0.90 | 32% | 1.14 | -609,178 |
| E_mfe_gt_mae | indep stop -0.75 | -13.1 | -16.6 | 0.89 | 29% | 1.47 | -837,299 |
| E_mfe_gt_mae | protect@regime | -12.3 | -16.2 | 0.91 | 30% | 1.47 | -852,808 |
| E_mfe_gt_mae | BE | -10.0 | -15.1 | 0.87 | 32% | 1.47 | -752,228 |

## 3. Validation questions

**Q1 — Any survivor state with positive forward expectancy (gross)?**
A: 2/14 states gross-positive; best = reach_0p25 (+0.9 $). YES.

**Q2 — Positive forward expectancy AFTER realistic costs?**
A: 0/14 states net-positive; best = reach_0p25 (-6.6 $). B: 1/14; best = no5s_opp_90 (+1.0 $). YES.

**Q3 — Is the ADD-ON contract itself profitable (net, per added contract)?**
Best net add (regime exit) A = reach_0p25 -6.6 $/add. NO — every add contract is net-negative.

**Q4 — Does `gate_pass` create a profitable add location?**
A net add = -13.4 $ (reach2 40%); B net add = -10.8 $ (reach2 42%). NO.

**Q5 — Does `no5s_opp_90` create a profitable add location?**
A net add = -11.0 $ (reach2 42%); B net add = +1.0 $ (reach2 44%). YES.

**Q6 — Raw (A) or Bar1 (B) superior for probe-and-add?**
Best net-add state: A reach_0p25 -6.6 vs B no5s_opp_90 +1.0. Probe net/tr: A -9.1, B -10.5.

**Q7 — Can a 1-contract probe + conditional add beat fixed-size entry?**
See add-on table: compare TOTAL net/trade & PF vs the Fixed-2 baseline (2×probe). A probe net/tr=-9.1 (fixed-2=-18.2).

## 4. Success criterion
At least one survivor state shows POSITIVE forward EV after costs. Probe-and-pyramid is a live research direction — see add-on table for whether the added contract nets positive per rule/variant.


## 5. VERDICT — Survivor / Add-On forward expectancy

### 27 of 28 state×population cells are net-negative after costs. The branch is effectively closed.

**Population A (raw flips): 0/14 states net-positive.** Best is reach_0p25 at
−$6.6/add. Gross is barely positive for only the two earliest progress states
(reach_0p25 +$0.9, reach_0p50 +$0.0) and negative for all else; costs sink
everything to −$6.6 to −$13.4. **The behavioral states are the WORST, not the
best** (gate_pass −$13.4, pos_path_eff −$12.7, mfe_gt_mae −$12.3). The 7-day
smoke's "gate_pass +$49" was pure trending-January noise.

**Population B (bar1): 1/14 net-positive** — no5s_opp_90 at **+$1.0/add** (gross
+$11.0). This is the only positive cell in the study, and it does NOT survive
scrutiny:
- **Not robust:** per-year +$1.7 / +$12.2 / **−$21.5** / +$12.2 (2021-24).
  3/4 years positive, but the one loss year (2023) is ~2× the gain years —
  classic "good on average, one disastrous year."
- **Direction-dependent:** short +$3.9, long −$1.8. The whisper of edge is short-only.
- **1 of 28 cells** (multiple comparisons — ~1 marginal positive expected by chance).
- **Pre-spread-reality:** uses 0.5-tick exit; real NQ spread likely erases +$1.0.

### Critical insight (Q4): a good EXIT location is NOT a good ADD location
The prove-it gate is valuable for CUTTING probe losers at +60s — but adding size
after it passes is −$13.4/add (A) / −$10.8 (B). Conditioning on "net≥0 at
+60s" selects trades whose FORWARD path is still negative. Surviving initial
adversity does not imply forward continuation.

### Q-answers
- **Q1** gross-positive states? A few, barely (reach_0p25 +$0.9 A; several small + on B).
- **Q2** net-positive after costs? A: 0/14. B: 1/14 (no5s_opp_90 +$1.0, non-robust).
- **Q3** is the added contract profitable? Essentially NO — every add net-negative
  except the one marginal/non-robust B cell.
- **Q4** gate_pass profitable add? NO (−$13.4 A / −$10.8 B).
- **Q5** no5s_opp_90 profitable add? Marginally on B (+$1.0) but short-biased &
  fails 2023; on A NO (−$11.0, 0/4 yrs).
- **Q6** A vs B? B slightly better for adds (the one + cell is B), consistent with
  bar1 quality — but A has the less-negative probe (−$9.1 vs −$10.5).
- **Q7** probe+add beat fixed-size? Only mechanically — probe+add total/tr (−$10
  to −$15) beats fixed-2 (−$18 to −$21) because it deploys LESS size (~1.1-1.8
  vs 2.0 contracts) on a losing system. Per-contract it is ~the same negative.
  The added contract is not a positive-EV trade.

### Success criterion
Strictly, one state (Bar1 + no-5s-opposed-90s) shows +$1.0 forward EV after the
modeled costs — but it is short-biased, fails 2023 by −$21.5, is 1/28 cells, and
is below spread-reality. This is noise-level, not a deployable edge. **The market
does not reveal enough post-entry information to make additional size reliably
profitable on this signal class.** The probe-and-pyramid branch is closed. The
only flicker is the clean-trend (no-5s-opposed) short on Bar1 — not recommended
for pursuit given the 2023 failure and multiple-comparison context.
