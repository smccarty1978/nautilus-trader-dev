"""Apply Target 2 model to V_A confirmed trades.

Question: among V_A trades (regime_flip + bar1 confirm), does the
Target 2 ML score (predicted 1-ATR-MFE-within-6-bars probability,
scored at flip time before confirmation) discriminate which V_A trades
make money?

Population: V_A confirmed trades on 2026 OOS RTH.
Score:      p_mfe1atr_oos from `ml_flip_rth_predictions.parquet`,
            evaluated at the regime_flip's decision_ts.
Outcome:    real V_A trade net_pnl (entry ~60s after flip, exit on
            regime flip), gross_pnl, MFE/MAE, hold time, exit reason.

The join key is `regime_flip.decision_ts + 60s == trade.decision_ts`
because V_A trade's decision_ts is the bar1_check timestamp (60s after
the flip's decision_ts).

Decile binning is done within the V_A-confirmed subpopulation to ask:
"if you're V_A-confirmed, does the ML score still discriminate?"

Also reports the intersection view: of the 240 top-decile flips
from the all-flips ML run, how many were V_A-confirmed and what was
their total/mean PnL?
"""
from __future__ import annotations
import os, sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd


OUT = Path("studies/v_a_excursion_regime/results_v0")
TRADES_2026 = "collectors/collector_v2/results/v_a_v0_2026/trades.parquet"
SEED = 42
N_BOOT = 2000


def bootstrap_mean_pnl(values: np.ndarray, n_boot=N_BOOT, seed=SEED):
    rng = np.random.default_rng(seed)
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": np.nan, "p05": np.nan,
                "p95": np.nan, "total": 0.0}
    boot = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        boot[b] = values[idx].mean()
    return {
        "n": n,
        "mean": float(values.mean()),
        "total": float(values.sum()),
        "p05": float(np.percentile(boot, 5)),
        "p95": float(np.percentile(boot, 95)),
    }


