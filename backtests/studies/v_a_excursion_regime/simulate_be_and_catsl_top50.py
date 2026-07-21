"""Simulate BE-stop + catastrophic SL bracket strategies on top-50%
ML cohort.

Logic per trade:
  - Walk path_checkpoints in elapsed_s order.
  - State machine:
      (a) Not BE-armed: check catastrophic SL first
          - If cur_mae_atr >= cat_sl_atr: exit at -cat_sl_atr (cat SL)
          - Else check if cur_mfe_atr >= BE_arm_atr (0.75 ATR default):
              arm BE
      (b) BE-armed: check BE touch
          - If cur_pnl_atr <= 0: exit at $0 - commission (BE)
          - (Cat SL is no longer active once BE is armed)
  - If no trigger fires by last checkpoint: use existing regime-flip
    exit PnL (net_pnl).

Variants:
  V0: hold to regime flip (baseline)
  V1: BE only @0.75
  V2: BE @0.75 + cat SL 1.0
  V3: BE @0.75 + cat SL 1.5
  V4: BE @0.75 + cat SL 2.0
  V5: cat SL 1.0 only (no BE)
  V6: cat SL 1.5 only (no BE)

PnL assumptions:
  - Cat SL fills at -cat_sl_atr * atr * 20 (no extra slip beyond mark);
    minus 2 * $5 commission.
  - BE fills at fill_price (zero PnL); minus 2 * $5 commission = -$10.
  - Regime-flip fills use existing net_pnl (already commission-adjusted).
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


def simulate_one_variant(top50: pd.DataFrame, pcs: pd.DataFrame,
                            be_arm_atr: float = None,
                            cat_sl_atr: float = None) -> pd.DataFrame:
    """For each trade in top50, simulate the variant and return a DataFrame
    with one row per trade: exit_reason ('cat_sl', 'be', 'regime'), pnl.
    """
    # Index path_checkpoints by trade_fill_ts + direction for fast access
    pcs_by_trade = pcs.groupby(
        ["trade_fill_ts", "trade_direction"], sort=False)

    results = []
    for _, trade in top50.iterrows():
        entry_ts = trade["entry_ts"]
        direction = trade["direction"]
        atr = trade["atr_at_signal"]
        net_pnl_default = trade["net_pnl"]   # regime-flip outcome
        try:
            tr_pcs = pcs_by_trade.get_group((entry_ts, direction)
                                                  ).sort_values("elapsed_s")
        except KeyError:
            results.append({
                "decision_ts": trade["decision_ts"],
                "direction": direction,
                "year": trade["year"],
                "exit_reason": "regime_no_pcs",
                "pnl": net_pnl_default,
            })
            continue

        be_armed = False
        triggered = None
        for _, cp in tr_pcs.iterrows():
            mfe = cp["cur_mfe_atr"]
            mae = cp["cur_mae_atr"]
            pnl_atr = cp["cur_pnl_atr"]
            if not be_armed:
                # Cat SL check first (before BE arms)
                if cat_sl_atr is not None and (
                        mae is not None and not pd.isna(mae)
                        and mae >= cat_sl_atr):
                    # Exit at -cat_sl_atr * atr * 20 - 2 * commission
                    triggered = ("cat_sl",
                                   -cat_sl_atr * atr * NQ_MULT
                                   - 2 * COMMISSION_ONE_WAY)
                    break
                # BE arm check
                if be_arm_atr is not None and (
                        mfe is not None and not pd.isna(mfe)
                        and mfe >= be_arm_atr):
                    be_armed = True
            else:
                # BE armed: check if PnL went to zero or below
                if pnl_atr is not None and not pd.isna(pnl_atr) \
                        and pnl_atr <= 0:
                    triggered = ("be", -2 * COMMISSION_ONE_WAY)
                    break

        if triggered is None:
            results.append({
                "decision_ts": trade["decision_ts"],
                "direction": direction,
                "year": trade["year"],
                "exit_reason": "regime",
                "pnl": net_pnl_default,
            })
        else:
            results.append({
                "decision_ts": trade["decision_ts"],
                "direction": direction,
                "year": trade["year"],
                "exit_reason": triggered[0],
                "pnl": float(triggered[1]),
            })
    return pd.DataFrame(results)


def report_variant(name: str, res: pd.DataFrame, baseline: pd.DataFrame):
    n = len(res)
    total = res["pnl"].sum()
    mean = res["pnl"].mean()
    wr = (res["pnl"] > 0).mean()
    base_t = baseline["pnl"].sum()
    delta = total - base_t
    er = res["exit_reason"].value_counts().to_dict()
    print(f"\n  {name}")
    print(f"    n={n:,}  total=${total:+,.0f}  mean=${mean:+.2f}/tr  "
          f"WR={wr:.1%}  Δ vs baseline=${delta:+,.0f}")
    # Per-year
    print(f"    {'year':>4}  {'n':>5}  {'total':>10}  {'mean':>8}  {'WR':>5}")
    for yr in sorted(res["year"].unique()):
        ysub = res[res["year"] == yr]
        print(f"    {int(yr):>4}  {len(ysub):>5,}  "
              f"${ysub['pnl'].sum():>+8,.0f}  "
              f"${ysub['pnl'].mean():>+6.2f}  "
              f"{(ysub['pnl']>0).mean():>5.1%}")
    # Exit-reason breakdown
    print(f"    Exit reasons:")
    for er_name, count in sorted(er.items(), key=lambda x: -x[1]):
        sub = res[res["exit_reason"] == er_name]
        pct = count / n
        print(f"      {er_name:<15}  n={count:>4}  ({pct:.1%})  "
              f"total=${sub['pnl'].sum():>+8,.0f}  "
              f"mean=${sub['pnl'].mean():>+7.2f}")


def main():
    t0 = time.time()
    print("=" * 78)
    print("BE + CAT-SL SIMULATION — top-50% ML cohort")
    print("=" * 78)

    # Load top-50% cohort and path_checkpoint scores
    top50 = pd.read_parquet(OUT / "ml_n40_top50_mfe_analysis.parquet")
    print(f"\nTop-50% trades: {len(top50):,}")

    # Load path_checkpoints (with-delay) for trade tracking
    print(f"Loading path_checkpoints from with-delay snapshots...")
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

    # Filter to checkpoints for top-50% trades
    top50_keys = top50[["entry_ts", "direction"]].copy()
    top50_keys = top50_keys.rename(columns={
        "entry_ts": "trade_fill_ts", "direction": "trade_direction"})
    pcs_t50 = pcs.merge(
        top50_keys, on=["trade_fill_ts", "trade_direction"], how="inner")
    print(f"  Path_checkpoints for top-50% trades: {len(pcs_t50):,}")

    # Baseline (hold to regime flip)
    baseline = pd.DataFrame({
        "decision_ts": top50["decision_ts"].values,
        "direction": top50["direction"].values,
        "year": top50["year"].values,
        "exit_reason": "regime",
        "pnl": top50["net_pnl"].values,
    })
    print(f"\n  V0 — BASELINE (hold to regime flip)")
    print(f"    n={len(baseline):,}  total=${baseline['pnl'].sum():+,.0f}  "
          f"mean=${baseline['pnl'].mean():+.2f}/tr  "
          f"WR={(baseline['pnl']>0).mean():.1%}")
    print(f"    {'year':>4}  {'n':>5}  {'total':>10}  {'mean':>8}  {'WR':>5}")
    for yr in sorted(baseline["year"].unique()):
        ysub = baseline[baseline["year"] == yr]
        print(f"    {int(yr):>4}  {len(ysub):>5,}  "
              f"${ysub['pnl'].sum():>+8,.0f}  "
              f"${ysub['pnl'].mean():>+6.2f}  "
              f"{(ysub['pnl']>0).mean():>5.1%}")

    print(f"\n{'='*78}")
    print(f"VARIANTS")
    print(f"{'='*78}")

    variants = [
        ("V1 — BE @0.75 only (no cat SL)", 0.75, None),
        ("V2 — BE @0.75 + cat SL 1.0 ATR", 0.75, 1.0),
        ("V3 — BE @0.75 + cat SL 1.5 ATR", 0.75, 1.5),
        ("V4 — BE @0.75 + cat SL 2.0 ATR", 0.75, 2.0),
        ("V5 — cat SL 1.0 ATR only (no BE)", None, 1.0),
        ("V6 — cat SL 1.5 ATR only (no BE)", None, 1.5),
        ("V7 — BE @0.50 + cat SL 1.0 ATR", 0.50, 1.0),
        ("V8 — BE @1.0  + cat SL 1.5 ATR", 1.0, 1.5),
    ]
    summary_rows = []
    for name, be, cat in variants:
        print(f"\n  Simulating: {name}")
        t1 = time.time()
        res = simulate_one_variant(top50, pcs_t50,
                                          be_arm_atr=be, cat_sl_atr=cat)
        elapsed = time.time() - t1
        print(f"    ({elapsed:.1f}s)")
        report_variant(name, res, baseline)
        summary_rows.append({
            "variant": name, "be_arm_atr": be, "cat_sl_atr": cat,
            "n": len(res), "total": res["pnl"].sum(),
            "mean": res["pnl"].mean(),
            "wr": (res["pnl"] > 0).mean(),
            "vs_baseline": res["pnl"].sum() - baseline["pnl"].sum(),
            "y2024_total": res[res["year"]==2024]["pnl"].sum(),
            "y2025_total": res[res["year"]==2025]["pnl"].sum(),
            "y2026_total": res[res["year"]==2026]["pnl"].sum(),
            "n_cat_sl": (res["exit_reason"] == "cat_sl").sum(),
            "n_be": (res["exit_reason"] == "be").sum(),
            "n_regime": (res["exit_reason"] == "regime").sum(),
        })

    # Final summary
    print(f"\n{'='*78}")
    print(f"VARIANT SUMMARY (top-50% ML cohort, all OOS years)")
    print(f"{'='*78}")
    print(f"  {'variant':<40}  {'total':>10}  {'mean':>8}  "
          f"{'Δ_base':>10}  {'2024':>9}  {'2025':>9}  {'2026':>9}")
    print(f"  {'V0 BASELINE (hold to regime flip)':<40}  "
          f"${baseline['pnl'].sum():>+8,.0f}  "
          f"${baseline['pnl'].mean():>+6.2f}  "
          f"{'':>10}  "
          f"${baseline[baseline['year']==2024]['pnl'].sum():>+7,.0f}  "
          f"${baseline[baseline['year']==2025]['pnl'].sum():>+7,.0f}  "
          f"${baseline[baseline['year']==2026]['pnl'].sum():>+7,.0f}")
    for r in summary_rows:
        print(f"  {r['variant']:<40}  "
              f"${r['total']:>+8,.0f}  ${r['mean']:>+6.2f}  "
              f"${r['vs_baseline']:>+8,.0f}  "
              f"${r['y2024_total']:>+7,.0f}  "
              f"${r['y2025_total']:>+7,.0f}  "
              f"${r['y2026_total']:>+7,.0f}")

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(OUT / "be_catsl_simulation_summary.csv", index=False)
    print(f"\nSaved: {OUT / 'be_catsl_simulation_summary.csv'}")
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
