"""Pullback DNA Atlas — analysis of collector observations.

Produces six deliverables (printed + saved):
  1. Pullback DNA Atlas       — entry context & feature distributions
  2. Lifecycle Report         — risk, excursion, time to targets
  3. Pullback Transition Atlas— probability surface at 30s intervals
  4. Opportunity Curves       — remaining MFE vs time / depth / pullback number / hC
  5. Archetype Report         — rule-based pullback shape classes
  6. Management Implications  — dominant exit style per archetype

Usage:
    python studies/pullback_dna/analyze.py
"""
from __future__ import annotations
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd

RESULTS = Path("studies/pullback_dna/results")
OUT     = RESULTS / "reports"
OUT.mkdir(parents=True, exist_ok=True)

NS = 1_000_000_000          # nanoseconds per second


# ── Helpers ────────────────────────────────────────────────────────────────────

def pct(v, tot):
    return 0.0 if tot == 0 else 100.0 * v / tot

def ev(df):
    return df["pnl"].mean() if len(df) else float("nan")

def wr(df):
    return pct((df["pnl"] > 0).sum(), len(df))

def pf(df):
    wins   = df.loc[df["pnl"] > 0, "pnl"].sum()
    losses = abs(df.loc[df["pnl"] < 0, "pnl"].sum())
    return wins / losses if losses > 0 else float("inf")

def p50(s):
    return s.median() if len(s) else float("nan")

def reach(df, ck):
    return pct(df[f"did_{ck}"].sum(), len(df))

def sep(title="", width=80):
    if title:
        pad = (width - len(title) - 2) // 2
        print("\n" + "=" * pad + f" {title} " + "=" * pad)
    else:
        print("\n" + "-" * width)


# ── Archetype classification ───────────────────────────────────────────────────

def classify(row) -> str:
    rsn     = row["exit_reason"]
    d025    = row["did_025"]
    d050    = row["did_050"]
    d100    = row["did_100"]
    revisit = row["after_050_revisit_entry"]
    mfe     = row["max_mfe_atr"]
    hold_m  = row["hold_s"] / 60.0

    if rsn == "sl":
        if not d025:
            return "ImmediateFail"       # stopped before any gain
        if not d050:
            return "PartialRun"          # reached +0.25, reversed
        if not d100:
            if revisit:
                return "VShapeFail"      # touched +0.50, retreated to entry, then SL
            return "MidReverse"          # touched +0.50, reversed to SL
        return "DeepReverse"             # reached +1 ATR or more, then reversed all the way

    # regime_flip exits
    if mfe < 0.25:
        return "FlipNegative"            # flip exit with little/no gain (loss)
    if mfe < 1.00:
        return "FlipModerate"            # flip with modest gain
    if mfe < 2.00:
        return "FlipRunner"              # flip with solid multi-ATR gain
    return "FlipExpansion"               # flip with exceptional gain (2+ ATR)


ARCHETYPE_ORDER = [
    "ImmediateFail", "PartialRun", "VShapeFail", "MidReverse",
    "DeepReverse", "FlipNegative", "FlipModerate", "FlipRunner", "FlipExpansion",
]

ARCHETYPE_MGMT = {
    "ImmediateFail":  "Tight SL works — these die fast. No adjustment to make.",
    "PartialRun":     "Consider BE stop at +0.25 ATR; rarely reaches 0.50. Exit at first sign of reversal.",
    "VShapeFail":     "BE stop at +0.50 is destructive — they revisit entry but then fail. Hold or SL only.",
    "MidReverse":     "PT at +0.50 ATR captures most value. Holding further rarely pays on this archetype.",
    "DeepReverse":    "Trail from +1 ATR. Large excursion available; don't exit too early.",
    "FlipNegative":   "Hold-to-flip is losers here. Quick PT or tight stop on early bars preferred.",
    "FlipModerate":   "Hold-to-flip is viable; modest winners. PT at +0.50 sacrifices some but reduces variance.",
    "FlipRunner":     "Hold-to-flip dominates. Any early PT dramatically undercuts the realized gain.",
    "FlipExpansion":  "Hold-to-flip dominates. Trail from +2 ATR; exceptional runners need room.",
}


# ── Load data ─────────────────────────────────────────────────────────────────

