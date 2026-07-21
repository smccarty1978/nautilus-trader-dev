# Exit Optimal Stopping — Frozen Test Report

DEVELOPMENT TEST — PREVIOUSLY INSPECTED, NOT PRISTINE OOS

---

## Executive Summary

```
SIM_V2 EXECUTION AUDIT:
PASS

FROZEN TEST REPLAY:
PASS

E5 TEST EV/TR:
$3.60

E0 TEST EV/TR:
$6.56

PAIRED E5-E0 DELTA:
$-2.96

PAIRED 95% CI:
(-10.03, 4.05)

MONTHS POSITIVE:
1/3

+1 TICK DELTA:
$-2.96

FEATURE MODEL:
FULL (29 of 57 contract features)

VERDICT:
FAIL

NEXT STEP:
Do not advance fitted-Q to RL; signal too weak or controls failed.
```

---

## 1. Frozen-Artifact Audit

| Artifact | Status |
|----------|--------|
| m4_full (29 features) | FROZEN hash=fff54a30e5fb773f |
| m4_minimal (5) | FROZEN hash=2fd28a1c82a51c24 |
| m4_minimal_plus (10) | FROZEN hash=f62296485007ca56 |
| m3_hazard (29) | FROZEN hash=7c04e45d5186894c |
| m4_full threshold | 104.0076 (re-derived; match=OK) |
| m3_hazard threshold | 0.0812 (re-derived) |
| All 29 features present | CONFIRMED |
| 28 absent features | Not materialised in checkpoint builder (known, documented) |
| No test data in train | CONFIRMED — temporal split enforced |

## 2. Test Checkpoint Audit

| Metric | Value |
|--------|-------|
| Test episodes | 5,660 |
| Checkpoints before truncation | 681,467 |
| Ghost rows removed | 61,921 |
| Checkpoints after truncation | 619,546 |
| Stop-hit episodes | 1,481 (26.2%) |
| Post-stop positioned rows | 0 ✓ |

Terminal reasons: {'opposing_flip': 3631, 'stop_hit': 1481, 'max_duration': 547, 'data_end': 1}

## 3. Policy Results (test period)

| Policy | EV/trade | vs E0 |
|--------|---------|------|
| E0 | $6.56 | +0.00 |
| E1 | $7.05 | +0.49 |
| E4 | $-0.36 | -6.92 |
| E5_full | $3.60 | -2.96 |
| E5h2 | $8.72 | +2.16 |
| E5_minimal | $3.74 | -2.82 |
| E5_minimal_plus | $6.37 | -0.19 |

## 4. Primary Paired E5-E0 Comparison

| Metric | Value |
|--------|-------|
| N episodes | 5,660 |
| Mean paired delta | **$-2.96/trade** |
| Median paired delta | $0.00/trade |
| Standard deviation | $272.33 |
| Standard error | $3.62 |
| Bootstrap 95% CI | **(-10.03, 4.05)** |
| % episodes improved | 37.5% |
| % episodes unchanged | 45.5% |
| % episodes worsened | 17.0% |
| Mean gain (improved) | $110.57 |
| Mean loss (worsened) | $-261.94 |
| Total paired delta | $-16,771 |

Other paired comparisons:
- delta_E5h2_E0: $2.16 CI=(-3.51,8.16)
- delta_E5min_E0: $-2.82 CI=(-9.93,4.51)
- delta_E5mpl_E0: $-0.19 CI=(-5.62,5.49)
- delta_E5_E1: $-3.45 CI=(-16.25,9.37)

## 5. Exit-Signal Attribution

| Category | N | E0 avg | E5 avg | Delta |
|----------|---|-------|--------|-------|
| E5_exited_early | 3157 | $140.5 | $135.2 | $-5.3 |
| no_signal | 1623 | $-92.1 | $-92.1 | $0.0 |
| stop_before_signal | 880 | $-291.9 | $-291.9 | $0.0 |

## 6. Monthly and Directional Stability

| Month | N | E0 | E5 | Delta | CI |
|-------|---|----|----|-------|----|  
| 2025-03 | 1871 | $0.3 | $-5.9 | $-6.3 | (-14.9,1.7) |
| 2025-04 | 1823 | $27.0 | $21.1 | $-5.9 | (-25.2,12.7) |
| 2025-05 | 1966 | $-6.5 | $-3.6 | $2.9 | (-3.8,9.1) |

