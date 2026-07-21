"""V_A filtered exit overlay backtests — 6 user-spec triggers + 2
Tier-A diagnostic-derived triggers.

For each filtered trade (total_excursion_slow=mid), walk forward in
30-second steps from entry to exit. At each tick, evaluate every
trigger condition. The FIRST tick a trigger fires becomes the exit
candidate for that trigger.

Exit fill: OPEN of the next 1s bar AFTER the trigger fires. NT-style.

Triggers tested:
  T1: ratio_xfast < 0.8  (fast ratio failure, fine 2.5m window)
  T2: ratio_xfast < 0.5 AND ratio_fast < 0.5  (regime inversion)
  T3: efficiency_xfast < 0.3  (efficiency collapse)
  T4: mae_xfast > mfe_xfast  (adverse > favorable in last 2.5m)
  T5: total_excursion_slow leaves [43, 71.75) bucket  (IS-derived cuts)
  T6: current_mfe_atr < 1.0 AND ratio_xfast < 0.8  (no-progress + bad regime)
  T_A1: at the +2m checkpoint, current_mae_atr > 1.0 AND current_mfe_atr
        < 0.25  (DOA killer — Tier A from diagnostics)
  T_A2: at the +3m checkpoint, unrealized_pnl < -100 AND current_mfe_atr
        < 0.25  (underwater stall — Tier A)

Per-year reporting:
  baseline (no overlay) vs each trigger overlay:
    n trades, WR, net PnL, $/tr, max DD,
    positive months, median monthly PnL

Causality: every feature read uses ONLY 1s bars with ts_event < tick_ts.
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
COMMISSION = 5.0  # net_pnl convention is gross - $10 round-trip

WINDOWS = {
    "fast":    5 * 60,
    "medium": 15 * 60,
    "slow":   30 * 60,
    "xfast":   5 * 30,
    "xmedium": 15 * 30,
    "xslow":   30 * 30,
}
MIN_BARS_PER_WINDOW = 60
TICK_INTERVAL_S = 30
SLOW_LO_CUT = 43.00
SLOW_HI_CUT = 71.75

OUT = Path("studies/v_a_excursion_regime/results_v0")
OUT.mkdir(parents=True, exist_ok=True)


def compute_tertile_cuts(dfs):
    is_combined = pd.concat(
        [dfs[yr] for yr in (2024, 2025) if yr in dfs], ignore_index=True)
    return is_combined["total_excursion_slow"].quantile([1/3, 2/3]).values


def tertile_label(v, lo, hi):
    if pd.isna(v): return np.nan
    if v < lo: return "low"
    if v < hi: return "mid"
    return "high"


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


def features_at_tick(tick_ts_ns, direction, atr, ts_index_ns,
                       opens, highs, lows, closes, entry_ts_ns, fill_price):
    """Compute trade-state and 6-window features at tick_ts_ns.
    Returns dict.
    """
    out = {}

    # 6 windows
    for win_name, win_secs in WINDOWS.items():
        win_start_ns = tick_ts_ns - win_secs * 1_000_000_000
        i_lo = np.searchsorted(ts_index_ns, win_start_ns, side="left")
        i_hi = np.searchsorted(ts_index_ns, tick_ts_ns, side="left")
        if i_hi - i_lo < MIN_BARS_PER_WINDOW:
            for k in ("mfe", "mae", "ratio", "total_excursion",
                       "efficiency", "net_move"):
                out[f"{k}_{win_name}"] = np.nan
            continue
        anchor_open = float(opens[i_lo])
        hi = float(highs[i_lo:i_hi].max())
        lo = float(lows[i_lo:i_hi].min())
        close_now = float(closes[i_hi - 1])
        if direction == 1:
            mfe = hi - anchor_open
            mae = anchor_open - lo
        else:
            mfe = anchor_open - lo
            mae = hi - anchor_open
        ratio = mfe / max(mae, 0.25)
        total_exc = mfe + mae
        eff = abs(close_now - anchor_open) / max(total_exc, 0.25)
        net = (close_now - anchor_open) if direction == 1 else (
            anchor_open - close_now)
        out[f"mfe_{win_name}"] = mfe
        out[f"mae_{win_name}"] = mae
        out[f"ratio_{win_name}"] = ratio
        out[f"total_excursion_{win_name}"] = total_exc
        out[f"efficiency_{win_name}"] = eff
        out[f"net_move_{win_name}"] = net

    # Trade-state
    j_lo = np.searchsorted(ts_index_ns, entry_ts_ns, side="left")
    j_hi = np.searchsorted(ts_index_ns, tick_ts_ns, side="left")
    if j_hi > j_lo:
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
        out["current_mfe_atr"] = cur_mfe / max(atr, 0.01)
        out["current_mae_atr"] = cur_mae / max(atr, 0.01)
        out["unrealized_pnl"] = unrealized_pts * NQ_MULT
        out["close_now"] = float(seg_c)
        out["fill_at_next_bar"] = (
            float(opens[j_hi]) if j_hi < len(opens) else np.nan)
    else:
        out["current_mfe_atr"] = 0.0
        out["current_mae_atr"] = 0.0
        out["unrealized_pnl"] = 0.0
        out["close_now"] = np.nan
        out["fill_at_next_bar"] = np.nan
    return out


# ---------------- Trigger evaluators ----------------

def fires_T1(f):  # ratio_xfast < 0.8
    return f.get("ratio_xfast", np.inf) < 0.8


def fires_T2(f):  # ratio_xfast < 0.5 AND ratio_fast < 0.5
    return (f.get("ratio_xfast", np.inf) < 0.5
              and f.get("ratio_fast", np.inf) < 0.5)


def fires_T3(f):  # efficiency_xfast < 0.3
    return f.get("efficiency_xfast", np.inf) < 0.3


def fires_T4(f):  # mae_xfast > mfe_xfast
    mae = f.get("mae_xfast", -np.inf)
    mfe = f.get("mfe_xfast", np.inf)
    if pd.isna(mae) or pd.isna(mfe): return False
    return mae > mfe


def fires_T5(f):  # total_excursion_slow leaves mid
    v = f.get("total_excursion_slow", np.nan)
    if pd.isna(v): return False
    return v < SLOW_LO_CUT or v >= SLOW_HI_CUT


def fires_T6(f):  # current_mfe_atr < 1.0 AND ratio_xfast < 0.8
    return (f.get("current_mfe_atr", np.inf) < 1.0
              and f.get("ratio_xfast", np.inf) < 0.8)


# Tier-A: only fire at specific elapsed time
def fires_T_A1(f, elapsed_s):
    if abs(elapsed_s - 120) > 30: return False  # only at +2m ±30s
    return (f.get("current_mae_atr", -np.inf) > 1.0
              and f.get("current_mfe_atr", np.inf) < 0.25)


def fires_T_A2(f, elapsed_s):
    if abs(elapsed_s - 180) > 30: return False  # only at +3m ±30s
    return (f.get("unrealized_pnl", np.inf) < -100
              and f.get("current_mfe_atr", np.inf) < 0.25)


TRIGGERS_CONTINUOUS = {
    "T1_fast_ratio_fail": fires_T1,
    "T2_regime_inversion": fires_T2,
    "T3_efficiency_collapse": fires_T3,
    "T4_adverse_dominant": fires_T4,
    "T5_slow_leaves_mid": fires_T5,
    "T6_noprog_bad_regime": fires_T6,
}
TRIGGERS_TIMED = {
    "T_A1_doa_2m": fires_T_A1,
    "T_A2_underwater_3m": fires_T_A2,
}


def process_trade(tr, ts_index_ns, opens, highs, lows, closes):
    """Walk a trade in 30s steps. For each trigger, record first-fire
    tick_ts and the alternate exit price (next 1s bar's open).
    """
    entry_ns = int(tr["entry_ts"])
    exit_ns = int(tr["exit_ts"])
    direction = int(tr["direction"])
    atr = float(tr["atr_at_signal"])
    fill_px = float(tr["fill_price"])

    # Don't evaluate before entry; warmup needed for windows
    first_tick_ns = entry_ns + TICK_INTERVAL_S * 1_000_000_000

    triggers = {name: {"fire_ts": None, "fire_px": None}
                  for name in (list(TRIGGERS_CONTINUOUS) +
                                list(TRIGGERS_TIMED))}

    tick_ns = first_tick_ns
    while tick_ns < exit_ns:
        f = features_at_tick(
            tick_ns, direction, atr, ts_index_ns,
            opens, highs, lows, closes, entry_ns, fill_px)
        elapsed_s = (tick_ns - entry_ns) // 1_000_000_000

        for name, fn in TRIGGERS_CONTINUOUS.items():
            if triggers[name]["fire_ts"] is None and fn(f):
                triggers[name]["fire_ts"] = tick_ns
                triggers[name]["fire_px"] = f.get("fill_at_next_bar")
        for name, fn in TRIGGERS_TIMED.items():
            if triggers[name]["fire_ts"] is None and fn(f, elapsed_s):
                triggers[name]["fire_ts"] = tick_ns
                triggers[name]["fire_px"] = f.get("fill_at_next_bar")

        tick_ns += TICK_INTERVAL_S * 1_000_000_000

    return triggers


def compute_alt_pnl(direction, fill_price, alt_exit_px):
    """Net PnL with $10 round-trip commission, point-to-dollar = NQ_MULT."""
    if pd.isna(alt_exit_px): return np.nan
    if direction == 1:
        pts = alt_exit_px - fill_price
    else:
        pts = fill_price - alt_exit_px
    return pts * NQ_MULT - 2 * COMMISSION


def add_drawdown(df, pnl_col="net_pnl"):
    df = df.sort_values("entry_ts").copy()
    df["cum"] = df[pnl_col].cumsum()
    df["cum_max"] = df["cum"].cummax()
    df["dd"] = df["cum"] - df["cum_max"]
    return df


def yearly_metrics(df, pnl_col):
    if not len(df) or pnl_col not in df.columns:
        return {}
    n = len(df)
    wins = (df[pnl_col] > 0).sum()
    net = df[pnl_col].sum()
    df_dd = add_drawdown(df, pnl_col)
    max_dd = df_dd["dd"].min()
    df = df.copy()
    df["entry_dt"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True)
    df["month"] = df["entry_dt"].dt.tz_convert("UTC").dt.to_period("M")
    monthly = df.groupby("month")[pnl_col].sum()
    pos_months = (monthly > 0).sum()
    return {
        "n": n,
        "wr_pct": wins / n * 100,
        "net_pnl": net,
        "per_trade": net / n,
        "max_dd": max_dd,
        "pos_months": pos_months,
        "total_months": len(monthly),
        "median_monthly_pnl": monthly.median(),
    }


def main():
    t0 = time.time()
    print("=" * 78)
    print("V_A FILTERED EXIT OVERLAY BACKTESTS")
    print("=" * 78)

    # Load filtered trades from with_excursion parquets
    dfs = {}
    for yr in (2024, 2025, 2026):
        p = OUT / f"v_a_v0_{yr}_with_excursion.parquet"
        dfs[yr] = pd.read_parquet(p)
    lo_cut, hi_cut = compute_tertile_cuts(dfs)
    print(f"Tertile cuts (2024+2025): low/mid={lo_cut:.2f}, "
          f"mid/high={hi_cut:.2f}")

    all_results = []  # per-trade per-trigger fire info

    for yr in (2024, 2025, 2026):
        d = dfs[yr].copy()
        d["bkt"] = d["total_excursion_slow"].apply(
            lambda v: tertile_label(v, lo_cut, hi_cut))
        filtered = d[d["bkt"] == "mid"].copy().reset_index(drop=True)
        print(f"\n=== Year {yr}: {len(filtered):,} filtered trades ===",
              flush=True)
        bars = load_year_bars(yr)
        ts_index_ns = bars.index.astype("int64").to_numpy()
        opens = bars["open"].values.astype(np.float64)
        highs = bars["high"].values.astype(np.float64)
        lows = bars["low"].values.astype(np.float64)
        closes = bars["close"].values.astype(np.float64)

        rows = []
        t1 = time.time()
        for i, tr in filtered.iterrows():
            triggers = process_trade(
                tr, ts_index_ns, opens, highs, lows, closes)
            row = {
                "year": yr,
                "trade_idx": i,
                "direction": int(tr["direction"]),
                "fill_price": float(tr["fill_price"]),
                "entry_ts": int(tr["entry_ts"]),
                "exit_ts": int(tr["exit_ts"]),
                "exit_price": float(tr["exit_price"]),
                "baseline_net_pnl": float(tr["net_pnl"]),
                "atr_at_signal": float(tr["atr_at_signal"]),
                "running_mfe": float(tr["running_mfe"]),
                "running_mae": float(tr["running_mae"]),
                "hold_s": float(tr["hold_s"]),
            }
            for name, info in triggers.items():
                row[f"{name}_fire_ts"] = info["fire_ts"]
                row[f"{name}_fire_px"] = info["fire_px"]
                if info["fire_ts"] is not None and info["fire_px"] is not None:
                    alt_pnl = compute_alt_pnl(
                        int(tr["direction"]),
                        float(tr["fill_price"]),
                        float(info["fire_px"]))
                    row[f"{name}_net_pnl"] = alt_pnl
                else:
                    row[f"{name}_net_pnl"] = float(tr["net_pnl"])
            rows.append(row)
            if i and i % 250 == 0:
                print(f"   {i}/{len(filtered)}  elapsed "
                      f"{time.time()-t1:.0f}s", flush=True)

        year_df = pd.DataFrame(rows)
        all_results.append(year_df)
        print(f"   year {yr} done in {time.time()-t1:.0f}s", flush=True)

    full = pd.concat(all_results, ignore_index=True)
    full.to_parquet(OUT / "trigger_overlay_results.parquet")
    print(f"\nWrote per-trade results: {OUT / 'trigger_overlay_results.parquet'}",
          flush=True)

    # ---------------- Per-year performance per trigger ----------------
    print(f"\n{'='*78}")
    print("PER-YEAR PERFORMANCE — baseline vs each trigger overlay")
    print(f"{'='*78}")
    triggers = list(TRIGGERS_CONTINUOUS.keys()) + list(TRIGGERS_TIMED.keys())

    summary_rows = []
    for yr in (2024, 2025, 2026):
        sub = full[full["year"] == yr]
        if not len(sub): continue
        # baseline
        m = yearly_metrics(sub, "baseline_net_pnl")
        m["year"] = yr; m["overlay"] = "baseline"
        summary_rows.append(m)
        # each trigger
        for tname in triggers:
            col = f"{tname}_net_pnl"
            m = yearly_metrics(sub, col)
            m["year"] = yr; m["overlay"] = tname
            summary_rows.append(m)

    summ = pd.DataFrame(summary_rows)
    summ.to_csv(OUT / "trigger_overlay_yearly.csv", index=False)

    # Print per-year tables
    for yr in (2024, 2025, 2026):
        s = summ[summ["year"] == yr]
        if not len(s): continue
        baseline = s[s["overlay"] == "baseline"].iloc[0]
        print(f"\n--- {yr} ---")
        print(f"  {'overlay':<26} {'n':>5} {'WR%':>5} {'net':>10} "
              f"{'$/tr':>7} {'maxDD':>10} {'posM':>5} {'medM':>9} "
              f"{'Δ_net':>9}")
        for _, r in s.iterrows():
            d = r["net_pnl"] - baseline["net_pnl"]
            d_str = f"{d:>+9,.0f}" if r["overlay"] != "baseline" else "ref"
            print(f"  {r['overlay']:<26} {int(r['n']):>5,} "
                  f"{r['wr_pct']:>4.1f}% {r['net_pnl']:>+9,.0f} "
                  f"{r['per_trade']:>+6.1f} "
                  f"{r['max_dd']:>+9,.0f} "
                  f"{int(r['pos_months']):>2}/{int(r['total_months']):>2} "
                  f"{r['median_monthly_pnl']:>+8,.0f} "
                  f"{d_str:>9}")

    # Across-year roll-up
    print(f"\n--- ALL YEARS ---")
    for tname in ["baseline"] + triggers:
        col = "baseline_net_pnl" if tname == "baseline" else f"{tname}_net_pnl"
        m = yearly_metrics(full, col)
        if not m: continue
        print(f"  {tname:<26} n={int(m['n']):>5,}  "
              f"WR={m['wr_pct']:.1f}%  net ${m['net_pnl']:+,.0f}  "
              f"$/tr {m['per_trade']:+.1f}  "
              f"maxDD ${m['max_dd']:+,.0f}  "
              f"posM {int(m['pos_months'])}/{int(m['total_months'])}")

    # Trigger fire-rate diagnostic
    print(f"\n{'='*78}")
    print("TRIGGER FIRE RATES (per year)")
    print(f"{'='*78}")
    for tname in triggers:
        col = f"{tname}_fire_ts"
        for yr in (2024, 2025, 2026):
            sub = full[full["year"] == yr]
            n = len(sub)
            fired = sub[col].notna().sum()
            print(f"  {tname:<26} {yr}: fired on "
                  f"{fired:,}/{n:,} trades ({100*fired/n:.1f}%)")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
