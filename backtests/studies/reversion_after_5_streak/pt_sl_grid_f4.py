"""PT × SL grid for the long-fade strategy with F4 filter (locked at 57.75 pts).

Goal: identify whether a different PT/SL combination than the current 1/2 ATR
produces a more stable IS→OOS edge, with the F4 filter held constant.

Approach:
  1. Load existing signals from feature_signals.parquet (signal indices,
     features, atr_at_signal). Signal definition unchanged.
  2. For each (PT_atr, SL_atr) combo, recompute bar-mode bracket outcomes
     via intra-bar OHLC scan with SL-first tie convention, EOD-flatten
     on bar at 15:00 CT, single-position dedup by bar exit (same as the
     existing signal generator). Forward bars must be 60s-consec + same RTH.
  3. Aggregate IS (2024-25) and OOS (2026) stats both baseline and F4-filtered
     for each combo. The F4 cutoff (total_exc_fast >= 57.75) is LOCKED.
  4. Per-year stability for top OOS-positive cells.

NOTES on multiple testing:
  - 5x5 PT/SL grid = 25 cells. We're scanning OOS performance directly,
    which is data-snooping. Treat the OOS-best cell with skepticism:
    likely overfit to 2026 Jan-Apr's specific volatility regime.
  - The honest reading is "consistency across cells" rather than "best cell".
    If many cells show similar OOS shape, the edge is real. If only one or
    two cells are positive OOS, it's noise.
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
NQ_MULT = 20.0
F4_CUTOFF = 57.75   # locked from prior IS Q5 derivation
PT_GRID = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
SL_GRID = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
RTH_END_MIN = 15 * 60
N_BOOT = 1000
RNG_SEED = 42
OUT = Path("studies/reversion_after_5_streak/results")


def load_1m_bars():
    print(f"Loading 1m bars 2020-2026...", flush=True)
    t0 = time.time()
    catalog = ParquetDataCatalog(CATALOG)
    bars = catalog.bars(
        bar_types=[BAR_TYPE],
        start=pd.Timestamp("2020-01-01", tz="UTC"),
        end=pd.Timestamp("2026-04-30 23:59:59", tz="UTC"),
    )
    df = pd.DataFrame({
        "ts_init":  [b.ts_init  for b in bars],
        "open":     [float(b.open)  for b in bars],
        "high":     [float(b.high)  for b in bars],
        "low":      [float(b.low)   for b in bars],
        "close":    [float(b.close) for b in bars],
    }).sort_values("ts_init").reset_index(drop=True)
    print(f"  {len(df):,} bars in {time.time()-t0:.0f}s", flush=True)
    return df


def session_of_close_ct(ts_init_ns):
    dt = pd.to_datetime(ts_init_ns, unit="ns", utc=True).tz_convert("America/Chicago")
    minutes = dt.hour * 60 + dt.minute
    rth = (minutes >= 8 * 60 + 30) & (minutes < RTH_END_MIN)
    return np.where(rth, "RTH", "ETH")


def session_end_ts(ts_init_ns: int) -> int:
    dt = pd.Timestamp(ts_init_ns, tz="UTC").tz_convert("America/Chicago")
    eod_ct = dt.replace(hour=15, minute=0, second=0, microsecond=0, nanosecond=0)
    return int(eod_ct.tz_convert("UTC").value)


def compute_outcome(bars_high, bars_low, bars_close, bars_ts_init,
                     bars_sess, i, c0, atr_i, pt_a, sl_a, n_total):
    """Bar-mode bracket outcome for a signal at bar i with (PT_atr, SL_atr).
    Walks forward from i+1 with SL-first tie convention. Stops at PT/SL/EOD.
    Returns (kind, outcome_atr, exit_bar)."""
    pt_px = c0 + pt_a * atr_i
    sl_px = c0 - sl_a * atr_i
    eod_ts = session_end_ts(int(bars_ts_init[i]))
    j = i + 1
    last_bar = i
    while j < n_total and bars_ts_init[j] < eod_ts:
        if bars_ts_init[j] - bars_ts_init[j - 1] != 60_000_000_000:
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
    # EOD-flatten
    if last_bar > i and last_bar < n_total:
        outcome = (float(bars_close[last_bar]) - c0) / atr_i
        return "eod", outcome, last_bar
    return "eod", 0.0, i


def bootstrap_mean_ci(arr, n_boot=N_BOOT, seed=RNG_SEED, ci=(0.025, 0.975)):
    if len(arr) < 5:
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(n_boot, len(arr)))
    means = arr[idx].mean(axis=1)
    return float(np.quantile(means, ci[0])), float(np.quantile(means, ci[1]))


def compute_dd(arr):
    if len(arr) == 0: return 0.0
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sigs = pd.read_parquet(OUT / "feature_signals.parquet")
    sigs = sigs.sort_values("signal_idx").reset_index(drop=True)
    print(f"Loaded {len(sigs):,} signals from feature_signals.parquet")

    bars = load_1m_bars()
    bars_high = bars["high"].to_numpy()
    bars_low  = bars["low"].to_numpy()
    bars_close = bars["close"].to_numpy()
    bars_ts   = bars["ts_init"].to_numpy()
    bars_sess = session_of_close_ct(bars_ts)
    n_total = len(bars)

    # We need to enforce single-position dedup PER (PT, SL) combo because
    # exit bars differ. Process signals chronologically per combo.
    grid_rows = []
    per_year_rows = []
    t0 = time.time()
    for pt_a in PT_GRID:
        for sl_a in SL_GRID:
            outcomes_atr = []
            outcomes_dollars = []
            outcomes_kind = []
            outcomes_idx = []   # signal_idx for join with features
            outcomes_year = []
            last_exit_bar = -10**12
            for _, row in sigs.iterrows():
                i = int(row["signal_idx"])
                if i <= last_exit_bar:
                    continue
                c0 = float(row["close_at_signal"])
                atr_i = float(row["atr_at_signal"])
                kind, oatr, exit_bar = compute_outcome(
                    bars_high, bars_low, bars_close, bars_ts, bars_sess,
                    i, c0, atr_i, pt_a, sl_a, n_total)
                outcomes_atr.append(oatr)
                outcomes_dollars.append(oatr * atr_i * NQ_MULT)
                outcomes_kind.append(kind)
                outcomes_idx.append(i)
                outcomes_year.append(int(row["year"]))
                last_exit_bar = exit_bar

            # Build a per-trade DataFrame for this combo
            combo_df = pd.DataFrame({
                "signal_idx": outcomes_idx,
                "year": outcomes_year,
                "kind": outcomes_kind,
                "outcome_atr": outcomes_atr,
                "outcome_dollars": outcomes_dollars,
            })
            # Join F4 feature (total_exc_fast)
            combo_df = combo_df.merge(
                sigs[["signal_idx", "total_exc_fast"]],
                on="signal_idx", how="left")

            # IS = 2024+2025, OOS = 2026
            is_df  = combo_df[combo_df["year"].isin([2024, 2025])]
            oos_df = combo_df[combo_df["year"] == 2026]
            is_f4  = is_df[is_df["total_exc_fast"] >= F4_CUTOFF]
            oos_f4 = oos_df[oos_df["total_exc_fast"] >= F4_CUTOFF]

            def agg(d):
                if len(d) == 0:
                    return dict(n=0, wr=np.nan, mean=np.nan, total=0.0,
                                ci_lo=np.nan, ci_hi=np.nan, dd=0.0)
                pt_n = (d["kind"] == "pt").sum()
                sl_n = (d["kind"] == "sl").sum()
                arr = d["outcome_dollars"].to_numpy()
                lo, hi = bootstrap_mean_ci(arr)
                return dict(n=len(d),
                              wr=pt_n / max(pt_n + sl_n, 1) * 100,
                              mean=float(arr.mean()),
                              total=float(arr.sum()),
                              ci_lo=lo, ci_hi=hi,
                              dd=compute_dd(arr))

            is_b   = agg(is_df)
            is_f   = agg(is_f4)
            oos_b  = agg(oos_df)
            oos_f  = agg(oos_f4)

            grid_rows.append({
                "PT": pt_a, "SL": sl_a, "RR": pt_a / sl_a,
                "IS_base_n":   is_b["n"],   "IS_base_mean":   is_b["mean"],
                "IS_base_wr":  is_b["wr"],  "IS_base_total":  is_b["total"],
                "IS_F4_n":     is_f["n"],   "IS_F4_mean":     is_f["mean"],
                "IS_F4_wr":    is_f["wr"],  "IS_F4_total":    is_f["total"],
                "IS_F4_ci_lo": is_f["ci_lo"], "IS_F4_ci_hi":  is_f["ci_hi"],
                "OOS_base_n":   oos_b["n"],   "OOS_base_mean":  oos_b["mean"],
                "OOS_base_wr":  oos_b["wr"],  "OOS_base_total": oos_b["total"],
                "OOS_F4_n":     oos_f["n"],   "OOS_F4_mean":    oos_f["mean"],
                "OOS_F4_wr":    oos_f["wr"],  "OOS_F4_total":   oos_f["total"],
                "OOS_F4_ci_lo": oos_f["ci_lo"], "OOS_F4_ci_hi": oos_f["ci_hi"],
                "OOS_F4_dd":    oos_f["dd"],
            })

            # Per-year for this combo (with F4 filter)
            for yr in sorted(combo_df["year"].unique()):
                y_df = combo_df[(combo_df["year"] == yr)
                                  & (combo_df["total_exc_fast"] >= F4_CUTOFF)]
                a = agg(y_df)
                per_year_rows.append({
                    "PT": pt_a, "SL": sl_a, "year": yr,
                    "n": a["n"], "wr": a["wr"], "mean": a["mean"],
                    "total": a["total"], "ci_lo": a["ci_lo"], "ci_hi": a["ci_hi"],
                })

        print(f"  PT={pt_a} done ({time.time()-t0:.0f}s)", flush=True)

    grid_df = pd.DataFrame(grid_rows)
    grid_df.to_csv(OUT / "pt_sl_grid_f4.csv", index=False)
    yr_df = pd.DataFrame(per_year_rows)
    yr_df.to_csv(OUT / "pt_sl_grid_f4_per_year.csv", index=False)

    # --- Print: OOS_F4_mean as a PT × SL matrix ---
    print("\n=== OOS 2026 F4-filtered mean $/trade (PT rows × SL cols) ===")
    pivot_mean = grid_df.pivot(index="PT", columns="SL", values="OOS_F4_mean")
    with pd.option_context("display.float_format", "{:+.2f}".format):
        print(pivot_mean.to_string())
    print("\n=== OOS 2026 F4-filtered total $ (PT rows × SL cols) ===")
    pivot_total = grid_df.pivot(index="PT", columns="SL", values="OOS_F4_total")
    with pd.option_context("display.float_format", "{:+,.0f}".format):
        print(pivot_total.to_string())
    print("\n=== OOS 2026 F4-filtered n (PT rows × SL cols) ===")
    pivot_n = grid_df.pivot(index="PT", columns="SL", values="OOS_F4_n")
    print(pivot_n.to_string())
    print("\n=== OOS 2026 F4-filtered WR resolved (PT rows × SL cols) ===")
    pivot_wr = grid_df.pivot(index="PT", columns="SL", values="OOS_F4_wr")
    with pd.option_context("display.float_format", "{:.1f}".format):
        print(pivot_wr.to_string())

    # IS comparison
    print("\n=== IS 2024-25 F4-filtered mean $/trade ===")
    pivot_is = grid_df.pivot(index="PT", columns="SL", values="IS_F4_mean")
    with pd.option_context("display.float_format", "{:+.2f}".format):
        print(pivot_is.to_string())

    # Top 5 cells by OOS F4 total
    print("\n=== TOP 8 CELLS BY OOS F4 TOTAL ===")
    top = grid_df.sort_values("OOS_F4_total", ascending=False).head(8)
    with pd.option_context("display.max_columns", None,
                           "display.width", 240,
                           "display.float_format", "{:.2f}".format):
        cols = ["PT", "SL", "RR", "IS_F4_n", "IS_F4_mean", "IS_F4_total",
                "OOS_F4_n", "OOS_F4_mean", "OOS_F4_wr", "OOS_F4_total",
                "OOS_F4_ci_lo", "OOS_F4_ci_hi", "OOS_F4_dd"]
        print(top[cols].to_string(index=False))

    # Per-year for the current PT=1/SL=2 reference plus the top OOS cell
    ref_pt, ref_sl = 1.0, 2.0
    top_row = top.iloc[0]
    top_pt, top_sl = float(top_row["PT"]), float(top_row["SL"])
    for (pt, sl, label) in [(ref_pt, ref_sl, "REFERENCE PT=1.0 SL=2.0"),
                              (top_pt, top_sl, f"TOP OOS PT={top_pt} SL={top_sl}")]:
        ydat = yr_df[(yr_df["PT"] == pt) & (yr_df["SL"] == sl)].sort_values("year")
        print(f"\n=== PER-YEAR F4 ({label}) ===")
        with pd.option_context("display.max_columns", None,
                               "display.width", 220,
                               "display.float_format", "{:.2f}".format):
            print(ydat.to_string(index=False))

    print(f"\nWrote: {OUT/'pt_sl_grid_f4.csv'}, {OUT/'pt_sl_grid_f4_per_year.csv'}")


if __name__ == "__main__":
    main()
