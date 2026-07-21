"""MR companion v2 — stricter fire conditions sweep.

Same architecture as mr_companion_v1.py (REPLACE V_A at +60s, fade
opposite, PT/SL=0.75 ATR, 4-min time stop). What's swept:

  xfast_net_atr cutoff: 0 (baseline raw <0), -0.25, -0.50, -0.75
  close_loc cutoff:    0.40 (baseline), 0.30, 0.25, 0.20

Fixed:
  trend_MFE_atr < 0.25
  trend_MAE_atr > 0.5
  PT = 0.75 ATR, SL = 0.75 ATR, 4-min time stop

xfast_net_atr = xfast_net_points / atr_at_signal (direction-aware)

For each (xfast, close_loc) cell, report:
  - n MR fires
  - Fire rate (% of V_A entries)
  - Exit mix PT/SL/time
  - MR-only PnL, $/tr, WR
  - V_A held on these trades
  - V_A early-exit at MR fire
  - REPLACE total (V_A_early + MR)
  - Δ vs HOLD (positive = REPLACE beats HOLD)

Goal: find any cell where REPLACE Δ > 0 with sample size >= 50/year.
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
PT_ATR = 0.75
SL_ATR = 0.75
TIME_STOP_S = 240
MR_FIRE_OFFSET_S = 60
EPS = 1e-6

# Sweep grids
XFAST_CUTS_ATR = [0.0, -0.25, -0.50, -0.75]   # xfast_net/atr <= cutoff
CLOSE_LOC_CUTS = [0.40, 0.30, 0.25, 0.20]

OUT = Path("studies/v_a_excursion_regime/results_v0")
OUT.mkdir(parents=True, exist_ok=True)


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


def features_at_60s(direction, atr, fill_px, entry_ts, exit_ts,
                       ts_idx, opens, highs, lows, closes):
    """Compute V_A trade-state features at +60s. Causal."""
    cp_ts = entry_ts + MR_FIRE_OFFSET_S * 1_000_000_000
    if cp_ts >= exit_ts: return None
    j_lo = np.searchsorted(ts_idx, entry_ts, side="left")
    j_hi = np.searchsorted(ts_idx, cp_ts, side="left")
    if j_hi <= j_lo: return None
    seg_h = highs[j_lo:j_hi]
    seg_l = lows[j_lo:j_hi]
    seg_c = closes[j_hi - 1]
    if direction == 1:
        cur_mfe = float(seg_h.max() - fill_px)
        cur_mae = float(fill_px - seg_l.min())
    else:
        cur_mfe = float(fill_px - seg_l.min())
        cur_mae = float(seg_h.max() - fill_px)
    rng = float(seg_h.max() - seg_l.min())
    if rng < EPS: close_loc = 0.5
    elif direction == 1:
        close_loc = (float(seg_c) - float(seg_l.min())) / rng
    else:
        close_loc = (float(seg_h.max()) - float(seg_c)) / rng
    win_start = cp_ts - 150 * 1_000_000_000
    i_xf_lo = np.searchsorted(ts_idx, win_start, side="left")
    if j_hi - i_xf_lo < 30:
        xfast_net = np.nan
    else:
        anc = float(opens[i_xf_lo])
        cn = float(closes[j_hi - 1])
        xfast_net = (cn - anc) if direction == 1 else (anc - cn)
    fill_at_next_bar = float(opens[j_hi]) if j_hi < len(opens) else np.nan
    return {
        "trend_mfe_atr": cur_mfe / max(atr, 0.01),
        "trend_mae_atr": cur_mae / max(atr, 0.01),
        "close_loc_in_range": close_loc,
        "xfast_net_points": xfast_net,
        "xfast_net_atr": (xfast_net / max(atr, 0.01)
                            if not pd.isna(xfast_net) else np.nan),
        "fill_at_next_bar": fill_at_next_bar,
        "cp_ts": cp_ts,
    }


def walk_mr_exit(mr_dir, mr_fill_px, mr_fill_ts, atr,
                    ts_idx, opens, highs, lows):
    pt_dist = PT_ATR * atr
    sl_dist = SL_ATR * atr
    if mr_dir == 1:
        pt_level = mr_fill_px + pt_dist
        sl_level = mr_fill_px - sl_dist
    else:
        pt_level = mr_fill_px - pt_dist
        sl_level = mr_fill_px + sl_dist
    time_stop_ts = mr_fill_ts + TIME_STOP_S * 1_000_000_000
    j_start = np.searchsorted(ts_idx, mr_fill_ts, side="left")
    j_time = np.searchsorted(ts_idx, time_stop_ts, side="left")
    j_end = min(j_time, len(ts_idx))
    if j_end <= j_start:
        return ("nodata", None, np.nan, np.nan, np.nan)
    seg_h = highs[j_start:j_end]; seg_l = lows[j_start:j_end]
    if mr_dir == 1:
        running_mfe = float(seg_h.max() - mr_fill_px)
        running_mae = float(mr_fill_px - seg_l.min())
    else:
        running_mfe = float(mr_fill_px - seg_l.min())
        running_mae = float(seg_h.max() - mr_fill_px)
    for k in range(j_start, j_end):
        bar_h = highs[k]; bar_l = lows[k]
        if mr_dir == 1:
            sl_hit = bar_l <= sl_level + EPS
            pt_hit = bar_h >= pt_level - EPS
        else:
            sl_hit = bar_h >= sl_level - EPS
            pt_hit = bar_l <= pt_level + EPS
        if sl_hit and pt_hit:
            return ("SL", int(ts_idx[k]), float(sl_level),
                     running_mfe / max(atr, 0.01),
                     running_mae / max(atr, 0.01))
        if sl_hit:
            return ("SL", int(ts_idx[k]), float(sl_level),
                     running_mfe / max(atr, 0.01),
                     running_mae / max(atr, 0.01))
        if pt_hit:
            return ("PT", int(ts_idx[k]), float(pt_level),
                     running_mfe / max(atr, 0.01),
                     running_mae / max(atr, 0.01))
    if j_time >= len(opens):
        return ("nodata", None, np.nan, np.nan, np.nan)
    return ("TIME", int(ts_idx[j_time]), float(opens[j_time]),
             running_mfe / max(atr, 0.01),
             running_mae / max(atr, 0.01))


def compute_pnl(direction, fill_px, exit_px):
    if pd.isna(exit_px): return np.nan
    pts = (exit_px - fill_px) if direction == 1 else (fill_px - exit_px)
    return pts * NQ_MULT - 2 * COMMISSION


def main():
    t0 = time.time()
    print("=" * 78)
    print("MR COMPANION v2 — stricter fire conditions sweep")
    print(f"  xfast_net_atr cutoffs: {XFAST_CUTS_ATR}")
    print(f"  close_loc cutoffs:     {CLOSE_LOC_CUTS}")
    print(f"  fixed: MFE<0.25 AND MAE>0.5; PT=SL={PT_ATR} ATR; "
          f"time={TIME_STOP_S//60}m")
    print("=" * 78)

    # ----- Pre-compute all V_A trades + features at +60s + per-grid MR
    # outcomes (so we sweep cheaply by filtering)
    all_rows = []
    for yr in (2024, 2025, 2026):
        print(f"\n--- year {yr} ---", flush=True)
        base = Path(f"collectors/collector_v2/results/v_a_v0_{yr}")
        trades = pd.read_parquet(base / "trades.parquet")
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
            va_pnl = float(tr["net_pnl"])

            f60 = features_at_60s(
                direction, atr, fill_px, entry_ts, exit_ts,
                ts_idx, opens, highs, lows, closes)
            base_row = {
                "year": yr, "va_entry_ts": entry_ts,
                "va_exit_ts": exit_ts, "va_dir": direction,
                "atr": atr, "va_fill": fill_px, "va_net_pnl": va_pnl,
            }
            if f60 is None:
                base_row.update({
                    "trend_mfe_atr": np.nan,
                    "trend_mae_atr": np.nan,
                    "close_loc": np.nan,
                    "xfast_atr": np.nan,
                    "mr_eligible": False,
                })
                all_rows.append(base_row); continue

            # Pre-condition: MFE<0.25 AND MAE>0.5 (always required)
            elig_pre = (f60["trend_mfe_atr"] < 0.25
                          and f60["trend_mae_atr"] > 0.5)
            base_row.update({
                "trend_mfe_atr": f60["trend_mfe_atr"],
                "trend_mae_atr": f60["trend_mae_atr"],
                "close_loc": f60["close_loc_in_range"],
                "xfast_atr": f60["xfast_net_atr"],
                "mr_eligible": elig_pre,
            })

            # If pre-conditions met, simulate the MR trade ONCE.
            # The grid only filters which trades to count.
            if elig_pre and not pd.isna(f60["fill_at_next_bar"]):
                mr_dir = -direction
                mr_fill_px = float(f60["fill_at_next_bar"])
                j_fill = np.searchsorted(ts_idx, f60["cp_ts"], side="left")
                if j_fill < len(ts_idx):
                    mr_fill_ts = int(ts_idx[j_fill])
                    exit_type, ex_ts, ex_px, mfe_atr, mae_atr = (
                        walk_mr_exit(mr_dir, mr_fill_px, mr_fill_ts, atr,
                                       ts_idx, opens, highs, lows))
                    if exit_type != "nodata":
                        mr_pnl = compute_pnl(mr_dir, mr_fill_px, ex_px)
                        # V_A early-exit at MR fire
                        if direction == 1:
                            va_early_pts = mr_fill_px - fill_px
                        else:
                            va_early_pts = fill_px - mr_fill_px
                        va_early_pnl = (va_early_pts * NQ_MULT
                                            - 2 * COMMISSION)
                        base_row.update({
                            "mr_pnl": mr_pnl,
                            "mr_exit_type": exit_type,
                            "va_early_pnl": va_early_pnl,
                            "replace_pnl": va_early_pnl + mr_pnl,
                            "mr_mfe_atr": mfe_atr,
                            "mr_mae_atr": mae_atr,
                        })
            all_rows.append(base_row)

    df = pd.DataFrame(all_rows)
    df.to_parquet(OUT / "mr_v2_all_trades.parquet")
    print(f"\nTotal V_A entries: {len(df):,}")
    print(f"Pre-eligible (MFE<0.25 AND MAE>0.5): "
          f"{df['mr_eligible'].sum():,}  "
          f"({100*df['mr_eligible'].sum()/len(df):.1f}%)")

    # ----- Grid sweep -----
    print(f"\n{'='*78}")
    print("GRID SWEEP — REPLACE Δ vs HOLD by year (positive = REPLACE wins)")
    print(f"{'='*78}")

    # Helper to compute metrics for a (xfast_cut, close_cut) cell
    def cell_metrics(xfast_cut, close_cut, year=None):
        sub = df[df["mr_eligible"] & df["mr_pnl"].notna()]
        if year is not None:
            sub = sub[sub["year"] == year]
        # If xfast_cut == 0, baseline rule: xfast_atr < 0
        if xfast_cut == 0:
            mask = sub["xfast_atr"] < 0
        else:
            mask = sub["xfast_atr"] <= xfast_cut
        mask &= sub["close_loc"] < close_cut
        sel = sub[mask]
        if not len(sel):
            return None
        n = len(sel)
        va_held = sel["va_net_pnl"].sum()
        va_early = sel["va_early_pnl"].sum()
        mr_only = sel["mr_pnl"].sum()
        replace = sel["replace_pnl"].sum()
        delta = replace - va_held
        # Exit mix
        exit_counts = sel["mr_exit_type"].value_counts().to_dict()
        pt = exit_counts.get("PT", 0)
        sl = exit_counts.get("SL", 0)
        tm = exit_counts.get("TIME", 0)
        wr = (sel["mr_pnl"] > 0).mean() * 100
        return {
            "n": n,
            "pt_pct": 100*pt/n, "sl_pct": 100*sl/n, "time_pct": 100*tm/n,
            "wr": wr,
            "va_held": va_held, "va_early": va_early,
            "mr_only": mr_only, "replace": replace,
            "delta": delta, "delta_per_tr": delta / n,
        }

    print(f"\n  {'xfast≤':>8} {'close<':>7} {'year':<6} {'n':>5} "
          f"{'PT%':>5} {'SL%':>5} {'fire%':>6} "
          f"{'VAheld':>9} {'REPLACE':>9} {'Δ':>9} {'Δ/tr':>7}")

    eligible_per_year = {
        yr: int(df[(df["year"]==yr) & df["mr_eligible"]
                     & df["mr_pnl"].notna()].shape[0])
        for yr in (2024, 2025, 2026)
    }

    for xc in XFAST_CUTS_ATR:
        for cc in CLOSE_LOC_CUTS:
            xc_label = f"<0" if xc == 0 else f"≤{xc:.2f}"
            print()
            for yr in (2024, 2025, 2026):
                m = cell_metrics(xc, cc, yr)
                if m is None:
                    print(f"  {xc_label:>8} {cc:>7.2f} {yr:<6} (no fires)")
                    continue
                fire_pct = 100 * m["n"] / max(eligible_per_year[yr], 1)
                print(f"  {xc_label:>8} {cc:>7.2f} {yr:<6} "
                      f"{int(m['n']):>5,} "
                      f"{m['pt_pct']:>4.0f}% {m['sl_pct']:>4.0f}% "
                      f"{fire_pct:>5.1f}% "
                      f"{m['va_held']:>+8,.0f} {m['replace']:>+8,.0f} "
                      f"{m['delta']:>+8,.0f} {m['delta_per_tr']:>+6.0f}")

    # ----- Find best cells across years -----
    print(f"\n{'='*78}")
    print("ALL-YEARS CELL RANKING (by REPLACE Δ vs HOLD)")
    print(f"{'='*78}")
    rows = []
    for xc in XFAST_CUTS_ATR:
        for cc in CLOSE_LOC_CUTS:
            m = cell_metrics(xc, cc, year=None)
            if m is None: continue
            xc_label = "<0" if xc == 0 else f"≤{xc}"
            rows.append({"xfast_atr": xc_label, "close_loc": cc, **m})
    rank = pd.DataFrame(rows)
    rank = rank.sort_values("delta", ascending=False)
    rank.to_csv(OUT / "mr_v2_sweep_ranking.csv", index=False)
    print(f"\n  {'xfast':<7} {'close':<6} {'n':>5} {'PT%':>5} "
          f"{'SL%':>5} {'WR%':>5} "
          f"{'VAheld':>9} {'REPLACE':>9} {'Δ_total':>9} {'Δ/tr':>7}")
    for _, r in rank.iterrows():
        print(f"  {r['xfast_atr']:<7} {r['close_loc']:<6.2f} "
              f"{int(r['n']):>5,} {r['pt_pct']:>4.0f}% "
              f"{r['sl_pct']:>4.0f}% {r['wr']:>4.1f}% "
              f"{r['va_held']:>+8,.0f} {r['replace']:>+8,.0f} "
              f"{r['delta']:>+8,.0f} {r['delta_per_tr']:>+6.0f}")

    # ----- Best cell per-year breakdown -----
    if len(rank) and rank.iloc[0]["delta"] > 0:
        best = rank.iloc[0]
        xc_label = best["xfast_atr"]
        cc = best["close_loc"]
        # Convert label back to value for cell_metrics
        xc = 0 if xc_label == "<0" else float(xc_label[1:])
        print(f"\n{'='*78}")
        print(f"BEST CELL: xfast_atr={xc_label}, close_loc<{cc}")
        print(f"{'='*78}")
        for yr in (2024, 2025, 2026):
            m = cell_metrics(xc, cc, yr)
            if m is None: continue
            print(f"  {yr}: n={int(m['n'])} "
                  f"WR={m['wr']:.1f}% "
                  f"REPLACE ${m['replace']:+,.0f} "
                  f"VA_held ${m['va_held']:+,.0f} "
                  f"Δ ${m['delta']:+,.0f} ({m['delta_per_tr']:+.0f}/tr)")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
