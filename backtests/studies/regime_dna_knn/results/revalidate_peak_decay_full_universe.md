# Step 2 — Peak-Decay Exit re-validated on FULL flip universe

Capsule flips: **146,831** total | survivors (n_post>=4): **124,292** | quick-failures dropped by published filter: **22,539** (15.4%)

Friction identical to decision_hc_sprint (entry+0.5t, exit-1.0t, $5 comm). Cat-stop at flip-bar extreme. Decay arms at bar 4.

## Baseline (hold-to-flip)

| Population | Split | n | Expectancy $/tr | Net PnL | Max DD | PF |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| A: survivor (n_post>=4, AS PUBLISHED) | IS | 93,562 | $+5.84 | $+546,490 | $51,135 | 1.08 |
| A: survivor (n_post>=4, AS PUBLISHED) | OOS | 30,730 | $+15.73 | $+483,400 | $21,388 | 1.16 |
| B: FULL universe (all flips) | IS | 110,589 | $-14.30 | $-1,581,028 | $1,590,455 | 0.82 |
| B: FULL universe (all flips) | OOS | 36,242 | $-15.30 | $-554,510 | $578,492 | 0.86 |

## Decay 20% (HEADLINE)

| Population | Split | n | Expectancy $/tr | Net PnL | Max DD | PF |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| A: survivor (n_post>=4, AS PUBLISHED) | IS | 93,562 | $+6.32 | $+590,985 | $51,135 | 1.10 |
| A: survivor (n_post>=4, AS PUBLISHED) | OOS | 30,730 | $+15.49 | $+475,915 | $15,290 | 1.17 |
| B: FULL universe (all flips) | IS | 110,589 | $-13.89 | $-1,536,532 | $1,545,715 | 0.81 |
| B: FULL universe (all flips) | OOS | 36,242 | $-15.51 | $-561,995 | $572,762 | 0.85 |

## Verdict

- Published headline (survivor subset, Decay 20%, OOS): **$+15.49/tr, net $+475,915**
- Same rule on FULL universe (Decay 20%, OOS): **$-15.51/tr, net $-561,995**
- Full-universe baseline hold-to-flip (OOS): **$-15.30/tr, net $-554,510**