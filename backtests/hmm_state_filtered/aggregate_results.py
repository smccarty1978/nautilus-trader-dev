"""Aggregate raw-flip + P4 and P1 NT sweep results per year + pooled OOS."""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
RESULTS = PROJECT_ROOT / "backtests/hmm_state_filtered/results"
NQ_MULT = 20.0
COMM_PER_CTR_RT = 5.0
IS_YEARS = (2020, 2021, 2022)
OOS_YEARS = (2023, 2024, 2025, 2026)
ALL_YEARS = IS_YEARS + OOS_YEARS


def load_trades(prefix: str) -> dict[int, pd.DataFrame]:
    """Load trades.parquet from each year directory matching prefix."""
    out = {}
    for y in ALL_YEARS:
        d = RESULTS / f"{prefix}_{y}"
        p = d / "trades.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        out[y] = df
    return out


def compute_pnl_p4(df: pd.DataFrame, mult=NQ_MULT, comm=COMM_PER_CTR_RT) -> pd.Series:
    """1-ctr trade PnL: (exit-entry)*dir*mult - commission."""
    px_move = (df["exit_px"] - df["entry_px"]) * df["signal_direction"]
    return px_move * mult - comm


def compute_pnl_p1(df: pd.DataFrame, mult=NQ_MULT, comm=COMM_PER_CTR_RT) -> pd.Series:
    """Partial+runner PnL net of commission (per ctr RT)."""
    dir_ = df["signal_direction"]
    partial_pnl = np.where(
        df["partial_filled"].fillna(False),
        (df["partial_px"].fillna(0) - df["entry_px"]) * dir_ * df["partial_qty"].fillna(0) * mult,
        0.0)
    runner_pnl = (df["runner_exit_px"] - df["entry_px"]) * dir_ * df["runner_qty"] * mult
    total_comm = df["entry_qty"] * comm  # each ctr round-trips
    return pd.Series(partial_pnl + runner_pnl - total_comm, index=df.index)


def report_p4(label: str, by_year: dict[int, pd.DataFrame]):
    print(f"\n{'='*78}\n  {label}\n{'='*78}")
    print(f"  {'year':<6}{'n':>6}{'win%':>8}{'$/tr':>10}{'$total':>12}"
          f"{'%PT':>8}{'%regime':>10}{'%maxh':>8}")
    pooled_oos = []
    yp_oos = 0
    for y in ALL_YEARS:
        if y not in by_year:
            continue
        df = by_year[y].copy()
        if len(df) == 0:
            continue
        df["pnl"] = compute_pnl_p4(df)
        wr = (df["pnl"] > 0).mean()
        dpt = df["pnl"].mean()
        tot = df["pnl"].sum()
        reasons = df["exit_reason"].value_counts(normalize=True)
        pct_pt = reasons.get("PT", 0.0)
        pct_regime = reasons.get("regime_flip", 0.0) + reasons.get("regime", 0.0)
        pct_mh = reasons.get("max_hold", 0.0)
        marker = "IS " if y in IS_YEARS else "   "
        print(f"  {y:<6}{len(df):>6}{wr:>7.1%}{dpt:>+10.2f}{tot:>+12.0f}"
              f"{pct_pt:>7.1%}{pct_regime:>9.1%}{pct_mh:>7.1%}  {marker}")
        if y in OOS_YEARS:
            pooled_oos.append(df)
            if dpt > 0:
                yp_oos += 1
    if pooled_oos:
        all_oos = pd.concat(pooled_oos)
        wr = (all_oos["pnl"] > 0).mean()
        dpt = all_oos["pnl"].mean()
        tot = all_oos["pnl"].sum()
        reasons = all_oos["exit_reason"].value_counts(normalize=True)
        pct_pt = reasons.get("PT", 0.0)
        pct_regime = reasons.get("regime_flip", 0.0) + reasons.get("regime", 0.0)
        pct_mh = reasons.get("max_hold", 0.0)
        print(f"  {'OOS':<6}{len(all_oos):>6}{wr:>7.1%}{dpt:>+10.2f}{tot:>+12.0f}"
              f"{pct_pt:>7.1%}{pct_regime:>9.1%}{pct_mh:>7.1%}  {yp_oos}/4 pos")


