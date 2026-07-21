"""Phase 14: Canonical event-driven replay spot-check.

Cached tables (flip_context_atlas.parquet) were used for all prior phases'
economics. This phase independently verifies, against the RAW 1-second
market data (not a pandas post-hoc join of pre-computed columns), that for a
deterministic sample of R0/R1-eligible episodes:
  1. entry_price == the raw open of the 1s bar at entry_ts (next-1s-open fill)
  2. exit_price is consistent with the raw OHLC bar at exit_ts (within the
     bar's [low, high] for a stop fill, or equals that bar's open for a
     regime-exit/timeout fill)
  3. pnl_base == direction * (exit_price - entry_price) * $20/pt - $5 commission
     (the documented NQ_MULTIPLIER / commission formula)
This does not re-derive the stop price from raw flip detection (out of scope
per the repair brief: no raw 1s feature-pipeline rerun), but it does confirm
the cached entry/exit fills and PnL arithmetic are genuine market-consistent
values, not an artifact of the caching/join process.
"""
import numpy as np
import pandas as pd
from common import OUT, PROJECT_ROOT, load_atlas, repair_and_build_f2
from center_sampling_reconciliation import year_file

NQ_MULTIPLIER = 20.0
N_SAMPLE_PER_PERIOD = 40


def run():
    df_atlas = load_atlas()
    f2_clean, _ = repair_and_build_f2(df_atlas)

    sample_rows = []
    for role, g in f2_clean.groupby("period_role"):
        idx = np.linspace(0, len(g) - 1, min(N_SAMPLE_PER_PERIOD, len(g))).astype(int)
        sample_rows.append(g.sort_values("episode_id").iloc[idx])
    sample = pd.concat(sample_rows)

    year_cache = {}
    results = []
    for _, ep in sample.iterrows():
        entry_ts = pd.Timestamp(int(ep["observation_time"]), unit="ns", tz="UTC")
        exit_ts = pd.Timestamp(int(ep["baseline_exit_ts"] if "baseline_exit_ts" in ep else ep["ep_end_time"]), unit="ns", tz="UTC")
        yr = entry_ts.year
        if yr not in year_cache:
            p = year_file(yr)
            if not p.exists():
                continue
            year_cache[yr] = pd.read_parquet(p, columns=["open", "high", "low", "close"])
        df_yr = year_cache[yr]

        # Raw 1s data is sparse (rows only emitted when the market prints), so
        # exact-second lookups frequently miss. build_flip_atlas.py fills via
        # `.loc[ts:end]` range slices, whose first row is the first index
        # AT-OR-AFTER ts -- i.e. forward/backfill, not backward-pad.
        idx = df_yr.index
        i_entry = idx.get_indexer([entry_ts], method="backfill")[0]
        i_exit = idx.get_indexer([exit_ts], method="backfill")[0]
        if i_entry < 0 or i_exit < 0:
            results.append({"episode_id": ep["episode_id"], "period_role": ep["period_role"],
                             "entry_bar_found": False, "exit_bar_found": False,
                             "entry_price_match": False, "exit_price_consistent": False, "pnl_arith_match": False})
            continue
        entry_bar = df_yr.iloc[i_entry]
        exit_bar = df_yr.iloc[i_exit]

        entry_price_match = bool(abs(float(entry_bar["open"]) - float(ep["entry_price"])) < 1e-6)

        exit_price = float(ep["exit_price"]) if "exit_price" in ep else float(ep["baseline_exit_price"])
        exit_type = ep.get("exit_type", "")
        if exit_type == "stop":
            exit_price_consistent = bool(float(exit_bar["low"]) - 1e-6 <= exit_price <= float(exit_bar["high"]) + 1e-6) or \
                                     bool(abs(float(exit_bar["open"]) - exit_price) < 1e-6)
        else:
            exit_price_consistent = bool(abs(float(exit_bar["open"]) - exit_price) < 1e-6)

        direction = int(ep["direction"])
        expected_pnl = direction * (exit_price - float(ep["entry_price"])) * NQ_MULTIPLIER - 5.0
        pnl_arith_match = bool(abs(expected_pnl - float(ep["pnl_base"])) < 1e-6)

        results.append({
            "episode_id": ep["episode_id"], "period_role": ep["period_role"],
            "entry_bar_found": True, "exit_bar_found": True,
            "entry_price_match": entry_price_match,
            "exit_price_consistent": exit_price_consistent,
            "pnl_arith_match": pnl_arith_match,
        })

    df = pd.DataFrame(results)
    df.to_parquet(OUT / "canonical_replay_spotcheck.parquet", index=False)

    summary = {
        "n_sampled": len(df),
        "entry_price_match_rate": float(df["entry_price_match"].mean()),
        "exit_price_consistent_rate": float(df["exit_price_consistent"].mean()),
        "pnl_arith_match_rate": float(df["pnl_arith_match"].mean()),
    }
    print(summary)
    return df, summary


if __name__ == "__main__":
    import os
    os.chdir(PROJECT_ROOT)
    run()
