# +2A giveback — sustained +2A winners (G2) vs +2A-then-terminal-loser (G3)

**Development trades:** G2 has 1,847 trades and G3 has **373**. G3 is 16.8% of +2A trades and 6.2% of all
trades.

Short trades give back more than longs: 19.6% of short +2A trades against 14.1% of long ones. Rates range
from 10% to 27% across initial states (`INITIAL_STATE_MAP.md`).

## When, if ever, are they distinguishable?

| anchor (information through it) | best separating variable | AUC [95% CI] | meaningful? |
|---|---|---|---|
| T0 (MTF state) | aligned_1h | 0.519 [0.492, 0.546] | no |
| +30 s / +60 s / +120 s (pre-+2A) | mae (sustained took less heat) | 0.46 / 0.44 [0.40, 0.47] at 120 s | no |
| **+285 s, trades still below +2A** | **mae** / mae_rate | **0.388 [0.345, 0.431]** | **yes (late movers only)** |
| first touch of +0.5A | time since T0 | 0.534 [0.494, 0.575] | no |
| first touch of +1.0A | time since T0 | 0.547 [0.510, 0.581] | no |
| first touch of +1.5A | time from +1A to +1.5A | 0.586 [0.555, 0.617] | no (just below the threshold) |
| **first touch of +2.0A** | **time since T0** / time from +1.5A | **0.632 [0.598, 0.663]** / 0.630 | **yes** |

**What separates them: speed at the top.** Givebacks reach +2A faster. The median is 265 s after T0 against
390 s for sustained winners, and they cover the last +1.5A → +2A step in 23 s against 50 s. The signal
builds gradually (AUC 0.53 → 0.55 → 0.59 → 0.63 from +0.5A to +2A). It only passes the frozen threshold
**at the +2A touch itself**.

**What does not separate them, anywhere:**
- 5m, 15m or 1h alignment (0.48–0.52);
- MAE through the touch (0.47–0.48);
- prior −0.5A or −1A hits.

The one checkpoint effect (+285 s, MAE AUC 0.39) applies only to the 1,366 +2A trades that were still
below +2A at 285 s. Those slow movers give back more often when they had taken more heat.

## Reading

Sustained runners and givebacks **cannot be told apart before +2A** with the variables tested, except weakly
through speed. Speed is on the way to the threshold (0.59 at +1.5A) and only becomes meaningful at +2A.

A fast spike to +2A is more likely to be retraced to a terminal loss. That is a **trade-management**
observation located at or after +2A, not an entry-selection one. No rule is proposed. Any use of it would
need a matched placebo, because early-exit style conclusions are known to be fragile here.

Machine-readable: `artifacts/GROUP_COMPARISONS_CHECKPOINT.*` (contrast C2) and
`artifacts/GROUP_COMPARISONS_EVENT.*` (outcome `win_given_plus2 (C2)`).
