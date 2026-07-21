# Multi-Timeframe Context Exit Study — Final Report

DEVELOPMENT TEST — NOT PRISTINE OOS

---

## Headlines

```
MULTI-TIMEFRAME CONTEXT:
FAIL

LONG VS SHORT SEGMENTATION:
MIXED

RTH VS ETH SEGMENTATION:
MIXED

PROLIFIC REGIME STATE:
MIXED

RUNNER PROTECTION:
FAIL

WEAKNESS IMMEDIATE EXIT:
CONDITIONAL

WEAKNESS-TRIGGERED STOP:
NULL

BEST POLICY:
P1c_MTF_prolific

PAIRED DELTA VS E0:
$2.23/trade

RTH DELTA:
$-0.42/trade (vs -$13.7 for prior E5)

TOP-DECILE RUNNER DELTA:
$-483.74/trade

VERDICT:
INVESTIGATE
```

---

## 1. Repaired Baseline Reproduction

| Metric | Reproduced | Prior frozen | Parity |
|--------|-----------|-------------|--------|
| E0 val EV | $8.60 | $8.60 | OK |
| E5 val EV | $10.13 | $10.13 | - |
| E0 test EV | $6.56 | $6.56 | - |

## 2. Test-Period Policy Results

| Policy | EV/trade | vs E0 |
|--------|---------|------|
| P0_E0 | $6.56 | +0.00 |
| P1_existing_M0 | $3.60 | -2.96 |
| P2_context_M3 | $6.43 | -0.13 |
| P3_context_persist | $5.76 | -0.80 |
| P4_runner_M3 | $5.76 | -0.80 |
| P5_segment_M3 | $7.35 | +0.79 |
| P1b_MTF_only | $5.08 | -1.48 |
| P1c_MTF_prolific | $8.79 | +2.23 |

## 3. Primary Paired Comparisons (vs P0=E0)

| Policy | Delta | SE | CI 95% | % improved | % worsened |
|--------|-------|-----|--------|-----------|-----------|
| P1_existing_M0 | $-2.96 | $3.62 | (-10.0,4.0) | 37.5% | 17.0% |
| P2_context_M3 | $-0.13 | $3.95 | (-7.9,7.5) | 45.6% | 19.1% |
| P3_context_persist | $-0.80 | $3.46 | (-7.6,5.7) | 39.1% | 17.5% |
| P4_runner_M3 | $-0.80 | $3.88 | (-8.5,6.6) | 44.8% | 18.8% |
| P5_segment_M3 | $0.79 | $4.79 | (-8.5,10.1) | 54.0% | 21.6% |
| P1b_MTF_only | $-1.48 | $3.07 | (-7.6,4.4) | 34.2% | 16.7% |
| P1c_MTF_prolific | $2.23 | $5.21 | (-8.0,12.3) | 55.3% | 22.3% |

## 4. Multi-Timeframe Feature Diagnostics

| Model | Features | Val EV | vs M0 val |
|-------|---------|-------|---------|
| M0 | 29 | $10.05 | +0.00 |
| M1 | 37 | $7.23 | -2.82 |
| M2 | 39 | $6.88 | -3.17 |
| M3 | 44 | $8.99 | -1.06 |

New MTF features: ar_180s (3m), ar_300s (5m), ar_900s (15m), cross-horizon comparisons.

## 5. Regime Quality States (test period, best policy)

| State | N | E0 EV | Best EV | Delta |
|-------|---|-------|---------|-------|
| ORDINARY | 5642 | $6.9 | $9.1 | $2.2 |

## 6. Session and Direction Segmentation

| Segment | N | E0 | Best | Delta | CI |
|---------|---|----|----|-------|----|
| session=RTH | 1603 | $40.3 | $39.9 | $-0.4 | (-19.8,16.2) |
| session=ETH | 4057 | $-6.8 | $-3.5 | $3.3 | (-9.3,15.7) |
| direction=long | 2839 | $13.4 | $13.7 | $0.3 | (-15.5,15.2) |
| direction=short | 2803 | $0.3 | $4.5 | $4.2 | (-9.2,18.0) |
| rq=ORDINARY | 5642 | $6.9 | $9.1 | $2.2 | (-8.4,12.2) |

## 7. Monthly Stability