def report_p1(label: str, by_year: dict[int, pd.DataFrame]):
    print(f"\n{'='*78}\n  {label}\n{'='*78}")
    print(f"  {'year':<6}{'n':>6}{'win%':>8}{'$/tr':>10}{'$/unit':>9}{'$total':>12}"
          f"{'%part':>8}{'%be':>7}{'%reg':>7}")
    pooled_oos = []
    yp_oos = 0
    for y in ALL_YEARS:
        if y not in by_year:
            continue
        df = by_year[y].copy()
        if len(df) == 0:
            continue
        df["pnl"] = compute_pnl_p1(df)
        # per-1-unit equivalent (so it compares directly to offline simulator)
        df["pnl_per_unit"] = df["pnl"] / df["entry_qty"]
        wr = (df["pnl"] > 0).mean()
        dpt = df["pnl"].mean()
        dpu = df["pnl_per_unit"].mean()
        tot = df["pnl"].sum()
        part_rate = df["partial_filled"].mean()
        reasons = df["runner_exit_reason"].value_counts(normalize=True)
        pct_be = reasons.get("be_stop", 0.0)
        pct_reg = reasons.get("regime_flip", 0.0)
        marker = "IS " if y in IS_YEARS else "   "
        print(f"  {y:<6}{len(df):>6}{wr:>7.1%}{dpt:>+10.2f}{dpu:>+9.2f}{tot:>+12.0f}"
              f"{part_rate:>7.1%}{pct_be:>6.1%}{pct_reg:>6.1%}  {marker}")
        if y in OOS_YEARS:
            pooled_oos.append(df)
            if dpt > 0:
                yp_oos += 1
    if pooled_oos:
        all_oos = pd.concat(pooled_oos)
        wr = (all_oos["pnl"] > 0).mean()
        dpt = all_oos["pnl"].mean()
        dpu = all_oos["pnl_per_unit"].mean()
        tot = all_oos["pnl"].sum()
        part_rate = all_oos["partial_filled"].mean()
        reasons = all_oos["runner_exit_reason"].value_counts(normalize=True)
        pct_be = reasons.get("be_stop", 0.0)
        pct_reg = reasons.get("regime_flip", 0.0)
        print(f"  {'OOS':<6}{len(all_oos):>6}{wr:>7.1%}{dpt:>+10.2f}{dpu:>+9.2f}{tot:>+12.0f}"
              f"{part_rate:>7.1%}{pct_be:>6.1%}{pct_reg:>6.1%}  {yp_oos}/4 pos")


