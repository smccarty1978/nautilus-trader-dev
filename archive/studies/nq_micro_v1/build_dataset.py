"""Build NQ V_A 1s microstructure dataset.

For each NQ RTH V_A trade across 2020-2026:
  - Join trades.parquet to micro_pre.parquet via decision_event_id
  - Join to micro_post.parquet via decision_event_id (conf-to-fill window)
  - Join to bar1_check snapshot for legacy registry context features
  - Compute trade outcome labels and label flags

Output:
  studies/nq_micro_v1/results/nq_micro_dataset.parquet
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
OUT = Path("studies/nq_micro_v1/results")
OUT.mkdir(parents=True, exist_ok=True)
CT = pytz.timezone("America/Chicago")
YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
NQ_MULT = 20.0


def build_year(year: int) -> pd.DataFrame:
    print(f"Year {year}...")
    d = PORTFOLIO / f"NQ_{year}"
    trades = pd.read_parquet(d / "trades.parquet")
    snaps = pd.read_parquet(d / "snapshots.parquet")
    micro_pre = pd.read_parquet(d / "micro_pre.parquet")
    micro_post = pd.read_parquet(d / "micro_post.parquet")
    print(f"  trades={len(trades):,}  micro_pre={len(micro_pre):,}  "
          f"micro_post={len(micro_post):,}")

    # RTH only
    rth = trades[trades["session"] == "RTH"].copy()
    if not len(rth):
        return pd.DataFrame()

    # Bar1_check snapshot for context registry features
    bar1 = snaps[snaps["kind"] == "bar1_check"].copy()
    bar1 = bar1.rename(columns={"event_id": "decision_event_id"})
    keep_b1 = [
        "decision_event_id",
        "regime_30s", "regime_1m", "regime_3m", "regime_5m",
        "bars_in_regime_30s", "bars_in_regime_1m",
        "bars_in_regime_3m", "bars_in_regime_5m",
        "atr_30s", "atr_1m", "atr_3m", "atr_5m",
        "dist_close_to_ema3_h_1m_atr",
        "dist_close_to_ema9_h_1m_atr",
        "dist_close_to_ema3_l_1m_atr",
        "dist_close_to_ema9_l_1m_atr",
        "dist_close_to_ema3_h_5m_atr",
        "dist_close_to_ema9_h_5m_atr",
        "dist_close_to_ema3_l_5m_atr",
        "dist_close_to_ema9_l_5m_atr",
        "flip_bar_h", "flip_bar_l", "flip_bar_c",
        "bar1_h", "bar1_l", "bar1_o", "bar1_c",
    ]
    bar1 = bar1[[c for c in keep_b1 if c in bar1.columns]]

    # micro_pre — keep all 169 cols, drop columns that conflict
    drop_pre = ["decision_ts", "bar_ts_event", "direction",
                "session", "confirmed"]
    mp = micro_pre.drop(
        columns=[c for c in drop_pre if c in micro_pre.columns])

    # micro_post — keep conf2fill_* + atr_at_signal
    drop_post = ["fill_ts", "fill_price", "direction"]
    mpost = micro_post.drop(
        columns=[c for c in drop_post if c in micro_post.columns])
    mpost = mpost.rename(
        columns={"atr_at_signal": "atr_at_signal_post"})

    # Merge
    df = rth.merge(bar1, on="decision_event_id", how="left")
    df = df.merge(mp, on="decision_event_id", how="left")
    df = df.merge(mpost, on="decision_event_id", how="left")
    if df["w60s_efficiency"].isna().any():
        n_miss = int(df["w60s_efficiency"].isna().sum())
        print(f"  WARN: {n_miss} trades missing micro_pre features; "
              "dropping")
        df = df[df["w60s_efficiency"].notna()].copy()

    # ---- Session/time features (decision_ts → CT) ----
    ct_dt = pd.to_datetime(
        df["decision_ts"], unit="ns",
        utc=True).dt.tz_convert(CT)
    df["minute_of_day_ct"] = ct_dt.dt.hour * 60 + ct_dt.dt.minute
    df["minutes_since_open"] = (df["minute_of_day_ct"] - 510).clip(
        lower=0)
    df["weekday"] = ct_dt.dt.dayofweek
    df["year"] = year

    # ---- Confirmation features (from bar1 fields) ----
    bar1_range = (df["bar1_h"] - df["bar1_l"]).clip(lower=1e-9)
    df["bar1_body_pct"] = (
        (df["bar1_c"] - df["bar1_o"]).abs() / bar1_range)
    df["bar1_close_loc"] = (
        (df["bar1_c"] - df["bar1_l"]) / bar1_range)
    df["bar1_range_atr"] = bar1_range / df["atr_1m"].replace(0, np.nan)
    long_break = (df["bar1_h"] - df["flip_bar_h"]).clip(lower=0)
    short_break = (df["flip_bar_l"] - df["bar1_l"]).clip(lower=0)
    direction = df["direction"]
    df["hhll_break_atr"] = np.where(
        direction == 1, long_break, short_break) / df["atr_1m"]
    long_close_thru = (df["bar1_c"] - df["flip_bar_h"]).clip(lower=0)
    short_close_thru = (df["flip_bar_l"] - df["bar1_c"]).clip(lower=0)
    df["close_through_atr"] = np.where(
        direction == 1, long_close_thru, short_close_thru
    ) / df["atr_1m"]
    df["aligned_5m"] = (df["regime_5m"] == direction).astype(int)
    df["aligned_3m"] = (df["regime_3m"] == direction).astype(int)
    df["aligned_30s"] = (df["regime_30s"] == direction).astype(int)
    df["all_3_aligned"] = (df["aligned_30s"] & df["aligned_3m"]
                              & df["aligned_5m"]).astype(int)

    # ---- Trade outcome labels ----
    df["is_winner"] = (df["net_pnl"] > 0).astype(int)
    safe_atr = df["atr_at_signal"].replace(0, np.nan)
    df["final_pnl_atr"] = df["net_pnl"] / (safe_atr * NQ_MULT)
    df["regime_dur_s"] = df["hold_s"]
    # MFE/MAE from path_checkpoint snapshots (max during trade)
    cps = snaps[snaps["kind"] == "path_checkpoint"].copy()
    if len(cps) and "trade_event_id" in cps.columns:
        cps_grp = cps.groupby("trade_event_id").agg(
            max_mfe_atr=("cur_mfe_atr", "max"),
            max_mae_atr=("cur_mae_atr", "max"),
            n_checkpoints=("cur_mfe_atr", "count"),
        ).reset_index().rename(
            columns={"trade_event_id": "decision_event_id"})
        df = df.merge(cps_grp, on="decision_event_id", how="left")
    else:
        df["max_mfe_atr"] = np.nan
        df["max_mae_atr"] = np.nan
        df["n_checkpoints"] = 0

    # Binary label flags
    df["final_pnl_positive"] = (df["net_pnl"] > 0).astype(int)
    df["mfe_ge_1_atr"] = (df["max_mfe_atr"] >= 1.0).astype(int)
    df["mfe_ge_2_atr"] = (df["max_mfe_atr"] >= 2.0).astype(int)
    df["mae_ge_1_atr"] = (df["max_mae_atr"] >= 1.0).astype(int)

    # Quartile flags within year
    pnl_q1 = df["net_pnl"].quantile(0.25)
    pnl_q3 = df["net_pnl"].quantile(0.75)
    df["top_quartile_winner"] = (df["net_pnl"] >= pnl_q3).astype(int)
    df["bottom_quartile_loser"] = (df["net_pnl"] <= pnl_q1).astype(int)

    # Clean winner / bad loser composite labels
    df["clean_winner"] = (
        (df["net_pnl"] > 0)
        & (df["max_mfe_atr"] >= 1.0)
        & (df["max_mae_atr"] < 0.7)).astype(int)
    df["bad_loser"] = (
        (df["net_pnl"] < 0)
        & (df["max_mae_atr"] >= 1.0)).astype(int)

    return df


def main():
    frames = []
    for yr in YEARS:
        d = build_year(yr)
        if len(d):
            frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    print(f"\nTotal RTH trades: {len(df):,}")

    out_path = OUT / "nq_micro_dataset.parquet"
    df.to_parquet(out_path, index=False)
    print(f"Saved: {out_path}")
    print(f"\nPer-year breakdown:")
    g = df.groupby("year").agg(
        n=("net_pnl", "count"),
        wr=("is_winner", "mean"),
        mean_pnl=("net_pnl", "mean"),
        total=("net_pnl", "sum"),
        clean_winner_pct=("clean_winner", "mean"),
        bad_loser_pct=("bad_loser", "mean"),
    )
    print(g)


if __name__ == "__main__":
    main()
