# KNN Neighbor Composition Atlas — path-DISTRIBUTION estimation

Per OOS state: 500-neighbor class mixture = predicted P(class). Shared 4-class by total MFE from Bar-4 entry (Runner ≥2.5 / Continuation ≥1.0 / Chop / Failure). The test is RELIABILITY: when KNN predicts P(Runner)=X, is the actual Runner rate X? And does P(Runner) ever rise meaningfully above base — i.e., can KNN LOCATE runners, not just average them?

Per-trade base rates: **Failure 22%**, **Chop 17%**, **Continuation 29%**, **Runner 32%**

## Bar 4 — RELIABILITY of P(Runner)  [base 32%]
| predicted P(Runner) bin | n | mean predicted | **actual Runner %** |
| --- | --- | --- | --- |
| 0–5% | 0 | — | — |
| 5–10% | 0 | — | — |
| 10–15% | 216 | 14% | **14%** |
| 15–20% | 3,531 | 18% | **18%** |
| 20–30% | 10,400 | 25% | **25%** |
| 30–50% | 9,018 | 37% | **38%** |
| 50–101% | 1,835 | 61% | **67%** |

## Bar 4 — RELIABILITY of P(Failure)  [base 22%]
| predicted P(Failure) bin | n | mean predicted | **actual Failure %** |
| --- | --- | --- | --- |
| 0–10% | 9,187 | 2% | **1%** |
| 10–20% | 3,026 | 15% | **12%** |
| 20–30% | 3,296 | 25% | **23%** |
| 30–40% | 3,273 | 35% | **33%** |
| 40–50% | 3,207 | 45% | **46%** |
| 50–70% | 3,011 | 56% | **58%** |
| 70–101% | 0 | — | — |

## Bar 4 — DISPERSION of predicted P(Runner)
- base 32%; predicted P(Runner) median 28%, p90 46%, p99 74%, max 91%
- → KNN DOES locate runner-rich pockets (p99 vs base).

## Bar 4 — BIFURCATION (P(Runner)≥20% AND P(Failure)≥30%)
- 5,762 states (23.0% of Bar-4 OOS)
- actual outcome: Runner 23%, Failure 39%, Chop 15%, Continuation 22% (base Runner 32% / Failure 22%)
- → the bifurcation flag does NOT elevate both tails vs base — not a real bimodal detector.

## Runner / Failure discrimination by bar (AUC + top-decile lift)
| Bar | AUC Runner | top-10% P(Runner) → actual (base) | AUC Failure | top-10% P(Fail) → actual (base) | P(Runner) p99 |
| --- | --- | --- | --- | --- | --- |
| 4 | 0.66 | 62% (32%) | 0.84 | 60% (22%) | 74% |
| 5 | 0.71 | 76% (34%) | 0.88 | 59% (17%) | 89% |
| 6 | 0.74 | 89% (38%) | 0.90 | 55% (13%) | 98% |
| 8 | 0.80 | 99% (44%) | 0.93 | 45% (8%) | 100% |

## Verdict — distribution estimator or not?

At Bar 4: AUC Runner 0.66; top-10%-P(Runner) states actually run 62% vs base 32% (**2.0× lift**); P(Runner) p99 74%.
> [!TIP]
> **KNN IS a path-DISTRIBUTION estimator at the entry bar** — it locates runner-rich pockets (top-decile lift + P(Runner) spanning well above base) and the mixture calibrates. The earlier 'low rem-MFE point-skill' verdict undersold this: the mean is uninformative, the MIXTURE is not. Next: confirm reliability monotonicity, then a size-up / scale-out money gate on the high-P(Runner) cohort (1s/NT validated). This reopens KNN.