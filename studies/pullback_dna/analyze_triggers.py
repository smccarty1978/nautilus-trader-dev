"""Compare the four entry trigger variants.

Key diagnostic: does 5s regime realignment reduce ImmediateFail %
without destroying FlipExpansion %?

Usage:
    python studies/pullback_dna/analyze_triggers.py
"""
from __future__ import annotations
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd

RESULTS = Path("studies/pullback_dna/results")
MULT = 20.0
COMM = 4.06


# ── Helpers ────────────────────────────────────────────────────────────────────

def pct(v, tot):
    return 0.0 if tot == 0 else 100.0 * v / tot

def wr(df):
    return pct((df["pnl"] > 0).sum(), len(df)) if len(df) else float("nan")

def ev(df):
    return df["pnl"].mean() if len(df) else float("nan")

def pf(df):
    wins   = df.loc[df["pnl"] > 0, "pnl"].sum()
    losses = abs(df.loc[df["pnl"] < 0, "pnl"].sum())
    return wins / losses if losses > 0 else float("inf")

def reach(df, ck):
    return pct(df[f"did_{ck}"].sum(), len(df))

def sep(title="", width=80):
    if title:
        pad = (width - len(title) - 2) // 2
        print("\n" + "=" * pad + f" {title} " + "=" * pad)
    else:
        print("\n" + "-" * width)


# ── Archetype classification (same as analyze.py) ─────────────────────────────

def classify(row) -> str:
    rsn     = row["exit_reason"]
    d025    = row["did_025"]
    d050    = row["did_050"]
    d100    = row["did_100"]
    revisit = row["after_050_revisit_entry"]
    mfe     = row["max_mfe_atr"]
    if rsn == "sl":
        if not d025:
            return "ImmediateFail"
        if not d050:
            return "PartialRun"
        if not d100:
            return "VShapeFail" if revisit else "MidReverse"
        return "DeepReverse"
    if mfe < 0.25:
        return "FlipNegative"
    if mfe < 1.00:
        return "FlipModerate"
    if mfe < 2.00:
        return "FlipRunner"
    return "FlipExpansion"


LOSS_ARCHETYPES = ["ImmediateFail", "PartialRun", "VShapeFail", "MidReverse", "DeepReverse"]
WIN_ARCHETYPES  = ["FlipNegative", "FlipModerate", "FlipRunner", "FlipExpansion"]
ALL_ARCHETYPES  = LOSS_ARCHETYPES + WIN_ARCHETYPES

TRIGGER_LABELS = {
    "A": "A  depth>=0.25 + up-close (baseline)",
    "B": "B  5s regime realignment",
    "C": "C  5s realignment + 50% reclaim",
    "D": "D  5s realignment + break adverse high",
}


# ── Load data ─────────────────────────────────────────────────────────────────

def load_all() -> dict[str, pd.DataFrame]:
    dfs: dict[str, pd.DataFrame] = {}
    for trig in ["A", "B", "C", "D"]:
        p = RESULTS / f"trigger_{trig}.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            df["archetype"] = df.apply(classify, axis=1)
            df["hold_m"]    = df["hold_s"] / 60.0
            df["year"]      = pd.to_datetime(
                df["entry_ts"], unit="ns", utc=True
            ).dt.year
            dfs[trig] = df
        else:
            print(f"  WARNING: {p.name} not found — run run_triggers.py first")
    return dfs


# ── Section 1: headline comparison ────────────────────────────────────────────

def report_headline(dfs: dict[str, pd.DataFrame]) -> None:
    sep("HEADLINE COMPARISON")

    print(f"\n  {'Trigger':<42}  {'n':>7}  {'WR':>6}  {'EV':>8}  {'PF':>5}  "
          f"{'P+0.5':>6}  {'P+1.0':>6}  {'Avg MFE':>8}  {'Avg hold':>9}")
    for trig, df in dfs.items():
        label = TRIGGER_LABELS[trig]
        print(f"  {label:<42}  {len(df):>7,}  {wr(df):>5.1f}%  "
              f"{ev(df):>+8.1f}  {pf(df):>5.2f}  "
              f"{reach(df,'050'):>5.1f}%  {reach(df,'100'):>5.1f}%  "
              f"{df['max_mfe_atr'].mean():>7.3f}A  "
              f"{df['hold_m'].mean():>8.1f}m")


# ── Section 2: ImmediateFail / FlipExpansion diagnostic ───────────────────────

