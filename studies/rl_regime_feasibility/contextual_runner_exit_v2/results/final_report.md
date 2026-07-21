FULL MULTI-TIMEFRAME CONTEXT:
PASS

CHECKPOINT REGIME-STATE IMPLEMENTATION:
PASS

PROLIFIC STATE DISTRIBUTION:
NON-DEGENERATE

LONG VS SHORT SEGMENTATION:
MIXED

RTH VS ETH SEGMENTATION:
USEFUL

PROLIFIC RUNNER LOCKOUT:
CONDITIONAL

IMMEDIATE WEAKNESS EXIT:
FAIL

WEAKNESS-TRIGGERED STRUCTURAL STOP:
FAIL

BEST FROZEN POLICY:
P1_fittedq

PAIRED DELTA VS E0:
$-1.17

RTH DELTA:
$-11.61

ETH DELTA:
$+2.97

LONG DELTA:
$-1.32

SHORT DELTA:
$-1.03

TOP-DECILE RUNNER DELTA:
$-253.70

PRIOR TOP-DECILE DELTA:
approximately -$484/trade

FALSE-EXIT LOSS:
$-326.4

SUCCESSFUL-EXIT BENEFIT:
+$134.9

VERDICT:
STOP

NEXT STEP:
Context and structural stops do not beat immediate exit or E0 on dev-test; the OHLCV runner-exit edge remains within noise — do not deploy.

---

# Full MTF Contextual Runner-Exit v2 — Final Report

**DEVELOPMENT TEST — PREVIOUSLY INSPECTED, NOT PRISTINE OOS**

## 1. Prior implementation audit

See `prior_implementation_audit.md`. Two structural bugs confirmed and repaired: (a) prior 'MTF' block was longer-window aligned returns only (most families omitted); (b) episode state attributed from the FIRST checkpoint (`groupby.first()`) and saved as a `.head(2000)` sample, collapsing 5642/5660 episodes to ORDINARY. P1c (+$2.23) was a test-selected exploratory result, not a validation-frozen winner.

## 2. Baseline reproduction

See `baseline_reproduction.parquet`. E0/E5 reproduced via the sim_v2 stack.

## 3. Complete MTF feature families

Families A–H implemented causally (returns/slope, efficiency, extremes, vol-decomposition, volume-response, structural HH/HL, pullback history, cross-horizon). Contract: `full_mtf_feature_contract.json`. Validation terminal-AUC by model:

| Model | features | val terminal AUC |
|---|---|---|
| M0 | 34 | 0.6572 |
| M1 | 128 | 0.6869 |
| M2 | 162 | 0.7152 |
| M3 | 170 | 0.7151 |
| M4 | 174 | 0.7149 |

## 4. Checkpoint regime-state distribution

State evaluated at EVERY checkpoint (see `regime_state_distribution.parquet`), attributed at the decision checkpoint. Non-degenerate across periods.

## 5. Frozen test policy results

| policy | ev | Δ vs E0 | CI | %impr | %wors |
|---|---|---|---|---|---|
| P0_E0 | $6.36 | $+0.0 | (0.0,0.0) | 0% | 0% |
| P1_fittedq | $5.19 | $-1.17 | (-8.29,6.17) | 38% | 17% |
| P2_context_exit | $-0.24 | $-6.6 | (-22.47,8.12) | 66% | 24% |
| P3_context_persist | $5.22 | $-1.14 | (-5.42,2.75) | 19% | 10% |
| P4_prolific_lockout | $-0.24 | $-6.6 | (-22.47,8.12) | 66% | 24% |
| P5_prolific_decay | $-2.38 | $-8.74 | (-27.66,10.03) | 63% | 28% |
| P6_segment | $-3.24 | $-9.6 | (-26.81,6.69) | 66% | 26% |
| P7_hybrid_stop | $-0.24 | $-6.6 | (-22.47,8.12) | 66% | 24% |

Best policy selected on VALIDATION EV: **P1_fittedq** (val Δ $+2.25).

## 6. Segment (RTH/ETH, long/short, state) results

| group | value | n | e0 | best | Δ | CI |
|---|---|---|---|---|---|---|
| session | RTH | 1603 | $40.3 | $28.7 | $-11.61 | (-22.49,-1.71) |
| session | ETH | 4039 | $-6.7 | $-3.7 | $+2.97 | (-6.29,12.17) |
| direction | long | 2839 | $13.0 | $11.6 | $-1.32 | (-12.1,9.65) |
| direction | short | 2803 | $0.3 | $-0.7 | $-1.03 | (-10.44,9.05) |
| state_at_decision | ORDINARY | 1010 | $23.4 | $1.2 | $-22.18 | (nan,nan) |
| state_at_decision | WEAKENING | 3785 | $18.1 | $21.2 | $+3.1 | (nan,nan) |
| state_at_decision | TERMINAL | 479 | $-46.2 | $-37.8 | $+8.32 | (nan,nan) |

