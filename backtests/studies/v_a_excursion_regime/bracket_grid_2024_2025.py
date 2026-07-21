"""Bracket grid sweep on 2024 + 2025 (the years to actually search on).

PT × SL × Timeout × {with-xfer, no-xfer} on V_A pre-flip T-1 N=20 no-flip
cohort. VA-confirm trades keep baseline. Find combos positive on BOTH
2024 AND 2025 before considering 2026 OOS evaluation.

If any combos survive both years, evaluate them on 2026 OOS as well.
"""
from __future__ import annotations
import os, sys, time, gc
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

sys.path.insert(0, str(project_root / "studies" / "v_a_excursion_regime"))
from bracket_2025_2026 import (
    build_schedule, apply_roll_day_filter, round_tick,
    replay_va_baseline_1s, replay_no_flip_baseline_1s,
    PRE_FLIP_OOS, COLLECTOR_DIR,
    BRACKET_START_S, TOP_QUANTILE,
    NQ_MULT, COMMISSION_RT, ROLL_DATES, ROLL_EXCL_DAYS,
)


OUT_DIR = Path("studies/v_a_excursion_regime/results_v0/"
                  "bracket_grid_24_25")
ONE_S_BAR_PATHS = {
    2024: "data/raw/NQ_v0_1s_2024.parquet",
    2025: "data/raw/NQ_v0_1s_2025.parquet",
    2026: "data/raw/NQ_v0_1s_2026_ytd.parquet",
}
PT_GRID = [0.5, 0.75, 1.0, 1.25, 1.5]
SL_GRID = [0.5, 0.75, 1.0, 1.25, 1.5]
TIMEOUT_GRID = [180, 300, 600]
ROLL_DATES_FULL = {
    2024: ["2024-03-21", "2024-06-20", "2024-09-19", "2024-12-19"],
    2025: ["2025-03-20", "2025-06-19", "2025-09-18", "2025-12-18"],
    2026: ["2026-03-19"],
}


def load_year_bars_and_flips(year):
    bars = pd.read_parquet(ONE_S_BAR_PATHS[year],
                              columns=["open", "high", "low", "close"])
    bars.index = pd.to_datetime(bars.index, utc=True)
    bars = bars.sort_index()
    ts = bars.index.view("int64")
    o = bars["open"].to_numpy().astype("float64")
    h = bars["high"].to_numpy().astype("float64")
    l = bars["low"].to_numpy().astype("float64")
    c = bars["close"].to_numpy().astype("float64")

    snap = pd.read_parquet(
        f"{COLLECTOR_DIR}/v_a_v0_{year}/snapshots_with_vol_vwap.parquet",
        columns=["kind", "decision_ts", "direction", "session"])
    flips = snap[(snap["kind"] == "regime_flip")
                    & (snap["session"] == "RTH")].copy()
    flips["decision_ts"] = flips["decision_ts"].astype("int64")
    flips = flips.sort_values("decision_ts").reset_index(drop=True)
    fu = flips[flips["direction"] == 1]["decision_ts"].to_numpy()
    fd = flips[flips["direction"] == -1]["decision_ts"].to_numpy()
    return ts, o, h, l, c, fu, fd


def apply_roll_filter_year(df, year):
    """Roll-day filter using the year-specific roll dates."""
    if year not in ROLL_DATES_FULL:
        return df, 0
    ts = pd.to_datetime(df["entry_ts_ns"], unit="ns", utc=True)
    mask = pd.Series(False, index=df.index)
    for rd_str in ROLL_DATES_FULL[year]:
        rd = pd.Timestamp(rd_str, tz="UTC")
        near = ((ts >= rd - pd.Timedelta(days=ROLL_EXCL_DAYS))
                  & (ts <= rd + pd.Timedelta(days=ROLL_EXCL_DAYS)))
        mask = mask | near
    return df[~mask].copy().reset_index(drop=True), int(mask.sum())