def report_key_archetypes(dfs: dict[str, pd.DataFrame]) -> None:
    sep("KEY ARCHETYPE DIAGNOSTIC")

    print(f"\n  {'Trigger':<42}  {'n':>7}  "
          f"{'ImFail%':>8}  {'PartRun%':>9}  {'VShape%':>8}  "
          f"{'DeepRev%':>9}  {'FlipExp%':>9}  "
          f"{'ImFail EV':>10}  {'FlipExp EV':>11}")
    for trig, df in dfs.items():
        n = len(df)
        label = TRIGGER_LABELS[trig]
        imf  = df[df["archetype"] == "ImmediateFail"]
        fexp = df[df["archetype"] == "FlipExpansion"]
        prun = df[df["archetype"] == "PartialRun"]
        vsh  = df[df["archetype"] == "VShapeFail"]
        drev = df[df["archetype"] == "DeepReverse"]
        print(f"  {label:<42}  {n:>7,}  "
              f"{pct(len(imf),n):>7.1f}%  "
              f"{pct(len(prun),n):>8.1f}%  "
              f"{pct(len(vsh),n):>7.1f}%  "
              f"{pct(len(drev),n):>8.1f}%  "
              f"{pct(len(fexp),n):>8.1f}%  "
              f"{ev(imf):>+10.1f}  "
              f"{ev(fexp):>+11.1f}")


# ── Section 3: full archetype table per trigger ────────────────────────────────

def report_archetypes_full(dfs: dict[str, pd.DataFrame]) -> None:
    sep("FULL ARCHETYPE TABLE BY TRIGGER")

    for trig, df in dfs.items():
        n = len(df)
        print(f"\n  -- Trigger {trig}: {TRIGGER_LABELS[trig]}  (n={n:,}) --")
        print(f"  {'Archetype':<18}  {'n':>6}  {'%':>6}  {'WR':>6}  "
              f"{'Avg EV':>8}  {'Avg MFE':>9}  {'Avg MAE':>9}  {'Hold':>7}")
        for arch in ALL_ARCHETYPES:
            sub = df[df["archetype"] == arch]
            if len(sub) == 0:
                continue
            print(f"  {arch:<18}  {len(sub):>6,}  {pct(len(sub),n):>5.1f}%  "
                  f"{wr(sub):>5.1f}%  "
                  f"{ev(sub):>+8.1f}  "
                  f"{sub['max_mfe_atr'].mean():>8.3f}A  "
                  f"{sub['max_mae_atr'].mean():>8.3f}A  "
                  f"{sub['hold_m'].mean():>6.0f}m")


# ── Section 4: year-by-year WR and EV ─────────────────────────────────────────

def report_yearly(dfs: dict[str, pd.DataFrame]) -> None:
    sep("YEAR-BY-YEAR WR AND EV")

    # Collect all years present
    all_years: list[int] = []
    for df in dfs.values():
        all_years.extend(df["year"].unique().tolist())
    years = sorted(set(all_years))

    # WR table
    print(f"\n  Win Rate by Year")
    print(f"  {'Trigger':<42}" + "".join(f"  {yr}" for yr in years))
    for trig, df in dfs.items():
        row = f"  {TRIGGER_LABELS[trig]:<42}"
        for yr in years:
            sub = df[df["year"] == yr]
            row += f"  {wr(sub):>4.1f}%"
        print(row)

    # EV table
    print(f"\n  Expectancy ($/trade) by Year")
    print(f"  {'Trigger':<42}" + "".join(f"  {yr:>7}" for yr in years))
    for trig, df in dfs.items():
        row = f"  {TRIGGER_LABELS[trig]:<42}"
        for yr in years:
            sub = df[df["year"] == yr]
            row += f"  {ev(sub):>+7.1f}"
        print(row)


# ── Section 5: entry context comparison ───────────────────────────────────────

