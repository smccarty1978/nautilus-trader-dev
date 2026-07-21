# Progressive Separability by Observation Bar (causal)

Features strictly through the observation bar. Train IS 2021–24, validate OOS 2025–26. AUC rises toward Bar 5 PARTLY tautologically (more of the label window is observed; at Bar 5 a QuickFailure is nearly resolved) — so the combined-filter NET/TRADE is the arbiter.

## 1. AUC progression
| Window | Launch AUC (LR/GBM) | Launch base | QuickFail AUC (LR/GBM) | QF base |
| --- | --- | --- | --- | --- |
| A pre-flip | 0.57/0.57 | 3.4% | 0.57/0.57 | 22.2% |
| B bar1 | 0.70/0.69 | 3.4% | 0.71/0.71 | 22.2% |
| C bar2 | 0.74/0.74 | 3.5% | 0.81/0.81 | 20.6% |
| D bar3 | 0.77/0.77 | 3.7% | 0.90/0.90 | 15.4% |
| E bar4 | 0.79/0.78 | 4.0% | 0.99/1.00 | 8.3% |
| F bar5 | 0.80/0.79 | 4.4% | — | — |

## 2. Launch precision/recall @ top-k% (GBM, OOS)
| Window | base | P@1% | P@5% | P@10% | R@5% | lift@1% |
| --- | --- | --- | --- | --- | --- | --- |
| A pre-flip | 3.4% | 5% | 5% | 5% | 7% | 1.5x |
| B bar1 | 3.4% | 8% | 8% | 7% | 11% | 2.3x |
| C bar2 | 3.5% | 11% | 9% | 8% | 13% | 3.2x |
| D bar3 | 3.7% | 10% | 10% | 9% | 13% | 2.8x |
| E bar4 | 4.0% | 17% | 13% | 11% | 16% | 4.3x |
| F bar5 | 4.4% | 18% | 13% | 12% | 15% | 4.2x |

## 3. Combined filter MONEY test (causal entry at next bar open, exit bar10 / opp-flip close)
Candidates: P(Launch) top X% AND P(QuickFail) bottom Y%. Net = $20/pt − $5 RT − 0.5t entry − 1.0t exit.

| Window | Filter | n | Launch% | Net/tr (bar10) | Net/tr (flip) | 2025 net | 2026 net | both+ & PF≥1.1? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A pre-flip | L≥5% & QF≤50% | 1,833 | 5% | $-30.24 | $-9.82 | $6,080 | $-24,078 | ❌ |
| A pre-flip | L≥5% & QF≤30% | 1,309 | 5% | $-17.45 | $-3.72 | $12,120 | $-16,988 | ❌ |
| A pre-flip | L≥5% & QF≤20% | 879 | 6% | $-10.29 | $+16.69 | $19,522 | $-4,850 | ❌ |
| A pre-flip | L≥10% & QF≤50% | 3,462 | 5% | $-22.76 | $-12.98 | $2,572 | $-47,512 | ❌ |
| A pre-flip | L≥10% & QF≤30% | 2,395 | 5% | $-20.80 | $-12.10 | $6,948 | $-35,925 | ❌ |
| A pre-flip | L≥10% & QF≤20% | 1,579 | 5% | $-16.75 | $+0.63 | $18,360 | $-17,372 | ❌ |
| B bar1 | L≥5% & QF≤50% | 1,886 | 8% | $+8.59 | $+23.00 | $58,288 | $-14,908 | ❌ |
| B bar1 | L≥5% & QF≤30% | 1,665 | 8% | $+15.56 | $+31.04 | $56,092 | $-4,415 | ❌ |
| B bar1 | L≥5% & QF≤20% | 1,198 | 8% | $+13.24 | $+34.48 | $43,928 | $-2,618 | ❌ |
| B bar1 | L≥10% & QF≤50% | 3,739 | 7% | $-6.33 | $-0.81 | $49,722 | $-52,765 | ❌ |
| B bar1 | L≥10% & QF≤30% | 3,154 | 7% | $-6.19 | $-2.39 | $31,275 | $-38,825 | ❌ |
| B bar1 | L≥10% & QF≤20% | 2,187 | 7% | $+1.42 | $+10.85 | $44,140 | $-20,402 | ❌ |
| C bar2 | L≥5% & QF≤50% | 1,813 | 9% | $-11.64 | $-22.55 | $-10,748 | $-30,130 | ❌ |
| C bar2 | L≥5% & QF≤30% | 1,646 | 9% | $-6.63 | $-15.84 | $-7,370 | $-18,705 | ❌ |
| C bar2 | L≥5% & QF≤20% | 1,349 | 9% | $-3.98 | $-11.05 | $-2,235 | $-12,672 | ❌ |
| C bar2 | L≥10% & QF≤50% | 3,674 | 8% | $-1.89 | $-12.02 | $-5,152 | $-38,998 | ❌ |
| C bar2 | L≥10% & QF≤30% | 3,187 | 9% | $+2.89 | $-7.74 | $970 | $-25,642 | ❌ |
| C bar2 | L≥10% & QF≤20% | 2,498 | 9% | $+4.73 | $-7.56 | $-3,402 | $-15,492 | ❌ |
| D bar3 | L≥5% & QF≤50% | 1,775 | 10% | $+1.36 | $+8.22 | $30,458 | $-15,875 | ❌ |
| D bar3 | L≥5% & QF≤30% | 1,510 | 10% | $+5.39 | $+7.52 | $23,925 | $-12,575 | ❌ |
| D bar3 | L≥5% & QF≤20% | 1,165 | 10% | $-5.38 | $-8.32 | $5,658 | $-15,355 | ❌ |
| D bar3 | L≥10% & QF≤50% | 3,524 | 9% | $-6.34 | $-5.36 | $16,992 | $-35,892 | ❌ |
| D bar3 | L≥10% & QF≤30% | 2,811 | 9% | $-0.30 | $+3.53 | $34,142 | $-24,225 | ❌ |
| D bar3 | L≥10% & QF≤20% | 2,017 | 9% | $-8.13 | $-2.82 | $16,065 | $-21,752 | ❌ |
| E bar4 | L≥5% & QF≤50% | 1,712 | 12% | $+3.52 | $-21.12 | $-14,365 | $-21,785 | ❌ |
| E bar4 | L≥5% & QF≤30% | 1,603 | 12% | $+6.54 | $-15.89 | $-5,052 | $-20,425 | ❌ |
| E bar4 | L≥5% & QF≤20% | 1,323 | 12% | $+10.93 | $-11.59 | $1,655 | $-16,982 | ❌ |
| E bar4 | L≥10% & QF≤50% | 3,379 | 11% | $-6.15 | $-16.93 | $2,200 | $-59,398 | ❌ |
| E bar4 | L≥10% & QF≤30% | 2,991 | 12% | $-6.21 | $-20.44 | $-11,835 | $-49,308 | ❌ |
| E bar4 | L≥10% & QF≤20% | 2,284 | 12% | $-6.91 | $-21.50 | $-7,302 | $-41,792 | ❌ |

