# Contract Check — Broad Post-Confirmation MFE and Model Exit Study

Date: 2026-07-27  
Gate: completion  
Reviewer: main-session fallback (explicitly authorized; configured
`contract_checker` model is unavailable in this Codex account)

| Contract item | Evidence | Result |
|---|---|---|
| Population disclosure | Report prominently limits inference to 5,836 first signals | PASS |
| Mandatory feasibility | Schema, cadence, joins, domains, thresholds, coverage, persistence and causality documented | PASS |
| Blocker handling | Bearish Top-10 and percentile tests explicit as unsupported; no estimation | PASS |
| Three baselines | All seven outcome counts reconcile exactly at 0.75/1.00/1.25 | PASS |
| Frozen Branch A grid | 12 floor, 12 giveback, 9 retention policies per stop | PASS |
| Branch B | Supported levels, crossing state, 1/2/3 persistence and diagnostics | PASS |
| Branch C | P1/P2/P3 first-event and warning-triggered tightening families | PASS |
| Causal ordering | Prior-bar MFE, post-confirm gating, exact model sources, next-open fills, ambiguity | PASS |
| Trade-policy artifact | 1,067,988 unique trade-stop-policy rows | PASS |
| Warning diagnostics | Threshold states plus confirmation/MFE/peak/giveback/final landmark structures | PASS |
| Metrics | Returns, PF, rates, MFE/capture/giveback, durations, time, drawdown, event counts | PASS |
| Transitions | Baseline outcome improvements/conversions/capture/giveback available | PASS |
| Breakdowns | Stop, model, direction, year and required cross dimensions available | PASS |
| Cross-stop evidence | Matching-baseline incremental return and capture evidence available | PASS |
| Validation | 300 trade-stop cases; baseline, MFE/P1 and Top-5 timing; 0 mismatches | PASS |
| Report discipline | Mixed verdict, no deployable policy, at most three candidates per family | PASS |

## Deliverables manifest

- `analysis/analyze_post_confirmation_mfe_and_model_exits.py`
- `results/post_confirmation_mfe_model_exit_trade_policy_results.parquet`
- `results/post_confirmation_model_warning_events.parquet`
- `results/post_confirmation_policy_cross_stop_comparison.parquet`
- `results/post_confirmation_mfe_model_exit_summary.json`
- `POST_CONFIRMATION_MFE_AND_MODEL_EXIT_REPORT.md`

CRITICAL: 0  
WARNING: 0  
NOTE: 0  
Verdict: PASS
