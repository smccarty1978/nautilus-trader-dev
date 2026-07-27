# Contract Check — 0.75 ATR First-Signal Stop Study

Date: 2026-07-26  
Gate: completion  
Reviewer: main-session fallback (explicitly authorized; configured
`contract_checker` model is unavailable in this Codex account)

| Contract item | Evidence | Result |
|---|---|---|
| Population | 5,836 canonical selected first signals; limitation disclosed | PASS |
| Sole policy change | Configured stop is 0.75 ATR; other accepted rules unchanged | PASS |
| Stop execution | Completed 1s high/low touch, next path bar open fill | PASS |
| Full-trade stop | Before- and after-confirmation stop outcomes retained | PASS |
| Outcomes | Seven exclusive classes sum to 5,836 | PASS |
| Trade-level evidence | 5,836 rows with required event, return, excursion, censor fields | PASS |
| Aggregate evidence | Pooled, model, direction, year, model-direction, MFE, giveback | PASS |
| Independent replay | Seed 20260726, 100 paths, 0 mismatches | PASS |
| Report | Dynamic 0.75 labels, methods, results, limitations, verdict | PASS |

## Deliverables

- `results/top2_5_stop_0_75_regime_exit_results.parquet`
- `results/top2_5_stop_0_75_regime_exit_summary.json`
- `TOP2_5_STOP_0_75_REGIME_EXIT_REPORT.md`

CRITICAL: 0  
WARNING: 0  
NOTE: 0  
Verdict: PASS
