"""Simulate BE @0.75 on the bottom-50% ML-rejected V_A trades.

Tests whether the ML filter is doing real work, or if BE-on-everything
would have worked just as well. If BE helps bottom-50% as much as
top-50%, the ML is irrelevant.

Compares:
  - Bottom-50% baseline (V_A regime-flip exit on rejected trades)
  - Bottom-50% + BE @0.75 (same simulation as top-50% V1)
  - Lift on bottom vs lift on top
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


OUT = Path("studies/v_a_excursion_regime/results_v0")
NQ_MULT = 20.0
COMMISSION_ONE_WAY = 5.0
BE_ARM_ATR = 0.75
TOP50_THRESHOLD = 0.2821


def simulate_be_only(cohort: pd.DataFrame, pcs: pd.DataFrame) -> pd.DataFrame:
    pcs_by_trade = pcs.groupby(
        ["trade_fill_ts", "trade_direction"], sort=False)
    rows = []
    for _, trade in cohort.iterrows():
        entry_ts = trade["entry_ts"]
        direction = trade["direction"]
        atr = trade["atr_at_signal"]
        net_pnl = trade["net_pnl"]
        try:
            tr_pcs = pcs_by_trade.get_group((entry_ts, direction)
                                                  ).sort_values("elapsed_s")
        except KeyError:
            rows.append({"decision_ts": trade["decision_ts"],
                          "direction": direction,
                          "year": trade["year"],
                          "exit_reason": "regime_no_pcs",
                          "pnl": net_pnl})
            continue
        be_armed = False
        triggered = None
        for _, cp in tr_pcs.iterrows():
            mfe = cp["cur_mfe_atr"]
            pnl_atr = cp["cur_pnl_atr"]
            if not be_armed:
                if mfe is not None and not pd.isna(mfe) and mfe >= BE_ARM_ATR:
                    be_armed = True
            else:
                if pnl_atr is not None and not pd.isna(pnl_atr) \
                        and pnl_atr <= 0:
                    triggered = ("be", -2 * COMMISSION_ONE_WAY)
                    break
        if triggered is None:
            rows.append({"decision_ts": trade["decision_ts"],
                          "direction": direction,
                          "year": trade["year"],
                          "exit_reason": "regime",
                          "pnl": net_pnl})
        else:
            rows.append({"decision_ts": trade["decision_ts"],
                          "direction": direction,
                          "year": trade["year"],
                          "exit_reason": triggered[0],
                          "pnl": float(triggered[1])})
    return pd.DataFrame(rows)


def report(name, res):
    n = len(res)
    total = res["pnl"].sum()
    mean = res["pnl"].mean()
    wr = (res["pnl"] > 0).mean()
    print(f"\n  {name}: n={n:,}  total=${total:+,.0f}  "
          f"mean=${mean:+.2f}/tr  WR={wr:.1%}")
    print(f"    {'year':>4}  {'n':>5}  {'total':>10}  {'mean':>8}  {'WR':>5}")
    for yr in sorted(res["year"].unique()):
        ysub = res[res["year"] == yr]
        print(f"    {int(yr):>4}  {len(ysub):>5,}  "
              f"${ysub['pnl'].sum():>+8,.0f}  "
              f"${ysub['pnl'].mean():>+6.2f}  "
              f"{(ysub['pnl']>0).mean():>5.1%}")
    er = res["exit_reason"].value_counts().to_dict()
    print(f"    Exit reasons: {er}")
    return total


def main():
    t0 = time.time()
    print("=" * 78)
    print("BE @0.75 ON BOTTOM-50% ML-REJECTED V_A TRADES")
    print("=" * 78)

    preds = pd.read_parquet(OUT / "ml_n40_oos_preds_with_trades.parquet")
    print(f"\nTotal OOS predictions: {len(preds):,}")

    top50 = preds[preds["p_unr075"] >= TOP50_THRESHOLD].copy().reset_index(drop=True)
    bot50 = preds[preds["p_unr075"] < TOP50_THRESHOLD].copy().reset_index(drop=True)
    print(f"  Top 50% (p >= {TOP50_THRESHOLD}): {len(top50):,}")
    print(f"  Bottom 50% (p < {TOP50_THRESHOLD}): {len(bot50):,}")

    # Load path_checkpoints for ALL trades
    print(f"\nLoading path_checkpoints...")
    pcs_list = []
    for yr in [2024, 2025, 2026]:
        snap = pd.read_parquet(
            f"collectors/collector_v2/results/v_a_v0_{yr}/snapshots_with_vol_vwap.parquet",
            columns=["kind", "trade_fill_ts", "trade_direction",
                       "elapsed_s", "cur_pnl_atr", "cur_mfe_atr",
                       "cur_mae_atr", "session"])
        pcs = snap[(snap["kind"] == "path_checkpoint")
                    & (snap["session"] == "RTH")].copy()
        pcs_list.append(pcs)
    pcs = pd.concat(pcs_list, ignore_index=True)
    print(f"  Total RTH path_checkpoints: {len(pcs):,}")

    # Filter path_checkpoints per cohort
    top_keys = top50[["entry_ts", "direction"]].rename(columns={
        "entry_ts": "trade_fill_ts", "direction": "trade_direction"})
    bot_keys = bot50[["entry_ts", "direction"]].rename(columns={
        "entry_ts": "trade_fill_ts", "direction": "trade_direction"})
    pcs_top = pcs.merge(top_keys, on=["trade_fill_ts", "trade_direction"],
                          how="inner")
    pcs_bot = pcs.merge(bot_keys, on=["trade_fill_ts", "trade_direction"],
                          how="inner")
    print(f"  PCs for top 50%: {len(pcs_top):,}")
    print(f"  PCs for bot 50%: {len(pcs_bot):,}")

    # Baselines
    print(f"\n{'='*78}")
    print(f"BASELINES (no BE, regime-flip exit)")
    print(f"{'='*78}")
    top_base_total = top50["net_pnl"].sum()
    bot_base_total = bot50["net_pnl"].sum()
    print(f"\n  Top 50% baseline:")
    print(f"    n={len(top50):,}  total=${top_base_total:+,.0f}  "
          f"mean=${top50['net_pnl'].mean():+.2f}/tr  "
          f"WR={(top50['net_pnl']>0).mean():.1%}")
    print(f"    2024 ${top50[top50['year']==2024]['net_pnl'].sum():+,.0f}  "
          f"2025 ${top50[top50['year']==2025]['net_pnl'].sum():+,.0f}  "
          f"2026 ${top50[top50['year']==2026]['net_pnl'].sum():+,.0f}")
    print(f"\n  Bottom 50% baseline:")
    print(f"    n={len(bot50):,}  total=${bot_base_total:+,.0f}  "
          f"mean=${bot50['net_pnl'].mean():+.2f}/tr  "
          f"WR={(bot50['net_pnl']>0).mean():.1%}")
    print(f"    2024 ${bot50[bot50['year']==2024]['net_pnl'].sum():+,.0f}  "
          f"2025 ${bot50[bot50['year']==2025]['net_pnl'].sum():+,.0f}  "
          f"2026 ${bot50[bot50['year']==2026]['net_pnl'].sum():+,.0f}")

    # Add atr_at_signal column for the simulator
    # Need to join with trades.parquet for atr_at_signal — it's in
    # ml_n40_oos_preds_with_trades.parquet already as 'atr_at_signal'.
    if "atr_at_signal" not in top50.columns:
        print("  WARN: atr_at_signal missing")

    # Apply BE @0.75
    print(f"\n{'='*78}")
    print(f"WITH BE @0.75")
    print(f"{'='*78}")
    print(f"\n  Simulating TOP 50% with BE @0.75...")
    top_be = simulate_be_only(top50, pcs_top)
    top_be_total = report("TOP 50% + BE @0.75", top_be)
    top_lift = top_be_total - top_base_total

    print(f"\n  Simulating BOTTOM 50% with BE @0.75...")
    bot_be = simulate_be_only(bot50, pcs_bot)
    bot_be_total = report("BOTTOM 50% + BE @0.75", bot_be)
    bot_lift = bot_be_total - bot_base_total

    # Summary comparison
    print(f"\n{'='*78}")
    print(f"COMPARISON — does ML matter?")
    print(f"{'='*78}")
    print(f"\n  Top 50% baseline:    ${top_base_total:+,.0f}")
    print(f"  Top 50% + BE @0.75:  ${top_be_total:+,.0f}  "
          f"(Δ ${top_lift:+,.0f})")
    print(f"\n  Bottom 50% baseline: ${bot_base_total:+,.0f}")
    print(f"  Bot 50% + BE @0.75:  ${bot_be_total:+,.0f}  "
          f"(Δ ${bot_lift:+,.0f})")
    print(f"\n  Top per-trade lift:    ${top_lift/len(top50):+.2f}/tr")
    print(f"  Bottom per-trade lift: ${bot_lift/len(bot50):+.2f}/tr")
    print(f"\n  Combined ALL V_A baseline:    "
          f"${top_base_total + bot_base_total:+,.0f}")
    print(f"  Combined ALL V_A + BE @0.75:  "
          f"${top_be_total + bot_be_total:+,.0f}")
    print(f"  Combined lift:                "
          f"${top_lift + bot_lift:+,.0f}")

    if abs(top_lift / len(top50)) > 2 * abs(bot_lift / len(bot50)):
        print(f"\n  → ML filter materially improves BE lift "
              f"({top_lift/len(top50):+.2f} vs {bot_lift/len(bot50):+.2f} /tr).")
    elif abs(top_lift / len(top50) - bot_lift / len(bot50)) < 5:
        print(f"\n  → ML filter is essentially irrelevant for BE — "
              f"applies equally to all V_A trades.")
    else:
        print(f"\n  → ML filter provides modest concentration of BE benefit.")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