def report_entry_context(dfs: dict[str, pd.DataFrame]) -> None:
    sep("ENTRY CONTEXT COMPARISON")

    print(f"\n  {'Trigger':<42}  {'Avg pb_depth':>13}  {'Avg SL risk':>12}  "
          f"{'Avg pb_dur':>11}  {'Avg bars in':>12}")
    for trig, df in dfs.items():
        label = TRIGGER_LABELS[trig]
        print(f"  {label:<42}  "
              f"{df['pb_depth_atr'].mean():>12.3f}A  "
              f"{df['sl_risk_atr'].mean():>11.3f}A  "
              f"{df['pb_duration_s'].mean()/60:>10.1f}m  "
              f"{df['bars_into_regime'].mean():>11.1f}")

    # Pullback depth distribution
    print(f"\n  Pullback Depth at Entry (ATR) — percentiles")
    print(f"  {'Trigger':<42}  {'p25':>6}  {'p50':>6}  {'p75':>6}  {'p90':>6}")
    for trig, df in dfs.items():
        label = TRIGGER_LABELS[trig]
        d = df["pb_depth_atr"]
        print(f"  {label:<42}  {d.quantile(.25):>5.3f}A  "
              f"{d.quantile(.50):>5.3f}A  {d.quantile(.75):>5.3f}A  "
              f"{d.quantile(.90):>5.3f}A")

    # SL risk distribution
    print(f"\n  SL Risk at Entry (ATR) — percentiles")
    print(f"  {'Trigger':<42}  {'p25':>6}  {'p50':>6}  {'p75':>6}  {'p90':>6}")
    for trig, df in dfs.items():
        label = TRIGGER_LABELS[trig]
        d = df["sl_risk_atr"]
        print(f"  {label:<42}  {d.quantile(.25):>5.3f}A  "
              f"{d.quantile(.50):>5.3f}A  {d.quantile(.75):>5.3f}A  "
              f"{d.quantile(.90):>5.3f}A")

    # Direction balance
    print(f"\n  Direction Balance (Long/Short)")
    for trig, df in dfs.items():
        n = len(df)
        nl = (df["direction"] == 1).sum()
        ns = (df["direction"] == -1).sum()
        print(f"  {TRIGGER_LABELS[trig]:<42}  "
              f"Long {pct(nl,n):.1f}%  Short {pct(ns,n):.1f}%")


# ── Section 6: 2025 / 2026 focus ──────────────────────────────────────────────

def report_recent_years(dfs: dict[str, pd.DataFrame]) -> None:
    sep("2025 / 2026 DETAILED")

    for yr in [2025, 2026]:
        print(f"\n  ── {yr} ────────────────────────────────────────────────────")
        print(f"  {'Trigger':<42}  {'n':>6}  {'WR':>6}  "
              f"{'EV':>8}  {'PF':>5}  {'ImFail%':>8}  {'FlipExp%':>9}")
        for trig, df in dfs.items():
            sub = df[df["year"] == yr]
            n   = len(sub)
            imf = (sub["archetype"] == "ImmediateFail").sum()
            fex = (sub["archetype"] == "FlipExpansion").sum()
            print(f"  {TRIGGER_LABELS[trig]:<42}  {n:>6,}  {wr(sub):>5.1f}%  "
                  f"{ev(sub):>+8.1f}  {pf(sub):>5.2f}  "
                  f"{pct(imf,n):>7.1f}%  {pct(fex,n):>8.1f}%")


# ── Section 7: management simulation ──────────────────────────────────────────

def report_management_sim(dfs: dict[str, pd.DataFrame]) -> None:
    sep("MANAGEMENT SIMULATION (EV by PT policy)")

    def sim_pt(sub: pd.DataFrame, pt_atr: float) -> float:
        ck      = f"{int(pt_atr * 100):03d}"
        col_did = f"did_{ck}"
        if col_did not in sub.columns:
            return float("nan")
        hit     = sub[col_did]
        pt_pnl  = sub["atr_base"] * pt_atr * MULT - COMM
        return (hit * pt_pnl + (~hit) * sub["pnl"]).mean()

    print(f"\n  {'Trigger':<42}  {'Hold':>8}  {'PT+0.25':>8}  "
          f"{'PT+0.50':>8}  {'PT+1.00':>8}  {'Best':>10}")
    for trig, df in dfs.items():
        label  = TRIGGER_LABELS[trig]
        ev_hld = ev(df)
        ev_025 = sim_pt(df, 0.25)
        ev_050 = sim_pt(df, 0.50)
        ev_100 = sim_pt(df, 1.00)
        evs    = {"Hold": ev_hld, "PT+0.25": ev_025, "PT+0.50": ev_050, "PT+1.00": ev_100}
        best   = max(evs, key=evs.get)
        print(f"  {label:<42}  {ev_hld:>+8.1f}  {ev_025:>+8.1f}  "
              f"{ev_050:>+8.1f}  {ev_100:>+8.1f}  {best:>10}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Loading trigger parquets ...")
    dfs = load_all()
    if not dfs:
        print("No parquets found. Run run_triggers.py first.")
        return
    for trig, df in dfs.items():
        print(f"  {trig}: {len(df):,} observations")

    report_headline(dfs)
    report_key_archetypes(dfs)
    report_archetypes_full(dfs)
    report_yearly(dfs)
    report_entry_context(dfs)
    report_recent_years(dfs)
    report_management_sim(dfs)

    sep("COMPLETE")


if __name__ == "__main__":
    main()