## Verdict
> [!WARNING]
> **No combined filter is net-positive in both years (PF≥1.10).** Launch AUC rises pre-flip 0.57 → Bar3 0.77 and QuickFail 0.57 → Bar4 1.00 (info DOES appear after the flip — but it is the label-window-overlap/observation kind). The combined Launch-high + QuickFail-low filter selects a smaller population that is STILL net-negative both years: **early OHLCV health is descriptive but not monetizable** (the user's third interpretation). Same wall. Note 2026 net is NEGATIVE in every single row.

---

## ⚠️ AUDIT TRAIL — a look-ahead leak was found and fixed mid-study (2026-06-15)

The FIRST run of this study reported a **false positive**: 6 combined filters net-positive both years, headline **+$131/trade at the pre-flip window**, replicating across 4 held-out years. It survived every offline robustness control I threw at it (random/ATR/single-feature negative controls, year-by-year walk-forward, direction & time-concentration checks). The mandatory `lookahead-auditor` pass caught what the controls could not:

- **CRITICAL 1 — `feats_through()`:** `k = max(Nbar, 1)` forced `k=1` at the pre-flip window (`Nbar=0`), so `H[:, :k+1] = H[:, :2]` sliced in the **first POST-FLIP bar**. `mfe / mae / health / dist_flip_open / pullback` at window "A pre-flip" were reading bar-1's HIGH/LOW **while the strategy enters at bar-1's open** — direct look-ahead. Fixed to `k = Nbar` (window A now sees only the flip bar, which is knowable at decision time).
- **CRITICAL 2 — money test:** filter thresholds `np.quantile(...)` were computed on the **OOS pool being evaluated**. Fixed to derive thresholds from IS GBM scores, applied to OOS.

**After the fix:** pre-flip Launch AUC 0.626 → 0.574, QuickFail 0.666 → 0.569, and **combined passes 6 → 0**. Re-audit: zero CRITICAL remaining (one immaterial NOTE: IS GBM self-scores are mildly overfit for threshold-setting — does not change passes=0).

**Why the controls missed it:** I tested the 5 `pre5` features in isolation, but the leak rode in on `mfe/mae/health` — features I wrongly assumed were zeroed at `Nbar=0` (only the 8 progression features were). The leak was structural (present every year), which is exactly why it *replicated* across held-out years and looked robust. **Lesson: cross-year replication is NOT proof against a structural leak; only a feature-provenance audit is.** Logged to memory.