def report_side_by_side(label_a, dict_a, label_b, dict_b):
    print(f"\n{'='*92}\n  SIDE-BY-SIDE  {label_a}  vs  {label_b}\n{'='*92}")
    print(f"  {'year':<6}"
          f"{'A_n':>6}{'A_WR':>7}{'A_$/tr':>10}{'A_total':>12}    "
          f"{'B_n':>6}{'B_WR':>7}{'B_$/tr':>10}{'B_total':>12}")
    pool_a, pool_b = [], []
    yp_a, yp_b = 0, 0
    for y in ALL_YEARS:
        sub_a = dict_a.get(y)
        sub_b = dict_b.get(y)
        if sub_a is None and sub_b is None:
            continue
        line = f"  {y:<6}"
        if sub_a is not None and len(sub_a):
            a = sub_a.copy()
            a["pnl"] = compute_pnl_p4(a)
            line += (f"{len(a):>6}{(a['pnl']>0).mean():>6.1%}"
                     f"{a['pnl'].mean():>+10.2f}{a['pnl'].sum():>+12.0f}    ")
            if y in OOS_YEARS:
                pool_a.append(a)
                if a["pnl"].mean() > 0: yp_a += 1
        else:
            line += f"{'-':>6}{'-':>7}{'-':>10}{'-':>12}    "
        if sub_b is not None and len(sub_b):
            b = sub_b.copy()
            b["pnl"] = compute_pnl_p4(b)
            line += (f"{len(b):>6}{(b['pnl']>0).mean():>6.1%}"
                     f"{b['pnl'].mean():>+10.2f}{b['pnl'].sum():>+12.0f}")
            if y in OOS_YEARS:
                pool_b.append(b)
                if b["pnl"].mean() > 0: yp_b += 1
        else:
            line += f"{'-':>6}{'-':>7}{'-':>10}{'-':>12}"
        marker = "  IS" if y in IS_YEARS else ""
        print(line + marker)
    # Pool OOS
    print(f"  {'OOS':<6}", end="")
    if pool_a:
        a = pd.concat(pool_a)
        print(f"{len(a):>6}{(a['pnl']>0).mean():>6.1%}"
              f"{a['pnl'].mean():>+10.2f}{a['pnl'].sum():>+12.0f}    ", end="")
    else:
        print(f"{'-':>6}{'-':>7}{'-':>10}{'-':>12}    ", end="")
    if pool_b:
        b = pd.concat(pool_b)
        print(f"{len(b):>6}{(b['pnl']>0).mean():>6.1%}"
              f"{b['pnl'].mean():>+10.2f}{b['pnl'].sum():>+12.0f}  "
              f"A:{yp_a}/{len(pool_a)}+  B:{yp_b}/{len(pool_b)}+")
    else:
        print(f"{'-':>6}{'-':>7}{'-':>10}{'-':>12}")


def main():
    # Baseline P4 (bar1_confirm)
    base = load_trades("nq_hmm_4_s3_pt2p0")
    if base:
        report_p4("P4 BASELINE  (bar1_confirm + PT 2.0 ATR)", base)

    # Raw-flip + P4
    rawflip = load_trades("nq_hmm_4_s3_pt2p0_ancflip")
    if rawflip:
        report_p4("RAW-FLIP + P4  (entry_anchor=flip + PT 2.0 ATR)", rawflip)

    # P1
    p1 = load_trades("nq_hmm_4_s3_p1_e2p1@1p0_BE")
    if p1:
        report_p1("P1  (bar1_confirm + 2-ctr; 1-partial @+1 ATR; runner BE->regime)", p1)

    # Layered Raw-Flip
    layered = load_trades("nq_hmm_4_s3_ancflip_m5_hmm_3_s2_flip")
    if layered:
        report_p4("LAYERED RAW-FLIP (hmm_4 s3 tactical + hmm_3 s2 macro)", layered)

    # Rolling Quarterly + P4
    rolling_q = load_trades("nq_hmm_4_rolling_s3_pt2p0_rollq")
    if rolling_q:
        report_p4("ROLLING QUARTERLY + P4  (24m train, qtrly refit, sig-ranked target)",
                  rolling_q)
        if base:
            report_side_by_side("STATIC P4", base, "ROLLING QUARTERLY P4", rolling_q)

    # Rolling Weekly + P4 (3-month training, weekly refit)
    rolling_w = load_trades("nq_hmm_4_rolling_s3_pt2p0_rollwk")
    if rolling_w:
        report_p4("ROLLING WEEKLY + P4  (3m train, weekly refit, sig-ranked target)",
                  rolling_w)
        if base:
            report_side_by_side("STATIC P4", base, "ROLLING WEEKLY P4", rolling_w)
        if rolling_q:
            report_side_by_side("ROLLING QTRLY P4", rolling_q, "ROLLING WEEKLY P4", rolling_w)


if __name__ == "__main__":
    main()
