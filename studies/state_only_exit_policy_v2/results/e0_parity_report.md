# E0 Baseline Parity Reconciliation

## Result: **PASS**

| quantity | value |
|---|---|
| prior reported E0 (test) | $6.36 |
| current E0 (test, repaired sim_v2) | $6.0371 |
| reported gap (prior - current) | $0.3229 |
| reconstructed OLD-rule E0 (test) | $6.3572 |
| reconstructed NEW-rule E0 (test) | $6.0371 |
| reconstructed gap (old - new) | $0.3201 |
| gap fully explained by stop-fill-rule alone | **True** |

## Population checks

- test trades (raw): 5660
- duplicate episode_ids in trades table: 0
- unique episodes with surviving checkpoints: 5642
- episodes common to old/new reconstruction: 5660

No missing/duplicate episodes were found between the old and new
reconstructions -- both operate on the identical trades population
(`tt[tt.period=='test']`), identical entry timestamps/prices, identical
session/data-end termination logic, identical commission ($5) and contract
multiplier. The ONLY code difference between the two reconstructions is
`detect_stop_hit`'s non-gapped fill price.

## Root cause

`sim_v2.detect_stop_hit` (in `exit_optimal_stopping/repair/sim_v2.py`) was
found during the contextual_runner_exit_v3 lookahead-audit cycle to credit a
fill at exactly `stop_px` whenever a bar's low/high touched the stop level,
**even when the bar did not gap through** (i.e. the bar's open was still on
the favorable side of the stop). A real stop can only be detected once that
bar closes, so the earliest a market order can fill is the NEXT bar's open --
crediting `stop_px` directly is a systematic, trader-favorable phantom fill
(the same failure pattern as `feedback_offline_sim_use_ohlc_for_triggers`,
`be_simulation_path_checkpoint_inflation` in project memory). The fix (already
applied and canonical in `sim_v2.py`) resolves the fill via
`next_1s_open(bars_arr, stop_bar_ts)` when not gapped.

- Mean per-episode delta (new - old), all test episodes: $-0.3201
- Episodes with a stop hit (old-rule): 1481/5660
- Mean delta on stop-hit episodes: $-1.2233
- Mean delta on non-stop episodes: $+0.0000 (expected ~0 -- confirms
  the fix touches ONLY stop-hit episodes, nothing else)

## Conclusion

The $6.36 -> $6.04 difference is **fully reconciled**: it is exactly the
stop-fill-price bug fix, isolated to stop-hit episodes, with zero effect on
non-stop episodes. **$6.04 (current, repaired sim_v2) is the canonical E0**
used throughout this study. No further discrepancy remains.
