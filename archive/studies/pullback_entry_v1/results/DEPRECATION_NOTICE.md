# DEPRECATION NOTICE — Pullback Entry Study v1

**As of 2026-04-26**, the entire pullback v1 study branch is **retired**.

## Why

The collectors that produced the original numbers had a non-causal regime-exit
bug. They:

1. Used `flip_bar_ts_event` (= 1m bar OPEN) as `regime_end_ts`, exiting trades
   ~60s before the regime flip is actually detectable in real time.
2. Used 1s bar CLOSE at flip-bar OPEN time as the regime exit price (~59s too
   early).
3. Dropped trades whose `fill_ts` exceeded `regime_end_ts` — using future
   regime knowledge that wouldn't be available at decision time in live trading.

These bugs jointly inflated per-trade economics by **$40-72/trade** (varies
by year). The "OOS edge" of +$13.69 to +$35.67/trade reported earlier was
100% an artifact.

The collectors in this directory have been **patched** with causal regime-exit
logic on 2026-04-26. Re-running them now produces realistic numbers that match
NT runtime within $1-2/trade. See:

- `oos_collector.py` — patched, header notes the fix
- `collector.py` — patched, header notes the fix
- `studies/hmm_5s_v1/bracket_exit_study.py` — audited, was already causal

## Reports

All reports in this directory have been **regenerated from causal data** as of
2026-04-26. They no longer contain inflated numbers. The pullback strategy
is unprofitable in offline AND in NT (PF 0.88-0.90 across 2024-2026).

The single remaining historical artifact is the comparison report
`CAUSAL_REPORT.md` which intentionally shows BUGGY-vs-CAUSAL economics
side-by-side as evidence of the bug's magnitude.

## Output files

| File | Status | Notes |
|---|---|---|
| `oos_pullback_1atr_<year>.parquet` | Causal | Regenerated 2026-04-26 |
| `oos_confirmed_entries_<year>.parquet` | Causal | Regenerated 2026-04-26 |
| `pullback_candidates_2025.parquet` | Causal | Regenerated 2026-04-26 |
| `matched_baseline_2025.parquet` | Causal | Regenerated 2026-04-26 |
| `nt_runtime_<year>/nt_trades.parquet` | Realistic | NT runtime (no bug) |
| `PULLBACK_REPORT.md` | Causal | Regenerated 2026-04-26 |
| `FOLLOWUP_REPORT.md` | Causal | Regenerated 2026-04-26 |
| `OOS_REPORT.md` | Causal | Regenerated 2026-04-26 |
| `NT_PARITY_REPORT.md` | Reflects pre-patch numbers | Conclusion was correct (bug existed) but root-cause attribution outdated. CAUSAL_REPORT.md supersedes. |
| `CAUSAL_REPORT.md` | Authoritative | Side-by-side BUGGY vs CAUSAL vs NT |
| `BRACKET_EXIT_REPORT.md` (in `hmm_5s_v1/results/`) | OK | Source `bracket_exit_study.py` was already causal |

## Methodology rule (stored in MEMORY.md)

See `offline_collector_regime_exit_optimism.md` in the project memory.
Any future collector that models "exit on opposing 1m regime flip" must:

- Use `next_flip.flip_bar_ts_init` (CLOSE) as `regime_end_ts`
- Use the next flip bar's CLOSE price as `regime_exit_price`
- Filter trades only on regime knowledge available at DECISION time, never
  on `fill_ts vs regime_end_ts` (future knowledge)
- Run NT parity validation BEFORE claiming any regime-exit-dependent edge
