# Contract Check — Top-2.5% First-Signal Stop Study

Date: 2026-07-26  
Gate: completion  
Reviewer: main-session fallback (explicitly authorized; configured
`contract_checker` model is unavailable in this Codex account)

## Compliance

| Contract item | Evidence | Result |
|---|---|---|
| Restricted population explicit | SPEC and report state 5,836 selected first signals, not all observations | PASS |
| Canonical inputs only | Config and loader calls reference summaries and paths; no rebuild | PASS |
| 1.25 ATR stop remains active | Frozen config and both pre/post-confirmation classifications | PASS |
| H4 fill convention | Touch from 1s high/low; fill at following bar open price and timestamp | PASS |
| Mutually exclusive outcomes | 5,836 output rows; counts sum to 5,836 | PASS |
| One row per entry | Result parquet has 5,836 rows and 5,836 unique trade IDs | PASS |
| Required result columns | Identity, event, stop, return, excursion, censor, and ambiguity fields present | PASS |
| Required aggregate evidence | Pooled, model, direction, year, model-direction, MFE incidence, giveback | PASS |
| Independent replay | Fixed seed 20260726; 100 rows; 0 mismatches | PASS |
| Human report | Required methodology, results, interpretation, limitations, verdict present | PASS |
| Final verdict vocabulary | `RESULTS VALID WITH LIMITATIONS` | PASS |

## Deliverables manifest

- `analysis/analyze_top2_5_stop_and_regime_exit.py`
- `results/top2_5_stop_1_25_regime_exit_results.parquet`
- `results/top2_5_stop_1_25_regime_exit_summary.json`
- `TOP2_5_STOP_1_25_REGIME_EXIT_REPORT.md`
- `results/top2_5_stop_1_25_run_status.json`

CRITICAL: 0  
WARNING: 0  
NOTE: 0  
Verdict: PASS