def load_all() -> dict[float, pd.DataFrame]:
    dfs: dict[float, pd.DataFrame] = {}
    for depth, label in [(0.25, "0p25"), (0.50, "0p5"), (0.75, "0p75")]:
        p = RESULTS / f"obs_depth{label}.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            df["archetype"] = df.apply(classify, axis=1)
            df["hold_m"]    = df["hold_s"] / 60.0
            df["year"]      = pd.to_datetime(df["entry_ts"], unit="ns", utc=True).dt.year
            df["pb_id_cat"] = df["pullback_id"].clip(upper=4).map(
                {1: "1st", 2: "2nd", 3: "3rd", 4: "4th+"}
            )
            dfs[depth] = df
        else:
            print(f"  WARNING: {p} not found")
    return dfs


# ═══════════════════════════════════════════════════════════════════════════════
# 1. PULLBACK DNA ATLAS
# ═══════════════════════════════════════════════════════════════════════════════

def report_dna_atlas(dfs: dict[float, pd.DataFrame]) -> None:
    sep("PULLBACK DNA ATLAS")

    for depth, df in dfs.items():
        n = len(df)
        print(f"\n── Depth {depth:.2f} ATR  (n={n:,}) ─────────────────────────────")

        # Basic outcomes
        n_sl   = (df["exit_reason"] == "sl").sum()
        n_flip = (df["exit_reason"] == "regime_flip").sum()
        print(f"  Exit split:       SL {pct(n_sl,n):.1f}%  |  Flip {pct(n_flip,n):.1f}%")
        print(f"  Win rate:         {wr(df):.1f}%")
        print(f"  Expectancy:       ${ev(df):.1f}/trade")
        print(f"  Profit factor:    {pf(df):.2f}")

        # Checkpoint reach rates
        print(f"  Reach +0.25 ATR:  {reach(df,'025'):.1f}%")
        print(f"  Reach +0.50 ATR:  {reach(df,'050'):.1f}%")
        print(f"  Reach +1.00 ATR:  {reach(df,'100'):.1f}%")
        print(f"  Reach +1.50 ATR:  {reach(df,'150'):.1f}%")
        print(f"  Reach +2.00 ATR:  {reach(df,'200'):.1f}%")

        # Continuation after 0.50
        d050 = df[df["did_050"]]
        if len(d050):
            print(f"  P(+1.0 | +0.50):  {reach(d050,'100'):.1f}%  "
                  f"P(+2.0 | +0.50):  {reach(d050,'200'):.1f}%")

        # Entry context
        print(f"  Avg pullback depth:   {df['pb_depth_atr'].mean():.3f} ATR")
        print(f"  Avg pullback dur:     {df['pb_duration_s'].mean()/60:.1f}min")
        print(f"  Avg initial SL risk:  {df['sl_risk_atr'].mean():.3f} ATR")
        print(f"  Avg bars into regime: {df['bars_into_regime'].mean():.1f}")
        print(f"  Avg hold time:        {df['hold_m'].mean():.1f}min  "
              f"(p50={p50(df['hold_m']):.1f}min)")

        # Direction split
        for d, label in [(1, "Long"), (-1, "Short")]:
            sub = df[df["direction"] == d]
            if len(sub):
                print(f"  {label} ({len(sub):,}):  WR={wr(sub):.1f}%  "
                      f"EV=${ev(sub):.1f}  "
                      f"P(+0.5)={reach(sub,'050'):.1f}%")

        # Year breakdown
        print(f"\n  {'Year':<6}  {'n':>6}  {'WR':>6}  {'EV':>8}  "
              f"{'P+0.5':>7}  {'P+1.0':>7}")
        for yr in sorted(df["year"].unique()):
            ydf = df[df["year"] == yr]
            print(f"  {yr:<6}  {len(ydf):>6,}  {wr(ydf):>5.1f}%  "
                  f"{ev(ydf):>+8.1f}  "
                  f"{reach(ydf,'050'):>6.1f}%  "
                  f"{reach(ydf,'100'):>6.1f}%")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. LIFECYCLE REPORT
# ═══════════════════════════════════════════════════════════════════════════════