def replay_with_bracket(
    bar_ts, bar_open, bar_high, bar_low, bar_close,
    entry_ts_ns, direction, atr,
    flips_dir_ts, flips_opp_ts,
    pt_atr, sl_atr, timeout_s, use_xfer,
):
    """Replay a single no-flip trade under a bracket policy."""
    d = direction
    eidx = int(np.searchsorted(bar_ts, entry_ts_ns, side="right"))
    if eidx >= len(bar_ts):
        return None, None
    entry_fill = float(bar_open[eidx])

    if d == 1:
        pt_lvl = round_tick(entry_fill + pt_atr * atr, "down")
        sl_lvl = round_tick(entry_fill - sl_atr * atr, "up")
    else:
        pt_lvl = round_tick(entry_fill - pt_atr * atr, "up")
        sl_lvl = round_tick(entry_fill + sl_atr * atr, "down")

    bs_ts = entry_ts_ns + BRACKET_START_S * 1_000_000_000
    to_ts = entry_ts_ns + timeout_s * 1_000_000_000
    bs = int(np.searchsorted(bar_ts, bs_ts, side="right"))
    te = int(np.searchsorted(bar_ts, to_ts, side="right"))
    te = min(te, len(bar_ts) - 1)
    if bs >= te:
        return None, None

    h = bar_high[bs:te + 1]
    l = bar_low[bs:te + 1]
    if d == 1:
        pt_touch = h >= pt_lvl
        sl_touch = l <= sl_lvl
    else:
        pt_touch = l <= pt_lvl
        sl_touch = h >= sl_lvl
    pf = int(np.argmax(pt_touch)) if pt_touch.any() else -1
    sf = int(np.argmax(sl_touch)) if sl_touch.any() else -1

    rg_first_ts = -1
    if use_xfer and len(flips_dir_ts) > 0:
        rel = flips_dir_ts[(flips_dir_ts >= bs_ts)
                              & (flips_dir_ts <= to_ts)]
        if len(rel) > 0:
            rg_first_ts = int(rel[0])

    events = []
    if pf >= 0:
        events.append((bs + pf, int(bar_ts[bs + pf]), "PT", pt_lvl))
    if sf >= 0:
        si = bs + sf
        ni = min(si + 1, len(bar_ts) - 1)
        events.append((si, int(bar_ts[si]), "SL",
                          float(bar_open[ni])))
    if rg_first_ts > 0:
        events.append((-1, rg_first_ts, "REGIME", None))

    if not events:
        return (te, int(bar_ts[te]), "TO",
                  float(bar_close[te])), entry_fill

    # Pick first by ts
    events.sort(key=lambda e: e[1])
    idx, evt_ts, reason, fill = events[0]
    if reason == "PT" and sf == pf:
        si = bs + sf
        ni = min(si + 1, len(bar_ts) - 1)
        return (si, int(bar_ts[si]), "SL",
                  float(bar_open[ni])), entry_fill

    if reason in ("PT", "SL", "TO"):
        return (idx, evt_ts, reason, fill), entry_fill

    # REGIME — hold to next opposite flip
    opp = flips_opp_ts[flips_opp_ts > evt_ts]
    if len(opp) > 0:
        opp_ts = int(opp[0])
        oi = int(np.searchsorted(bar_ts, opp_ts, side="right"))
        oi = min(oi, len(bar_ts) - 1)
        return (oi, int(bar_ts[oi]), "REGIME",
                  float(bar_open[oi])), entry_fill
    return (len(bar_ts) - 1, int(bar_ts[-1]), "REGIME_NO_OPP",
              float(bar_close[-1])), entry_fill


