# Stage 1 — Model B x hC capital-allocation screen (causal, full-universe, bar-5 entry)

Population alive at bar 5 (OOS): **28,191** trades. Exit = hold-to-flip + cat-stop (no triggers). pQ thresholds from IS terciles (lo=0.151, hi=0.530). hC buckets fixed (<.1 / .1-.5 / >=.5).

## 2D cohort EV — net $/tr (the arbiter). ✓ = net-positive in BOTH 2025 and 2026

| hC \ pQ | pQ-Low(safe) | pQ-Mid | pQ-High(risk) |
| --- | --- | --- | --- |
| **hC-Low(<.1)** | $-9 (n1,440; 25:$-1 26:$-33) | $-2 (n1,628; 25:$+3 26:$-19) | $+22 (n1,030; 25:$+13 26:$+50) ✓ |
| **hC-Med(.1-.5)** | $-12 (n3,591; 25:$-8 26:$-24) | $-17 (n3,866; 25:$-10 26:$-35) | $+1 (n3,721; 25:$-0 26:$+3) |
| **hC-High(>=.5)** | $-16 (n5,398; 25:$-10 26:$-36) | $-17 (n4,234; 25:$-6 26:$-54) | $-18 (n3,283; 25:$-14 26:$-32) |

## Booked P&L under the size map vs flat size=1

| Policy | Year | trades | units cap | net $ | $/unit-cap | flat-1 net $ |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| pQ-High->0.5; hC-High&safe->1.5 | 2025 | 21,195 | 20,192 | $-141,108 | $-6.99 | $-133,632 |
| pQ-High->0.5; hC-High&safe->1.5 | 2026 | 6,996 | 6,681 | $-208,138 | $-31.15 | $-188,770 |
| pQ-High->0; hC-High&safe->1.5 | 2025 | 21,195 | 17,163 | $-128,540 | $-7.49 | $-133,632 |
| pQ-High->0; hC-High&safe->1.5 | 2026 | 6,996 | 5,693 | $-203,358 | $-35.72 | $-188,770 |

## Verdict

- Best cohort (n>=200): **hC-Low(<.1) x pQ-High(risk)** = $+22/tr (2025 $+13, 2026 $+50, n=1,030), both-year-positive: **True**.
- Any cohort (n>=200) net-positive in BOTH years: **True**.
- If False: no allocation/management layer can rescue this — sizing only scales an across-the-board-negative book; Stage 2 (1s/NT BE+add management) is NOT warranted.