**Directional and session breakdown:**

- direction=-1.0: N=2803 E0=$0.3 E5=$-2.8 Δ=$-3.1 (-11.6,6.0)
- direction=1.0: N=2839 E0=$13.4 E5=$10.5 Δ=$-2.9 (-14.2,8.3)
- session=ETH: N=3930 E0=$-9.2 E5=$-7.5 Δ=$1.8 (-6.1,10.1)
- session=RTH: N=1730 E0=$42.5 E5=$28.7 Δ=$-13.7 (-28.8,-0.8)

## 7. Feature Baseline Comparison

| Model | Features | EV/trade | vs E0 |
|-------|---------|---------|------|
| E5_minimal | 5 | $3.74 | -2.82 |
| E5_minimal_plus | 10 | $6.37 | -0.19 |
| E5_full | 29 | $3.60 | -2.96 |

## 8. Cost Stress

| Scenario | E0 EV | E5 EV | Delta | CI |
|---------|------|------|-------|----|
| base | $6.56 | $3.60 | $-2.96 | (-10.03,4.05) |
| +1 tick RT | $1.56 | $-1.40 | $-2.96 | (-10.03,4.05) |
| +2 ticks RT | $-3.44 | $-6.40 | $-2.96 | (-10.03,4.05) |

## 9. Tail Dependence

**Sensitivity (E5-E0 delta after removing top outliers):**

- remove_top1: N=5,659 mean=$-4.38 CI=(-11.36,2.10)
- remove_top5: N=5,655 mean=$-6.06 CI=(-12.58,-0.16)
- remove_top1pct: N=5,604 mean=$-10.86 CI=(-17.24,-5.00)
- remove_top5pct: N=5,377 mean=$-21.72 CI=(-28.14,-15.84)

## 10. Controls

| Control | EV/trade | vs E5 | Expected | Pass? |
|---------|---------|-------|----------|-------|
| C1 label shuffle | $-2.78 | -6.4 | collapse | PASS |
| C2 seq shuffle | $-49.28 | -52.9 | collapse | PASS |
| C3 lag 5s | $4.41 | — | slight degrade | OK |
| C3 lag 10s | $3.96 | — | more degrade | OK |
| C3 lag 15s | $4.42 | — | most degrade | OK |
| C4 future lead | $9.68 | +6.1 | IMPROVE (oracle) | PASS |
| C5 post-stop | 0 | — | 0 | PASS |
| C6 pullback shuffle | $6.03 | +2.4 | minor degrade | OK |

## 11. Combined Validation + Test Evidence

COMBINED DEVELOPMENT EVIDENCE

| Metric | Value |
|--------|-------|
| N val | 3,601 |
| N test | 5,660 |
| N combined | 9,261 |
| Combined E0 EV | $7.35/trade |
| Combined E5 EV | $6.14/trade |
| **Combined delta** | **$-1.22/trade** |
| Combined SE | $2.51 |
| Combined 95% CI | **(-6.29, 3.80)** |

## 12. Decision

### Predeclared rule evaluation

| Rule | Required | Observed | Met? |
|------|---------|---------|------|
| Test E5-E0 ≥ $5 | ≥ $5 | $-2.96 | NO |
| CI reasonable (not far below 0) | CI > -10 | (-10.0,4.0) | NO |
| ≥ 2/3 months positive | 2/3 | 1/3 | NO |
| +1 tick stress positive | > 0 | $-2.96 | NO |
| Label shuffle collapses | C1 << E5 | $-2.8 vs $3.6 | YES |
| Future lead improves | C4 > E5 | $9.7 vs $3.6 | YES |
| Zero post-stop signals | 0 | 0 | YES |

Rules met: 3/7

### **VERDICT: FAIL**

**Next step: Do not advance fitted-Q to RL; signal too weak or controls failed.**

---

*Original inflated results (+$102/trade on broken simulation) are not used as evidence.*
*All results from the repaired sim_v2 with exact 1s-bar stop detection and next-1s-open fills.*