def report_lifecycle(dfs: dict[float, pd.DataFrame]) -> None:
    sep("PULLBACK LIFECYCLE REPORT")

    df = dfs[0.25].copy()   # primary analysis on deepest-resolution universe

    # Time to targets (median seconds for trades that reached each)
    print("\n── Time to Target (median, depth=0.25) ────────────────────")
    print(f"  {'Target':<12}  {'Reach%':>7}  {'Med time':>10}  {'p25':>8}  {'p75':>8}")
    for ck, label in zip(["025","050","100","150","200"],
                         ["+0.25A","+0.50A","+1.00A","+1.50A","+2.00A"]):
        reached = df[df[f"did_{ck}"]]
        if len(reached):
            dt = (reached[f"ts_{ck}"] - reached["entry_ts"]) / NS
            print(f"  {label:<12}  {pct(len(reached),len(df)):>6.1f}%  "
                  f"{dt.median():>9.0f}s  "
                  f"{dt.quantile(0.25):>7.0f}s  "
                  f"{dt.quantile(0.75):>7.0f}s")

    # MFE / MAE distributions
    print("\n── MFE / MAE Distributions (depth=0.25) ───────────────────")
    for col, label in [("max_mfe_atr","Max MFE"), ("max_mae_atr","Max MAE")]:
        s = df[col]
        print(f"  {label}: mean={s.mean():.3f}A  p25={s.quantile(.25):.3f}A  "
              f"p50={s.median():.3f}A  p75={s.quantile(.75):.3f}A  "
              f"p90={s.quantile(.90):.3f}A  p99={s.quantile(.99):.3f}A")

    # SL risk
    print(f"\n  SL risk: mean={df['sl_risk_atr'].mean():.3f}A  "
          f"p50={df['sl_risk_atr'].median():.3f}A")
    print(f"  SL ticks (0.25 pts/tick):  "
          f"mean={(df['sl_risk_atr']*df['atr_base']/0.25).mean():.1f} ticks  "
          f"p50={(df['sl_risk_atr']*df['atr_base']/0.25).median():.1f} ticks")

    # Retracement after +0.50
    d050 = df[df["did_050"]]
    if len(d050):
        rv_entry = d050["after_050_revisit_entry"].mean() * 100
        rv_sl    = d050["after_050_revisit_sl"].mean() * 100
        print(f"\n── Retracement After +0.50 ATR (n={len(d050):,}) ─────────────")
        print(f"  Price revisited entry:  {rv_entry:.1f}%  "
              f"({'destructive — BE stop fires often' if rv_entry > 40 else 'tolerable — BE stop fires rarely'})")
        print(f"  Price revisited SL:     {rv_sl:.1f}%  "
              f"(fraction stopped out after reaching +0.50)")

        # After reaching +0.50, how far do winners go?
        winners_050 = d050[d050["pnl"] > 0]
        if len(winners_050):
            rem = winners_050["max_mfe_atr"] - 0.50
            print(f"\n  Remaining MFE after +0.50 (winners only, n={len(winners_050):,}):")
            print(f"    mean={rem.mean():.3f}A  p50={rem.median():.3f}A  "
                  f"p75={rem.quantile(.75):.3f}A  p90={rem.quantile(.90):.3f}A")

    # Multiple pullbacks per regime
    sep("", 60)
    print("\n── Pullback Number Within Regime (depth=0.25) ─────────────")
    print(f"  {'#':>6}  {'n':>6}  {'WR':>6}  {'EV':>8}  {'P+0.5':>7}  {'P+1.0':>7}  {'Avg MFE':>9}")
    for cat in ["1st","2nd","3rd","4th+"]:
        sub = df[df["pb_id_cat"] == cat]
        if len(sub) > 10:
            print(f"  {cat:>6}  {len(sub):>6,}  {wr(sub):>5.1f}%  "
                  f"{ev(sub):>+8.1f}  "
                  f"{reach(sub,'050'):>6.1f}%  "
                  f"{reach(sub,'100'):>6.1f}%  "
                  f"{sub['max_mfe_atr'].mean():>8.3f}A")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. PULLBACK TRANSITION ATLAS
# ═══════════════════════════════════════════════════════════════════════════════