def main():
    print("=" * 78)
    print("APPLY TARGET 2 MODEL TO V_A CONFIRMED TRADES — 2026 OOS")
    print("=" * 78)

    # Load OOS predictions
    preds = pd.read_parquet(OUT / "ml_flip_rth_predictions.parquet")
    oos = preds[preds["year"] == 2026].copy().reset_index(drop=True)
    print(f"\n2026 OOS flip predictions: {len(oos):,}")
    print(f"  p_mfe1atr_oos non-null: {oos['p_mfe1atr_oos'].notna().sum():,}")
    print(f"  p_confirm_oos non-null: {oos['p_confirm_oos'].notna().sum():,}")

    # Load 2026 V_A trades
    trades = pd.read_parquet(TRADES_2026)
    print(f"\n2026 V_A trades total: {len(trades):,}")
    trades_rth = trades[trades["session"] == "RTH"].copy()
    print(f"  RTH only: {len(trades_rth):,}")
    print(f"  net_pnl RTH: mean=${trades_rth['net_pnl'].mean():+.2f}  "
          f"total=${trades_rth['net_pnl'].sum():+,.0f}  "
          f"WR={(trades_rth['net_pnl']>0).mean():.1%}")

    # Join: flip.decision_ts + 60s == trade.decision_ts
    oos = oos.rename(columns={"decision_ts": "flip_decision_ts"})
    oos["match_ts"] = oos["flip_decision_ts"] + 60_000_000_000
    trades_sub = trades_rth[[
        "decision_ts", "direction", "net_pnl", "gross_pnl", "hold_s",
        "exit_reason", "running_mfe", "running_mae", "atr_at_signal",
    ]].rename(columns={"decision_ts": "trade_decision_ts"})

    merged = oos.merge(
        trades_sub,
        left_on=["match_ts", "direction"],
        right_on=["trade_decision_ts", "direction"],
        how="inner",
    )
    print(f"\nV_A confirmed RTH trades on 2026 OOS (with ML score): "
          f"{len(merged):,}")

    # Sanity checks
    assert merged["p_mfe1atr_oos"].notna().all(), \
        "joined rows missing target2 score"
    n_target_confirmed = (merged["target_confirmed"] == 1).sum()
    print(f"  target_confirmed==1 (should match V_A confirm definition): "
          f"{n_target_confirmed:,} / {len(merged):,}")

    overall_total = merged["net_pnl"].sum()
    overall_mean = merged["net_pnl"].mean()
    overall_wr = (merged["net_pnl"] > 0).mean()
    print(f"\nMerged sample: {len(merged):,} trades, "
          f"mean ${overall_mean:+.2f}, total ${overall_total:+,.0f}, "
          f"WR {overall_wr:.1%}")

    # ===== Decile binning (within V_A confirmed) =====
    merged = merged.sort_values("p_mfe1atr_oos").reset_index(drop=True)
    merged["decile"] = pd.qcut(
        merged["p_mfe1atr_oos"].rank(method="first"),
        10, labels=False, duplicates="drop",
    )

    print(f"\n{'='*78}")
    print("DECILE LIFT — V_A trade PnL binned by Target 2 ML score")
    print(f"{'='*78}")
    print(f"  {'dec':>4}  {'n':>5}  {'p_mean':>8}  {'mean_$':>9}  "
          f"{'p05':>9}  {'p95':>9}  {'total_$':>11}  {'WR':>5}  "
          f"{'mean_MFE':>8}  {'mean_MAE':>8}")
    summary_rows = []
    for dec, grp in merged.groupby("decile"):
        bs = bootstrap_mean_pnl(grp["net_pnl"].to_numpy())
        wr = (grp["net_pnl"] > 0).mean()
        mfe = grp["running_mfe"].mean()
        mae = grp["running_mae"].mean()
        p_mean = grp["p_mfe1atr_oos"].mean()
        print(f"  d{int(dec)+1:>2}    {bs['n']:>5,}  {p_mean:>8.4f}  "
              f"${bs['mean']:>+7.2f}  ${bs['p05']:>+7.2f}  "
              f"${bs['p95']:>+7.2f}  ${bs['total']:>+9,.0f}  "
              f"{wr:>4.1%}  {mfe:>8.2f}  {mae:>8.2f}")
        summary_rows.append({
            "decile": int(dec) + 1, "n": bs["n"],
            "p_mean": p_mean, "mean_pnl": bs["mean"],
            "p05_pnl": bs["p05"], "p95_pnl": bs["p95"],
            "total_pnl": bs["total"], "wr": wr,
            "mean_mfe": mfe, "mean_mae": mae,
        })

    # ===== Top-half vs bottom-half (more robust given sample) =====
    print(f"\n{'='*78}")
    print("HALF-SPLIT (more stable than deciles at this sample size)")
    print(f"{'='*78}")
    n = len(merged)
    half = n // 2
    bot = merged.iloc[:half]
    top = merged.iloc[half:]
    for name, grp in [("BOTTOM 50% (low p_mfe1atr)", bot),
                       ("TOP 50% (high p_mfe1atr)", top)]:
        bs = bootstrap_mean_pnl(grp["net_pnl"].to_numpy())
        wr = (grp["net_pnl"] > 0).mean()
        print(f"  {name:<32}  n={bs['n']:>5,}  "
              f"mean=${bs['mean']:+8.2f}  CI95=[${bs['p05']:+7.2f}, "
              f"${bs['p95']:+7.2f}]  total=${bs['total']:+9,.0f}  "
              f"WR={wr:.1%}")

    # ===== Top decile / quintile detail =====
    print(f"\n{'='*78}")
    print("FILTER VARIANTS — apply ML score threshold as a deployment gate")
    print(f"{'='*78}")
    print(f"  {'gate':<24}  {'kept_n':>6}  {'kept%':>6}  "
          f"{'mean_$':>9}  {'p05_$':>9}  {'p95_$':>9}  "
          f"{'total_$':>11}  {'WR':>5}")
    for q_keep in [0.50, 0.30, 0.20, 0.10, 0.05]:
        thresh = merged["p_mfe1atr_oos"].quantile(1 - q_keep)
        kept = merged[merged["p_mfe1atr_oos"] >= thresh]
        bs = bootstrap_mean_pnl(kept["net_pnl"].to_numpy())
        wr = (kept["net_pnl"] > 0).mean()
        print(f"  top {q_keep*100:>3.0f}% (p>={thresh:.4f})  "
              f"{len(kept):>6,}  {len(kept)/len(merged):>5.1%}  "
              f"${bs['mean']:>+7.2f}  ${bs['p05']:>+7.2f}  "
              f"${bs['p95']:>+7.2f}  ${bs['total']:>+9,.0f}  "
              f"{wr:>4.1%}")

    # ===== Intersection with Target 1 (confirm) decile =====
    print(f"\n{'='*78}")
    print("CONJUNCTION — top p_mfe1atr AND top p_confirm")
    print(f"{'='*78}")
    if merged["p_confirm_oos"].notna().any():
        for q in [0.30, 0.20, 0.10]:
            t_mfe = merged["p_mfe1atr_oos"].quantile(1 - q)
            t_conf = merged["p_confirm_oos"].quantile(1 - q)
            kept = merged[(merged["p_mfe1atr_oos"] >= t_mfe)
                            & (merged["p_confirm_oos"] >= t_conf)]
            if len(kept) == 0:
                continue
            bs = bootstrap_mean_pnl(kept["net_pnl"].to_numpy())
            wr = (kept["net_pnl"] > 0).mean()
            print(f"  both top {q*100:>3.0f}%   n={len(kept):>4}  "
                  f"mean=${bs['mean']:+8.2f}  CI95=[${bs['p05']:+7.2f}, "
                  f"${bs['p95']:+7.2f}]  total=${bs['total']:+9,.0f}  "
                  f"WR={wr:.1%}")

    # ===== Save =====
    pd.DataFrame(summary_rows).to_csv(
        OUT / "target2_on_va_trades_deciles.csv", index=False)
    merged.to_parquet(
        OUT / "target2_on_va_trades_merged.parquet", index=False)
    print(f"\nWrote:")
    print(f"  {OUT/'target2_on_va_trades_deciles.csv'}")
    print(f"  {OUT/'target2_on_va_trades_merged.parquet'}")


if __name__ == "__main__":
    main()
