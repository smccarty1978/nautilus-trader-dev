"""Diagnostic tables: how do excursion features differ at each
checkpoint by eventual outcome category?

For each checkpoint × outcome category, report median values of:
  - ratio_fast / medium / slow / xfast / xmedium / xslow
  - efficiency_fast / medium / slow / xfast / xmedium / xslow
  - net_move_*
  - current_mfe_atr / current_mae_atr / unrealized_pnl

Goal: identify features that ALREADY look bad at +2/+3/+5 min for trades
that eventually become losers (esp. DOAs and sub-ATR failures).
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

OUT = Path("studies/v_a_excursion_regime/results_v0")

CHECKPOINT_ORDER = ["entry", "+2m", "+3m", "+5m", "+10m", "halfway",
                     "at_exit"]
OUTCOME_ORDER = ["runner", "winner", "loser_giveback", "loser_subatr",
                  "loser_doa"]


def main():
    print("=" * 78)
    print("CHECKPOINT DIAGNOSTICS — feature distributions by outcome × time")
    print("=" * 78)

    parts = []
    for yr in (2024, 2025, 2026):
        p = OUT / f"v_a_v0_{yr}_checkpoints.parquet"
        if p.exists():
            parts.append(pd.read_parquet(p))
    df = pd.concat(parts, ignore_index=True)
    print(f"\nTotal checkpoint rows: {len(df):,} across "
          f"{df['trade_idx'].nunique():,} unique trades")
    print(f"\nOutcome distribution (per trade):")
    per_trade = df.drop_duplicates("trade_idx")
    for cat in OUTCOME_ORDER:
        n = (per_trade["outcome"] == cat).sum()
        if n: print(f"  {cat}: {n:,}")

    # Median tables per (checkpoint, outcome)
    feature_groups = {
        "ratio (coarse)": ["ratio_fast", "ratio_medium", "ratio_slow"],
        "ratio (fine)":   ["ratio_xfast", "ratio_xmedium", "ratio_xslow"],
        "efficiency (coarse)": ["efficiency_fast", "efficiency_medium",
                                  "efficiency_slow"],
        "efficiency (fine)": ["efficiency_xfast", "efficiency_xmedium",
                                "efficiency_xslow"],
        "net_move (coarse)": ["net_move_fast", "net_move_medium",
                                "net_move_slow"],
        "net_move (fine)": ["net_move_xfast", "net_move_xmedium",
                              "net_move_xslow"],
        "trade state": ["current_mfe_atr", "current_mae_atr",
                        "unrealized_pnl"],
    }

    for grp_name, feats in feature_groups.items():
        print(f"\n{'='*78}")
        print(f"MEDIANS BY (checkpoint × outcome) — {grp_name}")
        print(f"{'='*78}")
        for feat in feats:
            if feat not in df.columns:
                continue
            print(f"\n--- {feat} ---")
            print(f"  {'cp':<10} " + "".join(
                f"{c:>13}" for c in OUTCOME_ORDER))
            for cp in CHECKPOINT_ORDER:
                sub = df[df["checkpoint"] == cp]
                if not len(sub): continue
                row = f"  {cp:<10} "
                for cat in OUTCOME_ORDER:
                    g = sub[sub["outcome"] == cat]
                    if len(g):
                        med = g[feat].median()
                        row += f"{med:>+13.2f}"
                    else:
                        row += f"{'-':>13}"
                print(row)

    # Spread analysis: at +5m, how much do losers and runners differ?
    print(f"\n{'='*78}")
    print("KEY SEPARATION SIGNALS at +5m (loser_doa vs runner)")
    print(f"{'='*78}")
    sub = df[df["checkpoint"] == "+5m"].copy()
    runners = sub[sub["outcome"] == "runner"]
    doas = sub[sub["outcome"] == "loser_doa"]
    subatr = sub[sub["outcome"] == "loser_subatr"]

    candidates = []
    for col in df.columns:
        if col in ("year", "trade_idx", "checkpoint", "checkpoint_ts",
                    "entry_ts", "exit_ts", "decision_ts", "direction",
                    "atr_at_signal", "fill_price", "outcome", "net_pnl",
                    "gross_pnl", "hold_s", "final_mfe_atr", "final_mae_atr",
                    "close_now"):
            continue
        if not pd.api.types.is_numeric_dtype(df[col]): continue
        r_med = runners[col].median()
        d_med = doas[col].median()
        s_med = subatr[col].median()
        if pd.isna(r_med) or pd.isna(d_med): continue
        # Separation: runner_median - loser_doa_median
        sep = r_med - d_med
        candidates.append({
            "feature": col,
            "runner_med": r_med,
            "winner_doa_diff": sep,
            "doa_med": d_med,
            "subatr_med": s_med,
        })
    cdf = pd.DataFrame(candidates)
    cdf["abs_sep"] = cdf["winner_doa_diff"].abs()
    cdf = cdf.sort_values("abs_sep", ascending=False).head(15)
    print(f"\n  Top 15 features by |runner − loser_doa| separation at +5m:")
    print(f"  {'feature':<32} {'runner':>10} {'doa':>10} "
          f"{'subatr':>10} {'sep':>10}")
    for _, r in cdf.iterrows():
        print(f"  {r['feature']:<32} {r['runner_med']:>+10.2f} "
              f"{r['doa_med']:>+10.2f} {r['subatr_med']:>+10.2f} "
              f"{r['winner_doa_diff']:>+10.2f}")
    cdf.to_csv(OUT / "checkpoint_separation_5m.csv", index=False)

    # +3m version
    print(f"\n{'='*78}")
    print("KEY SEPARATION at +3m (earlier trigger — less data, more noise)")
    print(f"{'='*78}")
    sub = df[df["checkpoint"] == "+3m"].copy()
    runners = sub[sub["outcome"] == "runner"]
    doas = sub[sub["outcome"] == "loser_doa"]
    subatr = sub[sub["outcome"] == "loser_subatr"]
    cands3 = []
    for col in cdf["feature"]:  # same top-15 features
        if col not in df.columns: continue
        r_med = runners[col].median()
        d_med = doas[col].median()
        s_med = subatr[col].median()
        cands3.append({"feature": col, "runner_med": r_med,
                        "doa_med": d_med, "subatr_med": s_med,
                        "sep": r_med - d_med})
    print(f"  {'feature':<32} {'runner':>10} {'doa':>10} "
          f"{'subatr':>10} {'sep':>10}")
    for r in cands3:
        print(f"  {r['feature']:<32} {r['runner_med']:>+10.2f} "
              f"{r['doa_med']:>+10.2f} {r['subatr_med']:>+10.2f} "
              f"{r['sep']:>+10.2f}")


if __name__ == "__main__":
    main()
