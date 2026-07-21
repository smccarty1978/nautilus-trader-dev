# Delayed Entry Study (v2 corpus)

## Hypothesis

Within HH/LL-confirmed 1m regime flips, **waiting some seconds (T_d s)
before entering the trade may improve trade quality** (better fill, more
favorable forward path, fewer first-minute SLs) enough to offset the
cost of (a) entering later in the move and (b) selecting only events
that survived to T_d.

## Base population

- v2 corpus, 2020-2025
- Confirmed events only (HH/LL satisfied per `_check_confirmation`)
- Already provided by the v2 collector — no further filter needed

## Checkpoints studied

`T_d ∈ {0, 30, 60, 90, 120, 300, 600}` seconds from `signal_time`.

`T=0` is the baseline ("enter immediately at the first 30s bar after
HH/LL confirmation"). All other T values are the delayed-entry
treatments.

## Matched cohort rule (load-bearing)

For each `T_d > 0`, the comparison is restricted to **events that
have a valid (alive_at_T, fillable_at_T=True) row at BOTH T=0 and
T_d**. This isolates the delay effect from the survivor effect.

Without this rule, late-T populations are silently selected for "didn't
die fast", which would re-create the survivor bias from the v1-era
work (April 2026 lessons).

For each event in the matched cohort, the study has two paired
outcomes:
- **T=0 outcome**: bracket / regime-exit PnL when entering at T=0
- **T_d outcome**: bracket / regime-exit PnL when entering at T_d

Both share the same `regime_exit_price` (the event's terminal close)
but differ in `fill_price` (different entry prices).

## Endpoints

For each (T_d, stratum), report:

| Endpoint | Source | Why |
|---|---|---|
| `regime_exit_pnl_dollars` (mean, median) | label table | Pure hold-to-flip economics |
| `pt100_before_sl100` rate | label table | 1:1 R/R bracket success |
| `pt150_before_sl100` rate | label table | 1.5:1 R/R bracket success |
| `pt200_before_sl100` rate | label table | 2:1 R/R bracket success |
| `mfe_300s_atr` (mean, median) | label table | Path quality at 5-min horizon |
| `mae_60s_atr` (mean, median) | label table | First-minute downside |
| `clean_path_300s` rate | label table | Clean trade rate |
| `fast_fail_60s` rate | label table | First-minute disaster rate |

## Strata

- **All** — population baseline
- **RTH** vs **ETH** — `is_rth_checkpoint`
- **Long** vs **Short** — `signal_direction`
- **RTH × Long, RTH × Short, ETH × Long, ETH × Short** — full 2×2

## Reading the result

For each T_d, the question is:

> Does the matched-cohort delta (T_d outcome − T=0 outcome) suggest
> waiting improves trade quality enough to be worth the lost-events
> cost?

Sign of the delta determines whether to keep investigating:
- All deltas near zero or negative → delay doesn't help, stop here
- Clear positive delta on bracket / clean-path metrics → ML ranking
  within the matched cohort might exploit the pattern
- Mixed: positive on path quality but negative on fill timing → study
  the tradeoff curve before ML

## Output

- `results/matched_cohort_long.parquet` — one row per (event_id, T_d) in
  matched cohort, with both T=0 and T_d label values side-by-side
- `results/descriptive_table.parquet` — aggregated table (T_d × stratum
  × endpoint)
- `results/REPORT.md` — written summary with the descriptive table and
  initial recommendation on whether to proceed to ML

## Out of scope (phase 1)

- ML ranking models — that's phase 2 if descriptive results justify it
- Custom bracket designs beyond the 4 already in the v2 contract
- Tick-level execution simulation — v2 labels are sufficient for first
  cut

## Files

- `collect.py` — pulls v2 parquets, builds matched cohort table
- `analyze.py` — descriptive analysis + table generation + report
- `run_study.py` — CLI orchestrator
