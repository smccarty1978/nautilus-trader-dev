"""Post-PT path-shape descriptive study (2026).

For every T=0 trade that hit the +1 ATR PT, walk the actual 1s bars
from PT-hit moment forward through min(regime_exit, fill+30min).
Characterize the post-PT path:

  - How much further does it extend? (+1.5, +2, +3 ATR rate)
  - How deep does it retrace from peak?
  - Does it return to entry / past entry to original SL?
  - Among the big runners, how many would have stopped a normal
    trailing-stop or break-even-stop structure before continuing?

This is a descriptive study — no model, no strategy. Just measuring
what the price path looks like AFTER the first +1 ATR is reached.
"""

from __future__ import annotations
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)
sys.path.insert(0, str(project_root))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from nautilus_trader.persistence.catalog import ParquetDataCatalog

OUT = Path("studies/post_pt_path_study/results")
OUT.mkdir(parents=True, exist_ok=True)


def main():
    print("Loading 2026 event + label data...")
    es = pd.read_parquet(
        "studies/1m_regime_collector_v2/results/"
        "v2_event_summary_2026.parquet")
    feats = pd.read_parquet(
        "studies/1m_regime_collector_v2/results/"
        "v2_feature_snapshots_2026.parquet",
        columns=["event_id", "checkpoint_s", "fillable_at_T",
                  "fill_time_actual", "fill_price",
                  "atr_at_signal", "is_rth_checkpoint"])
    labels = pd.read_parquet(
        "studies/1m_regime_collector_v2/results/"
        "v2_outcome_labels_2026.parquet",
        columns=["event_id", "checkpoint_s",
                  "pt100_before_sl100",
                  "bracket_resolution_time_s_pt100_before_sl100",
                  "mfe_300s_atr", "mfe_600s_atr"])

    # T=0 trades only (one per event), RTH-only, fillable
    df = (feats[feats["checkpoint_s"] == 0]
          .merge(labels[labels["checkpoint_s"] == 0],
                  on=["event_id", "checkpoint_s"], how="left"))
    df = df.merge(es[["event_id", "signal_time", "signal_direction",
                        "regime_exit_time"]],
                    on="event_id", how="left")
    df = df[df["fillable_at_T"] == True].copy()
    df = df[df["is_rth_checkpoint"] == 1].copy()
    print(f"  T=0 fillable RTH trades: {len(df):,}")

    # Restrict to PT-1.0 winners (where the post-PT question even applies)
    pt = df[df["pt100_before_sl100"] == 1].copy()
    pt = pt.dropna(subset=[
        "bracket_resolution_time_s_pt100_before_sl100",
        "fill_time_actual", "fill_price", "atr_at_signal"])
    print(f"  PT-1.0 winners: {len(pt):,}")
    print(f"  Avg ATR: {pt['atr_at_signal'].mean():.2f} pts")
    print()

    # PT-hit timestamp = fill_time_actual + bracket_resolution_time_s
    pt["pt_hit_ts_ns"] = (
        pt["fill_time_actual"].astype("int64")
        + (pt["bracket_resolution_time_s_pt100_before_sl100"]
           * 1_000_000_000).astype("int64"))
    # Walk window end = min(regime_exit, pt_hit + 30min)
    pt["walk_end_ts_ns"] = np.minimum(
        pt["regime_exit_time"].astype("int64"),
        (pt["pt_hit_ts_ns"]
         + 30 * 60 * 1_000_000_000).astype("int64"))

    # Need the catalog 1s bars in range
    print("Loading 2026 1s bars...")
    t0 = time.time()
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    start = pd.Timestamp(int(pt["pt_hit_ts_ns"].min()),
                          unit="ns", tz="UTC")
    end = pd.Timestamp(int(pt["walk_end_ts_ns"].max()),
                        unit="ns", tz="UTC") + pd.Timedelta(hours=1)
    bars_nt = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=start, end=end)
    bars = pd.DataFrame({
        "ts_event": [b.ts_event for b in bars_nt],
        "open": [float(b.open) for b in bars_nt],
        "high": [float(b.high) for b in bars_nt],
        "low": [float(b.low) for b in bars_nt],
        "close": [float(b.close) for b in bars_nt],
    })
    bars = bars.sort_values("ts_event").reset_index(drop=True)
    bars_ts = bars["ts_event"].values
    bars_h = bars["high"].values
    bars_l = bars["low"].values
    print(f"  {len(bars):,} 1s bars loaded "
           f"({time.time() - t0:.0f}s)")

    # For each PT trade, walk bars from pt_hit through walk_end
    print("\nWalking post-PT paths for each trade...")
    t0 = time.time()
    records = []
    for _, row in pt.iterrows():
        fp = float(row["fill_price"])
        atr = float(row["atr_at_signal"])
        d = int(row["signal_direction"])
        pt_hit_ts = int(row["pt_hit_ts_ns"])
        walk_end = int(row["walk_end_ts_ns"])
        if walk_end <= pt_hit_ts:
            continue

        # PT level price = fp + d * 1.0 * atr
        pt_price = fp + d * 1.0 * atr

        # Slice bars in [pt_hit_ts, walk_end)
        lo = np.searchsorted(bars_ts, pt_hit_ts, side="left")
        hi = np.searchsorted(bars_ts, walk_end, side="left")
        if hi <= lo:
            continue
        seg_h = bars_h[lo:hi]
        seg_l = bars_l[lo:hi]
        seg_ts = bars_ts[lo:hi]

        # Direction-adjusted favorable / adverse from FILL price
        # (so MFE > 1.0 ATR by construction at PT-hit moment)
        if d == 1:
            mfe_atr = (seg_h - fp) / atr
            mae_atr = (fp - seg_l) / atr
        else:
            mfe_atr = (fp - seg_l) / atr
            mae_atr = (seg_h - fp) / atr

        # Peak MFE seen during post-PT walk (cumulative max)
        peak_mfe = np.maximum.accumulate(mfe_atr)
        # Drawdown from running peak (for trailing-stop simulation)
        # Since post-PT, we always start at >=1.0 mfe (PT just hit)
        # Pullback amount = peak - current
        if d == 1:
            current_from_entry_atr = (seg_h - fp) / atr  # max in bar
            current_low_from_entry_atr = (seg_l - fp) / atr  # min in bar (signed)
        else:
            current_from_entry_atr = (fp - seg_l) / atr
            current_low_from_entry_atr = (fp - seg_h) / atr

        # Walk metrics:
        # 1. peak post-PT extension (max favorable from entry)
        peak_extension_atr = float(np.max(mfe_atr))
        # 2. min from entry (deepest retrace)
        # In direction terms: min favorable = max retrace
        min_from_entry_atr = float(np.min(current_low_from_entry_atr))
        # 3. did we touch entry (return to fp)?
        # For long: did seg_l reach fp? For short: did seg_h reach fp?
        if d == 1:
            touched_entry = bool(np.any(seg_l <= fp))
            touched_sl_minus1atr = bool(
                np.any(seg_l <= fp - 1.0 * atr))
        else:
            touched_entry = bool(np.any(seg_h >= fp))
            touched_sl_minus1atr = bool(
                np.any(seg_h >= fp + 1.0 * atr))

        # 4. Did extension reach +1.5 / +2 / +3 ATR?
        reached_15 = peak_extension_atr >= 1.5
        reached_20 = peak_extension_atr >= 2.0
        reached_30 = peak_extension_atr >= 3.0

        # 5. Trailing-stop-50pct-of-MFE: would it have cut the runner?
        # Sim: starting at PT-hit (mfe=1.0), if at any point
        # current MFE drops to 0.5 * peak_so_far, exit.
        # Then check whether peak_so_far KEPT extending after the
        # would-be exit moment.
        peak_so_far = float(mfe_atr[0])  # starts at >=1.0
        trailing_exit_idx = None
        for i in range(len(mfe_atr)):
            if mfe_atr[i] > peak_so_far:
                peak_so_far = float(mfe_atr[i])
            # Trailing trigger: current pullback >= half the peak
            current_low_signed = current_low_from_entry_atr[i]
            if current_low_signed <= 0.5 * peak_so_far:
                trailing_exit_idx = i
                break
        if trailing_exit_idx is not None:
            mfe_at_trailing_exit = peak_so_far
            mfe_after_trailing_exit = float(np.max(
                mfe_atr[trailing_exit_idx:]))
            trailing_left_on_table_atr = max(
                0.0, mfe_after_trailing_exit - mfe_at_trailing_exit)
        else:
            mfe_at_trailing_exit = peak_extension_atr
            trailing_left_on_table_atr = 0.0

        # 6. BE-stop simulation: after PT hits, move SL to fp.
        # Did price ever return to fp (would BE stop trigger)?
        # If yes, what's the FURTHER mfe extension before BE was hit?
        if d == 1:
            be_hit_idx = np.argmax(seg_l <= fp)
            be_hit = bool(np.any(seg_l <= fp))
        else:
            be_hit_idx = np.argmax(seg_h >= fp)
            be_hit = bool(np.any(seg_h >= fp))
        if be_hit and be_hit_idx > 0:
            mfe_at_be_exit = float(np.max(mfe_atr[:be_hit_idx]))
            mfe_after_be_exit = float(np.max(mfe_atr[be_hit_idx:]))
            be_left_on_table_atr = max(
                0.0, mfe_after_be_exit - mfe_at_be_exit)
        else:
            mfe_at_be_exit = peak_extension_atr  # no exit, keeps running
            be_left_on_table_atr = 0.0

        records.append({
            "event_id": int(row["event_id"]),
            "signal_direction": d,
            "atr_at_signal": atr,
            "fill_price": fp,
            "pt_hit_ts_ns": pt_hit_ts,
            "walk_secs": int((walk_end - pt_hit_ts) / 1e9),
            "n_bars_walked": int(hi - lo),
            "peak_extension_atr": peak_extension_atr,
            "min_from_entry_atr": min_from_entry_atr,
            "touched_entry": touched_entry,
            "touched_sl_neg1atr": touched_sl_minus1atr,
            "reached_15": reached_15,
            "reached_20": reached_20,
            "reached_30": reached_30,
            "mfe_at_trailing_exit": mfe_at_trailing_exit,
            "trailing_left_on_table_atr": trailing_left_on_table_atr,
            "be_hit": be_hit,
            "mfe_at_be_exit": mfe_at_be_exit,
            "be_left_on_table_atr": be_left_on_table_atr,
        })
    print(f"  Walked {len(records):,} trades "
           f"({time.time() - t0:.0f}s)")

    rec_df = pd.DataFrame(records)
    rec_df.to_parquet(OUT / "post_pt_walks_2026.parquet", index=False)

    # ----- Aggregate report -----
    print("\n" + "=" * 72)
    print("POST-PT EXTENSION DISTRIBUTION (peak ATR after first +1.0)")
    print("=" * 72)
    bins = [(1.0, 1.25), (1.25, 1.5), (1.5, 2.0),
             (2.0, 3.0), (3.0, 5.0), (5.0, 999)]
    for lo, hi in bins:
        n = ((rec_df["peak_extension_atr"] >= lo)
              & (rec_df["peak_extension_atr"] < hi)).sum()
        pct = 100 * n / len(rec_df)
        label = f">={lo}" if hi == 999 else f"{lo}-{hi}"
        print(f"  {label:<10} {n:>6,} ({pct:5.1f}%)")
    print()
    print(f"  Median peak extension: "
           f"{rec_df['peak_extension_atr'].median():.3f} ATR")
    print(f"  Mean   peak extension: "
           f"{rec_df['peak_extension_atr'].mean():.3f} ATR")
    print(f"  P75 peak extension: "
           f"{rec_df['peak_extension_atr'].quantile(0.75):.3f}")
    print(f"  P90 peak extension: "
           f"{rec_df['peak_extension_atr'].quantile(0.90):.3f}")
    print()
    n_15 = int(rec_df["reached_15"].sum())
    n_20 = int(rec_df["reached_20"].sum())
    n_30 = int(rec_df["reached_30"].sum())
    print(f"  Reached >= +1.5 ATR: {n_15:,} "
           f"({100*n_15/len(rec_df):.1f}%)")
    print(f"  Reached >= +2.0 ATR: {n_20:,} "
           f"({100*n_20/len(rec_df):.1f}%)")
    print(f"  Reached >= +3.0 ATR: {n_30:,} "
           f"({100*n_30/len(rec_df):.1f}%)")

    print()
    print("=" * 72)
    print("POST-PT RETRACE DEPTH (deepest favorable-side dip after PT)")
    print("=" * 72)
    print(f"  min_from_entry_atr is the lowest favorable level reached")
    print(f"  (negative = price moved past entry into adverse region)")
    print()
    print(f"  Median min: {rec_df['min_from_entry_atr'].median():.3f} ATR")
    print(f"  Mean   min: {rec_df['min_from_entry_atr'].mean():.3f}")
    print(f"  P25 min:    {rec_df['min_from_entry_atr'].quantile(0.25):.3f}")
    print(f"  P10 min:    {rec_df['min_from_entry_atr'].quantile(0.10):.3f}")
    print()
    n_touched_entry = int(rec_df["touched_entry"].sum())
    n_touched_sl = int(rec_df["touched_sl_neg1atr"].sum())
    print(f"  Touched entry (returned to fp):       "
           f"{n_touched_entry:,} ({100*n_touched_entry/len(rec_df):.1f}%)")
    print(f"  Touched -1 ATR (would hit orig SL):   "
           f"{n_touched_sl:,} ({100*n_touched_sl/len(rec_df):.1f}%)")

    print()
    print("=" * 72)
    print("WOULD A TRAILING STOP HAVE CUT THE RUNNERS?")
    print("=" * 72)
    print(f"  Trailing-stop sim: exit when current MFE drops to 50% of peak")
    print()
    print(f"  Median MFE captured by trailing stop: "
           f"{rec_df['mfe_at_trailing_exit'].median():.3f} ATR")
    print(f"  Mean   MFE captured: "
           f"{rec_df['mfe_at_trailing_exit'].mean():.3f}")
    print()
    print(f"  Median ATR LEFT ON TABLE by trailing stop: "
           f"{rec_df['trailing_left_on_table_atr'].median():.3f}")
    print(f"  Mean   ATR LEFT ON TABLE: "
           f"{rec_df['trailing_left_on_table_atr'].mean():.3f}")
    n_left = (rec_df["trailing_left_on_table_atr"] > 0).sum()
    print(f"  Trades where trailing left ANY $ on table: "
           f"{n_left:,} ({100*n_left/len(rec_df):.1f}%)")
    n_left_05 = (rec_df["trailing_left_on_table_atr"] > 0.5).sum()
    print(f"  Trades left > 0.5 ATR on table: {n_left_05:,} "
           f"({100*n_left_05/len(rec_df):.1f}%)")
    n_left_10 = (rec_df["trailing_left_on_table_atr"] > 1.0).sum()
    print(f"  Trades left > 1.0 ATR on table: {n_left_10:,} "
           f"({100*n_left_10/len(rec_df):.1f}%)")

    print()
    print("=" * 72)
    print("WOULD A BREAK-EVEN STOP HAVE CUT THE RUNNERS?")
    print("=" * 72)
    print(f"  BE-stop sim: after PT, move SL to fill price. Exit at touch.")
    print()
    n_be = int(rec_df["be_hit"].sum())
    print(f"  BE stop triggered: {n_be:,} "
           f"({100*n_be/len(rec_df):.1f}%)")
    print(f"  Median MFE BEFORE BE exit: "
           f"{rec_df['mfe_at_be_exit'].median():.3f}")
    print(f"  Mean   MFE BEFORE BE exit: "
           f"{rec_df['mfe_at_be_exit'].mean():.3f}")
    print()
    print(f"  Median ATR LEFT ON TABLE by BE stop: "
           f"{rec_df['be_left_on_table_atr'].median():.3f}")
    print(f"  Mean   ATR LEFT ON TABLE by BE stop: "
           f"{rec_df['be_left_on_table_atr'].mean():.3f}")
    n_be_left = (rec_df["be_left_on_table_atr"] > 0).sum()
    print(f"  Trades BE left ANY on table: {n_be_left:,} "
           f"({100*n_be_left/len(rec_df):.1f}%)")
    n_be_left_10 = (rec_df["be_left_on_table_atr"] > 1.0).sum()
    print(f"  Trades BE left > 1.0 ATR on table: "
           f"{n_be_left_10:,} ({100*n_be_left_10/len(rec_df):.1f}%)")

    print()
    print("=" * 72)
    print("CROSS-TAB: BIG RUNNERS — DID PRICE RETRACE TO ENTRY FIRST?")
    print("=" * 72)
    big_runners = rec_df[rec_df["reached_20"]]
    if len(big_runners):
        n_big_touched_entry = int(big_runners["touched_entry"].sum())
        n_big_touched_sl = int(big_runners["touched_sl_neg1atr"].sum())
        print(f"  Big runners (peak ext >= +2.0 ATR): "
               f"{len(big_runners):,}")
        print(f"  ...that returned to entry first: "
               f"{n_big_touched_entry:,} "
               f"({100*n_big_touched_entry/len(big_runners):.1f}%)")
        print(f"  ...that touched -1 ATR before extending: "
               f"{n_big_touched_sl:,} "
               f"({100*n_big_touched_sl/len(big_runners):.1f}%)")

    huge_runners = rec_df[rec_df["reached_30"]]
    if len(huge_runners):
        n_huge_touched_entry = int(huge_runners["touched_entry"].sum())
        n_huge_touched_sl = int(huge_runners["touched_sl_neg1atr"].sum())
        print()
        print(f"  Huge runners (peak ext >= +3.0 ATR): "
               f"{len(huge_runners):,}")
        print(f"  ...that returned to entry first: "
               f"{n_huge_touched_entry:,} "
               f"({100*n_huge_touched_entry/len(huge_runners):.1f}%)")
        print(f"  ...that touched -1 ATR before extending: "
               f"{n_huge_touched_sl:,} "
               f"({100*n_huge_touched_sl/len(huge_runners):.1f}%)")


if __name__ == "__main__":
    main()