def evaluate_combo(no_flip_trades, va_trades_meta, va_net_pnl_sum,
                          bar_data, flips_data,
                          pt_atr, sl_atr, timeout_s, use_xfer):
    """Evaluate one bracket combo on a single year's cohort."""
    bar_ts, bar_open, bar_high, bar_low, bar_close = bar_data
    fu, fd = flips_data
    pnls_pts = []
    reasons = []
    for _, tr in no_flip_trades.iterrows():
        d = int(tr["direction"])
        result, entry_fill = replay_with_bracket(
            bar_ts, bar_open, bar_high, bar_low, bar_close,
            int(tr["entry_ts_ns"]), d,
            float(tr["atr_at_signal"]),
            fu if d == 1 else fd,
            fd if d == 1 else fu,
            pt_atr, sl_atr, timeout_s, use_xfer)
        if result is None:
            continue
        _, _, reason, exit_fill = result
        pnls_pts.append((exit_fill - entry_fill) * d)
        reasons.append(reason)
    pnls = np.array(pnls_pts) * NQ_MULT - COMMISSION_RT
    nf_total = pnls.sum()
    nf_n = len(pnls)
    combined_total = nf_total + va_net_pnl_sum
    combined_n = nf_n + len(va_trades_meta)
    rs = pd.Series(reasons)
    return {
        "nf_n": nf_n,
        "nf_total": nf_total,
        "nf_per_tr": pnls.mean() if nf_n > 0 else 0,
        "nf_wr": (pnls > 0).mean() if nf_n > 0 else 0,
        "combined_n": combined_n,
        "combined_total": combined_total,
        "combined_per_tr": combined_total / combined_n if combined_n > 0 else 0,
        "pt_rate": (rs == "PT").mean(),
        "sl_rate": (rs == "SL").mean(),
        "to_rate": (rs == "TO").mean(),
        "rg_rate": (rs == "REGIME").mean(),
    }


