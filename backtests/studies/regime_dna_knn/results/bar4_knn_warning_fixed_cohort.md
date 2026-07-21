# Fixed-Cohort Warning Event Study — clean World A vs B

Cohort = warnings at bar ≥9 (full t=-5..0 pre-window, CONSTANT N): **460** trades; matched controls 460. Same set tracked across rel bars → no composition shift. Read World A/B from REALIZED metrics + KNN eMFE (clean); P(Fail) flagged (argmax-tied artifact at t=-1/0). NO trading logic.

## Fixed-cohort trajectory (warning) — n constant in the pre-window
| Rel | n | P(new high ≤1) | ≤3 | ≤5 | rem MFE | KNN eMFE | P(Runner) | P(Fail)* |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| -5 | 460 | 19% | 44% | 54% | 2.10 | 1.60 | 22% | 36% |
| -4 | 460 | 17% | 39% | 47% | 2.08 | 1.58 | 22% | 33% |
| -3 | 460 | 18% | 29% | 44% | 2.02 | 1.57 | 23% | 28% |
| -2 | 460 | 13% | 25% | 39% | 1.91 | 1.59 | 23% | 23% |
| -1 | 460 | 2% | 22% | 33% | 1.73 | 1.62 | 24% | 18% |
| +0 | 460 | 11% | 28% | 35% | 1.89 | 1.49 | 19% | 23% |
| +1 | 364 | 22% | 38% | 45% | 2.07 | 1.58 | 24% | 17% |
| +2 | 319 | 26% | 41% | 48% | 2.04 | 1.62 | 27% | 14% |
| +3 | 285 | 28% | 44% | 49% | 2.04 | 1.64 | 31% | 10% |
| +4 | 257 | 23% | 39% | 49% | 2.06 | 1.69 | 35% | 8% |
| +5 | 221 | 29% | 41% | 50% | 2.18 | 1.70 | 39% | 7% |
| +6 | 199 | 23% | 42% | 51% | 2.15 | 1.73 | 44% | 5% |
| +7 | 185 | 23% | 40% | 51% | 2.18 | 1.68 | 46% | 4% |
| +8 | 170 | 24% | 44% | 51% | 2.20 | 1.73 | 51% | 3% |
| +9 | 159 | 20% | 43% | 49% | 2.14 | 1.72 | 54% | 3% |
| +10 | 144 | 25% | 41% | 47% | 2.17 | 1.72 | 57% | 2% |

\* P(Fail) is argmax-tied (t=-1 is the last CONT bar, t=0 the first DETER bar) — not a clean trajectory.

## Warning vs matched-control (realized new-high ≤3 & KNN eMFE)
| Rel | new-high≤3 W / C | KNN eMFE W / C | rem MFE W / C |
| --- | --- | --- | --- |
| -5 | 44% / 65% | 1.60 / 1.43 | 2.10 / 2.51 |
| -4 | 39% / 58% | 1.58 / 1.42 | 2.08 / 2.41 |
| -3 | 29% / 50% | 1.57 / 1.42 | 2.02 / 2.34 |
| -2 | 25% / 48% | 1.59 / 1.39 | 1.91 / 2.28 |
| -1 | 22% / 45% | 1.62 / 1.37 | 1.73 / 2.20 |
| +0 | 28% / 43% | 1.49 / 1.36 | 1.89 / 2.02 |
| +1 | 38% / 41% | 1.58 / 1.37 | 2.07 / 2.04 |
| +2 | 41% / 43% | 1.62 / 1.40 | 2.04 / 2.09 |
| +3 | 44% / 44% | 1.64 / 1.41 | 2.04 / 2.12 |
| +4 | 39% / 46% | 1.69 / 1.46 | 2.06 / 2.17 |
| +5 | 41% / 44% | 1.70 / 1.45 | 2.18 / 2.15 |
| +6 | 42% / 42% | 1.73 / 1.47 | 2.15 / 2.14 |
| +7 | 40% / 40% | 1.68 / 1.46 | 2.18 / 2.16 |
| +8 | 44% / 43% | 1.73 / 1.48 | 2.20 / 2.20 |
| +9 | 43% / 43% | 1.72 / 1.51 | 2.14 / 2.15 |
| +10 | 41% / 44% | 1.72 / 1.52 | 2.17 / 2.08 |

## Decision — World A vs World B (fixed cohort, no composition shift)

Realized new-high≤3 across the FIXED cohort: t-5 44% → t-4 39% → t-3 29% → t-2 25% → t-1 22% → t+0 28%.
KNN eMFE (continuous): t-5 1.60 → t-4 1.58 → t-3 1.57 → t-2 1.59 → t-1 1.62 → t+0 1.49 (drop +0.12).
> [!NOTE]
> **MIXED — leans World B (a real multi-bar precursor), but NOT clean "gradual decay", and with two caveats.**
>
> **The real precursor (clean):** vs matched controls, the warning cohort sits **~20pp BELOW on new-high≤3
> throughout the pre-window, INCLUDING t=-5** (44% vs 65%) — 5 bars before the warning these trades are already
> degraded vs peers. So the warning is NOT a bolt from the blue; a pre-existing lower-opportunity state precedes it.
> realized new-high≤1 also collapses acutely at t=-1 (2%).
>
> **Why it's not clean "gradual decay":** (1) the absolute decline is PARTLY regime-AGING — controls also decline
> (65%→45%) as regimes age; the warning-specific signal is a roughly CONSTANT ~20pp level gap, not an accelerating
> divergence. (2) KNN's OWN continuous estimate (eMFE) is roughly FLAT pre-warning (1.57–1.62) then dips at the
> warning bar — KNN does not "see" gradual decay in its score; it crosses the threshold abruptly (World-A-like for
> the KNN estimate). (3) The new-high≤3 drop is concentrated t=-5→-2 then plateaus, not a smooth slide to t=0.
>
> **Caveat (audit N3):** this is the LATE-warning subpopulation only — 460 trades = **7%** of all 6,479 warnings
> (those firing at bar≥9, the only ones with a full pre-window). The other 93% (early warnings, bars 5-8) have no
> pre-window and may be more World-A (immediate). So: among late-warners, a real ≥5-bar precursor exists (warning
> trades persistently below peers) → supports the "opportunity-state monitor / state precedes threshold" reading;
> but it is a persistently-below-peers + acute-final-bar pattern, not pure gradual decay, and it is unestablished
> for the bulk of warnings.