def report_transition_atlas(dfs: dict[float, pd.DataFrame]) -> None:
    sep("PULLBACK TRANSITION ATLAS")

    df  = dfs[0.25].copy()
    n   = len(df)

    # Pre-compute time deltas (seconds) to each checkpoint
    for ck in ["025","050","100","150","200"]:
        df[f"dt_{ck}"] = np.where(
            df[f"did_{ck}"],
            (df[f"ts_{ck}"] - df["entry_ts"]) / NS,
            np.inf
        )

    intervals = list(range(0, 121, 1)) + list(range(122, 241, 2)) + list(range(245, 601, 5))

    rows = []
    for t in intervals:
        alive   = df[df["hold_s"] > t]
        n_alive = len(alive)

        row = {"t_s": t, "n_total": n, "n_alive": n_alive,
               "pct_alive": pct(n_alive, n)}
        for ck, label in [("025","+0.25A"),("050","+0.50A"),
                           ("100","+1.00A"),("150","+1.50A"),("200","+2.00A")]:
            # Among all trades: how many reached X within t seconds?
            reached_by_t = (df[f"dt_{ck}"] <= t).sum()
            row[f"p_{ck}_unconditional"] = pct(reached_by_t, n)

            # Among alive at t: how many have ALREADY reached X?
            if n_alive > 0:
                already = (alive[f"dt_{ck}"] <= t).sum()
                row[f"p_{ck}_given_alive"] = pct(already, n_alive)
            else:
                row[f"p_{ck}_given_alive"] = float("nan")

        rows.append(row)

    atlas = pd.DataFrame(rows)
    atlas_path = OUT / "transition_atlas.parquet"
    atlas.save = lambda: atlas.to_parquet(atlas_path, index=False)
    atlas.to_parquet(atlas_path, index=False)

    # Print snapshot at key intervals
    print(f"\n  depth=0.25 ATR  (n={n:,})")
    print(f"\n  {'t':>6}  {'alive%':>7}  "
          f"{'p+0.25':>7}  {'p+0.50':>7}  {'p+1.0':>7}  {'p+2.0':>7}  "
          f"  [given still alive: p+0.50]")
    for t in [30, 60, 120, 180, 300, 600, 900, 1800, 3600]:
        row = atlas[atlas["t_s"] == t]
        if len(row) == 0:
            # Find nearest
            row = atlas.iloc[(atlas["t_s"] - t).abs().argsort()[:1]]
        r = row.iloc[0]
        print(f"  {t:>6}s  {r['pct_alive']:>6.1f}%  "
              f"{r['p_025_unconditional']:>6.1f}%  "
              f"{r['p_050_unconditional']:>6.1f}%  "
              f"{r['p_100_unconditional']:>6.1f}%  "
              f"{r['p_200_unconditional']:>6.1f}%  "
              f"  {r['p_050_given_alive']:>6.1f}%")

    print(f"\n  Transition atlas saved → {atlas_path.name}")

    # Conditional continuation: P(reach +1.0 | reached +0.50, alive at t)
    print("\n── Conditional Continuation P(+1.0 | reached +0.50) ───────")
    after_050 = df[df["did_050"]]
    p100_given_050 = reach(after_050, "100")
    p200_given_050 = reach(after_050, "200")
    print(f"  P(+1.0 ATR | +0.50 reached): {p100_given_050:.1f}%")
    print(f"  P(+2.0 ATR | +0.50 reached): {p200_given_050:.1f}%")
    print(f"  P(+1.5 ATR | +0.50 reached): {reach(after_050,'150'):.1f}%")

    # Compare across depths
    print("\n── Cross-Depth Checkpoint Rates at t=300s ─────────────────")
    print(f"  {'Depth':>7}  {'p+0.25':>7}  {'p+0.50':>7}  {'p+1.0':>7}  {'alive':>7}")
    for depth, ddf in dfs.items():
        nddf = len(ddf)
        for ck in ["025","050","100"]:
            ddf[f"dt_{ck}"] = np.where(
                ddf[f"did_{ck}"],
                (ddf[f"ts_{ck}"] - ddf["entry_ts"]) / NS,
                np.inf
            )
        p25  = pct((ddf["dt_025"] <= 300).sum(), nddf)
        p50  = pct((ddf["dt_050"] <= 300).sum(), nddf)
        p100 = pct((ddf["dt_100"] <= 300).sum(), nddf)
        palv = pct((ddf["hold_s"] > 300).sum(), nddf)
        print(f"  {depth:>7.2f}  {p25:>6.1f}%  {p50:>6.1f}%  {p100:>6.1f}%  {palv:>6.1f}%")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. OPPORTUNITY CURVES
