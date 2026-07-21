"""Branch A — Atlas Diagnostics. Understand WHAT the KNN scorer sees (not whether
it is profitable). Opens the black box: per-bar score vs predicted vs actual.

Central question the audit raised: KNN recognizes regime *state* but not *payoff*.
This script tests it directly — does the score track actual forward MFE (the
opportunity) even though it fails on net PnL? And it explains the Decile-9-positive
/ Decile-10-negative rollover via bar-index / regime maturity.

    python studies/regime_state_transition_atlas/atlas_diagnostics.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_state_transition_atlas/results")
COST_ATR = None  # cost expressed per-trade in $; MFE/MAE are ATR so we keep ATR-space


def load():
    sc = pd.read_parquet(OUT / "scored_state_rows.parquet")
    fl = pd.read_parquet(OUT / "forward_labels.parquet",
                         columns=["regime_id", "bar_ts", "future_mfe_from_here_atr",
                                  "future_mae_from_here_atr", "remaining_regime_bars",
                                  "next_bar_makes_continuation"])
    df = pd.merge(sc, fl, on=["regime_id", "bar_ts"], suffixes=("", "_fl"))
    return df


def decile_table(df, score_col, L, title):
    d = df.copy()
    d["dec"] = pd.qcut(d[score_col], 10, labels=False, duplicates="drop") + 1
    g = d.groupby("dec")
    L.append(f"### {title}")
    L.append("| Decile | n | Mean score | Actual fwd MFE (ATR) | Actual fwd MAE (ATR) | "
             "Actual MFE−MAE | Actual fwd PnL ($) | Cont. rate | Mean bar idx | Mean rem. bars |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for dec, s in g:
        opp = s["future_mfe_from_here_atr"].mean() - s["future_mae_from_here_atr"].mean()
        L.append(f"| {int(dec)} | {len(s):,} | {s[score_col].mean():.3f} | "
                 f"{s['future_mfe_from_here_atr'].mean():.2f} | {s['future_mae_from_here_atr'].mean():.2f} | "
                 f"{opp:+.2f} | ${s['actual_forward_pnl'].mean():+.2f} | "
                 f"{s['actual_next_continuation'].mean()*100:.0f}% | "
                 f"{s['bar_index_in_regime'].mean():.1f} | {s['remaining_regime_bars'].mean():.1f} |")
    L.append("")


def corr_block(df, L):
    L.append("## 1. Does the score SEE opportunity (forward MFE) even if not payoff?")
    L.append("Spearman rank correlation of each prediction with the actual outcome (OOS).")
    L.append("")
    L.append("| Prediction | vs Actual fwd MFE | vs Actual fwd MAE | vs Actual MFE−MAE | vs Actual fwd PnL$ |")
    L.append("| --- | --- | --- | --- | --- |")
    act_opp = df["future_mfe_from_here_atr"] - df["future_mae_from_here_atr"]
    for pred, lab in [("pred_rem_mfe", "pred_rem_mfe"), ("pred_rem_mae", "pred_rem_mae"),
                      ("score_opportunity", "score_opportunity"), ("pred_c1", "pred_continuation")]:
        r_mfe = df[pred].corr(df["future_mfe_from_here_atr"], method="spearman")
        r_mae = df[pred].corr(df["future_mae_from_here_atr"], method="spearman")
        r_opp = df[pred].corr(act_opp, method="spearman")
        r_pnl = df[pred].corr(df["actual_forward_pnl"], method="spearman")
        L.append(f"| {lab} | {r_mfe:+.3f} | {r_mae:+.3f} | {r_opp:+.3f} | {r_pnl:+.3f} |")
    L.append("")


def fp_fn(df, L):
    """High score / low actual opportunity = false positive, and vice versa."""
    d = df.copy()
    d["dec"] = pd.qcut(d["score_opportunity"], 10, labels=False, duplicates="drop") + 1
    act_opp = d["future_mfe_from_here_atr"] - d["future_mae_from_here_atr"]
    d["act_opp"] = act_opp
    hi = d["dec"] >= 9          # top 20% score
    lo = d["dec"] <= 2          # bottom 20% score
    opp_hi = d["act_opp"] >= d["act_opp"].quantile(0.80)
    opp_lo = d["act_opp"] <= d["act_opp"].quantile(0.20)
    fp = d[hi & opp_lo]        # scored high, bad outcome
    tp = d[hi & opp_hi]
    fn = d[lo & opp_hi]        # scored low, great outcome
    L.append("## 3. False positives / negatives (score deciles 9–10 vs actual opportunity)")
    L.append(f"- **True positives** (top score & top-quintile actual opp): {len(tp):,} | "
             f"mean bar idx {tp['bar_index_in_regime'].mean():.1f} | mean fwd PnL ${tp['actual_forward_pnl'].mean():+.2f}")
    L.append(f"- **False positives** (top score, bottom-quintile actual opp): {len(fp):,} | "
             f"mean bar idx {fp['bar_index_in_regime'].mean():.1f} | mean fwd PnL ${fp['actual_forward_pnl'].mean():+.2f}")
    L.append(f"- **False negatives** (bottom score, top-quintile actual opp): {len(fn):,} | "
             f"mean bar idx {fn['bar_index_in_regime'].mean():.1f} | mean fwd PnL ${fn['actual_forward_pnl'].mean():+.2f}")
    base = (hi).sum()
    L.append(f"- Of top-score states, **{len(fp)/max(base,1)*100:.0f}%** are false positives "
             f"(scored high, landed in the worst actual-opportunity quintile).")
    L.append("")


def example_regimes(df, L):
    """Show bar-by-bar trajectories for a few high- and low-MFE OOS regimes."""
    bar1 = df[df.bar_index_in_regime == 1].copy()
    bar1 = bar1[bar1["remaining_regime_bars"] >= 6]
    top = bar1.nlargest(3, "future_mfe_from_here_atr")["regime_id"].tolist()
    bot = bar1.nsmallest(3, "future_mfe_from_here_atr")["regime_id"].tolist()
    L.append("## 4. Example regime trajectories (OOS)")
    for tag, rids in [("Highest-MFE regimes", top), ("Lowest-MFE regimes", bot)]:
        L.append(f"### {tag}")
        for rid in rids:
            r = df[df.regime_id == rid].sort_values("bar_index_in_regime")
            if r.empty:
                continue
            d0 = "Long" if r.iloc[0]["direction"] == 1 else "Short"
            L.append(f"**Regime {rid} ({d0})** — total fwd MFE {r.iloc[0]['future_mfe_from_here_atr']:.1f} ATR")
            L.append("| Bar | score_opp | pred_rem_mfe | pred_cont | actual_next_cont | act_rem_mfe | act_rem_mae |")
            L.append("| --- | --- | --- | --- | --- | --- | --- |")
            for _, b in r.head(10).iterrows():
                L.append(f"| {int(b['bar_index_in_regime'])} | {b['score_opportunity']:.2f} | "
                         f"{b['pred_rem_mfe']:.2f} | {b['pred_c1']*100:.0f}% | "
                         f"{'Yes' if b['next_bar_makes_continuation'] else 'No'} | "
                         f"{b['future_mfe_from_here_atr']:.2f} | {b['future_mae_from_here_atr']:.2f} |")
            L.append("")


def main():
    df = load()
    oos = df[df.is_oos == 1].copy()
    print(f"Loaded {len(df):,} scored bars; OOS {len(oos):,}")
    L = ["# Atlas Diagnostics — what the KNN scorer sees (OOS 2025–2026)", "",
         "Opens the black box: per-bar score vs prediction vs actual outcome. NOT a "
         "profitability test — a perception test. Key question from the audit: does the "
         "score track actual forward **MFE** (opportunity) even though it failed on net PnL?", ""]
    corr_block(oos, L)
    L.append("## 2. Score-opportunity deciles vs actual (OOS) — explains the Decile 9/10 rollover")
    decile_table(oos, "score_opportunity", L, "score_opportunity deciles")
    fp_fn(oos, L)
    example_regimes(oos, L)

    # headline takeaways computed
    act_opp = oos["future_mfe_from_here_atr"] - oos["future_mae_from_here_atr"]
    r_mfe = oos["score_opportunity"].corr(oos["future_mfe_from_here_atr"], method="spearman")
    r_mae = oos["score_opportunity"].corr(oos["future_mae_from_here_atr"], method="spearman")
    r_pnl = oos["score_opportunity"].corr(oos["actual_forward_pnl"], method="spearman")
    L.insert(4, f"> **TL;DR.** score_opportunity ranks actual forward MFE at Spearman "
                f"**{r_mfe:+.2f}** and actual forward MAE at **{r_mae:+.2f}** — it sees BOTH the "
                f"upside and the downside, so it nets to only **{r_pnl:+.2f}** vs actual PnL. "
                f"The model sees *magnitude/opportunity*, not *direction-of-payoff*.")
    (OUT / "atlas_diagnostics.md").write_text("\n".join(L), encoding="utf-8")
    print(f"score_opportunity Spearman: MFE {r_mfe:+.3f}, MAE {r_mae:+.3f}, PnL {r_pnl:+.3f}")
    print("Wrote results/atlas_diagnostics.md")


if __name__ == "__main__":
    main()
