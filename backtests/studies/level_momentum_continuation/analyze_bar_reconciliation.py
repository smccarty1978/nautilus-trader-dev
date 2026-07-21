"""Bar-level reconciliation between catalog 1s/1m and trade-tick 1m.

Tasks (per user request):
  1. Verify contract symbol in BOTH data sources (catalog and trades).
  2. Check Databento 1s bar source — trade-only or quote-derived?
  3. Distribution of 1s-only triggers by date — cluster around rolls?
  4. For 1s-only triggers, decompose mismatch:
        - same minute key (close-time)?
        - OHLC delta
        - EMA13 delta
        - breach trigger boolean delta
        - bucket category
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import date

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

OUT = Path("studies/level_momentum_continuation/results_breakout")


def main():
    # ---------- 1. Contract verification ----------
    print("=" * 78)
    print("1. CONTRACT VERIFICATION (both data sources)")
    print("=" * 78)

    print("\n  NQ_v0_1s_2025.parquet (catalog source):")
    cat_raw = pd.read_parquet(
        "data/raw/NQ_v0_1s_2025.parquet",
        columns=["symbol"]).head(1000)
    print(f"    columns: {list(pd.read_parquet('data/raw/NQ_v0_1s_2025.parquet').columns)[:15]}")
    if "symbol" in cat_raw.columns:
        print(f"    symbol values: {cat_raw['symbol'].unique()}")
    else:
        print(f"    no 'symbol' column — checking instrument_id")
        cat_raw2 = pd.read_parquet(
            "data/raw/NQ_v0_1s_2025.parquet",
            columns=["instrument_id"]).head(1000)
        print(f"    instrument_id values: {cat_raw2['instrument_id'].unique()}")

    print("\n  NQ_trades_20250101_20251231.parquet (tick source):")
    trd_sample = pd.read_parquet(
        "data/raw/NQ_trades_20250101_20251231.parquet",
        columns=["symbol"]).head(1000)
    print(f"    symbol values (sample): {trd_sample['symbol'].unique()}")

    # Sample ALL distinct symbols across full file
    print(f"\n  Loading full symbol column to check for any roll/contract changes...", flush=True)
    full_syms = pd.read_parquet(
        "data/raw/NQ_trades_20250101_20251231.parquet",
        columns=["symbol"])
    print(f"    full file: {len(full_syms):,} rows")
    print(f"    distinct symbols: {full_syms['symbol'].unique()}")
    print(f"    symbol counts:")
    for s, c in full_syms['symbol'].value_counts().items():
        print(f"      {s}: {c:,}")

    # ---------- 2. Databento 1s bar metadata ----------
    print(f"\n{'='*78}")
    print(f"2. CATALOG 1s BAR SOURCE — schema check")
    print(f"{'='*78}")
    print(f"\n  Full columns of NQ_v0_1s_2025.parquet:")
    cat_full = pd.read_parquet("data/raw/NQ_v0_1s_2025.parquet").head(5)
    print(f"    columns: {list(cat_full.columns)}")
    print(f"    sample:")
    print(cat_full)

    # Databento ohlcv-1s schema info: rtype field
    if "rtype" in cat_full.columns:
        rtype_sample = pd.read_parquet(
            "data/raw/NQ_v0_1s_2025.parquet",
            columns=["rtype"]).head(100000)
        print(f"\n    rtype values in sample: {rtype_sample['rtype'].unique()}")
        print(f"    Databento rtype legend:")
        print(f"      rtype=32 = OHLCV-1S (1-second OHLCV)")
        print(f"      rtype=33 = OHLCV-1M")
        print(f"      Note: Databento ohlcv schema includes both trade")
        print(f"      and quote-derived prices in OHLC depending on dataset")

    # ---------- 3. Roll date proximity ----------
    print(f"\n{'='*78}")
    print(f"3. 1s-ONLY TRIGGER DATE DISTRIBUTION (around roll dates?)")
    print(f"{'='*78}")
    # NQ futures quarterly rolls: 3rd Thursday Mar, Jun, Sep, Dec
    # 2025 roll dates:
    roll_dates_2025 = [date(2025, 3, 20), date(2025, 6, 19),
                         date(2025, 9, 18), date(2025, 12, 18)]
    print(f"\n  NQ 2025 quarterly roll dates (3rd Thursday):")
    for rd in roll_dates_2025:
        print(f"    {rd}")

    only_1s = pd.read_parquet(OUT / "chain_audit_1s_only.parquet")
    only_1s["date"] = pd.to_datetime(
        only_1s["sig_1s"]).dt.date
    only_1s["dist_to_roll"] = only_1s["date"].apply(
        lambda d: min(abs((d - rd).days) for rd in roll_dates_2025))

    print(f"\n  Total 1s-only triggers: {len(only_1s):,}")
    print(f"\n  Distribution of distance to nearest roll date:")
    for thr in [0, 1, 2, 3, 5, 7, 14, 30, 60, 999]:
        n = (only_1s["dist_to_roll"] <= thr).sum()
        print(f"    within {thr:>3}d: {n:>5,} ({100*n/len(only_1s):.1f}%)")

    # By month
    only_1s["month"] = pd.to_datetime(
        only_1s["sig_1s"]).dt.to_period("M").astype(str)
    print(f"\n  By month:")
    for m, c in only_1s["month"].value_counts().sort_index().items():
        print(f"    {m}: {c:,}")

    # ---------- 4. Bar-level reconciliation ----------
    # We have aligned bars from analyze_1m_bar_compare.py
    print(f"\n{'='*78}")
    print(f"4. BAR-LEVEL RECONCILIATION at 1s-only trigger times")
    print(f"{'='*78}")
    aligned = pd.read_parquet(
        OUT / "1m_bar_compare_jan2025.parquet")
    print(f"  aligned 1m bars (Jan 2025): {len(aligned):,}")
    aligned["date"] = aligned.index.date
    # Subset to Jan-only 1s-only triggers
    only_1s_jan = only_1s[
        only_1s["date"].apply(lambda d: d.month == 1)].copy()
    print(f"  1s-only triggers in Jan 2025: {len(only_1s_jan):,}")
    # For each, find the corresponding aligned 1m bar (sig_1s + 1s ~= 1m close)
    # Actually sig_1s IS the 1m close time per our convention
    only_1s_jan["sig_min"] = (pd.to_datetime(only_1s_jan["sig_1s"])
                                 .dt.floor("1min")
                                 .dt.tz_convert("UTC"))
    only_1s_jan["sig_min_close"] = only_1s_jan["sig_min"] + pd.Timedelta(
        minutes=1)

    # Match by sig_1s to aligned (which is indexed at 1m close time)
    # aligned.index already in UTC
    aligned_idx = aligned.index
    sig_set = set(only_1s_jan["sig_1s"].astype("datetime64[ns]"))

    # Find mismatches
    matches = aligned[aligned.index.isin(
        only_1s_jan["sig_1s"].astype("datetime64[ns]").values)]
    print(f"\n  Aligned bars at 1s-only trigger times: {len(matches):,} of {len(only_1s_jan):,}")

    if len(matches) > 0:
        # Decompose mismatches
        matches = matches.copy()
        # close difference between catalog and tick
        # For trigger detection (Goldilocks needs prev close < L < cur close):
        # If close_cat differs from close_trd by enough, trigger fires
        # in one but not the other
        print(f"\n  At 1s-only trigger 1m bars, close diff distribution:")
        cd = matches["close_diff"].abs().values
        for thr in [0, 0.25, 0.5, 1.0, 2.0]:
            n = (cd > thr).sum()
            print(f"    |close diff| > {thr:>4.2f}: {n:>4,} ({100*n/len(cd):.1f}%)")

        # Mismatch decomposition
        # For each 1s-only trigger:
        # - is the 1m bar present in tick aggregation?
        # - if yes: do close prices differ?
        # - if same close: was there NO trigger generation in tick mode?
        n_total = len(only_1s_jan)
        n_present = len(matches)
        n_close_same = (matches["close_diff"].abs() < 0.01).sum()
        n_close_differ = (matches["close_diff"].abs() >= 0.01).sum()

        print(f"\n  DECOMPOSITION ({n_total:,} 1s-only Jan triggers):")
        print(f"    1m bar present in BOTH cat & trd: {n_present:,}")
        print(f"    1m bar in CAT only (no trades that minute): "
              f"{n_total - n_present:,}")
        print(f"    1m bar in BOTH, close IDENTICAL: {n_close_same:,}")
        print(f"    1m bar in BOTH, close DIFFERS: {n_close_differ:,}")

        # For "same close" cases, why did trigger fire in 1s but not tick?
        # Probably PRIOR_CLOSE differs (the 1m bar BEFORE the trigger)
        # or EMA13 differs

    # ---------- 5. Aligned bars on roll dates specifically ----------
    print(f"\n{'='*78}")
    print(f"5. ARE OHLC DIFFERENCES WORSE NEAR ROLL DATES?")
    print(f"{'='*78}")
    aligned["dist_to_roll"] = pd.to_datetime(aligned["date"]).apply(
        lambda d: min(abs((d.date() - rd).days) for rd in roll_dates_2025))
    by_dist = aligned.groupby("dist_to_roll").agg(
        n=("close_diff", "size"),
        pct_close_differ=("close_diff", lambda x: 100 * (x.abs() > 0).mean()),
        mean_abs_close_diff=("close_diff", lambda x: x.abs().mean()),
    )
    print(f"\n  OHLC differ rate by distance to nearest roll (Jan 2025 sample):")
    print(f"  {'days from roll':<15} {'n_bars':>8} {'%close_differ':>14} {'mean_abs_diff':>14}")
    for d, row in by_dist.head(30).iterrows():
        print(f"  {int(d):<15} {int(row['n']):>8,} "
              f"{row['pct_close_differ']:>13.2f}% "
              f"{row['mean_abs_close_diff']:>13.4f}")

    # ---------- 6. Show examples around supposed phantom triggers ----------
    print(f"\n{'='*78}")
    print(f"6. EXAMPLE 1s-ONLY TRIGGER BAR-LEVEL DETAIL")
    print(f"{'='*78}")
    ex = only_1s_jan.head(5)
    for _, row in ex.iterrows():
        sig_1s = pd.Timestamp(row["sig_1s"])
        print(f"\n  Signal time: {sig_1s}  dir={row['direction']}  L={row['breach_level']:.2f}")
        # Find this bar in aligned
        if sig_1s.tz is None:
            sig_1s = sig_1s.tz_localize("UTC")
        # Look in aligned
        if sig_1s in aligned.index:
            r = aligned.loc[sig_1s]
            print(f"    THIS bar:")
            print(f"      cat: O={r['open_cat']:.2f} H={r['high_cat']:.2f} "
                  f"L={r['low_cat']:.2f} C={r['close_cat']:.2f} vol={int(r['volume_cat'])}")
            print(f"      trd: O={r['open_trd']:.2f} H={r['high_trd']:.2f} "
                  f"L={r['low_trd']:.2f} C={r['close_trd']:.2f} vol={int(r['volume_trd'])}")
            # Prior bar
            try:
                prev_idx = aligned.index.get_loc(sig_1s) - 1
                if prev_idx >= 0:
                    prev = aligned.iloc[prev_idx]
                    print(f"    PRIOR bar (close = prev_close for trigger):")
                    print(f"      cat: C={prev['close_cat']:.2f}  trd: C={prev['close_trd']:.2f}")
                    # Did EACH cross the breach level?
                    L = row["breach_level"]
                    cat_crossed = (prev["close_cat"] < L < r["close_cat"]
                                       if row["direction"] == 1
                                       else prev["close_cat"] > L > r["close_cat"])
                    trd_crossed = (prev["close_trd"] < L < r["close_trd"]
                                       if row["direction"] == 1
                                       else prev["close_trd"] > L > r["close_trd"])
                    print(f"      cat crosses L? {cat_crossed}")
                    print(f"      trd crosses L? {trd_crossed}")
            except Exception as e:
                print(f"    (couldn't get prev: {e})")
        else:
            print(f"    Bar NOT in aligned set (i.e., catalog has bar, "
                  f"trade aggregation doesn't)")


if __name__ == "__main__":
    main()
