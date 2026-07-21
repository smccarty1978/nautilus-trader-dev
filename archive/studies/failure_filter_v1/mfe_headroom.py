"""MFE headroom analysis on the combo-passed 2026 trades.

For trades that passed: failure filter (excl worst 10%) + winner
top-10% on 2026, look at the max MFE distribution to see if there's
headroom that a wider bracket would capture.

Key questions:
  1. What's the MFE distribution? Do trades reach 1.5 / 2.0 ATR often?
  2. Among PT-1.0 winners, how much further did price go after the
     bracket would have closed?
  3. Among SL losers, did they reach meaningful MFE first (close
     calls) or fail immediately?
  4. What does a 1.5 PT / 1.0 SL bracket race produce on this
     population (using deterministic mfe/mae window data)?
  5. What's the implied per-trade economics under different bracket
     geometries?
"""

from __future__ import annotations
from pathlib import Path
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import pandas as pd

NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0

OUT_DIR = Path("studies/failure_filter_v1/results")


def main():
    failure = pd.read_parquet(
        OUT_DIR / "models_oos_2026/oos_predictions.parquet")
    winner = pd.read_parquet(
        "studies/bracket_entry_v3_fullpop/results/"
        "models_oos_2026/full/oos_predictions.parquet")

    # Add MFE/MAE windows from labels parquet
    labels = pd.read_parquet(
        "studies/1m_regime_collector_v2/results/"
        "v2_outcome_labels_2026.parquet")
    label_cols = ["event_id", "checkpoint_s",
                   "mfe_30s_atr", "mfe_60s_atr", "mfe_120s_atr",
                   "mfe_180s_atr", "mfe_300s_atr", "mfe_600s_atr",
                   "mae_30s_atr", "mae_60s_atr", "mae_120s_atr",
                   "mae_180s_atr", "mae_300s_atr", "mae_600s_atr",
                   "bracket_resolution_time_s_pt100_before_sl100"]
    labels = labels[[c for c in label_cols if c in labels.columns]]

    failure = failure.rename(columns={"score": "failure_score"})
    winner = winner.rename(columns={"score": "winner_score"})
    # Drop mfe_300s_atr from failure preds so it comes from labels
    if "mfe_300s_atr" in failure.columns:
        failure = failure.drop(columns=["mfe_300s_atr"])
    df = failure.merge(
        winner[["event_id", "checkpoint_s", "winner_score"]],
        on=["event_id", "checkpoint_s"], how="inner")
    df = df.merge(labels, on=["event_id", "checkpoint_s"], how="left")

    # Combined filter: excl worst 10% by failure score + top 10% winner
    f_p90 = df["failure_score"].quantile(0.90)
    survivors = df[df["failure_score"] < f_p90]
    w_p90 = survivors["winner_score"].quantile(0.90)
    combo = survivors[survivors["winner_score"] >= w_p90].copy()
    print(f"Combined population: {len(combo):,} trades")
    print(f"PT rate: {(combo['pt100_before_sl100']==1).mean():.4f}")
    print(f"SL rate: {(combo['pt100_before_sl100']==0).mean():.4f}")
    print(f"Unresolved: {combo['pt100_before_sl100'].isna().mean():.4f}")
    print()

    # ----- 1. MFE distribution -----
    print("=" * 70)
    print("MAX MFE DISTRIBUTION (max across 30s/60s/120s/180s/300s/600s windows)")
    print("=" * 70)
    mfe_cols = ["mfe_30s_atr", "mfe_60s_atr", "mfe_120s_atr",
                 "mfe_180s_atr", "mfe_300s_atr", "mfe_600s_atr"]
    mae_cols = ["mae_30s_atr", "mae_60s_atr", "mae_120s_atr",
                 "mae_180s_atr", "mae_300s_atr", "mae_600s_atr"]
    combo["max_mfe"] = combo[mfe_cols].max(axis=1)
    combo["max_mae"] = combo[mae_cols].max(axis=1)

    bins = [(0, 0.5), (0.5, 1.0), (1.0, 1.5),
             (1.5, 2.0), (2.0, 3.0), (3.0, 999)]
    print(f"{'Bin (ATR)':<15} {'n':>6} {'%':>6}")
    for lo, hi in bins:
        n = ((combo["max_mfe"] >= lo) & (combo["max_mfe"] < hi)).sum()
        pct = 100 * n / len(combo)
        label = (f">={lo}" if hi == 999
                  else f"{lo}-{hi}")
        print(f"{label:<15} {n:>6,} {pct:>5.1f}%")
    print()
    print(f"Median max MFE: {combo['max_mfe'].median():.3f}")
    print(f"Mean max MFE:   {combo['max_mfe'].mean():.3f}")
    print(f"P75 max MFE:    {combo['max_mfe'].quantile(0.75):.3f}")
    print(f"P90 max MFE:    {combo['max_mfe'].quantile(0.90):.3f}")

    # ----- 2. MFE distribution by 1.0-bracket exit -----
    print()
    print("=" * 70)
    print("MAX MFE BY 1.0-BRACKET EXIT (where did winners actually peak?)")
    print("=" * 70)
    pt = combo[combo["pt100_before_sl100"] == 1]
    sl = combo[combo["pt100_before_sl100"] == 0]
    unr = combo[combo["pt100_before_sl100"].isna()]
    print(f"{'Subset':<20} {'n':>6} {'med MFE':>10} {'mean MFE':>10} "
           f"{'P75 MFE':>10} {'P90 MFE':>10}")
    for label, sub in [("PT winners", pt), ("SL losers", sl),
                         ("Unresolved", unr)]:
        if len(sub) == 0:
            continue
        m = sub["max_mfe"]
        print(f"{label:<20} {len(sub):>6,} {m.median():>10.3f} "
               f"{m.mean():>10.3f} {m.quantile(0.75):>10.3f} "
               f"{m.quantile(0.90):>10.3f}")
    print()

    # ----- 3. Bracket race for 1.5 PT / 1.0 SL using window data -----
    print("=" * 70)
    print("APPROXIMATE 1.5 PT / 1.0 SL BRACKET RACE (using 300s window peaks)")
    print("=" * 70)
    # Use 300s window — primary horizon for the model
    mfe_300 = combo["mfe_300s_atr"]
    mae_300 = combo["mae_300s_atr"]
    pt_15_no_sl_1 = (mfe_300 >= 1.5) & (mae_300 < 1.0)
    sl_1_no_pt_15 = (mae_300 >= 1.0) & (mfe_300 < 1.5)
    both = (mfe_300 >= 1.5) & (mae_300 >= 1.0)
    neither = (mfe_300 < 1.5) & (mae_300 < 1.0)
    print(f"  PT 1.5 hit & SL 1.0 NOT hit: {pt_15_no_sl_1.sum():,} "
           f"({100*pt_15_no_sl_1.mean():.1f}%) — DEFINITE WIN")
    print(f"  SL 1.0 hit & PT 1.5 NOT hit: {sl_1_no_pt_15.sum():,} "
           f"({100*sl_1_no_pt_15.mean():.1f}%) — DEFINITE LOSS")
    print(f"  BOTH hit (path-order ambiguous): {both.sum():,} "
           f"({100*both.mean():.1f}%)")
    print(f"  NEITHER hit (unresolved at 300s): {neither.sum():,} "
           f"({100*neither.mean():.1f}%)")
    # Conservative split: assume both -> 50/50, neither -> SL-equivalent
    pt_15_optimistic = pt_15_no_sl_1.sum() + 0.5 * both.sum()
    pt_15_conservative = pt_15_no_sl_1.sum()
    pt_15_rate_opt = pt_15_optimistic / len(combo)
    pt_15_rate_cons = pt_15_conservative / len(combo)
    print(f"\n  PT 1.5 win rate (optimistic, both -> 50/50): "
           f"{100*pt_15_rate_opt:.1f}%")
    print(f"  PT 1.5 win rate (conservative, both -> SL): "
           f"{100*pt_15_rate_cons:.1f}%")

    # ----- 4. Same for 2.0 PT / 1.0 SL -----
    print()
    print("=" * 70)
    print("APPROXIMATE 2.0 PT / 1.0 SL BRACKET RACE (using 300s window peaks)")
    print("=" * 70)
    pt_20_no_sl_1 = (mfe_300 >= 2.0) & (mae_300 < 1.0)
    sl_1_no_pt_20 = (mae_300 >= 1.0) & (mfe_300 < 2.0)
    both_2 = (mfe_300 >= 2.0) & (mae_300 >= 1.0)
    print(f"  PT 2.0 hit & SL 1.0 NOT hit: {pt_20_no_sl_1.sum():,} "
           f"({100*pt_20_no_sl_1.mean():.1f}%)")
    print(f"  SL 1.0 hit & PT 2.0 NOT hit: {sl_1_no_pt_20.sum():,} "
           f"({100*sl_1_no_pt_20.mean():.1f}%)")
    print(f"  Both: {both_2.sum():,} "
           f"({100*both_2.mean():.1f}%)")
    pt_20_rate_opt = (pt_20_no_sl_1.sum() + 0.5 * both_2.sum()) / len(combo)
    pt_20_rate_cons = pt_20_no_sl_1.sum() / len(combo)
    print(f"\n  PT 2.0 win rate (optimistic): {100*pt_20_rate_opt:.1f}%")
    print(f"  PT 2.0 win rate (conservative): {100*pt_20_rate_cons:.1f}%")

    # ----- 4b. 1.5/1 race using 600s window (broader horizon) -----
    print()
    print("=" * 70)
    print("APPROXIMATE 1.5 PT / 1.0 SL RACE (using 600s window, broader)")
    print("=" * 70)
    mfe_600 = combo["mfe_600s_atr"]
    mae_600 = combo["mae_600s_atr"]
    pt_15_no_sl_1_600 = (mfe_600 >= 1.5) & (mae_600 < 1.0)
    sl_1_no_pt_15_600 = (mae_600 >= 1.0) & (mfe_600 < 1.5)
    both_600 = (mfe_600 >= 1.5) & (mae_600 >= 1.0)
    neither_600 = (mfe_600 < 1.5) & (mae_600 < 1.0)
    print(f"  PT 1.5 hit & SL 1.0 NOT hit (600s): "
           f"{pt_15_no_sl_1_600.sum():,} "
           f"({100*pt_15_no_sl_1_600.mean():.1f}%) DEFINITE WIN")
    print(f"  SL 1.0 hit & PT 1.5 NOT hit (600s): "
           f"{sl_1_no_pt_15_600.sum():,} "
           f"({100*sl_1_no_pt_15_600.mean():.1f}%) DEFINITE LOSS")
    print(f"  BOTH (600s): {both_600.sum():,} "
           f"({100*both_600.mean():.1f}%)")
    print(f"  NEITHER (600s): {neither_600.sum():,} "
           f"({100*neither_600.mean():.1f}%)")
    pt_15_rate_opt_600 = (pt_15_no_sl_1_600.sum()
        + 0.5 * both_600.sum()) / len(combo)
    pt_15_rate_cons_600 = pt_15_no_sl_1_600.sum() / len(combo)
    print(f"  PT 1.5 rate 600s opt: {100*pt_15_rate_opt_600:.1f}%")
    print(f"  PT 1.5 rate 600s cons: {100*pt_15_rate_cons_600:.1f}%")

    # ----- 5. Implied per-trade economics under each geometry -----
    print()
    print("=" * 70)
    print("IMPLIED PER-TRADE ECONOMICS (combined population, 2026)")
    print("=" * 70)
    avg_atr = combo["atr_at_signal"].mean()
    print(f"Avg atr_at_signal: {avg_atr:.3f} pts")
    print()
    print(f"{'Bracket':<20} {'Win%':>10} {'Avg win $':>12} "
           f"{'Avg loss $':>12} {'Mean $/tr':>12} {'PF':>6}")

    def calc_econ(win_rate, pt_atr_mult, sl_atr_mult):
        avg_win = pt_atr_mult * avg_atr * NQ_MULT - COMMISSION - TICK_COST
        avg_loss = -sl_atr_mult * avg_atr * NQ_MULT - COMMISSION - 2 * TICK_COST
        mean = win_rate * avg_win + (1 - win_rate) * avg_loss
        pf = abs(win_rate * avg_win / ((1 - win_rate) * avg_loss))
        return avg_win, avg_loss, mean, pf

    # 1.0 / 1.0 baseline (actual)
    pt_10_rate = (combo["pt100_before_sl100"] == 1).mean()
    aw, al, m, pf = calc_econ(pt_10_rate, 1.0, 1.0)
    print(f"{'1.0 PT / 1.0 SL':<20} {100*pt_10_rate:>9.1f}% "
           f"{aw:>11.2f} {al:>11.2f} {m:>11.2f} {pf:>6.2f}")

    # 1.5 / 1.0 (approximate from window data)
    aw, al, m, pf = calc_econ(pt_15_rate_opt, 1.5, 1.0)
    print(f"{'1.5 PT / 1.0 SL':<20} {100*pt_15_rate_opt:>9.1f}% "
           f"{aw:>11.2f} {al:>11.2f} {m:>11.2f} {pf:>6.2f}  "
           "(opt)")
    aw, al, m, pf = calc_econ(pt_15_rate_cons, 1.5, 1.0)
    print(f"{'1.5 PT / 1.0 SL':<20} {100*pt_15_rate_cons:>9.1f}% "
           f"{aw:>11.2f} {al:>11.2f} {m:>11.2f} {pf:>6.2f}  "
           "(cons)")

    # 2.0 / 1.0
    aw, al, m, pf = calc_econ(pt_20_rate_opt, 2.0, 1.0)
    print(f"{'2.0 PT / 1.0 SL':<20} {100*pt_20_rate_opt:>9.1f}% "
           f"{aw:>11.2f} {al:>11.2f} {m:>11.2f} {pf:>6.2f}  "
           "(opt)")
    aw, al, m, pf = calc_econ(pt_20_rate_cons, 2.0, 1.0)
    print(f"{'2.0 PT / 1.0 SL':<20} {100*pt_20_rate_cons:>9.1f}% "
           f"{aw:>11.2f} {al:>11.2f} {m:>11.2f} {pf:>6.2f}  "
           "(cons)")

    # ----- 6. Save combo trades for further inspection -----
    keep = ["event_id", "checkpoint_s", "winner_score",
             "failure_score", "pt100_before_sl100",
             "mfe_300s_atr", "mae_300s_atr", "max_mfe",
             "atr_at_signal", "signal_direction"]
    combo[[c for c in keep if c in combo.columns]].to_parquet(
        OUT_DIR / "combo_2026_with_mfe.parquet", index=False)
    print(f"\nSaved: {OUT_DIR / 'combo_2026_with_mfe.parquet'}")


if __name__ == "__main__":
    main()
