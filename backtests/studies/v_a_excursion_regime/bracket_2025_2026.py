"""Run fallback bracket policy on 2025 + 2026 in 1s-bar mode.

Also re-runs 2026 MBP-1 with roll-day exclusion for a clean
year-over-year comparison.

Roll-day exclusion: drop trades within ±3 days of NQ quarterly roll
dates (3rd Thursday of Mar/Jun/Sep/Dec):
  2025: Mar 20, Jun 19, Sep 18, Dec 18
  2026: Mar 19, (Jun 18, Sep 17, Dec 17 — not in our OOS window)

Policy (grid winner from 2026):
  PT = 1.0 ATR (limit, fills at level)
  SL = 1.25 ATR (stop, fills at NEXT 1s bar OPEN after touch)
  Timeout = 600s (market exit at next bar OPEN after timeout_ts)
  Regime-flip-in-direction transition → hold to next opposite flip
  Bracket starts at entry + 60s
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


PRE_FLIP_OOS = ("studies/v_a_excursion_regime/results_v0/"
                  "pre_flip_T1_n20_oos.parquet")
PRE_FLIP_CANDIDATES = ("studies/v_a_excursion_regime/results_v0/"
                          "pre_flip_candidates_augmented.parquet")
COLLECTOR_DIR = "collectors/collector_v2/results"
ONE_S_BAR_PATHS = {
    2025: "data/raw/NQ_v0_1s_2025.parquet",
    2026: "data/raw/NQ_v0_1s_2026_ytd.parquet",
}
OUT_DIR = Path("studies/v_a_excursion_regime/results_v0/"
                  "bracket_2years")
PT_ATR = 1.0
SL_ATR = 1.25
TIMEOUT_S = 600
BRACKET_START_S = 60
TOP_QUANTILE = 0.10
HORIZON_S = 60
NQ_MULT = 20.0
COMMISSION_RT = 5.0   # $2.50 per side, $5 round trip (user's actual cost)
PRICE_TICK = 0.25
ROLL_EXCL_DAYS = 3

ROLL_DATES = {
    2025: ["2025-03-20", "2025-06-19", "2025-09-18", "2025-12-18"],
    2026: ["2026-03-19"],
}


def round_tick(px, side_round="nearest"):
    n = px / PRICE_TICK
    if side_round == "down":
        return np.floor(n) * PRICE_TICK
    elif side_round == "up":
        return np.ceil(n) * PRICE_TICK
    return np.round(n) * PRICE_TICK


def apply_roll_day_filter(df, ts_col, year):
    """Drop trades within ±ROLL_EXCL_DAYS of quarterly roll dates."""
    ts = pd.to_datetime(df[ts_col], unit="ns", utc=True)
    mask = pd.Series(False, index=df.index)
    for rd_str in ROLL_DATES[year]:
        rd = pd.Timestamp(rd_str, tz="UTC")
        near = ((ts >= rd - pd.Timedelta(days=ROLL_EXCL_DAYS))
                  & (ts <= rd + pd.Timedelta(days=ROLL_EXCL_DAYS)))
        mask = mask | near
    return df[~mask].copy().reset_index(drop=True), int(mask.sum())


def build_schedule(oos_df, year, threshold, va_trades_path, snap_path):
    """Build T-1 N=20 top-quantile schedule for a year, with VA exits."""
    fired = oos_df[(oos_df["p_score"] >= threshold)
                       & (oos_df["year"] == year)].copy()
    fired = fired.sort_values("close_ts_ns").reset_index(drop=True)
    fired["entry_ts_ns"] = fired["close_ts_ns"].astype("int64")
    fired["target_flip_ts_ns"] = (
        fired["close_ts_ns"] + HORIZON_S * 1_000_000_000)

    # VA-confirm exits
    snap = pd.read_parquet(snap_path,
                              columns=["kind", "decision_ts",
                                        "direction", "became_trade",
                                        "session"])
    b1 = snap[(snap["kind"] == "bar1_check")
                  & (snap["became_trade"])
                  & (snap["session"] == "RTH")].copy()
    b1["flip_bar_close_ts"] = b1["decision_ts"] - 61_000_000_000
    trades_full = pd.read_parquet(va_trades_path,
                                       columns=["decision_ts",
                                                 "direction",
                                                 "exit_ts",
                                                 "atr_at_signal",
                                                 "session"])
    va = b1.merge(
        trades_full[trades_full["session"] == "RTH"][[
            "decision_ts", "direction", "exit_ts", "atr_at_signal"]],
        on=["decision_ts", "direction"], how="inner")
    va_lookup = va.set_index(["flip_bar_close_ts", "direction"])

    cands = pd.read_parquet(PRE_FLIP_CANDIDATES,
                                columns=["close_ts_ns",
                                          "candidate_direction",
                                          "close_1m", "atr_1m"])
    cand_lookup = cands.set_index(
        ["close_ts_ns", "candidate_direction"])

    exit_ts_list, is_va_list, atr_list = [], [], []
    for _, fr in fired.iterrows():
        target = int(fr["target_flip_ts_ns"])
        d = int(fr["direction"])
        cts = int(fr["close_ts_ns"])
        try:
            va_row = va_lookup.loc[(target, d)]
            exit_ts_list.append(int(va_row["exit_ts"]))
            is_va_list.append(True)
            atr_list.append(float(va_row["atr_at_signal"]))
        except KeyError:
            exit_ts_list.append(target)
            is_va_list.append(False)
            try:
                atr_list.append(float(
                    cand_lookup.loc[(cts, d), "atr_1m"]))
            except KeyError:
                atr_list.append(np.nan)
    fired["exit_ts_ns"] = exit_ts_list
    fired["is_va_confirm"] = is_va_list
    fired["atr_at_signal"] = atr_list
    fired["year"] = year
    fired = fired.dropna(subset=["atr_at_signal"])
    return fired


def replay_one_1s_bracket(
    bar_ts, bar_open, bar_high, bar_low, bar_close,
    entry_ts_ns, direction, atr_at_signal,
    flips_dir_ts, flips_opp_ts,
):
    """Replay a single no-flip trade using 1s OHLC bars.

    Fills:
      entry: bar.open at next bar with open_ts > entry_ts_ns
      PT (limit): exact PT level (no slippage)
      SL (stop): bar.open of NEXT bar after touch
      TO (timeout): bar.close at timeout_ts
      REGIME: bar.open at next bar after opp_flip_ts
    """
    d = direction
    entry_idx = int(np.searchsorted(bar_ts, entry_ts_ns, side="right"))
    if entry_idx >= len(bar_ts):
        return None
    entry_fill = float(bar_open[entry_idx])

    if d == 1:
        pt_level = round_tick(entry_fill + PT_ATR * atr_at_signal,
                                  "down")
        sl_level = round_tick(entry_fill - SL_ATR * atr_at_signal,
                                  "up")
    else:
        pt_level = round_tick(entry_fill - PT_ATR * atr_at_signal,
                                  "up")
        sl_level = round_tick(entry_fill + SL_ATR * atr_at_signal,
                                  "down")

    bracket_start_ts = entry_ts_ns + BRACKET_START_S * 1_000_000_000
    timeout_ts = entry_ts_ns + TIMEOUT_S * 1_000_000_000
    bs_idx = int(np.searchsorted(bar_ts, bracket_start_ts,
                                       side="right"))
    to_idx = int(np.searchsorted(bar_ts, timeout_ts, side="right"))
    to_idx = min(to_idx, len(bar_ts) - 1)
    if bs_idx >= to_idx:
        return None

    h = bar_high[bs_idx:to_idx + 1]
    l = bar_low[bs_idx:to_idx + 1]
    if d == 1:
        pt_touch = h >= pt_level
        sl_touch = l <= sl_level
    else:
        pt_touch = l <= pt_level
        sl_touch = h >= sl_level
    pt_first = int(np.argmax(pt_touch)) if pt_touch.any() else -1
    sl_first = int(np.argmax(sl_touch)) if sl_touch.any() else -1

    # Regime flip in direction during bracket
    rg_first_ts = -1
    if len(flips_dir_ts) > 0:
        rel = flips_dir_ts[
            (flips_dir_ts >= bracket_start_ts)
            & (flips_dir_ts <= timeout_ts)]
        if len(rel) > 0:
            rg_first_ts = int(rel[0])

    events = []
    if pt_first >= 0:
        pt_ts = int(bar_ts[bs_idx + pt_first])
        events.append((pt_ts, "PT", pt_level))
    if sl_first >= 0:
        sl_bar_idx = bs_idx + sl_first
        sl_ts = int(bar_ts[sl_bar_idx])
        next_idx = sl_bar_idx + 1
        if next_idx >= len(bar_ts):
            next_idx = sl_bar_idx
        sl_fill = float(bar_open[next_idx])
        events.append((sl_ts, "SL", sl_fill))
    if rg_first_ts > 0:
        events.append((rg_first_ts, "REGIME", None))

    if not events:
        # Timeout — exit at bar close
        to_fill = float(bar_close[to_idx])
        return {
            "entry_ts_ns": entry_ts_ns,
            "entry_fill_price": entry_fill,
            "exit_ts_ns": int(bar_ts[to_idx]),
            "exit_fill_price": to_fill,
            "direction": d, "atr_at_signal": atr_at_signal,
            "pt_level": pt_level, "sl_level": sl_level,
            "exit_reason": "TO",
        }

    events.sort(key=lambda e: e[0])
    first_ts, reason, fill_price = events[0]
    if reason == "PT":
        same_ts = [e for e in events
                      if e[0] == first_ts and e[1] == "SL"]
        if same_ts:
            first_ts, reason, fill_price = same_ts[0]

    if reason in ("PT", "SL"):
        return {
            "entry_ts_ns": entry_ts_ns,
            "entry_fill_price": entry_fill,
            "exit_ts_ns": first_ts, "exit_fill_price": fill_price,
            "direction": d, "atr_at_signal": atr_at_signal,
            "pt_level": pt_level, "sl_level": sl_level,
            "exit_reason": reason,
        }

    # REGIME: hold to next opposite flip
    opp_after = flips_opp_ts[flips_opp_ts > first_ts]
    if len(opp_after) > 0:
        opp_ts = int(opp_after[0])
        opp_idx = int(np.searchsorted(bar_ts, opp_ts, side="right"))
        if opp_idx >= len(bar_ts):
            opp_idx = len(bar_ts) - 1
        opp_fill = float(bar_open[opp_idx])
        return {
            "entry_ts_ns": entry_ts_ns,
            "entry_fill_price": entry_fill,
            "exit_ts_ns": int(bar_ts[opp_idx]),
            "exit_fill_price": opp_fill,
            "direction": d, "atr_at_signal": atr_at_signal,
            "pt_level": pt_level, "sl_level": sl_level,
            "exit_reason": "REGIME",
        }
    return {
        "entry_ts_ns": entry_ts_ns,
        "entry_fill_price": entry_fill,
        "exit_ts_ns": int(bar_ts[-1]),
        "exit_fill_price": float(bar_close[-1]),
        "direction": d, "atr_at_signal": atr_at_signal,
        "pt_level": pt_level, "sl_level": sl_level,
        "exit_reason": "REGIME_NO_OPP",
    }


def replay_va_baseline_1s(
    bar_ts, bar_open,
    entry_ts_ns, exit_ts_ns, direction,
):
    """VA-confirm baseline — fill entry and exit at next 1s bar OPEN."""
    entry_idx = int(np.searchsorted(bar_ts, entry_ts_ns, side="right"))
    exit_idx = int(np.searchsorted(bar_ts, exit_ts_ns, side="right"))
    if entry_idx >= len(bar_ts) or exit_idx >= len(bar_ts):
        return None
    return {
        "entry_ts_ns": entry_ts_ns,
        "entry_fill_price": float(bar_open[entry_idx]),
        "exit_ts_ns": int(bar_ts[exit_idx]),
        "exit_fill_price": float(bar_open[exit_idx]),
        "direction": direction,
    }


def replay_no_flip_baseline_1s(
    bar_ts, bar_open, entry_ts_ns, direction,
):
    """No-flip baseline — exit at +60s bar OPEN (current policy)."""
    entry_idx = int(np.searchsorted(bar_ts, entry_ts_ns, side="right"))
    exit_ts = entry_ts_ns + 60 * 1_000_000_000
    exit_idx = int(np.searchsorted(bar_ts, exit_ts, side="right"))
    if entry_idx >= len(bar_ts) or exit_idx >= len(bar_ts):
        return None
    return {
        "entry_ts_ns": entry_ts_ns,
        "entry_fill_price": float(bar_open[entry_idx]),
        "exit_ts_ns": int(bar_ts[exit_idx]),
        "exit_fill_price": float(bar_open[exit_idx]),
        "direction": direction,
    }


def load_year_data(year):
    """Load 1s bars + regime flips for a year."""
    bars = pd.read_parquet(ONE_S_BAR_PATHS[year],
                              columns=["open", "high", "low", "close"])
    bars.index = pd.to_datetime(bars.index, utc=True)
    bars = bars.sort_index()
    bar_ts = bars.index.view("int64")
    bar_open = bars["open"].to_numpy().astype("float64")
    bar_high = bars["high"].to_numpy().astype("float64")
    bar_low = bars["low"].to_numpy().astype("float64")
    bar_close = bars["close"].to_numpy().astype("float64")

    snap = pd.read_parquet(
        f"{COLLECTOR_DIR}/v_a_v0_{year}/snapshots_with_vol_vwap.parquet",
        columns=["kind", "decision_ts", "direction", "session"])
    flips = snap[(snap["kind"] == "regime_flip")
                    & (snap["session"] == "RTH")].copy()
    flips["decision_ts"] = flips["decision_ts"].astype("int64")
    flips = flips.sort_values("decision_ts").reset_index(drop=True)
    flips_up_ts = flips[flips["direction"] == 1
                          ]["decision_ts"].to_numpy()
    flips_dn_ts = flips[flips["direction"] == -1
                          ]["decision_ts"].to_numpy()
    return bar_ts, bar_open, bar_high, bar_low, bar_close, \
              flips_up_ts, flips_dn_ts


def run_year(year, oos_df, threshold):
    print(f"\n{'='*78}")
    print(f"YEAR {year}")
    print(f"{'='*78}")
    t0 = time.time()
    # Build schedule
    sched = build_schedule(
        oos_df, year, threshold,
        f"{COLLECTOR_DIR}/v_a_v0_{year}/trades.parquet",
        f"{COLLECTOR_DIR}/v_a_v0_{year}/"
        f"snapshots_with_vol_vwap.parquet")
    n_pre_roll = len(sched)
    sched, n_dropped = apply_roll_day_filter(
        sched, "entry_ts_ns", year)
    print(f"  Schedule: {n_pre_roll:,} → {len(sched):,} after roll-day "
          f"exclusion (dropped {n_dropped} within ±{ROLL_EXCL_DAYS}d of "
          f"rolls)")
    print(f"    VA-confirm rate: {sched['is_va_confirm'].mean():.1%}")
    print(f"    Direction split: "
          f"{sched['direction'].value_counts().to_dict()}")

    # Load year data
    print(f"  Loading 1s bars + flips...")
    bar_ts, bar_open, bar_high, bar_low, bar_close, \
        flips_up_ts, flips_dn_ts = load_year_data(year)
    print(f"    {len(bar_ts):,} 1s bars  "
          f"flips: up={len(flips_up_ts):,} dn={len(flips_dn_ts):,}  "
          f"({time.time()-t0:.0f}s)")

    # Replay — both BRACKET policy and BASELINE policy
    results = []
    baseline_results = []
    for _, tr in sched.iterrows():
        d = int(tr["direction"])
        if bool(tr["is_va_confirm"]):
            r = replay_va_baseline_1s(
                bar_ts, bar_open,
                int(tr["entry_ts_ns"]),
                int(tr["exit_ts_ns"]), d)
            if r is not None:
                r["is_va_confirm"] = True
                r["exit_reason"] = "VA_BASELINE"
                r["atr_at_signal"] = float(tr["atr_at_signal"])
                results.append(r)
                # Baseline same as VA hold-to-flip (no change)
                baseline_results.append(dict(r))
        else:
            r = replay_one_1s_bracket(
                bar_ts, bar_open, bar_high, bar_low, bar_close,
                int(tr["entry_ts_ns"]), d,
                float(tr["atr_at_signal"]),
                flips_up_ts if d == 1 else flips_dn_ts,
                flips_dn_ts if d == 1 else flips_up_ts)
            if r is not None:
                r["is_va_confirm"] = False
                results.append(r)
                # Baseline: exit at +60s
                b = replay_no_flip_baseline_1s(
                    bar_ts, bar_open, int(tr["entry_ts_ns"]), d)
                if b is not None:
                    b["is_va_confirm"] = False
                    b["exit_reason"] = "NF_60S_BASELINE"
                    b["atr_at_signal"] = float(tr["atr_at_signal"])
                    baseline_results.append(b)
    df = pd.DataFrame(results)
    df["pnl_pts"] = (
        (df["exit_fill_price"] - df["entry_fill_price"])
        * df["direction"])
    df["gross_pnl"] = df["pnl_pts"] * NQ_MULT
    df["net_pnl"] = df["gross_pnl"] - COMMISSION_RT
    df["year"] = year
    df["entry_dt"] = pd.to_datetime(df["entry_ts_ns"], unit="ns",
                                          utc=True)
    df["month"] = df["entry_dt"].dt.month

    # Baseline df
    bdf = pd.DataFrame(baseline_results)
    bdf["pnl_pts"] = (
        (bdf["exit_fill_price"] - bdf["entry_fill_price"])
        * bdf["direction"])
    bdf["gross_pnl"] = bdf["pnl_pts"] * NQ_MULT
    bdf["net_pnl"] = bdf["gross_pnl"] - COMMISSION_RT
    bdf["year"] = year

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_DIR / f"replay_1s_{year}.parquet", index=False)
    bdf.to_parquet(OUT_DIR / f"baseline_1s_{year}.parquet",
                       index=False)

    # Report
    print(f"\n  Year {year} results ({time.time()-t0:.0f}s):")
    print(f"    Total trades: {len(df):,}  "
          f"Total: ${df['net_pnl'].sum():+,.0f}  "
          f"Mean: ${df['net_pnl'].mean():+.2f}/tr  "
          f"WR: {(df['net_pnl']>0).mean():.1%}")
    print(f"  Per cohort:")
    va = df[df["is_va_confirm"]]
    nf = df[~df["is_va_confirm"]]
    print(f"    VA-confirm: n={len(va):>4}  "
          f"${va['net_pnl'].sum():+,.0f}  "
          f"${va['net_pnl'].mean():+.2f}/tr  "
          f"WR={(va['net_pnl']>0).mean():.1%}")
    print(f"    No-flip:    n={len(nf):>4}  "
          f"${nf['net_pnl'].sum():+,.0f}  "
          f"${nf['net_pnl'].mean():+.2f}/tr  "
          f"WR={(nf['net_pnl']>0).mean():.1%}")
    print(f"  No-flip exit reasons:")
    for reason in ["PT", "SL", "TO", "REGIME", "REGIME_NO_OPP"]:
        sub = nf[nf["exit_reason"] == reason]
        if len(sub) > 0:
            print(f"    {reason:<14}: n={len(sub):>4}  "
                  f"({len(sub)/len(nf):>5.1%})  "
                  f"${sub['net_pnl'].sum():+9,.0f}  "
                  f"${sub['net_pnl'].mean():+.2f}/tr")
    print(f"  Per-month:")
    for mo in sorted(df["month"].unique()):
        sub = df[df["month"] == mo]
        sub_va = sub[sub["is_va_confirm"]]
        sub_nf = sub[~sub["is_va_confirm"]]
        print(f"    Mo {mo:02d}: n={len(sub):>4}  "
              f"${sub['net_pnl'].sum():+8,.0f}  "
              f"${sub['net_pnl'].mean():+6.2f}/tr  "
              f"WR={(sub['net_pnl']>0).mean():.1%}  "
              f"NF:${sub_nf['net_pnl'].sum() if len(sub_nf) else 0:+7,.0f}")

    print(f"  BASELINE (no bracket, +60s exit on no-flip):")
    print(f"    Total: ${bdf['net_pnl'].sum():+,.0f}  "
          f"${bdf['net_pnl'].mean():+.2f}/tr")
    bdf_nf = bdf[~bdf["is_va_confirm"]]
    print(f"    No-flip: ${bdf_nf['net_pnl'].sum():+,.0f}  "
          f"${bdf_nf['net_pnl'].mean():+.2f}/tr")
    print(f"  BRACKET vs BASELINE:")
    print(f"    Combined Δ: "
          f"${df['net_pnl'].sum()-bdf['net_pnl'].sum():+,.0f}  "
          f"(${df['net_pnl'].mean()-bdf['net_pnl'].mean():+.2f}/tr)")
    print(f"    No-flip  Δ: "
          f"${nf['net_pnl'].sum()-bdf_nf['net_pnl'].sum():+,.0f}  "
          f"(${nf['net_pnl'].mean()-bdf_nf['net_pnl'].mean():+.2f}/tr)")

    del bar_ts, bar_open, bar_high, bar_low, bar_close
    gc.collect()
    return df, bdf


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Policy: PT={PT_ATR} / SL={SL_ATR} / TO={TIMEOUT_S}s + "
          f"regime transition")
    print(f"Roll-day exclusion: ±{ROLL_EXCL_DAYS} days around "
          f"quarterly rolls")

    oos = pd.read_parquet(PRE_FLIP_OOS)
    threshold = oos["p_score"].quantile(1 - TOP_QUANTILE)
    print(f"\nGlobal top-{TOP_QUANTILE:.0%} threshold: p >= "
          f"{threshold:.4f}")
    print(f"Pre-filter: 2024 n={(oos['year']==2024).sum():,}  "
          f"2025 n={(oos['year']==2025).sum():,}  "
          f"2026 n={(oos['year']==2026).sum():,}")
    fired = oos[oos["p_score"] >= threshold]
    print(f"Top-10% fires: 2024 n={(fired['year']==2024).sum():,}  "
          f"2025 n={(fired['year']==2025).sum():,}  "
          f"2026 n={(fired['year']==2026).sum():,}")

    df_2025, bdf_2025 = run_year(2025, oos, threshold)
    df_2026, bdf_2026 = run_year(2026, oos, threshold)

    # Combined summary
    print(f"\n{'='*78}")
    print(f"SUMMARY (1s bar mode, roll-days excluded)")
    print(f"{'='*78}")
    print(f"  {'Year':<6} {'n':>6} "
          f"{'BL Total':>12} {'BL $/tr':>10} "
          f"{'BR Total':>12} {'BR $/tr':>10} "
          f"{'Δ Total':>10} {'Δ $/tr':>9}")
    for year, df, bdf in [(2025, df_2025, bdf_2025),
                                  (2026, df_2026, bdf_2026)]:
        delta = df["net_pnl"].sum() - bdf["net_pnl"].sum()
        delta_per_tr = df["net_pnl"].mean() - bdf["net_pnl"].mean()
        print(f"  {year:<6} {len(df):>6,} "
              f"${bdf['net_pnl'].sum():>+9,.0f} "
              f"${bdf['net_pnl'].mean():>+8.2f} "
              f"${df['net_pnl'].sum():>+9,.0f} "
              f"${df['net_pnl'].mean():>+8.2f} "
              f"${delta:>+8,.0f} ${delta_per_tr:>+7.2f}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
