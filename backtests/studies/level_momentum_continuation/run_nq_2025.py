"""Level Momentum Continuation — NQ 2025 (RTH + ETH stratified).

Loads NQ.v.0 1s data from data/raw/NQ_v0_1s_2025.parquet, resamples
to 1m bars, detects Goldilocks-filtered level breach triggers,
simulates forward, and writes report + per-trade CSVs.

Runs TWO passes for transparency:
  1. NO roll filter (per user spec — they asked for .v.0 thinking
     it has no rolls; empirically it does, ~200-242pt at quarterly
     rolls, so this output may be contaminated by phantom target
     hits on trades open at the roll moment).
  2. WITH ±3-day roll filter (around 3rd Thu Mar/Jun/Sep/Dec).

Outputs:
    studies/level_momentum_continuation/results_nq_2025/
        report.md
        trades_unfiltered.csv
        trades_rollfiltered.csv
        agg_overall.csv / agg_pair.csv / agg_session.csv /
        agg_pair_session.csv
"""
from __future__ import annotations

import os, sys
from pathlib import Path
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from studies.level_momentum_continuation.level_study import (
    load_v0_1s, resample_1s_to_1m, annotate_sessions_ct,
    filter_roll_window, detect_triggers, simulate_trade,
    trades_to_df, aggregate_stats, by_pair, by_session,
    by_pair_and_session,
)

V0_PARQUET = Path("data/raw/NQ_v0_1s_2025.parquet")
OUT = Path("studies/level_momentum_continuation/results_nq_2025")
OUT.mkdir(parents=True, exist_ok=True)


def run_pipeline(bars_1m: pd.DataFrame, label: str) -> dict:
    # Reset index once so both detect_triggers and simulate_trade
    # see ts_close as a column with consistent positional indexing.
    bars_reset = bars_1m.reset_index(drop=False)
    print(f"\n[{label}] detecting triggers...")
    triggers = detect_triggers(bars_reset)
    print(f"[{label}] {len(triggers):,} triggers found")
    print(f"[{label}] simulating trades (max 120 bars hold)...")
    outcomes = []
    for t in triggers:
        o = simulate_trade(t, bars_reset, max_bars=120)
        if o is not None:
            outcomes.append(o)
    trades = trades_to_df(outcomes)
    print(f"[{label}] {len(trades):,} trades simulated")
    return {"trades": trades, "n_triggers": len(triggers)}


def fmt_p(v):
    if v is None or pd.isna(v): return "—"
    return f"{100*v:.2f}%"


def fmt_f(v, dp=2):
    if v is None or pd.isna(v): return "—"
    return f"{v:.{dp}f}"


