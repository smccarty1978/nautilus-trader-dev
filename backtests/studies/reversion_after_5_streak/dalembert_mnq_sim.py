"""D'Alembert position sizing simulation on MNQ, 2024-2025.

D'Alembert rules:
  - Start at size = 1 contract.
  - After a LOSS (NET < 0): size += 1
  - After a WIN  (NET > 0): size = max(1, size - 1)
  - Optional max-cap: if size > cap, stay at cap.

Trade universe: feature_signals.parquet, F4 filter applied
(total_exc_fast >= 57.75), chronological order, single-position
(already enforced in the signal generator).

Bar-mode P&L per contract per trade:
  gross = outcome_atr * atr_at_signal * MNQ_MULT      (MNQ_MULT = $2)
  net   = gross - $2.50 RT commission

D'Alembert sizes the position: trade_net = size * net_per_contract.

Tested:
  - Config A: PT=1.0 / SL=2.0  (current, tick-validated)
  - Config B: PT=1.5 / SL=3.0  (proposed new winner)
  - Caps: none, 5, 10

Per-trade outcomes for PT=1.5/SL=3.0 are recomputed via bar-mode bracket
(intra-bar OHLC, SL-first tie, EOD-flatten) since feature_signals only
stored PT=1/SL=2.

Output:
  studies/reversion_after_5_streak/results/dalembert_mnq.csv
  studies/reversion_after_5_streak/results/dalembert_mnq_summary.csv
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
from nautilus_trader.persistence.catalog import ParquetDataCatalog


CATALOG = "data/catalog/NQ_v0_2020_2026"
BAR_TYPE = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
MNQ_MULT = 2.0
COMMISSION_RT = 2.50    # per contract
F4_CUTOFF = 57.75
IS_YEARS = [2024, 2025]
CAPS = [None, 5, 10]
CONFIGS = [
    ("PT1.0_SL2.0", 1.0, 2.0),
    ("PT1.5_SL3.0", 1.5, 3.0),
]
OUT = Path("studies/reversion_after_5_streak/results")


def load_1m_bars():
    print(f"Loading 1m bars 2024-2025...", flush=True)
    catalog = ParquetDataCatalog(CATALOG)
    bars = catalog.bars(
        bar_types=[BAR_TYPE],
        start=pd.Timestamp("2024-01-01", tz="UTC"),
        end=pd.Timestamp("2025-12-31 23:59:59", tz="UTC"),
    )
    df = pd.DataFrame({
        "ts_init": [b.ts_init for b in bars],
        "open":    [float(b.open)  for b in bars],
        "high":    [float(b.high)  for b in bars],
        "low":     [float(b.low)   for b in bars],
        "close":   [float(b.close) for b in bars],
    }).sort_values("ts_init").reset_index(drop=True)
    print(f"  {len(df):,} bars", flush=True)
    return df


def session_end_ts(ts_init_ns: int) -> int:
    dt = pd.Timestamp(ts_init_ns, tz="UTC").tz_convert("America/Chicago")
    eod_ct = dt.replace(hour=15, minute=0, second=0, microsecond=0, nanosecond=0)
    return int(eod_ct.tz_convert("UTC").value)


def compute_outcome_at_combo(bars_high, bars_low, bars_close, bars_ts,
                               bars_sess, i, c0, atr_i, pt_a, sl_a, n_total):
    """Bar-mode bracket outcome for signal at bar i, given PT/SL multiples.
    Returns (kind, outcome_atr, exit_bar)."""
    pt_px = c0 + pt_a * atr_i
    sl_px = c0 - sl_a * atr_i
    eod_ts = session_end_ts(int(bars_ts[i]))
    j = i + 1
    last_bar = i
    while j < n_total and bars_ts[j] < eod_ts:
        if bars_ts[j] - bars_ts[j - 1] != 60_000_000_000:
            break
        if bars_sess[j] != "RTH":
            break
        bh = float(bars_high[j]); bl = float(bars_low[j])
        if bl <= sl_px:
            return "sl", -sl_a, j
        if bh >= pt_px:
            return "pt", pt_a, j
        last_bar = j
        j += 1
    if last_bar > i and last_bar < n_total:
        return "eod", (float(bars_close[last_bar]) - c0) / atr_i, last_bar
    return "eod", 0.0, i


def session_of_close_ct(ts_init_ns):
    dt = pd.to_datetime(ts_init_ns, unit="ns", utc=True).tz_convert("America/Chicago")
    minutes = dt.hour * 60 + dt.minute
    rth = (minutes >= 8 * 60 + 30) & (minutes < 15 * 60)
    return np.where(rth, "RTH", "ETH")


def simulate_dalembert(trades, mult, commission_rt, cap=None):
    """Apply D'Alembert sizing to a chronological list of per-contract NET dicts.
    Each trade dict has keys: outcome_atr, atr_at_signal, year, kind, signal_ts.
    Returns enriched per-trade list + summary dict."""
    size = 1
    cumulative = 0.0
    rows = []
    sizes_taken = []
    losing_streak = 0
    max_streak = 0
    streak_dollar = 0.0
    max_dollar_loss_streak = 0.0
    for t in trades:
        gross_per_ctr = t["outcome_atr"] * t["atr_at_signal"] * mult
        net_per_ctr = gross_per_ctr - commission_rt
        trade_net = net_per_ctr * size
        cumulative += trade_net
        rows.append({
            "signal_ts": t["signal_ts"],
            "year": t["year"],
            "kind": t["kind"],
            "size": size,
            "outcome_atr": t["outcome_atr"],
            "atr_at_signal": t["atr_at_signal"],
            "gross_per_ctr": gross_per_ctr,
            "net_per_ctr": net_per_ctr,
            "trade_net_dollars": trade_net,
            "cum_net": cumulative,
        })
        sizes_taken.append(size)
        if net_per_ctr > 0:
            size = max(1, size - 1)
            if losing_streak > max_streak:
                max_streak = losing_streak
            if streak_dollar < max_dollar_loss_streak:
                max_dollar_loss_streak = streak_dollar
            losing_streak = 0
            streak_dollar = 0.0
        else:
            losing_streak += 1
            streak_dollar += trade_net
            size += 1
            if cap is not None and size > cap:
                size = cap
    # Final streak tally
    if losing_streak > max_streak: max_streak = losing_streak
    if streak_dollar < max_dollar_loss_streak: max_dollar_loss_streak = streak_dollar

    df = pd.DataFrame(rows)
    if len(df) == 0:
        return df, {}
    df["peak"] = df["cum_net"].cummax()
    df["dd"] = df["cum_net"] - df["peak"]
    summary = {
        "n": len(df),
        "final_cum_net": float(df["cum_net"].iloc[-1]),
        "max_dd": float(df["dd"].min()),
        "max_position_size": int(max(sizes_taken)),
        "avg_position_size": float(np.mean(sizes_taken)),
        "max_losing_streak": int(max_streak),
        "max_dollar_loss_streak": float(max_dollar_loss_streak),
        "trades_at_size_1": int(sum(s == 1 for s in sizes_taken)),
        "trades_at_size_2": int(sum(s == 2 for s in sizes_taken)),
        "trades_at_size_3": int(sum(s == 3 for s in sizes_taken)),
        "trades_at_size_4_to_5": int(sum(4 <= s <= 5 for s in sizes_taken)),
        "trades_at_size_6_to_10": int(sum(6 <= s <= 10 for s in sizes_taken)),
        "trades_at_size_gt_10": int(sum(s > 10 for s in sizes_taken)),
        "worst_single_trade_dollars": float(df["trade_net_dollars"].min()),
        "best_single_trade_dollars": float(df["trade_net_dollars"].max()),
    }
    return df, summary


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sigs = pd.read_parquet(OUT / "feature_signals.parquet")
    sigs = sigs[sigs["year"].isin(IS_YEARS)].copy()
    sigs = sigs[sigs["total_exc_fast"] >= F4_CUTOFF].copy()
    sigs = sigs.sort_values("signal_ts").reset_index(drop=True)
    print(f"IS F4 trades 2024-2025: {len(sigs):,}", flush=True)

    bars = load_1m_bars()
    bars_high = bars["high"].to_numpy()
    bars_low = bars["low"].to_numpy()
    bars_close = bars["close"].to_numpy()
    bars_ts = bars["ts_init"].to_numpy()
    bars_sess = session_of_close_ct(bars_ts)
    n_total = len(bars)

    # signal_idx in feature_signals references the FULL catalog (2020-2026).
    # We need to remap to local indices in our 2024-25 bars subset.
    # Easier path: lookup by ts_init.
    ts_to_idx = {int(t): i for i, t in enumerate(bars_ts)}

    all_summary = []
    for cfg_name, pt_a, sl_a in CONFIGS:
        # Recompute outcomes for this PT/SL
        trades = []
        last_exit_bar = -10**12
        for _, row in sigs.iterrows():
            i = ts_to_idx.get(int(row["signal_ts"]))
            if i is None:
                continue
            if i <= last_exit_bar:
                continue
            c0 = float(row["close_at_signal"])
            atr_i = float(row["atr_at_signal"])
            kind, oatr, exit_bar = compute_outcome_at_combo(
                bars_high, bars_low, bars_close, bars_ts, bars_sess,
                i, c0, atr_i, pt_a, sl_a, n_total)
            trades.append({
                "signal_ts": int(row["signal_ts"]),
                "year": int(row["year"]),
                "kind": kind,
                "outcome_atr": float(oatr),
                "atr_at_signal": atr_i,
            })
            last_exit_bar = exit_bar
        print(f"\n=== Config {cfg_name} ({pt_a}/{sl_a}): {len(trades):,} trades ===",
              flush=True)
        # Baseline (1-contract flat)
        flat_df, flat_summary = simulate_dalembert(trades, MNQ_MULT, COMMISSION_RT, cap=1)
        flat_summary["config"] = cfg_name
        flat_summary["sizing"] = "flat_1_contract"
        all_summary.append(flat_summary)
        print(f"  FLAT (1 MNQ):   final ${flat_summary['final_cum_net']:>+9,.0f}  "
              f"max_dd ${flat_summary['max_dd']:>+9,.0f}  "
              f"max_streak={flat_summary['max_losing_streak']}")

        for cap in CAPS:
            cap_label = "uncapped" if cap is None else f"cap_{cap}"
            df, summary = simulate_dalembert(trades, MNQ_MULT, COMMISSION_RT, cap=cap)
            summary["config"] = cfg_name
            summary["sizing"] = f"dalembert_{cap_label}"
            all_summary.append(summary)
            df.to_csv(OUT / f"dalembert_{cfg_name}_{cap_label}.csv", index=False)
            print(f"  D'Alembert {cap_label:>10s}: "
                  f"final ${summary['final_cum_net']:>+9,.0f}  "
                  f"max_dd ${summary['max_dd']:>+9,.0f}  "
                  f"max_size={summary['max_position_size']}  "
                  f"avg_size={summary['avg_position_size']:.2f}  "
                  f"worst_trade ${summary['worst_single_trade_dollars']:>+8,.0f}")

    out_df = pd.DataFrame(all_summary)
    out_df.to_csv(OUT / "dalembert_mnq_summary.csv", index=False)

    print("\n=== FULL SUMMARY ===")
    with pd.option_context("display.max_columns", None,
                            "display.width", 240,
                            "display.float_format", "{:.2f}".format):
        cols = ["config", "sizing", "n", "final_cum_net", "max_dd",
                "max_position_size", "avg_position_size", "max_losing_streak",
                "max_dollar_loss_streak",
                "trades_at_size_1", "trades_at_size_2", "trades_at_size_3",
                "trades_at_size_4_to_5", "trades_at_size_6_to_10",
                "trades_at_size_gt_10",
                "worst_single_trade_dollars", "best_single_trade_dollars"]
        print(out_df[cols].to_string(index=False))

    print(f"\nWrote: {OUT/'dalembert_mnq_summary.csv'} + per-config trade-by-trade CSVs")


if __name__ == "__main__":
    main()
