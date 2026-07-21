# Regime Health Decay — Lead-Time Diagnostic

OOS 2025-26 Bar-4 survivors: **30,730**. Health_k = P(reach +2 ATR MFE before flip | features thru bar k), walk-forward (IS 2021-24 pooled per-bar → OOS). Features strictly causal (bars 0..k); target is regime-level forward outcome.

Cohorts: **WIN2** reach ≥+2 ATR (35.6%) · **LOSE** hold-to-flip net<0 (70.1%) · **FAIL** MFE<1 ATR (43.7%).

## 1. Flip-aligned health curve — mean Health at j bars BEFORE the opposite flip
The decisive view. Lead time exists only if FAIL/LOSE health is already low while WIN2 is still high, several bars before the flip (j large). If all cohorts only collapse at j=0..1, the score OBSERVES the flip, it does not predict it.

| bars before flip (j) | WIN2 | LOSE | FAIL | all |
| --- | --- | --- | --- | --- |
| 0 | 94 | 7 | 4 | 12 |
| 1 | 96 | 21 | 16 | 31 |
| 2 | 96 | 27 | 19 | 42 |
| 3 | 96 | 29 | 21 | 50 |
| 4 | 95 | 31 | 21 | 55 |
| 5 | 95 | 31 | 21 | 58 |
| 7 | 91 | 31 | 22 | 61 |
| 10 | 86 | 30 | 21 | 64 |

## 2. Health peak location & collapse (per cohort)
peak bar = argmax health; collapse bar = first bar after peak with health<50; lead = flip_bar − collapse_bar (bars of warning before the flip).

| Cohort | n | median peak health | median peak bar | median collapse→flip lead | % no collapse pre-flip |
| --- | --- | --- | --- | --- | --- |
| WIN2 | 10,950 | 98 | 17 | 2 | 84% |
| LOSE | 21,533 | 34 | 5 | 2 | 11% |
| FAIL | 13,442 | 24 | 5 | 2 | 1% |

## 3. First-deterioration lead time (first bar Health<θ → flip), median bars
Median (bars) from the first time health drops below θ to the opposite flip. Higher = more warning. Also % of cohort that EVER drops below θ before the flip (coverage).

| θ | WIN2 lead (cov) | LOSE lead (cov) | FAIL lead (cov) |
| --- | --- | --- | --- |
| 70 | 18 (98%) | 4 (100%) | 3 (100%) |
| 60 | 18 (96%) | 4 (99%) | 3 (100%) |
| 50 | 18 (92%) | 4 (99%) | 3 (100%) |
| 40 | 18 (86%) | 4 (97%) | 2 (100%) |

## 4. Exit-rule separation (diagnostic): 'exit at first Health<θ'
For WIN2: % that would be exited BEFORE reaching their +2 ATR peak (premature kill = bad). For LOSE: median lead the exit gives before the flip (good). A usable engine needs LOW premature-kill on winners AND positive lead on losers.

| θ | WIN2 premature-exit % | LOSE median lead (bars) |
| --- | --- | --- |
| 70 | 94% | 4 |
| 60 | 92% | 4 |
| 50 | 89% | 4 |
| 40 | 82% | 4 |

## Verdict — does the health score give LEAD TIME (predict) or just OBSERVE?

j=5 before flip: WIN2 95 vs FAIL 21 (gap +73). LOSE median PEAK health **34** (were they ever healthy?). WIN2 flip-without-collapse **84%**. Exit-when-health<50 kills **89%** of winners before +2 ATR.
> [!WARNING]
> **NOT lead time — the separation is CONCURRENT, not LEADING.** The big j=5 gap is the MFE-tautology: health reads excursion-so-far, so winners (already moved) read high and failures read low — but failures are **born unhealthy** (LOSE median peak only 34, peaked ~bar 5), not decayed from health. Winners **flip abruptly from full health** (84% show no pre-collapse; collapse→flip lead is ~2 bars for ALL cohorts — no differential warning). An exit-on-unhealthy rule would prematurely kill **89% of winners**. So 1m OHLCV health confirms the break as it happens; it does not precede it. Consistent with rejection-power D6 (failures already resolving by the decision bar).
> 
> **The door this leaves OPEN (the user's instinct):** at 1m the flip is ABRUPT — winners flip from health ~95 with no 1m decay phase. Any genuine deterioration signature would therefore have to live in the **final-minute 5-SECOND microstructure**, which 1m bars structurally cannot resolve. That — a 5s micro-health layer measuring last-30-60s deterioration on still-healthy 1m regimes — is the motivated next test, NOT another 1m health model.