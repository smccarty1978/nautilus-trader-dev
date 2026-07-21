"""Apply the frozen R0/R1/R2/R4 rank-skip policies (threshold and exemption
logic NOT re-derived/altered) to the corrected F2 primary-window population
(canonical 30s-delay entry, corrected 08:30-15:00 CT RTH, pending-entry
cancellations preserved as first-class non-trade records).

Per-episode accounting (for every policy p in r0/r1/r2/r4):
  {p}_keep       - filter decision (score-based skip, independent of
                    whether the entry would later be canceled)
  {p}_skip       = ~keep
  {p}_status     - 'filter_skipped' | 'pending_entry_canceled' | 'filled'
                    (only meaningful when keep=True; 'filter_skipped' when
                    keep=False)
  {p}_net_pnl    - real PnL if filled-and-kept; 0.0 if filter_skipped or
                    kept-but-canceled (no capital was ever at risk in the
                    canceled case, which is the correct $0 contribution to
                    aggregate EV -- NOT the same as fabricating PnL for a
                    trade that happened, since none did)
"""
import numpy as np
import pandas as pd
from common import OUT, load_atlas, repair_f2_window, load_frozen_config, PRIMARY_START, PRIMARY_END


def build():
    df_atlas = load_atlas()
    signals, terminal_viol = repair_f2_window(df_atlas, PRIMARY_START, PRIMARY_END)
    frozen = load_frozen_config()

    thr = frozen["score_thresholds_test"]["R1"]
    for p in ("R1", "R2", "R4"):
        assert frozen["score_thresholds_test"][p] == thr, f"{p} threshold diverges from frozen R1 threshold"
        assert frozen["best_percentiles"][p] == 10, f"{p} frozen percentile is not top-10%"

    # exclude data-quality dropouts (missing_replay_bar) from all trading
    # economics -- a raw-data lookup limitation, not a trading mechanic.
    ep = signals[signals["trade_status"] != "missing_replay_bar"].copy()

    ep["frozen_score"] = ep["ridge_log_fail_prob"]
    ep["frozen_threshold"] = thr

    score_skip = ep["frozen_score"] >= thr
    strong_migration = ep["seq_5r_center_migration_slope_atr"] > 0.005   # frozen R2 exemption, unaltered
    fav_dominate = ep["seq_5r_asym_duration"] > 1.5                       # frozen R4 exemption, unaltered

    ep["r0_keep"] = True
    ep["r1_keep"] = ~score_skip
    ep["r2_keep"] = ~score_skip | strong_migration
    ep["r4_keep"] = ~score_skip | fav_dominate

    for p in ("r0", "r1", "r2", "r4"):
        keep = ep[f"{p}_keep"]
        ep[f"{p}_skip"] = ~keep
        status = np.where(~keep, "filter_skipped", ep["trade_status"])
        ep[f"{p}_status"] = status
        ep[f"{p}_net_pnl"] = np.where(status == "filled", ep["baseline_pnl"], 0.0)

    out_cols = [
        "episode_id", "confirmation_ts", "decision_ts", "expected_fill_ts", "actual_fill_ts",
        "chicago_local_ts", "month", "direction", "session",
        "entry_price", "atr", "seconds_in_current_ordering",
        "frozen_score", "frozen_threshold", "baseline_pnl", "trade_status",
        "r0_keep", "r0_skip", "r0_status", "r0_net_pnl",
        "r1_keep", "r1_skip", "r1_status", "r1_net_pnl",
        "r2_keep", "r2_skip", "r2_status", "r2_net_pnl",
        "r4_keep", "r4_skip", "r4_status", "r4_net_pnl",
        "exit_type", "opposing_flip_time", "ep_end_time",
    ]
    out_cols = [c for c in dict.fromkeys(out_cols) if c in ep.columns]
    out = ep[out_cols].copy()
    out.to_parquet(OUT / "corrected_episode_results.parquet", index=False)

    print(f"eligible confirmed signals (excl missing_replay_bar): {len(out)}  "
          f"pending_entry_canceled: {(out['trade_status']=='pending_entry_canceled').sum()}  "
          f"r1_skipped: {out['r1_skip'].sum()}  r2_skipped: {out['r2_skip'].sum()}  r4_skipped: {out['r4_skip'].sum()}")
    return out


if __name__ == "__main__":
    import os
    from common import PROJECT_ROOT
    os.chdir(PROJECT_ROOT)
    build()
