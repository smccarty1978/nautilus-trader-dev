# Continuous Health State-Transition Atlas

OOS states: 296,816. State from hC=P(new_high3)-P(flip3) + per-trade drawdown. REIGNITE = trade makes a new favorable high after this bar. The question: is each stall state a PAUSE (reignites) or DEATH (terminal flip)?

## 1. State frequency by bar index (k = bars since flip; entry=Bar4)
| bar k | Healthy | SoftStall | HardStall | DETER | n |
| --- | --- | --- | --- | --- | --- |
| 4 | 54% | 0% | 0% | 46% | 28,191 |
| 5 | 36% | 5% | 22% | 38% | 25,873 |
| 6 | 27% | 6% | 38% | 28% | 23,660 |
| 7 | 22% | 6% | 52% | 20% | 21,646 |
| 8 | 19% | 6% | 59% | 16% | 19,874 |
| 9 | 16% | 7% | 66% | 12% | 18,200 |
| 10 | 14% | 6% | 72% | 8% | 16,704 |
| 11 | 13% | 7% | 75% | 6% | 15,307 |
| 12 | 12% | 6% | 78% | 4% | 13,974 |
| 13 | 10% | 6% | 81% | 2% | 12,795 |
| 14 | 9% | 6% | 84% | 1% | 11,736 |
| 15 | 8% | 6% | 86% | 0% | 10,737 |

## 2+3. Per-state forward outcomes — PAUSE vs DEATH
| State | n | **P(reignite)** | P(flip≤3) | P(flip≤5) | P(flip≤10) | rem MFE | rem MAE | realized htf $ | med bars→flip |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Healthy | 55,443 | **93%** | 12% | 24% | 50% | 2.56 | 1.39 | $+221 | 10 |
| SoftStall | 15,757 | **92%** | 11% | 22% | 49% | 2.71 | 1.49 | $+460 | 11 |
| HardStall | 183,544 | **78%** | 25% | 38% | 61% | 2.25 | 1.16 | $+302 | 8 |
| DETER | 42,072 | **72%** | 35% | 47% | 67% | 1.92 | 0.99 | $-120 | 6 |

**Death-vs-pause headline:** P(reignite) — Healthy 93% · SoftStall 92% · HardStall 78% · DETER 72%.

## 4. State transitions (consecutive bars, counts)
| from → to | count |
| --- | --- |
| HardStall → HardStall | 140,599 |
| Healthy → HardStall | 27,674 |
| DETER → DETER | 21,584 |
| Healthy → Healthy | 16,797 |
| HardStall → Healthy | 12,114 |
| SoftStall → HardStall | 10,494 |
| DETER → Healthy | 8,333 |
| HardStall → SoftStall | 8,306 |
| Healthy → SoftStall | 5,101 |
| DETER → HardStall | 4,773 |
| Healthy → DETER | 4,687 |
| SoftStall → Healthy | 2,884 |
| HardStall → DETER | 2,691 |
| SoftStall → SoftStall | 1,806 |