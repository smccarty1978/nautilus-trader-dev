"""End-to-end pipeline re-run for no-delay V_A trades.

After collectors/collector_v2/run_v_a_year_v0_nodelay.py finishes
for all 3 years, this script:

  1. Reads v_a_v0_nodelay_{year}/trades.parquet
  2. Recomputes checkpoint features at +5m and +7m
     (matches checkpoint_filter_search.py logic)
  3. Saves to checkpoint_features_nodelay.parquet
  4. Runs matched comparison report (delayed-only, C, E variants)
     against the no-delay trades
  5. Compares no-delay vs original (with-delay) C result

This keeps the original data intact for side-by-side comparison.
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
EPS = 1e-6

CHECKPOINTS_S = [300, 420]
CHECKPOINT_LABELS = ["5m", "7m"]

OUT = Path("studies/v_a_excursion_regime/results_v0")
TRADES_DIR_TEMPLATE = "collectors/collector_v2/results/v_a_v0_nodelay_{}"


def load_year_bars(year):
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


def compute_features(entry_ts, cp_ts, direction, atr, fill_px,
                       ts_idx, opens, highs, lows, closes):
    j_lo = np.searchsorted(ts_idx, entry_ts, side="left")
    j_hi = np.searchsorted(ts_idx, cp_ts, side="left")
    if j_hi <= j_lo: return None
    seg_h = highs[j_lo:j_hi]
    seg_l = lows[j_lo:j_hi]
    seg_c = closes[j_hi - 1]
    if direction == 1:
        cur_mfe = float(seg_h.max() - fill_px)
        cur_mae = float(fill_px - seg_l.min())
        unr_pts = float(seg_c - fill_px)
        if seg_h.max() - seg_l.min() > EPS:
            close_loc = ((float(seg_c) - float(seg_l.min()))
                         / float(seg_h.max() - seg_l.min()))
        else:
            close_loc = 0.5
    else:
        cur_mfe = float(fill_px - seg_l.min())
        cur_mae = float(seg_h.max() - fill_px)
        unr_pts = float(fill_px - seg_c)
        if seg_h.max() - seg_l.min() > EPS:
            close_loc = ((float(seg_h.max()) - float(seg_c))
                         / float(seg_h.max() - seg_l.min()))
        else:
            close_loc = 0.5
    out = {
        "f_mfe_atr_T": cur_mfe / max(atr, 0.01),
        "f_mae_atr_T": cur_mae / max(atr, 0.01),
        "f_unr_pnl_T": unr_pts * NQ_MULT,
        "f_mfe_to_mae": ((cur_mfe / max(atr, 0.01))
                          / max(cur_mae / max(atr, 0.01), 0.01)),
        "f_close_loc_in_range": close_loc,
    }
    for win_s, name in [(30, "30s"), (60, "60s"),
                          (150, "150s"), (300, "300s")]:
        win_start = cp_ts - win_s * 1_000_000_000
        i_lo = np.searchsorted(ts_idx, win_start, side="left")
        if j_hi - i_lo < max(10, win_s // 3):
            out[f"f_net_move_{name}"] = np.nan
            continue
        anc = float(opens[i_lo])
        cn = float(closes[j_hi - 1])
        out[f"f_net_move_{name}"] = (
            (cn - anc) if direction == 1 else (anc - cn))
    out["f_atr"] = atr
    out["f_direction"] = direction
    return out


def collect_features():
    rows = []
    for yr in (2024, 2025, 2026):
        trades_path = Path(TRADES_DIR_TEMPLATE.format(yr)) / "trades.parquet"
        if not trades_path.exists():
            print(f"  WARN: missing {trades_path}, skipping {yr}")
            continue
        print(f"  loading {yr}...", flush=True)
        trades = pd.read_parquet(trades_path)
        bars = load_year_bars(yr)
        ts_idx = bars.index.astype("int64").to_numpy()
        opens = bars["open"].values.astype(np.float64)
        highs = bars["high"].values.astype(np.float64)
        lows = bars["low"].values.astype(np.float64)
        closes = bars["close"].values.astype(np.float64)

        for _, tr in trades.iterrows():
            entry_ts = int(tr["entry_ts"])
            exit_ts = int(tr["exit_ts"])
            direction = int(tr["direction"])
            atr = float(tr["atr_at_signal"])
            fill_px = float(tr["fill_price"])
            exit_px = float(tr["exit_price"])
            net_pnl = float(tr["net_pnl"])

            row = {
                "year": yr, "entry_ts": entry_ts, "exit_ts": exit_ts,
                "direction": direction, "atr": atr,
                "fill_px": fill_px, "exit_px": exit_px,
                "f_hour_utc": pd.Timestamp(entry_ts, unit="ns",
                                              tz="UTC").hour,
                "baseline_pnl": net_pnl,
            }

            for cp_s, cp_lab in zip(CHECKPOINTS_S, CHECKPOINT_LABELS):
                cp_ts = entry_ts + cp_s * 1_000_000_000
                if cp_ts >= exit_ts:
                    row[f"alive_{cp_lab}"] = False
                    row[f"d_pnl_{cp_lab}"] = 0.0
                    continue
                j_hi = np.searchsorted(ts_idx, cp_ts, side="left")
                if j_hi >= len(opens):
                    row[f"alive_{cp_lab}"] = False
                    row[f"d_pnl_{cp_lab}"] = 0.0
                    continue
                price_at_cp = float(opens[j_hi])
                if direction == 1:
                    pts = exit_px - price_at_cp
                else:
                    pts = price_at_cp - exit_px
                d_pnl = pts * NQ_MULT - 2 * COMMISSION
                row[f"alive_{cp_lab}"] = True
                row[f"d_pnl_{cp_lab}"] = d_pnl
                row[f"price_at_cp_{cp_lab}"] = price_at_cp
                feats = compute_features(
                    entry_ts, cp_ts, direction, atr, fill_px,
                    ts_idx, opens, highs, lows, closes)
                if feats:
                    for k, v in feats.items():
                        row[f"{k}_{cp_lab}"] = v
            rows.append(row)
    return pd.DataFrame(rows)


def metrics(df, pnl_col, ts_col="entry_ts"):
    if not len(df):
        return {"n": 0, "total": 0.0, "per_tr": 0.0, "wr_pct": 0.0,
                "max_dd": 0.0, "y2024": 0.0, "y2025": 0.0,
                "y2026": 0.0, "pos_months": 0, "total_months": 0}
    df = df.sort_values(ts_col).copy()
    total = df[pnl_col].sum()
    n = len(df)
    wr_pct = (df[pnl_col] > 0).mean() * 100
    df["cum"] = df[pnl_col].cumsum()
    df["cum_max"] = df["cum"].cummax()
    max_dd = float((df["cum"] - df["cum_max"]).min())
    y = df.groupby("year")[pnl_col].sum()
    df["entry_dt"] = pd.to_datetime(df[ts_col], unit="ns", utc=True)
    df["month"] = df["entry_dt"].dt.to_period("M")
    monthly = df.groupby("month")[pnl_col].sum()
    return {
        "n": n, "total": float(total), "per_tr": float(total / n),
        "wr_pct": float(wr_pct), "max_dd": max_dd,
        "y2024": float(y.get(2024, 0.0)),
        "y2025": float(y.get(2025, 0.0)),
        "y2026": float(y.get(2026, 0.0)),
        "pos_months": int((monthly > 0).sum()),
        "total_months": int(len(monthly)),
    }


def main():
    t0 = time.time()
    print("=" * 78)
    print("NO-DELAY V_A: REBUILD FEATURES + COMPARE C/E vs ORIGINAL")
    print("=" * 78)

    feats_path = OUT / "checkpoint_features_nodelay.parquet"
    if feats_path.exists():
        print("\nLoading cached no-delay features...")
        df = pd.read_parquet(feats_path)
    else:
        print("\nComputing no-delay features...")
        df = collect_features()
        df.to_parquet(feats_path)
    n_pre = len(df)
    df = df.sort_values(["entry_ts", "year"]).drop_duplicates(
        subset="entry_ts", keep="first").reset_index(drop=True)
    if n_pre != len(df):
        print(f"  deduped: {n_pre:,} -> {len(df):,}")
    print(f"\n  no-delay V_A trades: {len(df):,}")

    # Add ATR-normalized feature
    df["f_unr_atr_T_5m"] = df["f_unr_pnl_T_5m"] / (df["atr"] * NQ_MULT)

    # IS-fit thresholds
    is_alive_5m = df[df["alive_5m"] & df["year"].isin([2024, 2025])
                       & df["f_unr_pnl_T_5m"].notna()]
    thr_dollar = is_alive_5m["f_unr_pnl_T_5m"].quantile(0.80)
    is_alive_7m = df[df["alive_7m"] & df["year"].isin([2024, 2025])
                       & df["f_net_move_150s_7m"].notna()
                       & df["f_net_move_300s_7m"].notna()]
    thr_150 = is_alive_7m["f_net_move_150s_7m"].quantile(0.10)
    thr_300 = is_alive_7m["f_net_move_300s_7m"].quantile(0.20)
    print(f"\n  IS-fit thresholds (no-delay data):")
    print(f"    C: f_unr_pnl_T_5m >= ${thr_dollar:.0f}  "
          f"(was $325 with delay)")
    print(f"    E: f_net_move_150s_7m >= ${thr_150:.2f}, "
          f"f_net_move_300s_7m >= ${thr_300:.2f}")

    # Build cohorts
    alive_5m = df[df["alive_5m"]].copy()
    alive_7m = df[df["alive_7m"]].copy()
    c_mask = alive_5m["f_unr_pnl_T_5m"] >= thr_dollar
    c_atr_mask = alive_5m["f_unr_atr_T_5m"] >= 0.75
    e_mask = ((alive_7m["f_net_move_150s_7m"] >= thr_150)
                & (alive_7m["f_net_move_300s_7m"] >= thr_300))

    # Reports
    full_T0 = metrics(df, "baseline_pnl")
    A5m = metrics(alive_5m, "baseline_pnl")
    B = metrics(alive_5m, "d_pnl_5m")
    C = metrics(alive_5m[c_mask], "d_pnl_5m")
    C_atr = metrics(alive_5m[c_atr_mask], "d_pnl_5m")
    A7m = metrics(alive_7m, "baseline_pnl")
    D = metrics(alive_7m, "d_pnl_7m")
    E = metrics(alive_7m[e_mask], "d_pnl_7m")

    print(f"\n{'='*120}")
    print("NO-DELAY V_A RESULTS")
    print(f"{'='*120}")
    print(f"  {'strategy':<42}  {'n':>5}  {'total$':>11}  {'$/tr':>7}  "
          f"{'max DD':>10}  {'2024':>10}  {'2025':>10}  {'2026':>10}  "
          f"{'+mo':>6}")
    print("  " + "-" * 118)

    def pr(label, m):
        pos = f"{m['pos_months']}/{m['total_months']}"
        print(f"  {label:<42}  {m['n']:>5,}  ${m['total']:>+10,.0f}  "
              f"{m['per_tr']:>+6.2f}  ${m['max_dd']:>+8,.0f}  "
              f"${m['y2024']:>+8,.0f}  ${m['y2025']:>+8,.0f}  "
              f"${m['y2026']:>+8,.0f}  {pos:>6}")

    pr("Full V_A baseline 1c T0", full_T0)
    print()
    pr("A_5m matched T0 (alive@5m)", A5m)
    pr("B delayed-only @+5m", B)
    pr(f"C delayed @+5m + unr >= ${thr_dollar:.0f}", C)
    pr("C-ATR delayed @+5m + atr >= 0.75", C_atr)
    print()
    pr("A_7m matched T0 (alive@7m)", A7m)
    pr("D delayed-only @+7m", D)
    pr("E delayed @+7m + dual momentum", E)

    # Compare to original (with-delay) results
    # Load original checkpoint_features
    orig_path = OUT / "checkpoint_features.parquet"
    if orig_path.exists():
        orig = pd.read_parquet(orig_path)
        orig = orig.sort_values(["entry_ts", "year"]).drop_duplicates(
            subset="entry_ts", keep="first")
        is_o = orig[orig["alive_5m"] & orig["year"].isin([2024, 2025])]
        thr_o = is_o["f_unr_pnl_T_5m"].quantile(0.80)
        c_orig_mask = orig[orig["alive_5m"]]["f_unr_pnl_T_5m"] >= thr_o
        C_orig = metrics(orig[orig["alive_5m"]][c_orig_mask], "d_pnl_5m")
        baseline_orig = metrics(orig, "baseline_pnl")

        print(f"\n{'='*120}")
        print("HEAD-TO-HEAD: NO-DELAY vs ORIGINAL (30s delay)")
        print(f"{'='*120}")
        print(f"  {'metric':<40}  {'no-delay':>14}  {'original':>14}  "
              f"{'Δ':>10}")
        print("  " + "-" * 88)
        for label, m_new, m_old in [
            ("Full V_A baseline n", full_T0, baseline_orig),
            ("Full V_A baseline total $", full_T0, baseline_orig),
            ("Full V_A baseline $/tr", full_T0, baseline_orig),
            ("Full V_A 2024", full_T0, baseline_orig),
            ("Full V_A 2025", full_T0, baseline_orig),
            ("Full V_A 2026", full_T0, baseline_orig),
            ("C cohort n", C, C_orig),
            ("C total $", C, C_orig),
            ("C $/tr", C, C_orig),
            ("C 2024", C, C_orig),
            ("C 2025", C, C_orig),
            ("C 2026", C, C_orig),
            ("C +mo / total", C, C_orig),
        ]:
            if "n" in label and "/" not in label:
                print(f"  {label:<40}  {m_new['n']:>14,}  "
                      f"{m_old['n']:>14,}  {m_new['n']-m_old['n']:>+10,}")
            elif "total $" in label:
                print(f"  {label:<40}  ${m_new['total']:>+12,.0f}  "
                      f"${m_old['total']:>+12,.0f}  "
                      f"${m_new['total']-m_old['total']:>+8,.0f}")
            elif "$/tr" in label:
                print(f"  {label:<40}  {m_new['per_tr']:>+14.2f}  "
                      f"{m_old['per_tr']:>+14.2f}  "
                      f"{m_new['per_tr']-m_old['per_tr']:>+10.2f}")
            elif "2024" in label:
                print(f"  {label:<40}  ${m_new['y2024']:>+12,.0f}  "
                      f"${m_old['y2024']:>+12,.0f}  "
                      f"${m_new['y2024']-m_old['y2024']:>+8,.0f}")
            elif "2025" in label:
                print(f"  {label:<40}  ${m_new['y2025']:>+12,.0f}  "
                      f"${m_old['y2025']:>+12,.0f}  "
                      f"${m_new['y2025']-m_old['y2025']:>+8,.0f}")
            elif "2026" in label:
                print(f"  {label:<40}  ${m_new['y2026']:>+12,.0f}  "
                      f"${m_old['y2026']:>+12,.0f}  "
                      f"${m_new['y2026']-m_old['y2026']:>+8,.0f}")
            elif "+mo" in label:
                print(f"  {label:<40}  "
                      f"{m_new['pos_months']}/{m_new['total_months']:<11}  "
                      f"{m_old['pos_months']}/{m_old['total_months']}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
