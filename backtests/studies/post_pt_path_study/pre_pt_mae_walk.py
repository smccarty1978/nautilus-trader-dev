"""Pre-PT MAE walk: for trades that hit +1 ATR PT, characterize the
maximum adverse excursion BEFORE the PT was reached.

Question: are winners typically clean (low pre-PT MAE) or messy
(deep pre-PT drawdown)? If most winners have pre-PT MAE well below
1 ATR, a tighter SL (e.g., 0.5 ATR) wouldn't kill many winners
while halving the per-loss size.

Sample: same 710 PT winners on 2026 RTH T=0.
Walk: fill_time -> pt_hit_time only (NOT the full regime window).
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
OUT.mkdir(parents=True, exist_ok=True)

NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0


def main():
    print("Loading 2026 event + label data...")
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
    df = df.merge(es[["event_id", "signal_direction",
                        "regime_exit_time"]], on="event_id")
    df = df[(df["fillable_at_T"] == True)
             & (df["is_rth_checkpoint"] == 1)].copy()
    print(f"  T=0 fillable RTH trades: {len(df):,}")

    pt = df[df["pt100_before_sl100"] == 1].copy()
    pt = pt.dropna(subset=[
        "bracket_resolution_time_s_pt100_before_sl100",
        "fill_time_actual", "fill_price", "atr_at_signal"])
    pt["pt_hit_ts_ns"] = (
        pt["fill_time_actual"].astype("int64")
        + (pt["bracket_resolution_time_s_pt100_before_sl100"]
           * 1_000_000_000).astype("int64"))
    print(f"  PT-1.0 winners: {len(pt):,}")
    print(f"  Avg ATR: {pt['atr_at_signal'].mean():.2f} pts")

    print("\nLoading 2026 1s bars...")
    t0 = time.time()
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    start = pd.Timestamp(int(pt["fill_time_actual"].min()),
                          unit="ns", tz="UTC") - pd.Timedelta(minutes=1)
    end = pd.Timestamp(int(pt["pt_hit_ts_ns"].max()),
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

    print("\nWalking entry -> PT for each winner...")
    t0 = time.time()
    records = []
    for _, row in pt.iterrows():
        fp = float(row["fill_price"])
        atr = float(row["atr_at_signal"])
        d = int(row["signal_direction"])
        fill_ts = int(row["fill_time_actual"])
        pt_hit_ts = int(row["pt_hit_ts_ns"])

        # Slice bars [fill_ts, pt_hit_ts] inclusive of pt_hit
        lo = np.searchsorted(bars_ts, fill_ts, side="left")
        hi = np.searchsorted(bars_ts, pt_hit_ts, side="right")
        if hi <= lo:
            continue
        seg_h = bars_h[lo:hi]
        seg_l = bars_l[lo:hi]
        seg_ts = bars_ts[lo:hi]

        # MAE = max adverse excursion from entry, in ATR
        if d == 1:
            mae_atr = (fp - seg_l).max() / atr  # how far below fp
            mfe_atr_pre_pt = (seg_h - fp).max() / atr
        else:
            mae_atr = (seg_h - fp).max() / atr  # how far above fp
            mfe_atr_pre_pt = (fp - seg_l).max() / atr

        # Time to PT hit (seconds)
        time_to_pt_s = (pt_hit_ts - fill_ts) / 1e9

        records.append({
            "event_id": int(row["event_id"]),
            "signal_direction": d,
            "atr_at_signal": atr,
            "time_to_pt_s": time_to_pt_s,
            "n_bars": int(hi - lo),
            "mae_pre_pt_atr": float(max(0.0, mae_atr)),
            "mfe_pre_pt_atr": float(mfe_atr_pre_pt),
        })
    print(f"  Walked {len(records):,} winners "
           f"({time.time()-t0:.0f}s)")

    rec = pd.DataFrame(records)
    rec.to_parquet(OUT / "pre_pt_mae_2026.parquet", index=False)

    # ----- Distributions -----
    print()
    print("=" * 72)
    print("PRE-PT MAE DISTRIBUTION (winners only, ATR units)")
    print("=" * 72)
    bins = [(0, 0.10), (0.10, 0.25), (0.25, 0.50),
             (0.50, 0.70), (0.70, 1.00),
             (1.00, 1.50), (1.50, 999)]
    for lo, hi in bins:
        n = ((rec["mae_pre_pt_atr"] >= lo)
              & (rec["mae_pre_pt_atr"] < hi)).sum()
        pct = 100 * n / len(rec)
        label = f">={lo}" if hi == 999 else f"{lo}-{hi}"
        print(f"  {label:<12} {n:>5,} ({pct:5.1f}%)")
    print()
    print(f"  Median pre-PT MAE: {rec['mae_pre_pt_atr'].median():.3f} ATR")
    print(f"  Mean   pre-PT MAE: {rec['mae_pre_pt_atr'].mean():.3f}")
    print(f"  P75: {rec['mae_pre_pt_atr'].quantile(0.75):.3f}")
    print(f"  P90: {rec['mae_pre_pt_atr'].quantile(0.90):.3f}")
    print(f"  P99: {rec['mae_pre_pt_atr'].quantile(0.99):.3f}")
    print(f"  Max: {rec['mae_pre_pt_atr'].max():.3f}")

    # ----- Tighter-SL survival rates -----
    print()
    print("=" * 72)
    print("TIGHTER-SL SURVIVAL RATE (% of winners that would still PT)")
    print("=" * 72)
    print(f"{'SL level':<12} {'Survivors':>10} {'Survival %':>12}")
    for sl in [0.25, 0.40, 0.50, 0.60, 0.70, 0.80, 1.00]:
        survivors = (rec["mae_pre_pt_atr"] < sl).sum()
        pct = 100 * survivors / len(rec)
        print(f"SL={sl:<6.2f}   {survivors:>10,} {pct:>11.1f}%")

    print()
    print(f"  710 winners total. SL=0.5 keeps {(rec['mae_pre_pt_atr']<0.5).sum()}, "
           f"loses {(rec['mae_pre_pt_atr']>=0.5).sum()}.")

    # ----- Time-to-PT vs MAE -----
    print()
    print("=" * 72)
    print("TIME TO PT vs PRE-PT MAE")
    print("=" * 72)
    fast = rec[rec["time_to_pt_s"] <= 60]
    medium = rec[(rec["time_to_pt_s"] > 60)
                  & (rec["time_to_pt_s"] <= 180)]
    slow = rec[rec["time_to_pt_s"] > 180]
    for label, sub in [("Fast (<=60s)", fast),
                         ("Medium (60-180s)", medium),
                         ("Slow (>180s)", slow)]:
        if len(sub):
            print(f"  {label:<20} n={len(sub):>4,}  "
                   f"median MAE = {sub['mae_pre_pt_atr'].median():.3f}  "
                   f"mean MAE = {sub['mae_pre_pt_atr'].mean():.3f}  "
                   f"% MAE>0.5 = {100*(sub['mae_pre_pt_atr']>=0.5).mean():.1f}%")

    # ----- Bracket EV math under different SL levels -----
    print()
    print("=" * 72)
    print("PROJECTED ECONOMICS WITH TIGHTER SL")
    print("=" * 72)
    print("Population: T=0 fillable RTH trades on 2026 (n=1,512)")
    print()

    # Current full population stats
    n_total = len(df)
    n_pt = (df["pt100_before_sl100"] == 1).sum()
    n_sl = (df["pt100_before_sl100"] == 0).sum()
    n_unr = df["pt100_before_sl100"].isna().sum()
    avg_atr = df["atr_at_signal"].mean()
    print(f"  Current outcomes: PT {n_pt} ({100*n_pt/n_total:.1f}%), "
           f"SL {n_sl} ({100*n_sl/n_total:.1f}%), "
           f"Unresolved {n_unr} ({100*n_unr/n_total:.1f}%)")
    print(f"  Avg ATR: {avg_atr:.2f} pts")
    print()

    # For tighter SL projection:
    # - Among current PT winners: only those with mae_pre_pt < new_SL still PT.
    #   Others would have hit the tighter SL first → become losses (at -new_SL ATR).
    # - Among current SL losers: still lose, but at -new_SL ATR (smaller loss).
    # - Among current unresolved: assume same fraction would have MAE >= new_SL → become SL at -new_SL.
    #   For simplicity we keep them as their current effective PnL (no change).

    # We have rec data for PT winners' pre-PT MAE.
    # We don't have pre-resolution MAE for SL losers (they SL'd at MAE >= 1.0 ATR by def).
    # For unresolved, assume neutral.

    print(f"{'SL level':<10} {'New PT %':>10} {'New SL %':>10} "
           f"{'Mean $':>12} {'PF':>6}")

    def project(new_sl_atr):
        # PT winners that survive (mae_pre_pt < new_sl_atr) → still PT
        n_pt_survive = (rec["mae_pre_pt_atr"] < new_sl_atr).sum()
        # PT winners that don't survive → become tighter-SL losses
        n_pt_lose = len(rec) - n_pt_survive
        # Original SL losers: still losses, at smaller magnitude
        n_sl_unchanged = n_sl
        # Unresolved: assume unchanged for this projection (neutral)

        # Per-trade dollars
        pt_pnl = 1.0 * avg_atr * NQ_MULT - COMMISSION - TICK_COST
        sl_pnl = -new_sl_atr * avg_atr * NQ_MULT - COMMISSION - 2 * TICK_COST
        unr_pnl = -0.7 * avg_atr * NQ_MULT - COMMISSION - TICK_COST  # proxy

        total = (n_pt_survive * pt_pnl
                  + (n_pt_lose + n_sl_unchanged) * sl_pnl
                  + n_unr * unr_pnl)
        n_trades = n_total
        mean_pnl = total / n_trades
        wins = n_pt_survive * pt_pnl
        losses = abs((n_pt_lose + n_sl_unchanged) * sl_pnl
                       + n_unr * unr_pnl)
        pf = wins / losses if losses > 0 else float("inf")
        return {
            "n_pt": n_pt_survive,
            "pt_pct": n_pt_survive / n_trades,
            "n_sl": n_pt_lose + n_sl_unchanged,
            "sl_pct": (n_pt_lose + n_sl_unchanged) / n_trades,
            "mean": mean_pnl,
            "pf": pf,
            "total": total,
        }

    for sl in [1.00, 0.80, 0.70, 0.60, 0.50, 0.40, 0.25]:
        p = project(sl)
        print(f"SL={sl:<5.2f}   {100*p['pt_pct']:>9.1f}% "
               f"{100*p['sl_pct']:>9.1f}% "
               f"${p['mean']:>10.2f}  {p['pf']:>5.2f}")

    # Note caveats
    print()
    print("Notes:")
    print("- Assumes regime-exit (unresolved) trades unchanged "
           "(simplification; some would now SL faster).")
    print("- 'New PT %' shows fraction of FULL population that still "
           "PTs at the tighter SL.")
    print("- Real strategy would also see some current SL losers "
           "exit faster (no MAE upside). Net effect: tighter SL "
           "ALWAYS reduces both PT count and per-loss size.")


if __name__ == "__main__":
    main()
