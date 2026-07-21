"""Runner preservation, two methodologies (both retained per Phase 1 item 5):
1. retrospective OOS: top 10/5/1% tiers computed WITHIN Jun-Dec 2025 itself
   -- this is the metric used for the primary 95% runner-retention rule.
2. validation-frozen dollar thresholds: top 10/5/1% DOLLAR cutoffs computed
   on the validation period (Jan-Feb 2025) R0 baseline PnL distribution,
   frozen, applied unchanged to Jun-Dec 2025 -- reported as a separate
   robustness diagnostic only, not the primary pass/fail gate.

Runner tiers and 'skipped'/'retained' accounting are computed over FILLED R0
trades only (a canceled or filter-skipped episode cannot be a 'runner' --
there is no realized PnL to rank).
"""
import numpy as np
import pandas as pd
from common import OUT, load_atlas, repair_f2_window, VAL_START, VAL_END
from build_episodes import build

POLICIES = ["r1", "r2", "r4"]
TIERS = [("top10", 0.90), ("top5", 0.95), ("top1", 0.99)]


def assign_tiers_by_thresholds(pnl: pd.Series, thresholds: dict) -> pd.Series:
    tier = pd.Series("other", index=pnl.index)
    tier[pnl >= thresholds["top10"]] = "top10"
    tier[pnl >= thresholds["top5"]] = "top5"
    tier[pnl >= thresholds["top1"]] = "top1"
    return tier


def runner_rows_for_tiers(ep_filled_r0: pd.DataFrame, tier_col: str, methodology: str) -> list[dict]:
    rows = []
    for tier_name, _ in TIERS:
        t = ep_filled_r0[ep_filled_r0[tier_col] == tier_name]
        baseline_pnl = float(t["baseline_pnl"].sum())
        for p in POLICIES:
            # a runner is "retained" only if the policy kept it AND it still filled
            retained_mask = (t[f"{p}_status"] == "filled")
            retained_pnl = float(t.loc[retained_mask, "baseline_pnl"].sum())
            not_retained = t.loc[~retained_mask, "baseline_pnl"]
            rows.append({
                "methodology": methodology,
                "tier": tier_name,
                "policy": p.upper(),
                "episode_count": len(t),
                "baseline_pnl": baseline_pnl,
                "retained_pnl": retained_pnl,
                "runner_pnl_retention": (retained_pnl / baseline_pnl) if baseline_pnl != 0 else 1.0,
                "runner_count_retained": int(retained_mask.sum()),
                "runner_count_skipped": int((~retained_mask).sum()),
                "largest_skipped_runner": float(not_retained.max()) if len(not_retained) else 0.0,
            })
    return rows


def run():
    ep = build()
    ep_r0_filled = ep[ep["trade_status"] == "filled"].copy()  # R0's own realized outcomes define runner tiers

    p90 = ep_r0_filled["baseline_pnl"].quantile(0.90)
    p95 = ep_r0_filled["baseline_pnl"].quantile(0.95)
    p99 = ep_r0_filled["baseline_pnl"].quantile(0.99)
    ep_r0_filled["tier_retrospective"] = assign_tiers_by_thresholds(ep_r0_filled["baseline_pnl"], {"top10": p90, "top5": p95, "top1": p99})
    rows = runner_rows_for_tiers(ep_r0_filled, "tier_retrospective", "retrospective_OOS_within_primary_window")

    df_atlas = load_atlas()
    val, _ = repair_f2_window(df_atlas, VAL_START, VAL_END)
    val_filled = val[val["trade_status"] == "filled"]
    val_p90 = val_filled["baseline_pnl"].quantile(0.90)
    val_p95 = val_filled["baseline_pnl"].quantile(0.95)
    val_p99 = val_filled["baseline_pnl"].quantile(0.99)
    frozen_thresholds = {"top10": float(val_p90), "top5": float(val_p95), "top1": float(val_p99)}
    ep_r0_filled["tier_frozen"] = assign_tiers_by_thresholds(ep_r0_filled["baseline_pnl"], frozen_thresholds)
    rows += runner_rows_for_tiers(ep_r0_filled, "tier_frozen", "validation_frozen_dollar_threshold_robustness_diagnostic")

    df = pd.DataFrame(rows)
    assert df.isna().sum().sum() == 0, "NaN found in corrected_runner_retention"
    df.to_parquet(OUT / "corrected_runner_retention.parquet", index=False)

    print(f"PRIMARY RULE (retrospective OOS) top10 thresholds >=${p90:.2f}")
    print(f"Robustness-diagnostic (validation-frozen) top10 threshold >=${frozen_thresholds['top10']:.2f}")
    print()
    print(df[df["tier"] == "top10"].to_string(index=False))
    return df, frozen_thresholds


if __name__ == "__main__":
    import os
    from common import PROJECT_ROOT
    os.chdir(PROJECT_ROOT)
    run()
