"""T_A2 threshold sensitivity + drawdown investigation.

Part 1 — sweep 48 cells of (unrealized_pnl × current_mfe_atr × elapsed_t):
  unrealized_pnl < {-50, -100, -150, -200}
  current_mfe_atr < {0.15, 0.25, 0.35}
  elapsed_t in {+2m, +3m, +4m, +5m}  (each ±30s window)

For each cell, compute Δ vs baseline per year and across all years.

Part 2 — drawdown investigation:
Reload baseline (no overlay) and T_A2 (-100, 0.25, +3m) per-trade results.
Compute monthly cumulative net PnL for each. Identify months where T_A2
DD got WORSE than baseline. Inspect the trade clusters in those months.

Goal: confirm T_A2 isn't razor-edge AND identify what drives its DD
increase.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

NQ_MULT = 20.0
COMMISSION = 5.0

WINDOWS = {
    "fast":    5 * 60,
    "medium": 15 * 60,
    "slow":   30 * 60,
}
TICK_INTERVAL_S = 30
SLOW_LO_CUT = 43.00
SLOW_HI_CUT = 71.75

OUT = Path("studies/v_a_excursion_regime/results_v0")

UNREAL_THRESHOLDS = [-50.0, -100.0, -150.0, -200.0]
MFE_THRESHOLDS = [0.15, 0.25, 0.35]
ELAPSED_TIMES_S = [120, 180, 240, 300]   # +2m, +3m, +4m, +5m


def load_year_bars(year: int):
    parts = []
    files_for_year = {
        2024: ["data/raw/NQ_v0_1s_2023.parquet",
                "data/raw/NQ_v0_1s_2024.parquet"],
        2025: ["data/raw/NQ_v0_1s_2024.parquet",
                "data/raw/NQ_v0_1s_2025.parquet"],
        2026: ["data/raw/NQ_v0_1s_2025.parquet",
                "data/raw/NQ_v0_1s_2026_ytd.parquet"],
    }
    for f in files_for_year[year]:
        if Path(f).exists():
            df = pd.read_parquet(f, columns=["open","high","low","close"])
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            parts.append(df)
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    return bars


def trade_state_at_tick(tick_ts_ns, direction, atr, ts_index_ns,
                          opens, highs, lows, closes, entry_ts_ns,
                          fill_price):
    j_lo = np.searchsorted(ts_index_ns, entry_ts_ns, side="left")
    j_hi = np.searchsorted(ts_index_ns, tick_ts_ns, side="left")
    if j_hi <= j_lo:
        return None
    seg_h = highs[j_lo:j_hi]
    seg_l = lows[j_lo:j_hi]
    seg_c = closes[j_hi - 1]
    if direction == 1:
        cur_mfe = float(seg_h.max() - fill_price)
        cur_mae = float(fill_price - seg_l.min())
        unrealized_pts = float(seg_c - fill_price)
    else:
        cur_mfe = float(fill_price - seg_l.min())
        cur_mae = float(seg_h.max() - fill_price)
        unrealized_pts = float(fill_price - seg_c)
    fill_at_next_bar = float(opens[j_hi]) if j_hi < len(opens) else np.nan
    return {
        "current_mfe_atr": cur_mfe / max(atr, 0.01),
        "current_mae_atr": cur_mae / max(atr, 0.01),
        "unrealized_pnl": unrealized_pts * NQ_MULT,
        "fill_at_next_bar": fill_at_next_bar,
    }


def compute_alt_pnl(direction, fill_price, alt_exit_px):
    if pd.isna(alt_exit_px): return np.nan
    if direction == 1:
        pts = alt_exit_px - fill_price
    else:
        pts = fill_price - alt_exit_px
    return pts * NQ_MULT - 2 * COMMISSION


def add_drawdown(df, pnl_col):
    df = df.sort_values("entry_ts").copy()
    df["cum"] = df[pnl_col].cumsum()
    df["cum_max"] = df["cum"].cummax()
    df["dd"] = df["cum"] - df["cum_max"]
    return df


def yearly_metrics(df, pnl_col):
    if not len(df): return {}
    n = len(df)
    wins = (df[pnl_col] > 0).sum()
    net = df[pnl_col].sum()
    df_dd = add_drawdown(df, pnl_col)
    max_dd = df_dd["dd"].min()
    return {"n": n, "wr_pct": wins / n * 100, "net_pnl": net,
            "per_trade": net / n, "max_dd": max_dd}


def compute_tertile_cuts(dfs):
    is_combined = pd.concat(
        [dfs[yr] for yr in (2024, 2025) if yr in dfs], ignore_index=True)
    return is_combined["total_excursion_slow"].quantile([1/3, 2/3]).values


def tertile_label(v, lo, hi):
    if pd.isna(v): return np.nan
    if v < lo: return "low"
    if v < hi: return "mid"
    return "high"


def part1_sweep():
    """Sweep 48 cells of T_A2 variants and report Δ vs baseline."""
    print("=" * 78)
    print("PART 1 — T_A2 threshold sensitivity sweep (48 cells)")
    print("=" * 78)

    # Load filtered trades
    dfs = {}
    for yr in (2024, 2025, 2026):
        p = OUT / f"v_a_v0_{yr}_with_excursion.parquet"
        dfs[yr] = pd.read_parquet(p)
    lo_cut, hi_cut = compute_tertile_cuts(dfs)

    # For each year, walk each filtered trade and at each elapsed_t
    # compute trade-state. Then for each cell, evaluate trigger.
    all_results = []
    for yr in (2024, 2025, 2026):
        d = dfs[yr].copy()
        d["bkt"] = d["total_excursion_slow"].apply(
            lambda v: tertile_label(v, lo_cut, hi_cut))
        filtered = d[d["bkt"] == "mid"].copy().reset_index(drop=True)
        print(f"\n  Year {yr}: walking {len(filtered):,} filtered trades",
              flush=True)
        bars = load_year_bars(yr)
        ts_index_ns = bars.index.astype("int64").to_numpy()
        opens = bars["open"].values.astype(np.float64)
        highs = bars["high"].values.astype(np.float64)
        lows = bars["low"].values.astype(np.float64)
        closes = bars["close"].values.astype(np.float64)

        rows = []
        t0 = time.time()
        for i, tr in filtered.iterrows():
            entry_ns = int(tr["entry_ts"])
            exit_ns = int(tr["exit_ts"])
            direction = int(tr["direction"])
            atr = float(tr["atr_at_signal"])
            fill_px = float(tr["fill_price"])

            # Get trade-state at each elapsed_t (single tick, not window)
            states = {}
            for et_s in ELAPSED_TIMES_S:
                tick_ns = entry_ns + et_s * 1_000_000_000
                if tick_ns >= exit_ns:
                    states[et_s] = None
                    continue
                states[et_s] = trade_state_at_tick(
                    tick_ns, direction, atr, ts_index_ns,
                    opens, highs, lows, closes, entry_ns, fill_px)

            row = {
                "year": yr,
                "trade_idx": i,
                "direction": direction,
                "fill_price": fill_px,
                "entry_ts": entry_ns,
                "exit_ts": exit_ns,
                "baseline_net_pnl": float(tr["net_pnl"]),
            }
            # Evaluate every (unr, mfe, et) cell
            for unr_t in UNREAL_THRESHOLDS:
                for mfe_t in MFE_THRESHOLDS:
                    for et_s in ELAPSED_TIMES_S:
                        cell_name = f"unr{int(unr_t)}_mfe{int(mfe_t*100)}_t{et_s}"
                        s = states.get(et_s)
                        if s is None:
                            row[f"{cell_name}_pnl"] = float(tr["net_pnl"])
                            row[f"{cell_name}_fired"] = False
                            continue
                        if (s["unrealized_pnl"] < unr_t
                                and s["current_mfe_atr"] < mfe_t):
                            alt_pnl = compute_alt_pnl(
                                direction, fill_px, s["fill_at_next_bar"])
                            row[f"{cell_name}_pnl"] = alt_pnl
                            row[f"{cell_name}_fired"] = True
                        else:
                            row[f"{cell_name}_pnl"] = float(tr["net_pnl"])
                            row[f"{cell_name}_fired"] = False
            rows.append(row)
            if i and i % 250 == 0:
                print(f"    {i}/{len(filtered)} elapsed {time.time()-t0:.0f}s",
                      flush=True)

        all_results.append(pd.DataFrame(rows))
        print(f"    year {yr} done in {time.time()-t0:.0f}s", flush=True)

    full = pd.concat(all_results, ignore_index=True)
    full.to_parquet(OUT / "t_a2_sweep_results.parquet")

    # Build summary
    print(f"\n{'='*78}")
    print("CELL-BY-CELL Δ vs BASELINE")
    print(f"{'='*78}")
    rows = []
    for unr_t in UNREAL_THRESHOLDS:
        for mfe_t in MFE_THRESHOLDS:
            for et_s in ELAPSED_TIMES_S:
                cell_name = f"unr{int(unr_t)}_mfe{int(mfe_t*100)}_t{et_s}"
                pnl_col = f"{cell_name}_pnl"
                fire_col = f"{cell_name}_fired"
                # Per-year deltas
                row = {"unr": unr_t, "mfe_atr": mfe_t, "elapsed_s": et_s}
                for yr in (2024, 2025, 2026):
                    sub = full[full["year"] == yr]
                    base_net = sub["baseline_net_pnl"].sum()
                    cell_net = sub[pnl_col].sum()
                    row[f"{yr}_base"] = base_net
                    row[f"{yr}_cell"] = cell_net
                    row[f"{yr}_delta"] = cell_net - base_net
                    row[f"{yr}_fire_pct"] = sub[fire_col].mean() * 100
                row["all_base"] = full["baseline_net_pnl"].sum()
                row["all_cell"] = full[pnl_col].sum()
                row["all_delta"] = row["all_cell"] - row["all_base"]
                # Pass user gate: improves 2026 AND total positive
                row["passes_gate"] = (row["2026_delta"] > 0
                                          and row["all_delta"] > 0
                                          and row["2024_delta"] > -3000
                                          and row["2025_delta"] > -10000)
                rows.append(row)
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT / "t_a2_sweep_summary.csv", index=False)

    print(f"\n  {'unr':>5} {'mfe':>5} {'elap':>5} {'fire%24':>7} "
          f"{'fire%26':>7} {'2024Δ':>9} {'2025Δ':>9} {'2026Δ':>9} "
          f"{'allΔ':>9} {'gate':>5}")
    for _, r in summary.iterrows():
        gate = "✓" if r["passes_gate"] else "-"
        print(f"  {r['unr']:>+5.0f} {r['mfe_atr']:>5.2f} "
              f"{int(r['elapsed_s']):>5} "
              f"{r['2024_fire_pct']:>6.1f}% "
              f"{r['2026_fire_pct']:>6.1f}% "
              f"{r['2024_delta']:>+8,.0f} {r['2025_delta']:>+8,.0f} "
              f"{r['2026_delta']:>+8,.0f} {r['all_delta']:>+8,.0f} "
              f"{gate:>5}")

    # Best cells
    print(f"\n--- TOP 10 cells by all_delta (only gate-passing) ---")
    survivors = summary[summary["passes_gate"]].nlargest(10, "all_delta")
    print(survivors[["unr", "mfe_atr", "elapsed_s", "2024_delta",
                       "2025_delta", "2026_delta", "all_delta"]].to_string(
        index=False, float_format="%.0f"))


def part2_dd_investigation():
    """Investigate why T_A2 max DD got worse despite higher net PnL."""
    print(f"\n\n{'='*78}")
    print("PART 2 — Drawdown investigation: T_A2 (unr=-100, mfe=0.25, +3m)")
    print(f"{'='*78}")

    df = pd.read_parquet(OUT / "trigger_overlay_results.parquet")
    df["entry_dt"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True)
    df["month"] = df["entry_dt"].dt.tz_convert("UTC").dt.to_period("M")
    df = df.sort_values("entry_ts").reset_index(drop=True)

    # Cumulative PnL series
    df["cum_baseline"] = df["baseline_net_pnl"].cumsum()
    df["cum_T_A2"] = df["T_A2_underwater_3m_net_pnl"].cumsum()
    df["cum_max_baseline"] = df["cum_baseline"].cummax()
    df["cum_max_T_A2"] = df["cum_T_A2"].cummax()
    df["dd_baseline"] = df["cum_baseline"] - df["cum_max_baseline"]
    df["dd_T_A2"] = df["cum_T_A2"] - df["cum_max_T_A2"]

    print(f"  Baseline 3yr max DD: ${df['dd_baseline'].min():+,.0f}")
    print(f"  T_A2     3yr max DD: ${df['dd_T_A2'].min():+,.0f}")
    print(f"  Δ DD: ${df['dd_T_A2'].min() - df['dd_baseline'].min():+,.0f}")

    # When did each max DD occur?
    base_dd_idx = df["dd_baseline"].idxmin()
    ta2_dd_idx = df["dd_T_A2"].idxmin()
    print(f"\n  Baseline max DD occurred at trade idx {base_dd_idx} "
          f"({df.loc[base_dd_idx, 'entry_dt'].strftime('%Y-%m-%d %H:%M')})")
    print(f"  T_A2     max DD occurred at trade idx {ta2_dd_idx} "
          f"({df.loc[ta2_dd_idx, 'entry_dt'].strftime('%Y-%m-%d %H:%M')})")

    # Monthly DD comparison
    print(f"\n--- Monthly max DD: baseline vs T_A2 ---")
    rows = []
    for month, g in df.groupby("month"):
        g = g.copy()
        g["m_cum_b"] = g["baseline_net_pnl"].cumsum()
        g["m_cum_t"] = g["T_A2_underwater_3m_net_pnl"].cumsum()
        g["m_dd_b"] = g["m_cum_b"] - g["m_cum_b"].cummax()
        g["m_dd_t"] = g["m_cum_t"] - g["m_cum_t"].cummax()
        rows.append({
            "month": str(month),
            "n": len(g),
            "base_net": g["baseline_net_pnl"].sum(),
            "ta2_net": g["T_A2_underwater_3m_net_pnl"].sum(),
            "base_dd": g["m_dd_b"].min(),
            "ta2_dd": g["m_dd_t"].min(),
            "fired": g["T_A2_underwater_3m_fire_ts"].notna().sum(),
        })
    mdf = pd.DataFrame(rows)
    mdf["dd_diff"] = mdf["ta2_dd"] - mdf["base_dd"]   # negative = T_A2 worse
    mdf["pnl_diff"] = mdf["ta2_net"] - mdf["base_net"]
    mdf.to_csv(OUT / "t_a2_monthly_dd.csv", index=False)

    # Worst months for T_A2 vs baseline DD
    worst = mdf.nsmallest(8, "dd_diff")
    print(f"\n  Months where T_A2 DD got WORSE than baseline (top 8):")
    print(f"  {'month':<10} {'n':>4} {'fired':>5} {'base_dd':>9} "
          f"{'ta2_dd':>9} {'ddΔ':>8} {'pnlΔ':>8}")
    for _, r in worst.iterrows():
        print(f"  {r['month']:<10} {int(r['n']):>4,} {int(r['fired']):>5,} "
              f"{r['base_dd']:>+8,.0f} {r['ta2_dd']:>+8,.0f} "
              f"{r['dd_diff']:>+7,.0f} {r['pnl_diff']:>+7,.0f}")

    # Best months for T_A2 vs baseline DD
    best = mdf.nlargest(8, "dd_diff")
    print(f"\n  Months where T_A2 DD got BETTER than baseline (top 8):")
    print(f"  {'month':<10} {'n':>4} {'fired':>5} {'base_dd':>9} "
          f"{'ta2_dd':>9} {'ddΔ':>8} {'pnlΔ':>8}")
    for _, r in best.iterrows():
        print(f"  {r['month']:<10} {int(r['n']):>4,} {int(r['fired']):>5,} "
              f"{r['base_dd']:>+8,.0f} {r['ta2_dd']:>+8,.0f} "
              f"{r['dd_diff']:>+7,.0f} {r['pnl_diff']:>+7,.0f}")

    # Investigate the worst T_A2 DD month — what trades fired and what
    # was their alternate vs baseline outcome?
    worst_month = worst.iloc[0]["month"]
    print(f"\n--- Trades in worst-DD-Δ month {worst_month} that T_A2 fired on ---")
    sub = df[(df["month"] == pd.Period(worst_month))
                & df["T_A2_underwater_3m_fire_ts"].notna()].copy()
    sub["alt_minus_baseline"] = (sub["T_A2_underwater_3m_net_pnl"]
                                       - sub["baseline_net_pnl"])
    print(f"  {'entry_dt':<19} {'dir':>3} {'baseline':>9} "
          f"{'T_A2':>9} {'Δ':>9}")
    for _, r in sub.iterrows():
        print(f"  {r['entry_dt'].strftime('%Y-%m-%d %H:%M:%S'):<19} "
              f"{r['direction']:>+3} "
              f"{r['baseline_net_pnl']:>+8,.0f} "
              f"{r['T_A2_underwater_3m_net_pnl']:>+8,.0f} "
              f"{r['alt_minus_baseline']:>+8,.0f}")

    # Aggregate: when T_A2 fires, what's the average Δ vs baseline?
    fired_only = df[df["T_A2_underwater_3m_fire_ts"].notna()].copy()
    fired_only["delta"] = (fired_only["T_A2_underwater_3m_net_pnl"]
                              - fired_only["baseline_net_pnl"])
    print(f"\n--- T_A2 fired-only trades ({len(fired_only):,}) ---")
    print(f"  Mean Δ vs baseline: ${fired_only['delta'].mean():+,.2f}")
    print(f"  Median Δ vs baseline: ${fired_only['delta'].median():+,.2f}")
    print(f"  Trades T_A2 saved (Δ > 0): {(fired_only['delta'] > 0).sum()} "
          f"({(fired_only['delta'] > 0).mean()*100:.1f}%)")
    print(f"  Trades T_A2 hurt   (Δ < 0): {(fired_only['delta'] < 0).sum()} "
          f"({(fired_only['delta'] < 0).mean()*100:.1f}%)")


def main():
    t0 = time.time()
    part1_sweep()
    part2_dd_investigation()
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