# ═══════════════════════════════════════════════════════════════════════════════

def report_opportunity_curves(dfs: dict[float, pd.DataFrame]) -> None:
    sep("PULLBACK OPPORTUNITY CURVES")

    df = dfs[0.25].copy()

    # Remaining MFE curve: for trades alive at each time T, what is their eventual max_mfe?
    print("\n── Remaining Eventual MFE vs Time (depth=0.25) ─────────────")
    print("  (Among trades still open at each time horizon)")
    print(f"  {'t':>6}  {'n_alive':>8}  {'mean_eventual_MFE':>19}  "
          f"{'med_eventual_MFE':>17}  {'p75_MFE':>9}")
    checkpoints_t = [0, 30, 60, 120, 180, 300, 600, 900, 1800]
    rows_opp = []
    for t in checkpoints_t:
        alive = df[df["hold_s"] > t]
        if len(alive) < 10:
            break
        mfe_alive = alive["max_mfe_atr"]
        row = {
            "t_s": t,
            "n_alive": len(alive),
            "mean_eventual_mfe": mfe_alive.mean(),
            "med_eventual_mfe":  mfe_alive.median(),
            "p75_eventual_mfe":  mfe_alive.quantile(0.75),
        }
        rows_opp.append(row)
        print(f"  {t:>6}s  {len(alive):>8,}  {mfe_alive.mean():>18.3f}A  "
              f"{mfe_alive.median():>16.3f}A  {mfe_alive.quantile(.75):>8.3f}A")

    pd.DataFrame(rows_opp).to_parquet(OUT / "opportunity_curve.parquet", index=False)

    # Opportunity by regime age (bars_into_regime)
    print("\n── Opportunity by Regime Age at Entry ──────────────────────")
    print(f"  {'Bars':>6}  {'n':>6}  {'WR':>6}  {'P+0.5':>7}  {'Mean MFE':>10}  {'Mean EV':>9}")
    df["bir_bucket"] = pd.cut(df["bars_into_regime"],
                              bins=[0,5,10,15,20,30,50,200],
                              labels=["1-5","6-10","11-15","16-20","21-30","31-50","51+"])
    for bkt in ["1-5","6-10","11-15","16-20","21-30","31-50","51+"]:
        sub = df[df["bir_bucket"] == bkt]
        if len(sub) > 20:
            print(f"  {bkt:>6}  {len(sub):>6,}  {wr(sub):>5.1f}%  "
                  f"{reach(sub,'050'):>6.1f}%  "
                  f"{sub['max_mfe_atr'].mean():>9.3f}A  "
                  f"{ev(sub):>+9.1f}")

    # Opportunity by pullback number
    print("\n── Opportunity by Pullback Number ──────────────────────────")
    print(f"  {'#':>6}  {'n':>6}  {'WR':>6}  {'P+0.5':>7}  {'Mean MFE':>10}  {'Mean EV':>9}")
    for cat in ["1st","2nd","3rd","4th+"]:
        sub = df[df["pb_id_cat"] == cat]
        if len(sub) > 10:
            print(f"  {cat:>6}  {len(sub):>6,}  {wr(sub):>5.1f}%  "
                  f"{reach(sub,'050'):>6.1f}%  "
                  f"{sub['max_mfe_atr'].mean():>9.3f}A  "
                  f"{ev(sub):>+9.1f}")

    # Opportunity by hC
    print("\n── Opportunity by hC Quartile ───────────────────────────────")
    print(f"  {'hC':>10}  {'n':>6}  {'WR':>6}  {'P+0.5':>7}  {'Mean MFE':>10}  {'Mean EV':>9}")
    df["hC_q"] = pd.qcut(df["hC"], q=4, labels=["Q1","Q2","Q3","Q4"])
    for q in ["Q1","Q2","Q3","Q4"]:
        sub = df[df["hC_q"] == q]
        hc_rng = f"{sub['hC'].min():.3f}-{sub['hC'].max():.3f}"
        if len(sub) > 10:
            print(f"  {q} {hc_rng:>10}  {len(sub):>6,}  {wr(sub):>5.1f}%  "
                  f"{reach(sub,'050'):>6.1f}%  "
                  f"{sub['max_mfe_atr'].mean():>9.3f}A  "
                  f"{ev(sub):>+9.1f}")

    # Opportunity by depth (cross-depth comparison)
    print("\n── Opportunity by Entry Depth ───────────────────────────────")
    print(f"  {'Depth':>7}  {'n':>6}  {'WR':>6}  {'P+0.5':>7}  {'Mean MFE':>10}  {'Mean EV':>9}")
    for depth, ddf in dfs.items():
        print(f"  {depth:>7.2f}  {len(ddf):>6,}  {wr(ddf):>5.1f}%  "
              f"{reach(ddf,'050'):>6.1f}%  "
              f"{ddf['max_mfe_atr'].mean():>9.3f}A  "
              f"{ev(ddf):>+9.1f}")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ARCHETYPE REPORT
