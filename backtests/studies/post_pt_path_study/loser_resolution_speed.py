"""How fast do SL losers resolve on 2026 RTH T=0?

Plus pre-SL MFE: did losers ever look like winners?
And side-by-side comparison of PT vs SL resolution speed.
"""

from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)
sys.path.insert(0, str(project_root))

from nautilus_trader.persistence.catalog import ParquetDataCatalog

OUT = Path("studies/post_pt_path_study/results")


def main():
    print("Loading 2026 data...")
    es = pd.read_parquet(
        "studies/1m_regime_collector_v2/results/v2_event_summary_2026.parquet")
    feats = pd.read_parquet(
        "studies/1m_regime_collector_v2/results/v2_feature_snapshots_2026.parquet",
        columns=["event_id", "checkpoint_s", "fillable_at_T",
                  "fill_time_actual", "fill_price",
                  "atr_at_signal", "is_rth_checkpoint"])
    labels = pd.read_parquet(
        "studies/1m_regime_collector_v2/results/v2_outcome_labels_2026.parquet",
        columns=["event_id", "checkpoint_s", "pt100_before_sl100",
                  "bracket_resolution_time_s_pt100_before_sl100"])

    df = (feats[feats["checkpoint_s"] == 0]
          .merge(labels[labels["checkpoint_s"] == 0],
                  on=["event_id", "checkpoint_s"]))
    df = df.merge(es[["event_id", "signal_direction"]], on="event_id")
    df = df[(df["fillable_at_T"] == True)
             & (df["is_rth_checkpoint"] == 1)].copy()

    pt_win = df[df["pt100_before_sl100"] == 1].copy()
    sl_lose = df[df["pt100_before_sl100"] == 0].copy()
    unres = df[df["pt100_before_sl100"].isna()].copy()
    print(f"  T=0 RTH fillable: {len(df):,}")
    print(f"  PT winners: {len(pt_win):,}")
    print(f"  SL losers:  {len(sl_lose):,}")
    print(f"  Unresolved: {len(unres):,}")

    res_col = "bracket_resolution_time_s_pt100_before_sl100"

    # ----- Side-by-side resolution timing -----
    print()
    print("=" * 72)
    print("RESOLUTION TIME COMPARISON: PT WINNERS vs SL LOSERS")
    print("=" * 72)
    pt_t = pt_win[res_col].dropna()
    sl_t = sl_lose[res_col].dropna()
    print(f"{'Stat':<20} {'PT winners':>15} {'SL losers':>15}")
    print(f"{'n':<20} {len(pt_t):>15,} {len(sl_t):>15,}")
    print(f"{'Median (s)':<20} {pt_t.median():>15.1f} {sl_t.median():>15.1f}")
    print(f"{'Mean (s)':<20} {pt_t.mean():>15.1f} {sl_t.mean():>15.1f}")
    print(f"{'P25':<20} {pt_t.quantile(0.25):>15.1f} {sl_t.quantile(0.25):>15.1f}")
    print(f"{'P75':<20} {pt_t.quantile(0.75):>15.1f} {sl_t.quantile(0.75):>15.1f}")
    print(f"{'P90':<20} {pt_t.quantile(0.90):>15.1f} {sl_t.quantile(0.90):>15.1f}")
    print(f"{'P99':<20} {pt_t.quantile(0.99):>15.1f} {sl_t.quantile(0.99):>15.1f}")
    print(f"{'Max':<20} {pt_t.max():>15.1f} {sl_t.max():>15.1f}")

    print()
    print("=" * 72)
    print("CUMULATIVE RESOLUTION % BY TIME")
    print("=" * 72)
    print(f"{'Within':>10} {'PT %':>10} {'SL %':>10}")
    for t in [15, 30, 45, 60, 90, 120, 180, 300, 600, 1200]:
        pt_pct = 100 * (pt_t <= t).mean()
        sl_pct = 100 * (sl_t <= t).mean()
        print(f"{t:>9}s {pt_pct:>9.1f}% {sl_pct:>9.1f}%")

    # ----- SL loser bucketed distribution -----
    print()
    print("=" * 72)
    print("SL-LOSER RESOLUTION-TIME DISTRIBUTION")
    print("=" * 72)
    bins = [(0, 15), (15, 30), (30, 60), (60, 120),
             (120, 180), (180, 300), (300, 600), (600, 1200),
             (1200, 99999)]
    for lo, hi in bins:
        mask = (sl_t >= lo) & (sl_t < hi)
        n = int(mask.sum())
        pct = 100 * n / len(sl_t) if len(sl_t) else 0
        if hi == 99999:
            label = f">={lo}s"
        else:
            label = f"{lo}-{hi}s"
        print(f"  {label:<12} {n:>5,} ({pct:5.1f}%)")

    # ----- Walk bars to compute pre-SL MFE -----
    print()
    print("=" * 72)
    print("PRE-SL MFE: did losers ever look like winners?")
    print("=" * 72)
    print("Loading 1s bars + walking entry -> SL-hit for each loser...")
    t0 = time.time()
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    sl_lose["sl_hit_ts_ns"] = (
        sl_lose["fill_time_actual"].astype("int64")
        + (sl_lose[res_col] * 1_000_000_000).astype("int64"))

    start = pd.Timestamp(int(sl_lose["fill_time_actual"].min()),
                          unit="ns", tz="UTC") - pd.Timedelta(minutes=1)
    end = pd.Timestamp(int(sl_lose["sl_hit_ts_ns"].max()),
                        unit="ns", tz="UTC") + pd.Timedelta(hours=1)
    bars_nt = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=start, end=end)
    bars = pd.DataFrame({
        "ts_event": [b.ts_event for b in bars_nt],
        "high": [float(b.high) for b in bars_nt],
        "low": [float(b.low) for b in bars_nt],
    }).sort_values("ts_event").reset_index(drop=True)
    bars_ts = bars["ts_event"].values
    bars_h = bars["high"].values
    bars_l = bars["low"].values
    print(f"  {len(bars):,} 1s bars ({time.time()-t0:.0f}s)")

    records = []
    t0 = time.time()
    for _, row in sl_lose.iterrows():
        fp = float(row["fill_price"])
        atr = float(row["atr_at_signal"])
        d = int(row["signal_direction"])
        fill_ts = int(row["fill_time_actual"])
        sl_hit_ts = int(row["sl_hit_ts_ns"])
        lo = np.searchsorted(bars_ts, fill_ts, side="left")
        hi = np.searchsorted(bars_ts, sl_hit_ts, side="right")
        if hi <= lo:
            continue
        if d == 1:
            mfe_atr = max(0.0, (bars_h[lo:hi].max() - fp) / atr)
        else:
            mfe_atr = max(0.0, (fp - bars_l[lo:hi].min()) / atr)
        records.append({
            "event_id": int(row["event_id"]),
            "time_to_sl_s": (sl_hit_ts - fill_ts) / 1e9,
            "mfe_pre_sl_atr": float(mfe_atr),
        })
    print(f"  Walked {len(records):,} losers ({time.time()-t0:.0f}s)")
    rec = pd.DataFrame(records)
    rec.to_parquet(OUT / "pre_sl_mfe_2026.parquet", index=False)

    print()
    print(f"  Median pre-SL MFE: {rec['mfe_pre_sl_atr'].median():.3f} ATR")
    print(f"  Mean   pre-SL MFE: {rec['mfe_pre_sl_atr'].mean():.3f}")
    print(f"  P75: {rec['mfe_pre_sl_atr'].quantile(0.75):.3f}")
    print(f"  P90: {rec['mfe_pre_sl_atr'].quantile(0.90):.3f}")
    print(f"  P99: {rec['mfe_pre_sl_atr'].quantile(0.99):.3f}")
    print()
    print(f"  Pre-SL MFE distribution:")
    bins_mfe = [(0, 0.1), (0.1, 0.25), (0.25, 0.5),
                  (0.5, 0.7), (0.7, 1.0), (1.0, 999)]
    for lo, hi in bins_mfe:
        n = ((rec["mfe_pre_sl_atr"] >= lo)
              & (rec["mfe_pre_sl_atr"] < hi)).sum()
        pct = 100 * n / len(rec)
        label = f">={lo}" if hi == 999 else f"{lo}-{hi}"
        print(f"    {label:<10} {n:>5,} ({pct:5.1f}%)")

    # Cross-tab: fast vs slow losers
    print()
    print("  Pre-SL MFE by speed of loss:")
    fast = rec[rec["time_to_sl_s"] <= 60]
    medium = rec[(rec["time_to_sl_s"] > 60)
                  & (rec["time_to_sl_s"] <= 180)]
    slow = rec[rec["time_to_sl_s"] > 180]
    for label, sub in [("Fast SL (<=60s)", fast),
                         ("Medium (60-180s)", medium),
                         ("Slow SL (>180s)", slow)]:
        if len(sub):
            print(f"    {label:<22} n={len(sub):>4,}  "
                   f"median MFE = {sub['mfe_pre_sl_atr'].median():.3f}  "
                   f"% MFE>0.5 = {100*(sub['mfe_pre_sl_atr']>=0.5).mean():.1f}%  "
                   f"% MFE>0.8 = {100*(sub['mfe_pre_sl_atr']>=0.8).mean():.1f}%")


if __name__ == "__main__":
    main()
