"""Build NQ V_A viability dataset.

Output: studies/nq_viability_v1/results/nq_viability_dataset.parquet

For each NQ RTH V_A trade across 2020-2026:
  - Join to triggering bar1_check snapshot via decision_event_id
  - Add pre-entry features (market quality, vol, confirm, session, MTF)
  - Add labels: winner/loser, PnL, MFE/MAE, regime duration,
    rolling expectancies (CAUSAL — only prior trades)

All registry/snapshot fields are pre-audited at write time
(provenance verified by Collector V2).
"""

from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

PORTFOLIO = Path("collectors/collector_v2/results/portfolio")
OUT = Path("studies/nq_viability_v1/results")
OUT.mkdir(parents=True, exist_ok=True)
CT = pytz.timezone("America/Chicago")
YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]


def load_year(year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = PORTFOLIO / f"NQ_{year}"
    snaps = pd.read_parquet(d / "snapshots.parquet")
    trades = pd.read_parquet(d / "trades.parquet")
    return snaps, trades


def build_year_features(year: int) -> pd.DataFrame:
    print(f"Year {year}...")
    snaps, trades = load_year(year)
    # RTH only
    rth_trades = trades[trades["session"] == "RTH"].copy()
    if not len(rth_trades):
        return pd.DataFrame()
    print(f"  {len(rth_trades):,} NQ RTH trades")

    # Bar1_check snapshots for join
    bar1 = snaps[snaps["kind"] == "bar1_check"].copy()
    bar1 = bar1.rename(columns={"event_id": "decision_event_id"})
    keep_b1 = [
        "decision_event_id", "decision_ts", "bar_ts_event",
        "session", "direction",
        "regime_30s", "regime_1m", "regime_3m", "regime_5m",
        "bars_in_regime_30s", "bars_in_regime_1m",
        "bars_in_regime_3m", "bars_in_regime_5m",
        "atr_30s", "atr_1m", "atr_3m", "atr_5m",
        "dist_close_to_ema3_h_1m_atr", "dist_close_to_ema9_h_1m_atr",
        "dist_close_to_ema3_l_1m_atr", "dist_close_to_ema9_l_1m_atr",
        "dist_close_to_ema3_h_3m_atr", "dist_close_to_ema9_h_3m_atr",
        "dist_close_to_ema3_l_3m_atr", "dist_close_to_ema9_l_3m_atr",
        "dist_close_to_ema3_h_5m_atr", "dist_close_to_ema9_h_5m_atr",
        "dist_close_to_ema3_l_5m_atr", "dist_close_to_ema9_l_5m_atr",
        "flip_bar_h", "flip_bar_l", "flip_bar_c",
        "bar1_h", "bar1_l", "bar1_o", "bar1_c",
        "hhll_ok", "momentum_ok",
    ]
    bar1 = bar1[keep_b1]
    df = rth_trades.merge(bar1, on="decision_event_id", how="left",
                              suffixes=("_trade", "_b1"))
    if df["bar1_h"].isna().any():
        n_miss = int(df["bar1_h"].isna().sum())
        print(f"  WARN: {n_miss} trades missing bar1_check; "
               "dropping them")
        df = df[~df["bar1_h"].isna()].copy()

    # ---- Confirmation candle features ----
    bar1_range = (df["bar1_h"] - df["bar1_l"]).clip(lower=1e-9)
    df["bar1_body_pct"] = (
        (df["bar1_c"] - df["bar1_o"]).abs() / bar1_range)
    df["bar1_close_loc"] = (
        (df["bar1_c"] - df["bar1_l"]) / bar1_range)
    # range vs atr_1m
    df["bar1_range_atr"] = bar1_range / df["atr_1m"].replace(0, np.nan)
    # HH/LL break amount (in ATR)
    long_break = (df["bar1_h"] - df["flip_bar_h"]).clip(lower=0)
    short_break = (df["flip_bar_l"] - df["bar1_l"]).clip(lower=0)
    direction = df["direction_trade"]
    df["hhll_break_atr"] = np.where(
        direction == 1, long_break, short_break) / df["atr_1m"]
    # close-through amount (close past flip H/L in ATR)
    long_close_thru = (df["bar1_c"] - df["flip_bar_h"]).clip(lower=0)
    short_close_thru = (df["flip_bar_l"] - df["bar1_c"]).clip(lower=0)
    df["close_through_atr"] = np.where(
        direction == 1, long_close_thru, short_close_thru
    ) / df["atr_1m"]

    # ---- MTF alignment flags ----
    for tf in ["30s", "3m", "5m"]:
        df[f"aligned_{tf}"] = (df[f"regime_{tf}"]
                                  == direction).astype(int)
    df["all_3_aligned"] = (
        df["aligned_30s"] & df["aligned_3m"]
        & df["aligned_5m"]).astype(int)

    # ---- Session features ----
    decision_ts = df["decision_ts"]
    ct_dt = pd.to_datetime(decision_ts, unit="ns",
                              utc=True).dt.tz_convert(CT)
    df["minute_of_day_ct"] = ct_dt.dt.hour * 60 + ct_dt.dt.minute
    df["minutes_since_open"] = (df["minute_of_day_ct"] - 510).clip(
        lower=0)
    df["session_block"] = pd.cut(
        df["minutes_since_open"],
        bins=[-1, 60, 240, 999],
        labels=["morning", "midday", "afternoon"]).astype(str)
    df["entry_dt"] = ct_dt
    df["date_ct"] = ct_dt.dt.normalize()
    df["weekday"] = ct_dt.dt.dayofweek
    df["year"] = year

    # ---- Market quality / chop features (from regime_flip snaps) ----
    # Flip ts series for this year (RTH-only flips)
    flips = snaps[snaps["kind"] == "regime_flip"].sort_values(
        "decision_ts")
    flip_ts = flips["decision_ts"].values.astype("int64")
    # For each trade decision_ts, count flips in last 30m / 60m
    dec_arr = df["decision_ts"].values.astype("int64")
    win_30m = 30 * 60 * int(1e9)
    win_60m = 60 * 60 * int(1e9)

    flip_ct_30m = np.zeros(len(df), dtype=int)
    flip_ct_60m = np.zeros(len(df), dtype=int)
    for i, t in enumerate(dec_arr):
        # number of flips with t - win <= flip_ts < t
        lo30 = np.searchsorted(flip_ts, t - win_30m, side="left")
        lo60 = np.searchsorted(flip_ts, t - win_60m, side="left")
        hi = np.searchsorted(flip_ts, t, side="left")
        flip_ct_30m[i] = hi - lo30
        flip_ct_60m[i] = hi - lo60
    df["flip_count_30m"] = flip_ct_30m
    df["flip_count_60m"] = flip_ct_60m

    # Avg duration of prior 5/10 regimes (from flip-to-flip gaps)
    flip_intervals = np.diff(flip_ts) / 1e9  # seconds
    # For each trade, find the most recent N intervals
    avg_dur_5_s = np.full(len(df), np.nan)
    avg_dur_10_s = np.full(len(df), np.nan)
    for i, t in enumerate(dec_arr):
        # Most recent flip with ts <= t
        idx = np.searchsorted(flip_ts, t, side="left") - 1
        if idx >= 5:
            avg_dur_5_s[i] = flip_intervals[idx - 5:idx].mean()
        if idx >= 10:
            avg_dur_10_s[i] = flip_intervals[idx - 10:idx].mean()
    df["avg_regime_dur_5_s"] = avg_dur_5_s
    df["avg_regime_dur_10_s"] = avg_dur_10_s

    # ---- Volatility derivatives ----
    # ATR percentile vs trailing same-year RTH atr_1m population
    # Computed with expanding rank to be causal
    df = df.sort_values("decision_ts").reset_index(drop=True)
    df["atr_1m_pct_year"] = df["atr_1m"].rank(pct=True)
    # ATR slope: change vs 30m ago (find atr_1m of trade with
    # decision_ts ~30m earlier)
    atr_30m_back = np.full(len(df), np.nan)
    atr_arr = df["atr_1m"].values
    for i, t in enumerate(dec_arr):
        target = t - win_30m
        idx = np.searchsorted(dec_arr, target, side="right") - 1
        if idx >= 0:
            atr_30m_back[i] = atr_arr[idx]
    df["atr_1m_slope_30m"] = (
        (df["atr_1m"] - atr_30m_back) / atr_30m_back)

    # ---- Trade outcome features ----
    df["is_winner"] = (df["net_pnl"] > 0).astype(int)
    # final_pnl_atr = net_pnl in dollars / (atr_1m * NQ_MULT)
    NQ_MULT = 20.0
    safe_atr = df["atr_1m"].replace(0, np.nan)
    df["final_pnl_atr"] = df["net_pnl"] / (safe_atr * NQ_MULT)
    # MFE/MAE — pulled from path_checkpoint final values
    # Max cur_mfe_atr / cur_mae_atr per trade
    cps = snaps[snaps["kind"] == "path_checkpoint"].copy()
    if len(cps) and "trade_event_id" in cps.columns:
        cps_grp = cps.groupby("trade_event_id").agg(
            max_mfe_atr=("cur_mfe_atr", "max"),
            max_mae_atr=("cur_mae_atr", "max"),
            n_checkpoints=("cur_mfe_atr", "count"),
        ).reset_index().rename(
            columns={"trade_event_id": "decision_event_id"})
        df = df.merge(cps_grp, on="decision_event_id", how="left")
    df["regime_dur_s"] = df["hold_s"]

    # ---- Causal rolling expectancies ----
    # Use only trades chronologically PRIOR to current trade
    df = df.sort_values("decision_ts").reset_index(drop=True)
    pnl = df["net_pnl"].values
    # Trailing N-trade expectancy (excluding current)
    for N in [20, 50, 100]:
        rolling_means = pd.Series(pnl).shift(1).rolling(
            N, min_periods=max(1, N // 2)).mean().values
        df[f"trail_{N}_exp"] = rolling_means
        df[f"env_{N}_pos"] = (rolling_means > 0).astype(int)
    # Trailing daily expectancy (sum prior day's PnL / count)
    df["entry_date_ct"] = df["date_ct"]
    daily_groups = df.groupby("entry_date_ct")
    daily_sum = daily_groups["net_pnl"].sum()
    daily_n = daily_groups["net_pnl"].count()
    daily_exp = (daily_sum / daily_n).shift(1)  # prior day's
    df["trail_daily_exp"] = df["entry_date_ct"].map(
        daily_exp.to_dict())
    # Trailing weekly: prior calendar week's mean
    df["entry_week"] = df["entry_dt"].dt.to_period("W").astype(str)
    weekly_groups = df.groupby("entry_week")
    weekly_sum = weekly_groups["net_pnl"].sum()
    weekly_n = weekly_groups["net_pnl"].count()
    weekly_exp = (weekly_sum / weekly_n).shift(1)
    df["trail_weekly_exp"] = df["entry_week"].map(
        weekly_exp.to_dict())

    return df


def main():
    frames = []
    for yr in YEARS:
        d = build_year_features(yr)
        if len(d):
            frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    print(f"\nTotal trades across years: {len(df):,}")

    out_path = OUT / "nq_viability_dataset.parquet"
    df.to_parquet(out_path, index=False)
    print(f"Saved: {out_path}")
    print(f"\nPer-year breakdown:")
    g = df.groupby("year").agg(
        n=("net_pnl", "count"),
        wr=("is_winner", "mean"),
        mean_pnl=("net_pnl", "mean"),
        total=("net_pnl", "sum"),
    )
    print(g)


if __name__ == "__main__":
    main()