def prepare_year_data(year, oos_df, threshold):
    """Build schedule + replay VA baseline for one year."""
    sched = build_schedule(
        oos_df, year, threshold,
        f"{COLLECTOR_DIR}/v_a_v0_{year}/trades.parquet",
        f"{COLLECTOR_DIR}/v_a_v0_{year}/"
        f"snapshots_with_vol_vwap.parquet")
    n_pre = len(sched)
    sched, n_drop = apply_roll_filter_year(sched, year)
    print(f"  {year}: schedule {n_pre:,} → {len(sched):,} "
          f"(-{n_drop} roll-day)")

    bar_ts, bar_open, bar_high, bar_low, bar_close, fu, fd = \
        load_year_bars_and_flips(year)
    print(f"    {len(bar_ts):,} bars  flips: up={len(fu)}/dn={len(fd)}")

    # VA-confirm baseline
    va_sched = sched[sched["is_va_confirm"]].copy()
    va_results = []
    for _, tr in va_sched.iterrows():
        r = replay_va_baseline_1s(
            bar_ts, bar_open,
            int(tr["entry_ts_ns"]),
            int(tr["exit_ts_ns"]),
            int(tr["direction"]))
        if r is not None:
            va_results.append(r)
    va_df = pd.DataFrame(va_results)
    va_df["pnl_pts"] = (
        (va_df["exit_fill_price"] - va_df["entry_fill_price"])
        * va_df["direction"])
    va_df["net_pnl"] = va_df["pnl_pts"] * NQ_MULT - COMMISSION_RT
    va_net = va_df["net_pnl"].sum()

    # Baseline no-flip (for reference)
    nf_sched = sched[~sched["is_va_confirm"]].copy()
    bl_results = []
    for _, tr in nf_sched.iterrows():
        r = replay_no_flip_baseline_1s(
            bar_ts, bar_open,
            int(tr["entry_ts_ns"]),
            int(tr["direction"]))
        if r is not None:
            bl_results.append(r)
    bl_df = pd.DataFrame(bl_results)
    bl_df["pnl_pts"] = (
        (bl_df["exit_fill_price"] - bl_df["entry_fill_price"])
        * bl_df["direction"])
    bl_df["net_pnl"] = bl_df["pnl_pts"] * NQ_MULT - COMMISSION_RT
    baseline_combined = va_net + bl_df["net_pnl"].sum()

    print(f"    VA-confirm: n={len(va_df)}  ${va_net:+,.0f} "
          f"(${va_net/max(len(va_df),1):+.2f}/tr)")
    print(f"    Baseline (no bracket): combined "
          f"${baseline_combined:+,.0f} "
          f"(${baseline_combined/(len(va_df)+len(bl_df)):+.2f}/tr)")

    return {
        "sched": sched,
        "no_flip": nf_sched,
        "va_meta": va_sched,
        "va_net": va_net,
        "baseline_combined": baseline_combined,
        "bars": (bar_ts, bar_open, bar_high, bar_low, bar_close),
        "flips": (fu, fd),
    }


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Bracket grid sweep on 2024 + 2025 (in-sample search)")
    print(f"PT={PT_GRID}  SL={SL_GRID}  TO={TIMEOUT_GRID}  "
          f"+/− xfer = {2*len(PT_GRID)*len(SL_GRID)*len(TIMEOUT_GRID)} "
          f"combos per year")
    oos = pd.read_parquet(PRE_FLIP_OOS)
    threshold = oos["p_score"].quantile(1 - TOP_QUANTILE)
    print(f"Threshold: p >= {threshold:.4f}")

    print(f"\nPreparing data...")
    y24 = prepare_year_data(2024, oos, threshold)
    y25 = prepare_year_data(2025, oos, threshold)
    print(f"  ({time.time()-t0:.0f}s)")

    print(f"\nRunning grid...")
    rows = []
    for pt in PT_GRID:
        for sl in SL_GRID:
            for to in TIMEOUT_GRID:
                for xfer in [False, True]:
                    r24 = evaluate_combo(
                        y24["no_flip"], y24["va_meta"], y24["va_net"],
                        y24["bars"], y24["flips"],
                        pt, sl, to, xfer)
                    r25 = evaluate_combo(
                        y25["no_flip"], y25["va_meta"], y25["va_net"],
                        y25["bars"], y25["flips"],
                        pt, sl, to, xfer)
                    rows.append({
                        "pt": pt, "sl": sl, "to": to, "xfer": xfer,
                        "y24_total": r24["combined_total"],
                        "y24_per_tr": r24["combined_per_tr"],
                        "y24_nf_total": r24["nf_total"],
                        "y24_pt_rate": r24["pt_rate"],
                        "y24_sl_rate": r24["sl_rate"],
                        "y24_to_rate": r24["to_rate"],
                        "y24_rg_rate": r24["rg_rate"],
                        "y25_total": r25["combined_total"],
                        "y25_per_tr": r25["combined_per_tr"],
                        "y25_nf_total": r25["nf_total"],
                        "y25_pt_rate": r25["pt_rate"],
                        "y25_sl_rate": r25["sl_rate"],
                        "y25_to_rate": r25["to_rate"],
                        "y25_rg_rate": r25["rg_rate"],
                        "combined_total": r24["combined_total"]
                            + r25["combined_total"],
                        "both_pos": r24["combined_total"] > y24["baseline_combined"]
                            and r25["combined_total"] > y25["baseline_combined"],
                    })
    grid = pd.DataFrame(rows)
    grid.to_parquet(OUT_DIR / "grid_results.parquet", index=False)
    print(f"  {len(grid)} combos done ({time.time()-t0:.0f}s)")

    # Filter to combos beating baseline on BOTH years
    survivors = grid[grid["both_pos"]].copy()
    print(f"\n{'='*100}")
    print(f"COMBOS BEATING BASELINE ON BOTH 2024 AND 2025: {len(survivors)}/{len(grid)}")
    print(f"{'='*100}")
    print(f"  Baselines (no bracket combined): "
          f"2024=${y24['baseline_combined']:+,.0f} "
          f"2025=${y25['baseline_combined']:+,.0f}")
    if len(survivors) > 0:
        survivors = survivors.sort_values("combined_total",
                                                ascending=False)
        print(f"\n  {'PT':<5} {'SL':<5} {'TO':<5} {'X':<4} "
              f"{'2024 $':>10} {'2024 $/tr':>10} "
              f"{'2025 $':>10} {'2025 $/tr':>10} "
              f"{'Comb $':>10}")
        for _, r in survivors.head(20).iterrows():
            x = "Y" if r["xfer"] else "N"
            print(f"  {r['pt']:<5} {r['sl']:<5} {int(r['to']):<5} "
                  f"{x:<4} "
                  f"${r['y24_total']:>+8,.0f} "
                  f"${r['y24_per_tr']:>+8.2f} "
                  f"${r['y25_total']:>+8,.0f} "
                  f"${r['y25_per_tr']:>+8.2f} "
                  f"${r['combined_total']:>+8,.0f}")
    else:
        print("\n  NO bracket combo beats baseline on both years.")
        print("  Top 10 by combined PnL (none beat baseline):")
        print(f"  {'PT':<5} {'SL':<5} {'TO':<5} {'X':<4} "
              f"{'2024 $':>10} {'2024 $/tr':>10} "
              f"{'2025 $':>10} {'2025 $/tr':>10} "
              f"{'Comb $':>10}")
        for _, r in grid.sort_values("combined_total",
                                            ascending=False).head(10).iterrows():
            x = "Y" if r["xfer"] else "N"
            print(f"  {r['pt']:<5} {r['sl']:<5} {int(r['to']):<5} "
                  f"{x:<4} "
                  f"${r['y24_total']:>+8,.0f} "
                  f"${r['y24_per_tr']:>+8.2f} "
                  f"${r['y25_total']:>+8,.0f} "
                  f"${r['y25_per_tr']:>+8.2f} "
                  f"${r['combined_total']:>+8,.0f}")

    # If we have survivors, evaluate on 2026 OOS
    if len(survivors) > 0:
        print(f"\n{'='*100}")
        print(f"OUT-OF-SAMPLE: TOP SURVIVORS ON 2026")
        print(f"{'='*100}")
        del y24, y25
        gc.collect()
        y26 = prepare_year_data(2026, oos, threshold)
        oos_rows = []
        for _, r in survivors.head(20).iterrows():
            r26 = evaluate_combo(
                y26["no_flip"], y26["va_meta"], y26["va_net"],
                y26["bars"], y26["flips"],
                r["pt"], r["sl"], int(r["to"]), bool(r["xfer"]))
            oos_rows.append({**r.to_dict(),
                                "y26_total": r26["combined_total"],
                                "y26_per_tr": r26["combined_per_tr"]})
        oos_df = pd.DataFrame(oos_rows)
        oos_df["all3_total"] = (oos_df["y24_total"]
                                  + oos_df["y25_total"]
                                  + oos_df["y26_total"])
        oos_df = oos_df.sort_values("all3_total", ascending=False)
        oos_df.to_parquet(OUT_DIR / "grid_with_oos.parquet",
                             index=False)
        print(f"\n  {'PT':<5} {'SL':<5} {'TO':<5} {'X':<4} "
              f"{'2024 $':>9} {'2025 $':>9} {'2026 OOS':>10} "
              f"{'3yr $':>10}")
        print(f"  2026 baseline: "
              f"${y26['baseline_combined']:+,.0f}")
        for _, r in oos_df.iterrows():
            x = "Y" if r["xfer"] else "N"
            print(f"  {r['pt']:<5} {r['sl']:<5} {int(r['to']):<5} "
                  f"{x:<4} "
                  f"${r['y24_total']:>+7,.0f} "
                  f"${r['y25_total']:>+7,.0f} "
                  f"${r['y26_total']:>+8,.0f} "
                  f"${r['all3_total']:>+8,.0f}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