def main():
    print("=" * 70)
    print("Level Momentum Continuation — NQ 2025 (.v.0 1s -> 1m)")
    print("=" * 70)

    print(f"\nLoading {V0_PARQUET}...")
    bars_1s = load_v0_1s(V0_PARQUET)
    print(f"  loaded {len(bars_1s):,} 1s bars "
          f"[{bars_1s.index[0]} .. {bars_1s.index[-1]}]")
    print("Resampling 1s -> 1m...")
    bars_1m = resample_1s_to_1m(bars_1s)
    print(f"  resampled to {len(bars_1m):,} 1m bars")
    bars_1m = annotate_sessions_ct(bars_1m)
    n_rth = int((bars_1m["session"] == "RTH").sum())
    n_eth = int((bars_1m["session"] == "ETH").sum())
    print(f"  RTH bars: {n_rth:,}   ETH bars: {n_eth:,}")

    # Pass 1: unfiltered
    res_unf = run_pipeline(bars_1m, "UNFILTERED")
    # Pass 2: roll-filtered
    bars_rf, dropped = filter_roll_window(bars_1m, window_days=3)
    print(f"\n[ROLLFILTER] dropped {dropped:,} bars from "
          "+/-3 day windows around quarterly rolls")
    res_rf = run_pipeline(bars_rf, "ROLLFILTERED")

    # Save trades + aggregates
    print("\nWriting outputs...")
    res_unf["trades"].to_csv(OUT / "trades_unfiltered.csv",
                                    index=False)
    res_rf["trades"].to_csv(OUT / "trades_rollfiltered.csv",
                                  index=False)

    # Aggregate stats per pass
    for tag, res in [("unfiltered", res_unf),
                          ("rollfiltered", res_rf)]:
        trades = res["trades"]
        if len(trades) == 0:
            print(f"  {tag}: empty, skipping aggregates")
            continue
        ovr = aggregate_stats(trades)
        pd.DataFrame([ovr]).to_csv(
            OUT / f"agg_overall_{tag}.csv", index=False)
        by_pair(trades).to_csv(
            OUT / f"agg_pair_{tag}.csv", index=False)
        by_session(trades).to_csv(
            OUT / f"agg_session_{tag}.csv", index=False)
        by_pair_and_session(trades).to_csv(
            OUT / f"agg_pair_session_{tag}.csv", index=False)

    # Build markdown report
    lines = []
    lines.append("# Level Momentum Continuation — NQ 2025\n")
    lines.append(f"Run: {pd.Timestamp.now(tz='UTC').isoformat()}\n")
    lines.append("## Source")
    lines.append(f"- File: `{V0_PARQUET}`")
    lines.append(f"- Symbol: NQ.v.0 (volume-roll continuous)")
    lines.append(f"- Schema: ohlcv-1s, resampled to 1m")
    lines.append(f"- 1s bars: {len(bars_1s):,}")
    lines.append(f"- 1m bars: {len(bars_1m):,} "
                  f"(RTH={n_rth:,}, ETH={n_eth:,})\n")

    lines.append("## Method")
    lines.append("- Levels: 00, 11, 25, 50, 75, 90 within each "
                  "100-pt handle; sequence wraps across handles")
    lines.append("- Long trigger: 1m close strictly above a level "
                  "where prior close was below")
    lines.append("- Short trigger: 1m close strictly below a level "
                  "where prior close was above")
    lines.append("- Goldilocks filter: close must lie strictly in "
                  "the LOWER half of the move toward (next level - "
                  "10 ticks)")
    lines.append("- Multi-level breach in single bar: take the "
                  "LATEST qualifying level (highest for long, "
                  "lowest for short)")
    lines.append("- Re-entry: every Goldilocks-qualifying close is "
                  "an independent trigger")
    lines.append("- Entry: open of the bar AFTER the trigger "
                  "(causal)")
    lines.append("- Stop: level ONE PRIOR in sequence (e.g. long "
                  "50→75 stops at 25)")
    lines.append("- Exit priority within a bar: stop-out beats "
                  "target (conservative)")
    lines.append("- Time limit: 120 bars (120 min); marked to "
                  "bar-120 close at expiry\n")

    lines.append("## Roll discontinuity finding")
    lines.append("Empirical check on NQ.v.0 1s data resampled to "
                  "1m: quarterly rolls produce single-bar gaps of "
                  "~200-242 pts (similar magnitude and dates as "
                  ".c.0). The 4 rolls in 2025: ")
    lines.append("- 2025-03-19 19:01 CT: 200.75 pt gap")
    lines.append("- 2025-06-22 17:00 CT: 275.00 pt gap (also "
                  "captured as roll-window contamination)")
    lines.append("- 2025-09-17 19:00 CT: 242.75 pt gap")
    lines.append("- 2025-12-16 18:00 CT: 237.50 pt gap\n")
    lines.append("The Goldilocks filter naturally rejects entries "
                  "ON these gap bars (close is far past the "
                  "midpoint), but trades that were already OPEN "
                  "when a roll occurs can be falsely closed at "
                  "target/stop by the gap. Two passes are reported "
                  "below to quantify the contamination.\n")

    for tag, res in [("UNFILTERED (per user spec)", res_unf),
                          ("ROLL-FILTERED (±3 days around quarterly rolls)",
                           res_rf)]:
        trades = res["trades"]
        lines.append(f"## {tag}")
        if len(trades) == 0:
            lines.append("No trades.\n")
            continue
        ovr = aggregate_stats(trades)
        lines.append(f"- Triggers detected: {res['n_triggers']:,}")
        lines.append(f"- Trades simulated: {ovr['n']:,}")
        lines.append(f"- **Win rate: {fmt_p(ovr['win_rate'])}**")
        lines.append(f"- Loss rate: {fmt_p(ovr['loss_rate'])}")
        lines.append(f"- Timed-out: {fmt_p(ovr['timed_out_rate'])}"
                      f"  (positive: {ovr['timed_out_positive']}, "
                      f"negative: {ovr['timed_out_negative']})")
        lines.append(f"- Avg time to target (winners): "
                      f"{fmt_f(ovr['avg_time_to_target_min'], 1)} min")
        lines.append(f"- Mean PnL: {fmt_f(ovr['mean_pnl_pts'], 2)} "
                      f"pts/trade  (median "
                      f"{fmt_f(ovr['median_pnl_pts'], 2)})")
        lines.append(f"- Mean MAE (all): "
                      f"{fmt_f(ovr['mean_mae_pts_all'], 2)} pts; "
                      f"wins-only "
                      f"{fmt_f(ovr['mean_mae_pts_wins'], 2)}; "
                      f"losses-only "
                      f"{fmt_f(ovr['mean_mae_pts_losses'], 2)}\n")

        # By session
        sess_df = by_session(trades)
        lines.append("### By session\n")
        lines.append("| Session | n | WinR | LossR | TimedOut | "
                     "MeanPnL | AvgTimeToTgt(min) | MeanMAE(all) |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
        for _, r in sess_df.iterrows():
            lines.append(
                f"| {r['entry_session']} | {int(r['n']):,} | "
                f"{fmt_p(r['win_rate'])} | "
                f"{fmt_p(r['loss_rate'])} | "
                f"{fmt_p(r['timed_out_rate'])} | "
                f"{fmt_f(r['mean_pnl_pts'], 2)} | "
                f"{fmt_f(r['avg_time_to_target_min'], 1)} | "
                f"{fmt_f(r['mean_mae_pts_all'], 2)} |")
        lines.append("")

        # By pair (overall) — sorted by n desc
        pair_df = by_pair(trades).sort_values("n", ascending=False)
        lines.append("### By level pair (overall, sorted by n)\n")
        lines.append("| Pair | n | WinR | LossR | TimedOut | "
                     "MeanPnL | AvgTime(min) | MeanMAE |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
        for _, r in pair_df.iterrows():
            lines.append(
                f"| {r['level_pair']} | {int(r['n']):,} | "
                f"{fmt_p(r['win_rate'])} | "
                f"{fmt_p(r['loss_rate'])} | "
                f"{fmt_p(r['timed_out_rate'])} | "
                f"{fmt_f(r['mean_pnl_pts'], 2)} | "
                f"{fmt_f(r['avg_time_to_target_min'], 1)} | "
                f"{fmt_f(r['mean_mae_pts_all'], 2)} |")
        lines.append("")

        # By pair × session
        ps_df = by_pair_and_session(trades).sort_values(
            ["level_pair", "entry_session"])
        lines.append("### By level pair × session\n")
        lines.append("| Pair | Session | n | WinR | LossR | "
                     "TimedOut | MeanPnL | AvgTime(min) |")
        lines.append("|---|---|--:|--:|--:|--:|--:|--:|")
        for _, r in ps_df.iterrows():
            lines.append(
                f"| {r['level_pair']} | {r['entry_session']} | "
                f"{int(r['n']):,} | "
                f"{fmt_p(r['win_rate'])} | "
                f"{fmt_p(r['loss_rate'])} | "
                f"{fmt_p(r['timed_out_rate'])} | "
                f"{fmt_f(r['mean_pnl_pts'], 2)} | "
                f"{fmt_f(r['avg_time_to_target_min'], 1)} |")
        lines.append("")

    (OUT / "report.md").write_text("\n".join(lines),
                                            encoding="utf-8")
    print(f"\nReport: {OUT / 'report.md'}")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
