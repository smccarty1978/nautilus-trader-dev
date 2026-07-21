"""Tick-validate V_A C strategy on 2026 OOS using MBP-1 quotes.

Strategy: V_A signal + delayed entry @+5m (from legacy entry_ts) +
unrealized-PnL filter (unr ≥ $325 at +5m using bar data).

Tick validation methodology:
  - Take the V_A C cohort already selected by the bar-driven filter
    (apples-to-apples — same trades, just real fills).
  - Replace bar-driven entry/exit fills with real top-of-book fills
    from MBP-1:
      Long entry  at +5m: fill = ask_at(entry_ts_C)
      Short entry at +5m: fill = bid_at(entry_ts_C)
      Long exit  at regime: fill = bid_at(exit_ts)
      Short exit at regime: fill = ask_at(exit_ts)
  - "_at(t)" = last quote with ts_event <= t (prevailing top-of-book)
  - Compare bar PnL vs tick PnL: per-trade slippage = bar - tick

Per memory rules:
  - Use real fills from top-of-book (no flat spread tax)
  - Commission $5/side ($10 RT) separate
  - Track bad-quote fallbacks (e.g. wide spreads, missing quotes)

Output: per-trade tick PnL, slippage breakdown, total $ tick vs bar.
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
COMMISSION = 5.0   # $5 one-way, $10 RT
DELAY_S = 300      # +5m for C strategy

OUT = Path("studies/v_a_excursion_regime/results_v0")
MBP1_PATHS = {
    1: "data/raw/NQ_v0_mbp1_2026_01.parquet",
    2: "data/raw/NQ_v0_mbp1_2026_02.parquet",
    3: "data/raw/NQ_v0_mbp1_2026_03.parquet",
    4: "data/raw/NQ_v0_mbp1_2026_04.parquet",
}


def load_mbp1_month(path):
    """Load MBP-1 file, keep only ts_event/bid/ask columns, sort by
    ts_event."""
    print(f"  loading {path}...", flush=True)
    df = pd.read_parquet(
        path, columns=["ts_event", "bid_px_00", "ask_px_00",
                          "bid_sz_00", "ask_sz_00"])
    print(f"    {len(df):,} quotes", flush=True)
    if df["ts_event"].dt.tz is None:
        df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
    df = df.sort_values("ts_event").reset_index(drop=True)
    return df


def lookup_quotes_at(mbp_df, target_ts_array):
    """Look up bid/ask at each timestamp in target_ts_array.
    Returns DataFrame with bid, ask, bid_sz, ask_sz, quote_age_s, ok.
    'ok' = a quote was found within 5 minutes."""
    ts_idx = mbp_df["ts_event"].values.astype("int64")
    bid = mbp_df["bid_px_00"].values
    ask = mbp_df["ask_px_00"].values
    bsz = mbp_df["bid_sz_00"].values
    asz = mbp_df["ask_sz_00"].values
    out = []
    for t in target_ts_array:
        # Find last quote with ts_event <= t
        j = np.searchsorted(ts_idx, np.int64(t), side="right") - 1
        if j < 0:
            out.append({"bid": np.nan, "ask": np.nan,
                          "bid_sz": 0, "ask_sz": 0,
                          "quote_age_s": np.nan, "ok": False})
            continue
        b = float(bid[j]); a = float(ask[j])
        age_ns = int(t) - int(ts_idx[j])
        age_s = age_ns / 1e9
        ok = (a > 0 and b > 0 and a > b
                and (a - b) < 5.0   # spread < $5/contract
                and age_s < 300)    # quote within 5min
        out.append({"bid": b, "ask": a,
                      "bid_sz": int(bsz[j]),
                      "ask_sz": int(asz[j]),
                      "quote_age_s": float(age_s), "ok": ok})
    return pd.DataFrame(out)


def main():
    t0 = time.time()
    print("=" * 78)
    print("TICK VALIDATION — V_A C strategy on 2026 OOS (Jan-Apr)")
    print("=" * 78)

    # Load V_A C cohort (already filtered on bar data)
    feats = pd.read_parquet(OUT / "checkpoint_features.parquet")
    n_pre = len(feats)
    feats = feats.sort_values(["entry_ts", "year"]).drop_duplicates(
        subset="entry_ts", keep="first").reset_index(drop=True)
    if n_pre != len(feats):
        print(f"  deduped: {n_pre:,} -> {len(feats):,}")
    is_alive_5m = feats[feats["alive_5m"]
                          & feats["year"].isin([2024, 2025])]
    thr_unr = is_alive_5m["f_unr_pnl_T_5m"].quantile(0.80)
    print(f"\n  V_A C filter: f_unr_pnl_T_5m >= ${thr_unr:.0f}")

    c_pop = feats[feats["alive_5m"]
                    & (feats["f_unr_pnl_T_5m"] >= thr_unr)].copy()
    c_2026 = c_pop[c_pop["year"] == 2026].copy()
    c_2026 = c_2026.sort_values("entry_ts").reset_index(drop=True)

    # checkpoint_features.parquet already has entry_ts, exit_ts,
    # exit_px, fill_px — no merge needed.
    assert c_2026["exit_ts"].notna().all(), "missing exit_ts"
    assert c_2026["fill_px"].notna().all(), "missing fill_px"
    assert c_2026["exit_px"].notna().all(), "missing exit_px"
    # Rename to consistent names used downstream
    c_2026 = c_2026.rename(
        columns={"fill_px": "fill_price", "exit_px": "exit_price"})
    print(f"  V_A C 2026 OOS cohort: {len(c_2026):,} trades")

    # Compute the +5m entry timestamp for C strategy
    c_2026["entry_ts_C"] = c_2026["entry_ts"] + DELAY_S * 1_000_000_000

    # ===== Group by month and look up quotes =====
    c_2026["entry_dt"] = pd.to_datetime(
        c_2026["entry_ts_C"], unit="ns", utc=True)
    c_2026["entry_month"] = c_2026["entry_dt"].dt.month
    c_2026["exit_dt"] = pd.to_datetime(
        c_2026["exit_ts"], unit="ns", utc=True)
    c_2026["exit_month"] = c_2026["exit_dt"].dt.month

    print(f"\n  Trade distribution by month:")
    print(c_2026["entry_month"].value_counts().sort_index())

    # For each trade, look up entry quote and exit quote.
    # Group by month for efficient MBP load.
    entry_quotes = pd.DataFrame()
    exit_quotes = pd.DataFrame()
    for month in sorted(set(c_2026["entry_month"].unique())
                          | set(c_2026["exit_month"].unique())):
        if month not in MBP1_PATHS:
            print(f"  WARN: no MBP-1 file for month {month}")
            continue
        mbp = load_mbp1_month(MBP1_PATHS[month])
        # Entry lookups
        entry_mask = c_2026["entry_month"] == month
        if entry_mask.sum() > 0:
            sub_idx = c_2026[entry_mask].index
            ts_arr = c_2026.loc[sub_idx, "entry_ts_C"].values
            res = lookup_quotes_at(mbp, ts_arr)
            res.index = sub_idx
            res.columns = [f"entry_{c}" for c in res.columns]
            entry_quotes = pd.concat([entry_quotes, res])
        # Exit lookups
        exit_mask = c_2026["exit_month"] == month
        if exit_mask.sum() > 0:
            sub_idx = c_2026[exit_mask].index
            ts_arr = c_2026.loc[sub_idx, "exit_ts"].values
            res = lookup_quotes_at(mbp, ts_arr)
            res.index = sub_idx
            res.columns = [f"exit_{c}" for c in res.columns]
            exit_quotes = pd.concat([exit_quotes, res])
        del mbp

    c_2026 = c_2026.join(entry_quotes).join(exit_quotes)

    # ===== Compute realistic fills =====
    # Long entry: fill at ASK; short entry: fill at BID
    # Long exit: fill at BID; short exit: fill at ASK
    long_mask = c_2026["direction"] == 1
    c_2026["entry_fill_tick"] = np.where(
        long_mask, c_2026["entry_ask"], c_2026["entry_bid"])
    c_2026["exit_fill_tick"] = np.where(
        long_mask, c_2026["exit_bid"], c_2026["exit_ask"])
    # Tick PnL
    c_2026["pts_tick"] = np.where(
        long_mask,
        c_2026["exit_fill_tick"] - c_2026["entry_fill_tick"],
        c_2026["entry_fill_tick"] - c_2026["exit_fill_tick"],
    )
    c_2026["pnl_tick"] = c_2026["pts_tick"] * NQ_MULT - 2 * COMMISSION

    # Bar PnL (already in d_pnl_5m)
    c_2026["pnl_bar"] = c_2026["d_pnl_5m"]

    # Slippage = bar - tick
    c_2026["slippage_per_trade"] = (
        c_2026["pnl_bar"] - c_2026["pnl_tick"])

    # ===== Quote quality =====
    bad_entry = ~c_2026["entry_ok"]
    bad_exit = ~c_2026["exit_ok"]
    print(f"\n{'='*78}")
    print(f"QUOTE QUALITY")
    print(f"{'='*78}")
    print(f"  Bad entry quote (gaps/wide spread): "
          f"{bad_entry.sum():,} / {len(c_2026):,}")
    print(f"  Bad exit quote: {bad_exit.sum():,} / {len(c_2026):,}")
    print(f"  Mean entry quote age: "
          f"{c_2026['entry_quote_age_s'].mean():.2f}s")
    print(f"  Mean exit quote age:  "
          f"{c_2026['exit_quote_age_s'].mean():.2f}s")
    print(f"  Mean entry spread: $"
          f"{(c_2026['entry_ask'] - c_2026['entry_bid']).mean():.4f}")
    print(f"  Mean exit spread:  $"
          f"{(c_2026['exit_ask'] - c_2026['exit_bid']).mean():.4f}")

    valid = ~(bad_entry | bad_exit)
    print(f"\n  Trades with valid quotes both sides: "
          f"{valid.sum():,} / {len(c_2026):,} "
          f"({100*valid.sum()/len(c_2026):.1f}%)")

    # ===== Headline comparison =====
    print(f"\n{'='*78}")
    print(f"HEADLINE — V_A C 2026 OOS  (n={len(c_2026):,})")
    print(f"{'='*78}")
    print(f"  {'metric':<40}  {'bar':>12}  {'tick (top of book)':>20}  "
          f"{'Δ':>10}")
    print("  " + "-" * 88)
    for label, mask in [("ALL trades", c_2026.index),
                            ("Valid quotes only", c_2026[valid].index)]:
        sub = c_2026.loc[mask]
        n = len(sub)
        if n == 0: continue
        bar_total = sub["pnl_bar"].sum()
        tick_total = sub["pnl_tick"].sum()
        bar_per = bar_total / n
        tick_per = tick_total / n
        slip = sub["slippage_per_trade"].sum()
        print(f"  {label} n={n:,}")
        print(f"  {'  Total $':<40}  ${bar_total:>+10,.0f}  "
              f"${tick_total:>+18,.0f}  ${tick_total-bar_total:>+8,.0f}")
        print(f"  {'  $/tr':<40}  {bar_per:>+12.2f}  "
              f"{tick_per:>+20.2f}  {tick_per-bar_per:>+10.2f}")
        print(f"  {'  Slippage per trade (bar - tick)':<40}  "
              f"{'':<12}  {'':<20}  {slip/n:>+10.2f}")
        bar_wr = (sub["pnl_bar"] > 0).mean() * 100
        tick_wr = (sub["pnl_tick"] > 0).mean() * 100
        print(f"  {'  WR %':<40}  {bar_wr:>+11.1f}%  "
              f"{tick_wr:>+19.1f}%")

    # ===== Slippage breakdown =====
    print(f"\n{'='*78}")
    print(f"SLIPPAGE BREAKDOWN (per trade, valid quotes only)")
    print(f"{'='*78}")
    sub = c_2026[valid].copy()
    if len(sub):
        # Decompose: entry slippage + exit slippage
        # bar_entry_fill = price_at_cp_5m (the bar we fill at +5m)
        # tick_entry_fill = ask/bid
        # entry_slip = (tick_entry_fill - bar_entry_fill) * dir
        #              (positive = pay more / receive less = bad for us)
        # bar_exit_fill = exit_price (V_A regime exit fill from collector)
        # tick_exit_fill = bid/ask
        # exit_slip = (bar_exit_fill - tick_exit_fill) * dir
        sub["entry_slip_pts"] = np.where(
            sub["direction"] == 1,
            sub["entry_fill_tick"] - sub["price_at_cp_5m"],
            sub["price_at_cp_5m"] - sub["entry_fill_tick"])
        sub["exit_slip_pts"] = np.where(
            sub["direction"] == 1,
            sub["exit_price"] - sub["exit_fill_tick"],
            sub["exit_fill_tick"] - sub["exit_price"])
        sub["entry_slip_$"] = sub["entry_slip_pts"] * NQ_MULT
        sub["exit_slip_$"] = sub["exit_slip_pts"] * NQ_MULT
        print(f"  Entry slip (positive = bad, pay above bar OPEN):")
        print(f"    mean ${sub['entry_slip_$'].mean():+.2f}/tr  "
              f"median ${sub['entry_slip_$'].median():+.2f}  "
              f"p90 ${sub['entry_slip_$'].quantile(0.9):+.2f}  "
              f"max ${sub['entry_slip_$'].max():+.2f}")
        print(f"  Exit slip (positive = bad, sell below bar exit_price):")
        print(f"    mean ${sub['exit_slip_$'].mean():+.2f}/tr  "
              f"median ${sub['exit_slip_$'].median():+.2f}  "
              f"p90 ${sub['exit_slip_$'].quantile(0.9):+.2f}  "
              f"max ${sub['exit_slip_$'].max():+.2f}")
        total_slip = (sub['entry_slip_$'].sum()
                       + sub['exit_slip_$'].sum())
        print(f"  Total slippage 2026: ${total_slip:+,.0f}  "
              f"(${total_slip/len(sub):+.2f}/tr)")

    # ===== Save per-trade detail =====
    out_p = OUT / "tick_validation_va_c_2026.parquet"
    c_2026.to_parquet(out_p)
    print(f"\n  Saved: {out_p}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