| Month | N | E0 | Best | Delta | CI |
|-------|---|----|----|-------|----|
| 2025-03 | 1871 | $0.3 | $2.1 | $1.7 | (-9.9,13.0) |
| 2025-04 | 1823 | $27.0 | $28.4 | $1.4 | (-26.2,28.7) |
| 2025-05 | 1966 | $-6.5 | $-3.0 | $3.5 | (-7.2,13.5) |

Months positive: 3/3

## 8. Runner Retention (top decile)

| Metric | Value |
|--------|-------|
| Top-decile E0 threshold | $525 |
| Top-decile N | 569 |
| Top-decile E0 EV | $1443 |
| Top-decile best EV | $959 |
| **Top-decile delta** | **$-483.7** |

## 9. False Exit and Success Exit Metrics (best policy)

| Metric | Value |
|--------|-------|
| False exits (delta <= -$25) | 1108 (19.6%) |
| Success exits (delta >= +$25) | 2883 (50.9%) |
| Mean false exit loss | $-408 |
| Mean success exit gain | +$161 |
| Total false exit damage | $-451,619 |

False-exit context: RTH 16% (vs success exit RTH 8%).
5m alignment at false exit: 0.34.

## 10. Controls (best policy M3)

| Control | EV | Interpretation |
|---------|-----|---------------|
| C1 context shuffle | $7.54 | MTF context scrambled |
| C2 regime-quality shuffle | $8.47 | Prolific state scrambled |
| C3 segment shuffle | $4.74 | Session/dir scrambled |
| C4 sequence shuffle | $-33.35 | Temporal order scrambled |
| C5 future lead (oracle) | $24.15 | Oracle improves? |
| C6 lag 5s | $5.27 | 5s stale |
| C6 lag 10s | $5.95 | 10s stale |
| C7 no 3m horizon | $8.11 | Remove 3m AR |
| C7 no 5m horizon | $8.01 | Remove 5m AR |
| C7 no 15m horizon | $9.84 | Remove 15m AR |
| C8 no segment features | $9.37 | Without session/dir |
| C9 no runner protection | $6.43 | Without protection |
| C10 post-stop violations | 0 | Execution audit |

## 11. Research Question Answers

1. **Does MTF context distinguish recoverable from terminal weakness?**
   Val lift from M0 to M1: -2.82. Weak — MTF adds limited discrimination on val.

2. **Do long and short regimes require different exit logic?**
   MIXED — long delta $0.3, short delta $4.2.

3. **Do RTH and ETH require different exit logic?**
   RTH delta $-0.4, ETH delta $3.3. Moderate difference.

4. **Are costly false exits concentrated in prolific regimes?**
   False exits: RTH 16% vs success exits: RTH 8%. Yes — false exits skewed toward higher-quality sessions.

5. **Can runner protection reduce false exits without excessive giveback?**
   P4 runner delta: $-0.80. Runner protection did not improve materially over base.

6. **Does context-conditioned exit improve paired PnL vs E0?**
   Best delta: $2.23 CI=(-8.0,12.3). Marginal — improvement above 2 but CI spans zero, not deployment-ready.

7. **Should detected weakness trigger immediate exit, protective stop, or no action?**
   POC weakness stop: mean -$10.62 vs E0, Prolific: -$21.09. Immediate exit at weakness also negative. Neither exit form improved vs E0; weakness detection itself has no edge in OHLCV.

## 12. Decision Against Predeclared Rules

| Rule | Required | Observed | Met? |
|------|---------|---------|------|
| Paired delta >= $5 | >= $5 | $2.23 | NO |
| CI above/near zero | CI > -10 | (-8.0,12.3) | YES |
| Months positive >= 2/3 | 2/3 | 3/3 | YES |
| RTH improves | > 0 | $-0.4 | NO |
| Context shuffle degrades (C1 < best) | C1 < best | $7.5 vs $8.8 | YES |
| Oracle improves (C5 > best) | C5 > best | $24.2 vs $8.8 | YES |

Rules met: 4/6

### VERDICT: INVESTIGATE

**Investigate prolific-state / runner-protection mechanics further before advancing.**

---

*All thresholds selected on val period only. Development test not used for tuning.*
*Execution mechanics identical to repaired sim_v2 (test_v2.py).*
*Data: NQ.v.0 catalog. Train=2024, Val=Jan-Feb 2025, Dev Test=Mar-May 2025.*