# ═══════════════════════════════════════════════════════════════════════════════

def report_archetypes(dfs: dict[float, pd.DataFrame]) -> None:
    sep("PULLBACK ARCHETYPE REPORT")

    df = dfs[0.25].copy()
    n  = len(df)

    arch_stats = []
    print(f"\n  depth=0.25 ATR  (n={n:,})")
    print(f"\n  {'Archetype':<18}  {'n':>6}  {'%':>6}  {'WR':>6}  "
          f"{'Avg EV':>8}  {'Avg MFE':>9}  {'Avg MAE':>9}  {'Hold':>7}")
    for arch in ARCHETYPE_ORDER:
        sub = df[df["archetype"] == arch]
        if len(sub) == 0:
            continue
        row = {
            "archetype": arch,
            "n":         len(sub),
            "pct":       pct(len(sub), n),
            "win_rate":  wr(sub),
            "avg_ev":    ev(sub),
            "avg_mfe":   sub["max_mfe_atr"].mean(),
            "avg_mae":   sub["max_mae_atr"].mean(),
            "avg_hold_m": sub["hold_m"].mean(),
            "p_050":     reach(sub, "050"),
            "p_100":     reach(sub, "100"),
        }
        arch_stats.append(row)
        print(f"  {arch:<18}  {len(sub):>6,}  {row['pct']:>5.1f}%  "
              f"{row['win_rate']:>5.1f}%  "
              f"{row['avg_ev']:>+8.1f}  "
              f"{row['avg_mfe']:>8.3f}A  "
              f"{row['avg_mae']:>8.3f}A  "
              f"{row['avg_hold_m']:>6.0f}m")

    pd.DataFrame(arch_stats).to_parquet(OUT / "archetypes.parquet", index=False)

    # Archetype by direction
    print("\n── Archetype Distribution by Direction ─────────────────────")
    for d, label in [(1,"Long"), (-1,"Short")]:
        sub_dir = df[df["direction"] == d]
        print(f"\n  {label} (n={len(sub_dir):,}):")
        for arch in ARCHETYPE_ORDER:
            sub = sub_dir[sub_dir["archetype"] == arch]
            if len(sub) > 0:
                print(f"    {arch:<18}  {pct(len(sub),len(sub_dir)):>5.1f}%  "
                      f"WR={wr(sub):>4.1f}%  EV=${ev(sub):>+7.1f}")

    # Archetype by year (stability check)
    print("\n── Archetype WR Stability Across Years ─────────────────────")
    years = sorted(df["year"].unique())
    header = f"  {'Archetype':<18}" + "".join(f"  {yr}" for yr in years)
    print(header)
    for arch in ARCHETYPE_ORDER:
        sub = df[df["archetype"] == arch]
        if len(sub) < 50:
            continue
        row_str = f"  {arch:<18}"
        for yr in years:
            ysub = sub[sub["year"] == yr]
            row_str += f"  {wr(ysub):>4.1f}%"
        print(row_str)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. MANAGEMENT IMPLICATIONS
# ═══════════════════════════════════════════════════════════════════════════════

