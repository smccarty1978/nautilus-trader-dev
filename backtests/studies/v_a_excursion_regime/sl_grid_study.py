"""Catastrophic SL grid study — V_A + total_excursion_slow=mid + V4 +
hard SL at entry.

For each filtered V_A trade, place an SL at entry at:
    long:  SL = fill_price - SL_mult * atr_at_signal
    short: SL = fill_price + SL_mult * atr_at_signal

SL grid: [0.5, 0.75, 1.0, 1.25, 1.5] × ATR

Stack precedence (earliest fire wins, evaluated chronologically):
  1. SL hits before V4 candidate (+3m) → SL exit at SL level (exact fill)
  2. V4 candidate at +3m + confirm at +4m → V4 exit at next 1s OPEN
  3. SL hits between +4m and regime exit → SL exit at SL level
  4. None → regime exit (baseline)

Note: SL is "always-on" — it fires whenever it hits, regardless of
checkpoint. V4 only fires at +3m/+4m. Detection on 1s bars (low/high
crosses SL).

Causality:
  - SL hits when 1s bar low (long) or high (short) crosses SL level
  - SL_ts = ts_event of the bar where SL was hit
  - V4 evaluation uses bars strictly before checkpoint
  - Earliest fire wins → if SL hits at, say, +90s but V4 fires at +4m,
    SL exit applies (since SL_ts < V4_ts)

Reports:
  - Per-year n, WR, $/tr, gross/net, max DD for each SL multiple
  - Per-class (C1 runners cut, C5 losers caught) at each SL multiple
  - Fire breakdown: SL fires, V4 fires (when SL didn't fire first),
    regime exits
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
SLOW_LO_CUT = 43.00
SLOW_HI_CUT = 71.75
SL_GRID = [0.5, 0.75, 1.0, 1.25, 1.5]

OUT = Path("studies/v_a_excursion_regime/results_v0")


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


def find_sl_hit(direction, sl_level, entry_ts, exit_ts,
                  ts_idx, highs, lows):
    """Find first 1s bar in [entry_ts, exit_ts) where SL is breached.
    Returns (hit_ts, None) or (None, None) if no hit before exit.
    Long: low <= SL. Short: high >= SL.
    """
    i_lo = np.searchsorted(ts_idx, entry_ts, side="left")
    i_hi = np.searchsorted(ts_idx, exit_ts, side="left")
    if i_hi <= i_lo:
        return None
    if direction == 1:
        seg_low = lows[i_lo:i_hi]
        hit_mask = seg_low <= sl_level
    else:
        seg_high = highs[i_lo:i_hi]
        hit_mask = seg_high >= sl_level
    if not hit_mask.any():
        return None
    first_hit_idx = i_lo + int(np.argmax(hit_mask))
    return int(ts_idx[first_hit_idx])


def evaluate_v4(direction, atr, fill_px, entry_ts, exit_ts,
                  ts_idx, opens, highs, lows, closes):
    """V4: candidate at +3m (unr<-50 AND mfe<0.25); confirm at +4m
    (unr<0 AND mfe<0.35 AND xfast_net<0). Exit at OPEN of bar at +4m.
    Returns (fired, fire_ts, fill_at_4m) or (False, None, None).
    """
    ts_3m = entry_ts + 180 * 1_000_000_000
    ts_4m = entry_ts + 240 * 1_000_000_000
    if ts_3m >= exit_ts or ts_4m >= exit_ts:
        return False, None, None

    j_entry = np.searchsorted(ts_idx, entry_ts, side="left")
    j_3m = np.searchsorted(ts_idx, ts_3m, side="left")
    if j_3m <= j_entry:
        return False, None, None

    seg_h = highs[j_entry:j_3m]
    seg_l = lows[j_entry:j_3m]
    seg_c = closes[j_3m - 1]
    if direction == 1:
        cur_mfe = float(seg_h.max() - fill_px)
        cur_mae = float(fill_px - seg_l.min())
        unr_pts = float(seg_c - fill_px)
    else:
        cur_mfe = float(fill_px - seg_l.min())
        cur_mae = float(seg_h.max() - fill_px)
        unr_pts = float(fill_px - seg_c)
    if not (unr_pts * NQ_MULT < -50
              and cur_mfe / max(atr, 0.01) < 0.25):
        return False, None, None

    # Candidate fired — check confirm at +4m
    j_4m = np.searchsorted(ts_idx, ts_4m, side="left")
    if j_4m <= j_entry:
        return False, None, None
    seg_h4 = highs[j_entry:j_4m]
    seg_l4 = lows[j_entry:j_4m]
    seg_c4 = closes[j_4m - 1]
    if direction == 1:
        cur_mfe4 = float(seg_h4.max() - fill_px)
        unr_pts4 = float(seg_c4 - fill_px)
    else:
        cur_mfe4 = float(fill_px - seg_l4.min())
        unr_pts4 = float(fill_px - seg_c4)
    # xfast_net 2.5min
    win_start = ts_4m - 150 * 1_000_000_000
    i_xf_lo = np.searchsorted(ts_idx, win_start, side="left")
    if j_4m <= i_xf_lo:
        return False, None, None
    anc = float(opens[i_xf_lo])
    cn = float(closes[j_4m - 1])
    xfast_net = (cn - anc) if direction == 1 else (anc - cn)
    if not (unr_pts4 * NQ_MULT < 0
              and cur_mfe4 / max(atr, 0.01) < 0.35
              and xfast_net < 0):
        return False, None, None

    # Confirmed — fill at OPEN of next bar at-or-after +4m
    if j_4m >= len(opens):
        return False, None, None
    return True, ts_4m, float(opens[j_4m])


def compute_pnl(direction, fill_px, exit_px):
    if pd.isna(exit_px): return np.nan
    pts = (exit_px - fill_px) if direction == 1 else (fill_px - exit_px)
    return pts * NQ_MULT - 2 * COMMISSION


def add_drawdown(df, col):
    df = df.sort_values("entry_ts").copy()
    df["cum"] = df[col].cumsum()
    df["cum_max"] = df["cum"].cummax()
    df["dd"] = df["cum"] - df["cum_max"]
    return df


def yearly_metrics(df, col):
    if not len(df): return {}
    n = len(df)
    wins = (df[col] > 0).sum()
    net = df[col].sum()
    max_dd = add_drawdown(df, col)["dd"].min()
    df = df.copy()
    df["entry_dt"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True)
    df["month"] = df["entry_dt"].dt.tz_convert("UTC").dt.to_period("M")
    monthly = df.groupby("month")[col].sum()
    return {"n": n, "wr_pct": wins / n * 100, "net_pnl": net,
            "per_trade": net / n, "max_dd": max_dd,
            "pos_months": (monthly > 0).sum(),
            "total_months": len(monthly)}


def main():
    t0 = time.time()
    print("=" * 78)
    print(f"CATASTROPHIC SL GRID — {SL_GRID} × ATR")
    print(f"V_A + filter + V4 + SL stack")
    print("=" * 78)

    # Load class labels from attribution to allow per-class reporting
    attr = pd.read_parquet(OUT / "trade_quality_attribution.parquet")
    cls_map = {"1_good_runner": "C1", "2_good_normal_win": "C2",
                 "3_v4_false_exit": "C3", "4_v4_true_save": "C4",
                 "5_v4_missed_loser": "C5"}
    classes = attr[(attr["cp"] == "+1m")][["year", "trade_idx",
                                                 "class"]].copy()
    classes["cls"] = classes["class"].map(cls_map)

    all_rows = []
    for yr in (2024, 2025, 2026):
        print(f"\n--- year {yr} ---", flush=True)
        wex = pd.read_parquet(OUT / f"v_a_v0_{yr}_with_excursion.parquet")
        filt = wex[(wex["total_excursion_slow"] >= SLOW_LO_CUT)
                     & (wex["total_excursion_slow"] < SLOW_HI_CUT)].copy()
        # Preserve original wex index as trade_idx for class merge
        filt["trade_idx"] = filt.index
        print(f"  filtered trades: {len(filt):,}")

        bars = load_year_bars(yr)
        ts_idx = bars.index.astype("int64").to_numpy()
        opens = bars["open"].values.astype(np.float64)
        highs = bars["high"].values.astype(np.float64)
        lows = bars["low"].values.astype(np.float64)
        closes = bars["close"].values.astype(np.float64)

        for _, tr in filt.iterrows():
            entry_ts = int(tr["entry_ts"])
            exit_ts = int(tr["exit_ts"])
            direction = int(tr["direction"])
            atr = float(tr["atr_at_signal"])
            fill_px = float(tr["fill_price"])
            baseline_pnl = float(tr["net_pnl"])
            old_exit_px = float(tr["exit_price"])

            # V4 (unchanged across SL grid)
            v4_fired, v4_ts, v4_fill = evaluate_v4(
                direction, atr, fill_px, entry_ts, exit_ts,
                ts_idx, opens, highs, lows, closes)
            if v4_fired:
                v4_pnl = compute_pnl(direction, fill_px, v4_fill)
            else:
                v4_pnl = baseline_pnl

            row = {
                "year": yr, "trade_idx": int(tr["trade_idx"]),
                "direction": direction, "atr_at_signal": atr,
                "fill_price": fill_px,
                "entry_ts": entry_ts, "exit_ts": exit_ts,
                "baseline_pnl": baseline_pnl,
                "v4_fired": v4_fired, "v4_ts": v4_ts,
                "v4_pnl": v4_pnl,
            }

            # For each SL multiple, compute SL hit + stack
            for sl_mult in SL_GRID:
                if direction == 1:
                    sl_level = fill_px - sl_mult * atr
                else:
                    sl_level = fill_px + sl_mult * atr

                # Find first SL hit in [entry, exit)
                sl_ts = find_sl_hit(direction, sl_level, entry_ts,
                                       exit_ts, ts_idx, highs, lows)

                if sl_ts is not None and (
                        not v4_fired or sl_ts < v4_ts):
                    # SL fires first (or V4 doesn't fire)
                    sl_pnl = compute_pnl(direction, fill_px, sl_level)
                    row[f"sl{sl_mult}_fired"] = True
                    row[f"sl{sl_mult}_ts"] = sl_ts
                    row[f"sl{sl_mult}_pnl"] = sl_pnl
                    row[f"sl{sl_mult}_exit_type"] = "SL"
                elif v4_fired:
                    # V4 fires first
                    row[f"sl{sl_mult}_fired"] = (sl_ts is not None
                                                       and sl_ts >= v4_ts)
                    row[f"sl{sl_mult}_ts"] = sl_ts
                    row[f"sl{sl_mult}_pnl"] = v4_pnl
                    row[f"sl{sl_mult}_exit_type"] = "V4"
                else:
                    # Neither — regime exit
                    row[f"sl{sl_mult}_fired"] = False
                    row[f"sl{sl_mult}_ts"] = None
                    row[f"sl{sl_mult}_pnl"] = baseline_pnl
                    row[f"sl{sl_mult}_exit_type"] = "regime"

            all_rows.append(row)

    full = pd.DataFrame(all_rows)
    # Merge class labels
    full = full.merge(classes[["year","trade_idx","cls"]],
                          on=["year","trade_idx"], how="left")
    full.to_parquet(OUT / "sl_grid_study_results.parquet")
    print(f"\nWrote {OUT}/sl_grid_study_results.parquet  "
          f"({len(full):,} rows × {len(full.columns)} cols)")

    # ==========================================================
    # Per-year performance
    # ==========================================================
    print(f"\n{'='*78}")
    print("PER-YEAR PERFORMANCE")
    print(f"{'='*78}")
    summary = []
    for yr in (2024, 2025, 2026):
        sub = full[full["year"] == yr]
        if not len(sub): continue
        print(f"\n--- {yr} ---")
        print(f"  {'variant':<14} {'n':>5} {'WR%':>5} {'net':>9} "
              f"{'$/tr':>7} {'maxDD':>9} {'posM':>5}")
        # Baseline
        m = yearly_metrics(sub, "baseline_pnl")
        print(f"  {'baseline':<14} {int(m['n']):>5,} "
              f"{m['wr_pct']:>4.1f}% {m['net_pnl']:>+8,.0f} "
              f"{m['per_trade']:>+6.1f} {m['max_dd']:>+8,.0f} "
              f"{int(m['pos_months']):>2}/{int(m['total_months']):>2}")
        # V4 only
        m = yearly_metrics(sub, "v4_pnl")
        print(f"  {'V4 only':<14} {int(m['n']):>5,} "
              f"{m['wr_pct']:>4.1f}% {m['net_pnl']:>+8,.0f} "
              f"{m['per_trade']:>+6.1f} {m['max_dd']:>+8,.0f} "
              f"{int(m['pos_months']):>2}/{int(m['total_months']):>2}")
        # Each SL grid value
        for sl_mult in SL_GRID:
            col = f"sl{sl_mult}_pnl"
            m = yearly_metrics(sub, col)
            row_summary = {"year": yr, "sl_mult": sl_mult,
                            **m}
            summary.append(row_summary)
            n_sl = (sub[f"sl{sl_mult}_exit_type"] == "SL").sum()
            n_v4 = (sub[f"sl{sl_mult}_exit_type"] == "V4").sum()
            n_reg = (sub[f"sl{sl_mult}_exit_type"] == "regime").sum()
            print(f"  V4+SL {sl_mult:>4} {int(m['n']):>5,} "
                  f"{m['wr_pct']:>4.1f}% {m['net_pnl']:>+8,.0f} "
                  f"{m['per_trade']:>+6.1f} {m['max_dd']:>+8,.0f} "
                  f"{int(m['pos_months']):>2}/{int(m['total_months']):>2}  "
                  f"[SL:{n_sl} V4:{n_v4} reg:{n_reg}]")

    # ==========================================================
    # Across-year roll-up
    # ==========================================================
    print(f"\n--- ALL YEARS ---")
    print(f"  {'variant':<14} {'n':>5} {'WR%':>5} {'net':>9} "
          f"{'$/tr':>7} {'maxDD':>9} {'posM':>5}")
    for label, col in [("baseline", "baseline_pnl"),
                        ("V4 only", "v4_pnl")]:
        m = yearly_metrics(full, col)
        print(f"  {label:<14} {int(m['n']):>5,} "
              f"{m['wr_pct']:>4.1f}% {m['net_pnl']:>+8,.0f} "
              f"{m['per_trade']:>+6.1f} {m['max_dd']:>+8,.0f} "
              f"{int(m['pos_months']):>2}/{int(m['total_months']):>2}")
    for sl_mult in SL_GRID:
        m = yearly_metrics(full, f"sl{sl_mult}_pnl")
        print(f"  V4+SL {sl_mult:>4} {int(m['n']):>5,} "
              f"{m['wr_pct']:>4.1f}% {m['net_pnl']:>+8,.0f} "
              f"{m['per_trade']:>+6.1f} {m['max_dd']:>+8,.0f} "
              f"{int(m['pos_months']):>2}/{int(m['total_months']):>2}")

    # ==========================================================
    # Per-class catch (runners cut, losers saved)
    # ==========================================================
    print(f"\n{'='*78}")
    print("PER-CLASS SL FIRE RATES (across all years)")
    print(f"{'='*78}")
    classes_ord = ["C1", "C2", "C3", "C4", "C5"]
    print(f"\n  {'sl_mult':<8} " + "".join(
        f"{c:>9}" for c in classes_ord) + f"  {'fire%':>6}")
    for sl_mult in SL_GRID:
        line = f"  {sl_mult:<8} "
        type_col = f"sl{sl_mult}_exit_type"
        sl_fired_col = full[type_col] == "SL"
        for cls in classes_ord:
            sub = full[full["cls"] == cls]
            if not len(sub):
                line += f"{'-':>9}"; continue
            sl_fired_cls = (sub[type_col] == "SL").sum()
            pct = 100 * sl_fired_cls / len(sub)
            line += f"{pct:>+8.1f}%"
        total_pct = 100 * sl_fired_col.sum() / len(full)
        line += f"  {total_pct:>+5.1f}%"
        print(line)

    # ==========================================================
    # PnL delta vs V4 by class × SL_mult
    # ==========================================================
    print(f"\n{'='*78}")
    print("PER-CLASS PnL DELTA (sl_pnl - v4_pnl) by class × SL_mult")
    print(f"{'='*78}")
    print(f"\n  {'sl_mult':<8} " + "".join(
        f"{c:>9}" for c in classes_ord) + f"  {'TOTAL':>10}")
    for sl_mult in SL_GRID:
        line = f"  {sl_mult:<8} "
        col = f"sl{sl_mult}_pnl"
        for cls in classes_ord:
            sub = full[full["cls"] == cls]
            if not len(sub):
                line += f"{'-':>9}"; continue
            d = sub[col].sum() - sub["v4_pnl"].sum()
            line += f"{d:>+8,.0f}"
        total_d = full[col].sum() - full["v4_pnl"].sum()
        line += f"  {total_d:>+9,.0f}"
        print(line)

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
