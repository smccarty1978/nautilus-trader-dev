# Post-Confirmation 5m Context × Forward Opportunity — Report

**Verdict:** `C3_EXPLAINED_BY_CONFIRMATION_QUALITY`. 9/9 gates pass.
Full numeric facts: `results/summary.json`.

---

## Primary table (excerpt, TRANSITION population)

| metric | WITH_5M (n=629) | AGAINST_5M (n=4,027) |
|---|---:|---:|
| confirm return median | 1.018 ATR | 0.824 ATR |
| confirm MFE median | 1.212 ATR | 1.011 ATR |
| remaining MFE @300s | 0.557 ATR | 0.369 ATR |
| terminal return | 0.352 ATR | 0.037 ATR |
| terminal giveback | 2.033 ATR | 1.998 ATR |

**Reproduced under both population definitions, conclusions unchanged**
(SPEC section 4 Phase 0's explicit requirement): the STABLE_STATE definition
(WITH→WITH n=623 / AGAINST→AGAINST n=4,018, excluding the two tiny
transition cells) gives remaining-MFE-@300s 0.560 vs 0.365 and terminal
return 0.349 vs 0.037 — indistinguishable from the transition-inclusive
numbers above. The rare transition cells (WITH→AGAINST n=9, AGAINST→WITH
n=6) do not drive the result.

## Opportunity capture curve

| | WITH_5M | AGAINST_5M |
|---|---:|---:|
| time to 25% captured | 45s (87% coverage) | 30s (84% coverage) |
| time to 50% captured | 90s (80% coverage) | 90s (77% coverage) |
| time to 75% captured | 135s (71% coverage) | 120s (68% coverage) |
| time to 90% captured | 135s (65% coverage) | 135s (63% coverage) |

WITH_5M is not meaningfully slower to capture its post-confirm opportunity
— the timing gap at the 50% mark is **zero seconds**. AGAINST_5M reaches
75% slightly faster (120s vs 135s), the opposite of what would support "give
AGAINST_5M less time." Coverage (the % of trades that ever reach a given
threshold within the dense ≤600s grid) runs 3-4 points higher for WITH_5M
at every threshold, consistent with WITH_5M's larger eventual MFE pool, not
with a materially different *pace*.

## Phase 12 — confirmation quality control (the decisive test)

WITH_5M trades arrive at confirmation stronger (median return 1.018 vs.
0.824 ATR). Stratifying on 8 confirmation-time-only variables (side, year,
confirm-MFE/MAE/return/speed buckets, `arm_score` quartile, time-of-day) and
re-evaluating 8 outcome metrics via exposure-weighted delta + trade-clustered
bootstrap CI:

| outcome metric | raw Δ | stratified Δ | 95% CI | excludes zero? |
|---|---:|---:|---|:---:|
| incremental MFE @300s | +0.017 | −0.003 | [−0.18, +0.19] | no |
| incremental MFE @600s | −0.031 | −0.109 | [−0.54, +0.30] | no |
| remaining MFE @300s | +0.195 | +0.243 | [−0.15, +0.67] | no |
| remaining MFE @600s | −0.038 | +0.079 | [−0.41, +0.60] | no |
| continuation value @300s | +0.061 | +0.179 | [−0.21, +0.57] | no |
| continuation value @600s | −0.056 | +0.055 | [−0.46, +0.57] | no |
| new-extreme probability @300s | +0.034 | +0.038 | [−0.01, +0.08] | no (barely) |
| terminal return | +0.168 | +0.160 | [−0.18, +0.48] | no |

**0 of 8 metrics survive stratification.** Every stratified delta's CI
includes zero. The 8-way stratification is genuinely thin (only 189 of
2,614 cells have both WITH and AGAINST trades present at the +300s
landmark, 94 of 1,837 at +600s — WITH_5M is only 13.5% of the confirming
population), which widens every CI, but that thinness is a property of the
data, not a methodology choice that was loosened to force a null. The
correct reading is not "we lack power to know" but "the raw pooled
advantage cannot be attributed to 5m alignment with any confidence once the
comparison is restricted to similarly-situated trades."

## Year / side stability

Neither required for the verdict (C3 fires regardless), but checked:
`years_stable=False`, `no_side_inversion=False` — the +300s incremental-MFE
WITH/AGAINST delta does not hold a consistent sign across all years or both
sides. This reinforces C3 rather than contradicting it.

## Bottom line

Per SPEC section 4 Phase 12's own framing: **does 5m alignment add
information after accounting for how strong the trade already looks at
confirmation? No.** The apparent post-confirmation advantage M2 found
(+0.33 ATR terminal return, +5.6pp on P(MFE≥3ATR)) is a real pooled pattern,
but Phase 12 finds no metric where it survives stratification on
confirmation-time-only variables, and the capture-curve timing gap that
would be needed for C1 (WITH taking meaningfully longer to realize its
opportunity) does not exist — the 50%-capture time is identical (90s vs
90s) between groups. This closes the 5m branch on the timing question: 5m
alignment does not identify a faster-harvest population (AGAINST_5M) or a
population that deserves more time to run (WITH_5M). The M2-era
post-confirmation difference is better explained as another representation
of the trade already being stronger at confirmation — return, MFE, and MAE
already known at the confirmation instant — not as a causal effect of the
5-minute regime itself.