def report_management(dfs: dict[float, pd.DataFrame]) -> None:
    sep("MANAGEMENT IMPLICATIONS REPORT")

    df = dfs[0.25].copy()
    n  = len(df)

    # For each archetype: compare four management styles
    #   style A: hold-to-SL-or-flip (current)
    #   style B: PT at +0.25 ATR (if reached, exit there; else SL/flip)
    #   style C: PT at +0.50 ATR (if reached, exit there; else SL/flip)
    #   style D: PT at +1.00 ATR (if reached, exit there; else SL/flip)
    MULT = 20.0; COMM = 4.06

    def sim_pt(sub: pd.DataFrame, pt_atr: float) -> float:
        """Simulate PT exit at pt_atr if reached, else hold-to-SL-or-flip."""
        ck = f"{int(pt_atr * 100):03d}"
        col_did = f"did_{ck}"
        if col_did not in sub.columns:
            return float("nan")
        hit_pt   = sub[col_did]
        pt_pnl   = sub["atr_base"] * pt_atr * MULT - COMM
        sl_pnl   = sub["pnl"]                           # original SL/flip exit PnL
        return (hit_pt * pt_pnl + (~hit_pt) * sl_pnl).mean()

    print(f"\n  depth=0.25 ATR  (n={n:,})")
    print(f"\n  {'Archetype':<18}  {'Hold(curr)':>11}  "
          f"{'PT@+0.25':>9}  {'PT@+0.50':>9}  {'PT@+1.00':>9}  "
          f"{'Best':>12}")

    mgmt_rows = []
    for arch in ARCHETYPE_ORDER:
        sub = df[df["archetype"] == arch]
        if len(sub) < 20:
            continue
        ev_hold = ev(sub)
        ev_025  = sim_pt(sub, 0.25)
        ev_050  = sim_pt(sub, 0.50)
        ev_100  = sim_pt(sub, 1.00)
        evs     = {"Hold": ev_hold, "PT@+0.25": ev_025,
                   "PT@+0.50": ev_050, "PT@+1.00": ev_100}
        best    = max(evs, key=evs.get)
        mgmt_rows.append({**{"archetype": arch}, **evs, "best": best})
        print(f"  {arch:<18}  {ev_hold:>+11.1f}  "
              f"{ev_025:>+9.1f}  {ev_050:>+9.1f}  {ev_100:>+9.1f}  "
              f"{best:>12}")

    pd.DataFrame(mgmt_rows).to_parquet(OUT / "management_implications.parquet", index=False)

    sep("", 60)
    print("\n── Management Recommendation by Archetype ──────────────────")
    for arch, rec in ARCHETYPE_MGMT.items():
        sub = df[df["archetype"] == arch]
        n_arch = len(sub)
        if n_arch < 20:
            continue
        print(f"\n  {arch} ({pct(n_arch,n):.1f}% of trades)")
        print(f"    {rec}")

    # Key structural question: is breakeven stop harmful?
    sep("", 60)
    print("\n── Breakeven Stop Impact ───────────────────────────────────")
    d050 = df[df["did_050"]]
    print(f"  Trades reaching +0.50 ATR: {len(d050):,} ({pct(len(d050),n):.1f}%)")
    if len(d050):
        rv = d050["after_050_revisit_entry"].mean() * 100
        rv_sl = d050["after_050_revisit_sl"].mean() * 100
        print(f"  Of those, revisit entry:   {rv:.1f}%")
        print(f"  Of those, hit SL anyway:   {rv_sl:.1f}%")
        if rv > 35:
            print(f"  VERDICT: BE stop would fire on {rv:.0f}% of trades that reached +0.50.")
            print(f"  This is DESTRUCTIVE — most of those trades would recover.")
        else:
            print(f"  VERDICT: BE stop fires rarely ({rv:.0f}%). May be acceptable.")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    print("Loading observation parquets …")
    dfs = load_all()
    if not dfs:
        print("No parquets found. Run run_collector.py first.")
        return
    print(f"  Loaded: " +
          "  ".join(f"depth={d:.2f}: {len(df):,}" for d, df in dfs.items()))

    report_dna_atlas(dfs)
    report_lifecycle(dfs)
    report_transition_atlas(dfs)
    report_opportunity_curves(dfs)
    report_archetypes(dfs)
    report_management(dfs)

    sep("COMPLETE")
    print(f"  Parquet outputs saved to: {OUT}")


if __name__ == "__main__":
    main()
