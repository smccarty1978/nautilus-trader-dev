# Population definition

Primary policy economics use all continuous NQ one-second bars (RTH and ETH),
one contract, from 2025-03-01 through 2025-12-31 and 2026-01-01 through the
available catalog end 2026-04-29. Jan-Feb 2025 calibrates the absolute D10 score
threshold and is excluded from 2025 policy economics.

The regime state is the project-standard causal one-minute regime engine driven
from completed bars. A score checkpoint is usable only when its source one-second
bar is complete; therefore `causal_available_ts = observation_time + 1 second`.
The first below-to-at/above-threshold transition per regime defines treatment.

P0/P2 include regime-flip entries for which ATR has warmed and a next executable
bar exists. P1/P3 allow one D10 reversal attempt per originating regime. Rejected
or unfilled orders still consume that attempt. P4 donors are validly scored,
never-D10, non-right-censored regimes observed no later than the treated event;
self-matches, treated-regime donors, and donor reuse are prohibited.

Trades still open at the data boundary are right-censored, reported in attrition,
and excluded from completed-trade economics. The final regime in each catalog
segment is right-censored; no end time is inferred from another year.
