"""Entry location bucketing study.

For each Goldilocks-EMA13 trigger, compute:
  progress_to_target = (trigger_close - L) / (PT - L)   long
                     = (L - trigger_close) / (L - PT)   short

By Goldilocks rule, progress is in (0, 0.5). Bucket into:
  0-10%, 10-20%, 20-30%, 30-40%, 40-50%

For each (group × bucket), measure outcomes (1-contract path with
prior_level_SL + full PT) and report:

  n
  full PT hit %  (= win)
  PT1 hit %      (= MFE >= 4 pts from entry; PT1=4)
  prior_SL hit % (= loss)
  MFE p50/p75/p90
  MAE p50/p75/p90
  bucket dist:
    clean win  (win, max_mae < 3)
    vshape win (win, max_mae >= 3)
    quick loss (loss, max_mfe < 2.5)
    RtB loss   (loss, max_mfe >= 2.5)
  conservative 1-ctr PnL (with 0.125 pt slippage on stops)

This is the descriptive/diagnostic study to identify which entry
locations are clearly profitable, fail-prone, or chop.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from studies.level_momentum_continuation.level_study import (
    load_v0_1s, resample_1s_to_1m, annotate_sessions_ct,
)
from studies.level_momentum_continuation.analyze_breakout_filter import (
    detect_triggers_breakout, assign_group,
)
from studies.level_momentum_continuation.analyze_1s_precision import (
    annotate_sessions_1s, precompute_eod_1s, map_1m_trigger_to_1s_entry,
)

OUT = Path("studies/level_momentum_continuation/results_breakout")
OUT.mkdir(parents=True, exist_ok=True)

NQ_MULT = 20.0
COMMISSION = 0.25
SLIP_PTS = 0.125
EMA_PERIOD = 13
PT1_PTS = 4.0  # for "PT1 hit %" metric

# Bucket edges (fraction of distance to PT)
BUCKETS = [(0.00, 0.10), (0.10, 0.20), (0.20, 0.30),
           (0.30, 0.40), (0.40, 0.50)]


def bucket_label(progress):
    for lo, hi in BUCKETS:
        if lo <= progress < hi:
            return f"{int(lo*100):02d}-{int(hi*100):02d}%"
    if progress >= 0.5:
        return ">=50%"
    return "<0%"


def walk_path(entry_idx, di, entry_px, full_pt, prior_sl,
                eod_idx, highs, lows, closes):
    """Walk 1s path with prior_SL and full PT (1-contract baseline).
    Returns dict with outcome, max MFE, max MAE, exit_idx, PnL."""
    n = len(highs)
    last = min(eod_idx, n - 1)
    if entry_idx >= n or last < entry_idx:
        return None
    nbars = last - entry_idx + 1
    running_mfe = 0.0
    running_mae = 0.0
    if di == 1:
        sl_fill = prior_sl - SLIP_PTS
    else:
        sl_fill = prior_sl + SLIP_PTS

    for s in range(nbars):
        i = entry_idx + s
        h = highs[i]; l = lows[i]
        if di == 1:
            mfe_now = h - entry_px
            mae_now = entry_px - l
            sl_hit = (l <= prior_sl)
            tgt_hit = (h >= full_pt)
        else:
            mfe_now = entry_px - l
            mae_now = h - entry_px
            sl_hit = (h >= prior_sl)
            tgt_hit = (l <= full_pt)
        if mfe_now > running_mfe: running_mfe = mfe_now
        if mae_now > running_mae: running_mae = mae_now
        # Conservative: SL beats PT same bar
        if sl_hit:
            return {
                "outcome": "loss",
                "max_mfe": float(running_mfe),
                "max_mae": float(running_mae),
                "exit_idx_global": i,
                "pnl_pts": float((sl_fill - entry_px) * di - COMMISSION),
            }
        if tgt_hit:
            return {
                "outcome": "win",
                "max_mfe": float(running_mfe),
                "max_mae": float(running_mae),
                "exit_idx_global": i,
                "pnl_pts": float((full_pt - entry_px) * di - COMMISSION),
            }
    # EOD
    last_close = closes[entry_idx + nbars - 1]
    return {
        "outcome": "eod_flat",
        "max_mfe": float(running_mfe),
        "max_mae": float(running_mae),
        "exit_idx_global": entry_idx + nbars - 1,
        "pnl_pts": float((last_close - entry_px) * di - COMMISSION),
    }


def assign_bucket_outcome(outcome, max_mfe, max_mae):
    if outcome == "win":
        return "clean_win" if max_mae < 3.0 else "vshape_win"
    if outcome == "loss":
        return "RtB_loss" if max_mfe >= 2.5 else "quick_loss"
    return "eod"


def harvest(year):
    print(f"\n[{year}] loading...", flush=True)
    bars_1s = load_v0_1s(Path(f"data/raw/NQ_v0_1s_{year}.parquet"))
    bars_1s = annotate_sessions_1s(bars_1s)
    bars_1m = bars_1s[
        ["open", "high", "low", "close", "volume"]
    ].resample("1min", label="right", closed="right").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).dropna(subset=["open", "high", "low", "close"])
    bars_1m = annotate_sessions_ct(bars_1m)
    bars_1m["ema13"] = bars_1m["close"].ewm(
        span=EMA_PERIOD, adjust=False).mean()
    triggers = detect_triggers_breakout(bars_1m)
    print(f"  triggers: {len(triggers):,}", flush=True)

    bars_1s_reset = bars_1s.reset_index(drop=False)
    opens = bars_1s_reset["open"].values.astype(np.float64)
    highs = bars_1s_reset["high"].values.astype(np.float64)
    lows = bars_1s_reset["low"].values.astype(np.float64)
    closes = bars_1s_reset["close"].values.astype(np.float64)
    sessions = bars_1s_reset["session"].values
    ts_close_1s = pd.DatetimeIndex(bars_1s_reset["ts_close"])
    if ts_close_1s.tz is None:
        ts_close_1s = ts_close_1s.tz_localize("UTC")
    else:
        ts_close_1s = ts_close_1s.tz_convert("UTC")
    next_eod = precompute_eod_1s(bars_1s_reset)
    ema_lookup = pd.Series(
        bars_1m["ema13"].values, index=bars_1m.index)

    rows = []
    last_chain_exit = -1
    for tr in triggers:
        ts = pd.Timestamp(tr["bar_ts_close"])
        if ts.tz is None: ts = ts.tz_localize("UTC")
        else: ts = ts.tz_convert("UTC")
        e = map_1m_trigger_to_1s_entry(ts, ts_close_1s)
        if e < 0: continue
        if e <= last_chain_exit: continue
        if ts not in ema_lookup.index: continue
        ema_val = ema_lookup.loc[ts]
        if pd.isna(ema_val): continue
        di = tr["direction"]
        cur_close = float(tr["close_at_breach"])
        # EMA13 filter
        if di == 1 and cur_close <= ema_val: continue
        if di == -1 and cur_close >= ema_val: continue
        # RTH only
        if sessions[e] != "RTH":
            continue

        entry_px = float(opens[e])
        L = float(tr["breach_level"])
        full_pt = float(tr["target"])
        prior_sl = float(tr["stop"])
        # Distance from L to PT
        if di == 1:
            dist_to_pt = full_pt - L
            dist_past = cur_close - L
        else:
            dist_to_pt = L - full_pt
            dist_past = L - cur_close
        if dist_to_pt <= 0:
            continue
        progress = dist_past / dist_to_pt

        # Walk path
        wp = walk_path(e, di, entry_px, full_pt, prior_sl,
                         int(next_eod[e]), highs, lows, closes)
        if wp is None: continue
        last_chain_exit = wp["exit_idx_global"]

        bucket = bucket_label(progress)
        outcome_bk = assign_bucket_outcome(
            wp["outcome"], wp["max_mfe"], wp["max_mae"])
        # Did MFE reach PT1 = 4 pts?
        pt1_hit = wp["max_mfe"] >= PT1_PTS

        rows.append({
            "year": year,
            "trigger_ts": ts,
            "level_pair": tr["level_pair"],
            "group": assign_group(tr["level_pair"]),
            "direction": di,
            "trigger_close": cur_close,
            "entry_px": entry_px,
            "breach_L": L,
            "full_pt": full_pt,
            "prior_sl": prior_sl,
            "dist_past": dist_past,
            "dist_to_pt": dist_to_pt,
            "progress_to_target": progress,
            "entry_progress": ((entry_px - L) / dist_to_pt
                                if di == 1
                                else (L - entry_px) / dist_to_pt),
            "bucket": bucket,
            "outcome": wp["outcome"],
            "outcome_bucket": outcome_bk,
            "max_mfe": wp["max_mfe"],
            "max_mae": wp["max_mae"],
            "pnl_pts": wp["pnl_pts"],
            "pnl_dollars": wp["pnl_pts"] * NQ_MULT,
            "pt1_hit": pt1_hit,
        })
    print(f"  RTH+EMA13 chained trades: {len(rows):,}", flush=True)
    return rows


def main():
    t0 = time.time()
    all_trades = []
    for year in (2024, 2025):
        all_trades.extend(harvest(year))
    df = pd.DataFrame(all_trades)
    df.to_parquet(OUT / "entry_location_buckets.parquet")
    print(f"\nTotal trades: {len(df):,}")

    # ---- Per (group × bucket) summary ----
    print(f"\n{'='*78}")
    print(f"PER GROUP × BUCKET — descriptive metrics")
    print(f"{'='*78}")

    bucket_order = [f"{int(lo*100):02d}-{int(hi*100):02d}%"
                     for lo, hi in BUCKETS]
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        if len(g) == 0: continue
        n_total = len(g)
        print(f"\n[{grp}] n_total={n_total:,}")
        print(f"  {'bucket':<10} {'n':>5} {'pct':>5} "
              f"{'WR':>5} {'PT1%':>5} {'SL%':>5} "
              f"{'mfe_p50':>8} {'mfe_p75':>8} {'mfe_p90':>8} "
              f"{'mae_p50':>8} {'mae_p75':>8} {'mae_p90':>8} "
              f"{'$/tr':>7} {'total_$':>10}")
        for bk in bucket_order:
            sub = g[g["bucket"] == bk]
            n = len(sub)
            if n == 0:
                print(f"  {bk:<10} {0:>5,}")
                continue
            wr = (sub["outcome"] == "win").mean() * 100
            pt1 = sub["pt1_hit"].mean() * 100
            sl = (sub["outcome"] == "loss").mean() * 100
            mfe = sub["max_mfe"]
            mae = sub["max_mae"]
            pnl = sub["pnl_dollars"]
            print(f"  {bk:<10} {n:>5,} "
                  f"{100*n/n_total:>4.1f}% "
                  f"{wr:>4.1f}% {pt1:>4.1f}% {sl:>4.1f}% "
                  f"{np.percentile(mfe,50):>8.2f} "
                  f"{np.percentile(mfe,75):>8.2f} "
                  f"{np.percentile(mfe,90):>8.2f} "
                  f"{np.percentile(mae,50):>8.2f} "
                  f"{np.percentile(mae,75):>8.2f} "
                  f"{np.percentile(mae,90):>8.2f} "
                  f"{pnl.mean():>+6.2f} "
                  f"{pnl.sum():>+9,.0f}")

    # ---- Outcome bucket distribution per (group × bucket) ----
    print(f"\n{'='*78}")
    print(f"OUTCOME BUCKET DISTRIBUTION per (group × entry-bucket)")
    print(f"  clean_win = win + max_mae < 3 pts")
    print(f"  vshape_win = win + max_mae >= 3 pts")
    print(f"  quick_loss = loss + max_mfe < 2.5 pts")
    print(f"  RtB_loss = loss + max_mfe >= 2.5 pts")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        if len(g) == 0: continue
        print(f"\n[{grp}]")
        print(f"  {'bucket':<10} {'n':>5}  "
              f"{'clean_win':>10} {'vshape_win':>11} "
              f"{'quick_loss':>11} {'RtB_loss':>9} {'eod':>5}")
        for bk in bucket_order:
            sub = g[g["bucket"] == bk]
            n = len(sub)
            if n == 0: continue
            counts = sub["outcome_bucket"].value_counts()
            line = f"  {bk:<10} {n:>5,}  "
            for ob in ("clean_win", "vshape_win",
                       "quick_loss", "RtB_loss", "eod"):
                pct = 100 * counts.get(ob, 0) / n
                line += f"{pct:>9.1f}% "
            print(line)

    # ---- Per-year stability ----
    print(f"\n{'='*78}")
    print(f"PER-YEAR PnL by (group × bucket)")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        if len(g) == 0: continue
        print(f"\n[{grp}]")
        print(f"  {'bucket':<10} {'n':>5}  "
              f"{'2024_n':>7} {'2024_$':>10} {'2024_$/tr':>10}  "
              f"{'2025_n':>7} {'2025_$':>10} {'2025_$/tr':>10}")
        for bk in bucket_order:
            sub = g[g["bucket"] == bk]
            n = len(sub)
            if n == 0: continue
            y24 = sub[sub["year"] == 2024]
            y25 = sub[sub["year"] == 2025]
            n24 = len(y24); n25 = len(y25)
            print(f"  {bk:<10} {n:>5,}  "
                  f"{n24:>7,} {y24['pnl_dollars'].sum():>+9,.0f} "
                  f"{(y24['pnl_dollars'].mean() if n24 else 0):>+9.2f}  "
                  f"{n25:>7,} {y25['pnl_dollars'].sum():>+9,.0f} "
                  f"{(y25['pnl_dollars'].mean() if n25 else 0):>+9.2f}")

    # ---- Save summary CSV ----
    summary = []
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        for bk in bucket_order:
            sub = g[g["bucket"] == bk]
            n = len(sub)
            if n == 0: continue
            row = {
                "group": grp, "bucket": bk, "n": n,
                "pct_of_group": 100 * n / len(g),
                "wr_pct": (sub["outcome"] == "win").mean() * 100,
                "pt1_hit_pct": sub["pt1_hit"].mean() * 100,
                "sl_pct": (sub["outcome"] == "loss").mean() * 100,
                "mfe_p50": float(np.percentile(sub["max_mfe"], 50)),
                "mfe_p75": float(np.percentile(sub["max_mfe"], 75)),
                "mfe_p90": float(np.percentile(sub["max_mfe"], 90)),
                "mae_p50": float(np.percentile(sub["max_mae"], 50)),
                "mae_p75": float(np.percentile(sub["max_mae"], 75)),
                "mae_p90": float(np.percentile(sub["max_mae"], 90)),
                "mean_pnl_dollars": float(sub["pnl_dollars"].mean()),
                "total_pnl_dollars": float(sub["pnl_dollars"].sum()),
                "y2024_total": float(
                    sub[sub["year"]==2024]["pnl_dollars"].sum()),
                "y2025_total": float(
                    sub[sub["year"]==2025]["pnl_dollars"].sum()),
            }
            counts = sub["outcome_bucket"].value_counts()
            for ob in ("clean_win", "vshape_win", "quick_loss",
                        "RtB_loss", "eod"):
                row[f"{ob}_pct"] = 100 * counts.get(ob, 0) / n
            summary.append(row)
    pd.DataFrame(summary).to_csv(
        OUT / "entry_location_buckets_summary.csv", index=False)
    print(f"\nsaved: {OUT / 'entry_location_buckets_summary.csv'}")
    print(f"saved: {OUT / 'entry_location_buckets.parquet'}")
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