## 7. Monthly stability

| month | n | e0 | best | Δ | CI |
|---|---|---|---|---|---|
| 2025-03 | 1871 | $0.4 | $-4.6 | $-4.98 | (-13.43,3.04) |
| 2025-04 | 1823 | $27.0 | $31.0 | $+3.98 | (-13.65,22.2) |
| 2025-05 | 1966 | $-7.1 | $-9.4 | $-2.33 | (-12.59,7.11) |

Months positive: 1/3

## 8. Prolific runner results (top decile)

| policy | n | e0 | policy | Δ | retention |
|---|---|---|---|---|---|
| P1_fittedq | 569 | $1443.0 | $1189.3 | $-253.7 | 0.824 |
| P2_context_exit | 569 | $1443.0 | $570.5 | $-872.5 | 0.395 |
| P3_context_persist | 569 | $1443.0 | $1357.1 | $-85.9 | 0.94 |
| P4_prolific_lockout | 569 | $1443.0 | $570.5 | $-872.5 | 0.395 |
| P5_prolific_decay | 569 | $1443.0 | $130.8 | $-1312.2 | 0.091 |
| P6_segment | 569 | $1443.0 | $321.0 | $-1122.0 | 0.222 |
| P7_hybrid_stop | 569 | $1443.0 | $570.5 | $-872.5 | 0.395 |

Prior top-decile damage ~ -$484/trade; best policy P1_fittedq: $-253.7.

## 9. Immediate exit vs structural stop

| rule | mean pnl | Δ vs E0 | Δ vs immediate | %stopped | %recovered_first |
|---|---|---|---|---|---|
| s1_immediate | $1.34 | $-11.95 | $+0.0 | nan | nan |
| s2 | $17.99 | $+4.71 | $+16.66 | 0.665 | 0.596 |
| s3 | $10.71 | $-2.57 | $+9.38 | 0.542 | 0.569 |
| s4 | $7.21 | $-6.07 | $+5.88 | 0.972 | 0.151 |

Stop placebo (S2 armed at random checkpoint) Δ vs E0: $+35.54. Frozen buffer 0.25 ATR.

## 10. Tail robustness

| policy | full | -top1 | -top5 | -top1% | -top5% |
|---|---|---|---|---|---|
| P1_fittedq | $-1.17 | $-2.61 | $-4.59 | $-9.32 | $-20.96 |
| P2_context_exit | $-6.6 | $-8.03 | $-11.54 | $-21.77 | $-46.63 |
| P3_context_persist | $-1.14 | $-1.28 | $-1.81 | $-5.13 | $-11.51 |
| P4_prolific_lockout | $-6.6 | $-8.03 | $-11.54 | $-21.77 | $-46.63 |
| P5_prolific_decay | $-8.74 | $-10.17 | $-13.73 | $-28.42 | $-64.16 |
| P6_segment | $-9.6 | $-11.05 | $-14.49 | $-26.13 | $-54.78 |
| P7_hybrid_stop | $-6.6 | $-8.03 | $-11.54 | $-21.77 | $-46.63 |

## 11. Controls

| control | ev / value |
|---|---|
| C1_mtf_shuffle | -0.76 |
| C2_state_shuffle | -0.11 |
| C5_seq_shuffle | 38.07 |
| C6_future_oracle | 53.64 |
| C7_lag_5s | 0.41 |
| C7_lag_10s | 0.95 |
| C7_lag_15s | -0.86 |
| C8_no_60s | 1.17 |
| C8_no_180s | 2.21 |
| C8_no_300s | 4.04 |
| C8_no_900s | 0.39 |
| C9_no_slopes | 1.15 |
| C9_no_efficiency | 0.17 |
| C9_no_vol_decomp | -0.17 |
| C9_no_structural | 1.96 |
| C9_no_pullback | -0.28 |
| C9_no_volume | 3.38 |
| C10_stop_placebo_s2_vs_e0 | 35.54 |
| C11_post_terminal_rows | 0.0 |

## 12. Decision against predeclared rules

- Paired delta $-1.17 (need >= $5 strong / >= $2 conditional)
- RTH delta $-11.61 (need not-negative)
- Months positive 1/3
- Top-decile runner delta $-253.7 (prior -$484; need >=50% reduction => >= -$242)
- Structural stop vs immediate $+16.66, vs placebo Δ $-30.83

### VERDICT: STOP

## 13. Recommended next step

Context and structural stops do not beat immediate exit or E0 on dev-test; the OHLCV runner-exit edge remains within noise — do not deploy.