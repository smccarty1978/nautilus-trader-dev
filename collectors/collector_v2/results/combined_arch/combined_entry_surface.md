# 2D Entry Surface — P_bad_short x P_runner (causal Bar-3, enter Bar-4)

Pop alive@bar4: 124,292 | base bad 46% / runner 36%.
Scored OOS baseline fills: 2025 n=19,871, 2026 n=6,558.

Axis AUC (OOS): P_bad=0.627 (target bad), P_runner=0.564 (target runner).

## 2D surface — pooled $/tr (rows=P_bad quintile lo→hi, cols=P_runner quintile lo→hi)
✓ = net-positive in BOTH 2025 and 2026 (n>=100 each).

| P_bad \ P_run | Q1 lo | Q2 | Q3 | Q4 | Q5 hi |
| --- | --- | --- | --- | --- | --- |
| bad Q1 | · | $-270(n1) | $-155(n43) | $-66(n1197) | $-2(n3986) |
| bad Q2 | $-300(n2) | $+62(n109) | $-57(n1164) | $-48(n2918) | $-99(n1156) |
| bad Q3 | $+182(n130) | $-40(n1081) | $+20(n2551)✓ | $-53(n1336) | $-124(n134) |
| bad Q4 | $-5(n1144) | $-36(n2507) | $-41(n1503) | $-29(n185) | $-107(n20) |
| bad Q5 | $-30(n3761) | $-71(n1285) | $-26(n203) | $-251(n13) | · |

## Composition by P_bad quintile (OOS): bad% / runner% / $/tr
| P_bad | n | bad% | runner% | $/tr | 2025 $/tr | 2026 $/tr |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Q1 | 5,227 | 30% | 43% | $-18 | $+3 | $-83 |
| Q2 | 5,349 | 39% | 37% | $-59 | $-52 | $-79 |
| Q3 | 5,232 | 45% | 36% | $-11 | $-0 | $-43 |
| Q4 | 5,359 | 51% | 34% | $-31 | $-23 | $-55 |
| Q5 | 5,262 | 60% | 29% | $-41 | $-36 | $-55 |

## Combined entry rules (IS-derived thresholds, real fills, 2025/2026 separate)
Keep if P_bad < (100−X) IS-pctile AND P_run >= Y IS-pctile.

| rule | 2025 n | 2025 $/tr | 2026 n | 2026 $/tr | both>baseline? | both>0? | beats random? |
| --- | ---: | ---: | ---: | ---: | :---: | :---: | :---: |
| baseline (scored) | 19,871 | $-21.7 | 6,558 | $-63.0 | — | — | — |
| bad<top30% & run>=p50 | 9,918 | $-24.5 | 3,387 | $-62.2 | no | no | no |
| bad<top30% & run>=p60 | 8,329 | $-23.3 | 2,843 | $-85.3 | no | no | no |
| bad<top30% & run>=p70 | 6,411 | $-29.5 | 2,129 | $-83.3 | no | no | no |
| bad<top40% & run>=p50 | 9,661 | $-23.7 | 3,255 | $-63.6 | no | no | no |
| bad<top40% & run>=p60 | 8,250 | $-22.8 | 2,786 | $-81.2 | no | no | no |
| bad<top40% & run>=p70 | 6,389 | $-29.0 | 2,112 | $-83.5 | no | no | no |

## hC4 reference panel — NON-CAUSAL for bar-4 entry (hC4 uses bar-4 close; shown for the hC framing only, NOT deployable)
| rule | 2025 $/tr | 2026 $/tr | both>0? |
| --- | ---: | ---: | :---: |
| bad<top30% & hC4>=p50 | $+127.9 | $+82.4 | YES |
| bad<top30% & hC4>=p60 | $+155.4 | $+111.8 | YES |
| bad<top30% & hC4>=p70 | $+191.9 | $+144.9 | YES |
| bad<top40% & hC4>=p50 | $+134.7 | $+76.9 | YES |
| bad<top40% & hC4>=p60 | $+166.1 | $+102.0 | YES |
| bad<top40% & hC4>=p70 | $+202.4 | $+138.7 | YES |

## VERDICT

**No causal P_bad×P_runner cell or rule is net-positive in both 2025 and 2026.** The two KNNs combine to reduce damage and improve composition, but do not create expectancy — 2026 stays negative. Price-only entry geometry has reached its ceiling; a 2026-robust non-price input (order flow / book) is required.