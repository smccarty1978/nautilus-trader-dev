"""Stop-geometry study for Trigger C entries.

Tests three fixed ATR-from-entry stops (0.25, 0.50, 0.75) against the
structural pullback-extreme SL, over 2024-07-01 through 2025-06-30.

Simulation logic
----------------
For SL-exit trades (exit_reason == "sl"):
    - Simulation is EXACT: fixed stop fires if stop_atr < sl_risk_atr,
      otherwise structural SL fires first (same outcome).

For regime-flip exits (exit_reason == "regime_flip"):
    - CONSERVATIVE: if max_mae_atr >= stop_atr we assume the fixed stop
      fires at that level.  This OVERSTATES stop-outs for trades that
      briefly dipped before expanding (FlipExpansion archetype).  The
      table flags the number of "uncertain" (flip-exit, MAE >= stop) trades
      so the reader can judge the magnitude of the approximation.

Usage:
    python studies/pullback_dna/stop_geometry.py
"""
from __future__ import annotations
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

RESULTS   = Path("studies/pullback_dna/results")
MULT      = 20.0
COMM      = 4.06

START     = pd.Timestamp("2024-07-01", tz="UTC")
END       = pd.Timestamp("2025-06-30 23:59:59", tz="UTC")

STOP_SIZES = [0.25, 0.50, 0.75]


# ── Helpers ────────────────────────────────────────────────────────────────────

def pct(v, t):
    return 0.0 if t == 0 else 100.0 * v / t

def wr(pnls):
    if len(pnls) == 0: return float("nan")
    return pct((pnls > 0).sum(), len(pnls))

def ev(pnls):
    return pnls.mean() if len(pnls) else float("nan")

def pf(pnls):
    w = pnls[pnls > 0].sum()
    l = abs(pnls[pnls < 0].sum())
    return w / l if l > 0 else float("inf")

def max_dd(pnls):
    equity = pnls.cumsum()
    roll_max = equity.cummax()
    dd = (equity - roll_max)
    return dd.min()

def sep(title="", width=84):
    if title:
        pad = (width - len(title) - 2) // 2
        print("\n" + "=" * pad + f" {title} " + "=" * pad)
    else:
        print("\n" + "-" * width)


# ── Original archetype (from structural SL) ───────────────────────────────────

def classify_orig(row) -> str:
    rsn     = row["exit_reason"]
    d025    = row["did_025"]
    d050    = row["did_050"]
    d100    = row["did_100"]
    revisit = row["after_050_revisit_entry"]
    mfe     = row["max_mfe_atr"]
    if rsn == "sl":
        if not d025: return "ImmediateFail"
        if not d050: return "PartialRun"
        if not d100: return "VShapeFail" if revisit else "MidReverse"
        return "DeepReverse"
    if mfe < 0.25: return "FlipNegative"
    if mfe < 1.00: return "FlipModerate"
    if mfe < 2.00: return "FlipRunner"
    return "FlipExpansion"


# ── Fixed-stop simulation ──────────────────────────────────────────────────────

def simulate_fixed_stop(df: pd.DataFrame, stop_atr: float) -> pd.DataFrame:
    """Apply a fixed ATR-from-entry stop to every trade.

    Returns a copy with added columns:
        sim_pnl         : outcome under fixed stop
        sim_stop_hit    : True when fixed stop fired
        sim_uncertain   : True for regime-flip exits where stop *might* have
                          fired (max_mae_atr >= stop_atr) — conservative.
        sim_exit        : 'fixed_sl' | 'sl' | 'regime_flip'
        sim_arch        : simplified archetype under fixed-stop outcome
    """
    out = df.copy()

    stop_pnl = -(stop_atr * out["atr_base"] * MULT) - COMM

    # Default: keep original outcome
    out["sim_pnl"]       = out["pnl"]
    out["sim_stop_hit"]  = False
    out["sim_uncertain"] = False
    out["sim_exit"]      = out["exit_reason"]

    # SL-exit trades: EXACT — fixed stop fires if tighter than structural SL
    sl_mask = out["exit_reason"] == "sl"
    fixed_earlier = sl_mask & (stop_atr < out["sl_risk_atr"])
    out.loc[fixed_earlier, "sim_pnl"]      = stop_pnl[fixed_earlier]
    out.loc[fixed_earlier, "sim_stop_hit"] = True
    out.loc[fixed_earlier, "sim_exit"]     = "fixed_sl"

    # Regime-flip exits: CONSERVATIVE — stop fires if MAE >= threshold
    flip_mask     = out["exit_reason"] == "regime_flip"
    flip_stop     = flip_mask & (out["max_mae_atr"] >= stop_atr)
    out.loc[flip_stop, "sim_pnl"]       = stop_pnl[flip_stop]
    out.loc[flip_stop, "sim_stop_hit"]  = True
    out.loc[flip_stop, "sim_uncertain"] = True   # timing unknown
    out.loc[flip_stop, "sim_exit"]      = "fixed_sl"

    # Archetype under fixed stop
    # FlipExpansion survivor: regime_flip exit, MFE >= 2 ATR (stop never fired)
    # ImmFail-like: any stop exit where max_mfe_atr < 0.25 (never moved our way)
    def sim_arch(r):
        if r["sim_exit"] == "regime_flip":
            mfe = r["max_mfe_atr"]
            if mfe < 0.25: return "FlipNegative"
            if mfe < 1.00: return "FlipModerate"
            if mfe < 2.00: return "FlipRunner"
            return "FlipExpansion"
        # stopped (fixed_sl or sl)
        mfe = r["max_mfe_atr"]
        if mfe < 0.25: return "ImmFail-like"
        if mfe < 0.50: return "Partial-like"
        return "Runner-stopped"
    out["sim_arch"] = out.apply(sim_arch, axis=1)
    return out


# ── Metrics for a simulated frame ─────────────────────────────────────────────

def metrics(sim: pd.DataFrame, stop_atr: float | str) -> dict:
    p = sim["sim_pnl"]
    winners = p[p > 0]
    losers  = p[p < 0]

    total_n          = len(sim)
    stop_hit_n       = sim["sim_stop_hit"].sum()
    uncertain_n      = sim["sim_uncertain"].sum()
    regime_exit_n    = (sim["sim_exit"] == "regime_flip").sum()
    imm_fail_n       = (sim["sim_arch"] == "ImmFail-like").sum()
    flip_exp_n       = (sim["sim_arch"] == "FlipExpansion").sum()

    return {
        "stop_atr":        stop_atr,
        "n":               total_n,
        "wr":              wr(p),
        "ev":              ev(p),
        "total_pnl":       p.sum(),
        "pf":              pf(p),
        "max_dd":          max_dd(p),
        "imm_fail_pct":    pct(imm_fail_n, total_n),
        "flip_exp_pct":    pct(flip_exp_n, total_n),
        "avg_loss":        losers.mean() if len(losers) else float("nan"),
        "median_loss":     losers.median() if len(losers) else float("nan"),
        "avg_winner":      winners.mean() if len(winners) else float("nan"),
        "median_winner":   winners.median() if len(winners) else float("nan"),
        "stop_hit_pct":    pct(stop_hit_n, total_n),
        "regime_exit_pct": pct(regime_exit_n, total_n),
        "n_uncertain":     int(uncertain_n),
    }


# ── Report sections ────────────────────────────────────────────────────────────

def report_summary(rows: list[dict]) -> None:
    sep("SUMMARY TABLE")
    hdr = (
        f"  {'Stop':>8}  {'n':>6}  {'WR':>6}  {'EV':>8}  {'TotPnL':>9}  "
        f"{'PF':>5}  {'MaxDD':>9}  {'ImmFail':>8}  {'FlipExp':>8}"
    )
    print(f"\n{hdr}")
    for r in rows:
        s = r["stop_atr"]
        lbl = "struct" if s == "struct" else f"{s:.2f}A"
        print(
            f"  {lbl:>8}  {r['n']:>6,}  {r['wr']:>5.1f}%  "
            f"{r['ev']:>+8.1f}  {r['total_pnl']:>+9,.0f}  "
            f"{r['pf']:>5.2f}  {r['max_dd']:>+9,.0f}  "
            f"{r['imm_fail_pct']:>7.1f}%  {r['flip_exp_pct']:>7.1f}%"
        )


def report_loss_win(rows: list[dict]) -> None:
    sep("LOSS / WINNER PROFILE")
    hdr = (
        f"  {'Stop':>8}  {'AvgLoss':>9}  {'MedLoss':>9}  "
        f"{'AvgWin':>9}  {'MedWin':>9}  {'StopHit%':>9}  {'RegExit%':>9}"
    )
    print(f"\n{hdr}")
    for r in rows:
        s = r["stop_atr"]
        lbl = "struct" if s == "struct" else f"{s:.2f}A"
        print(
            f"  {lbl:>8}  {r['avg_loss']:>+9.1f}  {r['median_loss']:>+9.1f}  "
            f"{r['avg_winner']:>+9.1f}  {r['median_winner']:>+9.1f}  "
            f"{r['stop_hit_pct']:>8.1f}%  {r['regime_exit_pct']:>8.1f}%"
        )
    print(
        "\n  NOTE: regime-flip exits with MAE >= stop are conservatively assumed"
        "\n  stopped (n_uncertain per stop shown below).  Actual stop-hit% for"
        "\n  these trades may be lower — they may have dipped then expanded."
    )
    for r in rows:
        if r["stop_atr"] == "struct":
            continue
        lbl = f"{r['stop_atr']:.2f}A"
        print(f"    {lbl}: {r['n_uncertain']:,} uncertain flip-exit stop-outs")


def report_composition(base_df: pd.DataFrame, sims: dict) -> None:
    sep("COMPOSITION: WHAT FIXED STOP DOES TO EACH ORIGINAL ARCHETYPE")

    orig_archs = [
        "ImmediateFail", "PartialRun", "VShapeFail", "MidReverse",
        "DeepReverse", "FlipNegative", "FlipModerate", "FlipRunner", "FlipExpansion"
    ]

    for stop_atr, sim in sims.items():
        lbl = f"{stop_atr:.2f}A"
        print(f"\n  -- Fixed stop {lbl} --")
        print(
            f"  {'Orig Archetype':<18}  {'n':>6}  "
            f"{'StopHit%':>9}  {'Uncert%':>8}  "
            f"{'Orig EV':>9}  {'Sim EV':>9}  {'Delta':>8}"
        )
        for arch in orig_archs:
            sub_orig = base_df[base_df["orig_arch"] == arch]
            sub_sim  = sim[sim["orig_arch"] == arch]
            if len(sub_orig) == 0:
                continue
            sh_pct = pct(sub_sim["sim_stop_hit"].sum(), len(sub_sim))
            unc_pct= pct(sub_sim["sim_uncertain"].sum(), len(sub_sim))
            orig_ev = sub_orig["pnl"].mean()
            sim_ev  = sub_sim["sim_pnl"].mean()
            delta   = sim_ev - orig_ev
            print(
                f"  {arch:<18}  {len(sub_orig):>6,}  "
                f"{sh_pct:>8.1f}%  {unc_pct:>7.1f}%  "
                f"{orig_ev:>+9.1f}  {sim_ev:>+9.1f}  {delta:>+8.1f}"
            )


def report_monthly(base_df: pd.DataFrame, sims: dict) -> None:
    sep("MONTHLY EV BREAKDOWN")

    months = sorted(base_df["ym"].unique())
    stops  = ["struct"] + [f"{s:.2f}A" for s in STOP_SIZES]

    print(f"\n  {'Month':<8}" + "".join(f"  {s:>10}" for s in stops))

    for ym in months:
        row = f"  {ym:<8}"
        # baseline
        sub = base_df[base_df["ym"] == ym]
        row += f"  {sub['pnl'].mean():>+10.1f}"
        # each sim
        for stop_atr, sim in sims.items():
            sub_s = sim[sim["ym"] == ym]
            row += f"  {sub_s['sim_pnl'].mean():>+10.1f}"
        print(row)

    print(f"\n  {'TOTAL':8}" + "".join(f"  {'$/trade':>10}" for _ in stops))
    row = f"  {'':8}"
    row += f"  {base_df['pnl'].mean():>+10.1f}"
    for sim in sims.values():
        row += f"  {sim['sim_pnl'].mean():>+10.1f}"
    print(row)


def report_diagnostic(base_df: pd.DataFrame, sims: dict) -> None:
    sep("KEY DIAGNOSTICS")

    print("\n  1. Does fixed SL reduce avg ImmFail loss vs structural SL?")
    imf = base_df[base_df["orig_arch"] == "ImmediateFail"]
    print(f"     Structural SL:  avg loss = {imf['pnl'].mean():+.1f}  "
          f"median loss = {imf['pnl'].median():+.1f}  "
          f"avg sl_risk = {imf['sl_risk_atr'].mean():.3f}A")
    for stop_atr, sim in sims.items():
        sub = sim[sim["orig_arch"] == "ImmediateFail"]
        sh  = pct(sub["sim_stop_hit"].sum(), len(sub))
        print(f"     {stop_atr:.2f}A fixed stop:  avg loss = {sub['sim_pnl'].mean():+.1f}  "
              f"median loss = {sub['sim_pnl'].median():+.1f}  "
              f"stop-hit% = {sh:.0f}%")

    print("\n  2. Does it preserve the improved FlipExpansion composition?")
    fexp = base_df[base_df["orig_arch"] == "FlipExpansion"]
    n_fexp = len(fexp)
    print(f"     Original FlipExpansion: {n_fexp:,} trades  "
          f"avg MAE = {fexp['max_mae_atr'].mean():.3f}A  "
          f"avg MFE = {fexp['max_mfe_atr'].mean():.3f}A")
    for stop_atr, sim in sims.items():
        sub   = sim[sim["orig_arch"] == "FlipExpansion"]
        surv  = sub[sub["sim_exit"] == "regime_flip"]
        print(f"     {stop_atr:.2f}A fixed stop:  "
              f"survive = {len(surv):,}/{n_fexp:,} ({pct(len(surv),n_fexp):.0f}%)  "
              f"stopped = {n_fexp-len(surv):,}  "
              f"uncertain of stopped = {sub['sim_uncertain'].sum():,}")

    print("\n  3. Does 0.25 ATR over-tighten (stop trades that later expand)?")
    sim25 = sims[0.25]
    runners_stopped = sim25[
        (sim25["sim_stop_hit"]) &
        (sim25["max_mfe_atr"] >= 1.0)
    ]
    print(f"     Trades stopped at 0.25A that had max_mfe >= 1.0 ATR: "
          f"{len(runners_stopped):,} ({pct(len(runners_stopped),len(sim25)):.1f}%)")
    print(f"     Their avg max_mfe_atr: {runners_stopped['max_mfe_atr'].mean():.2f}A "
          f"  avg max_mae_atr: {runners_stopped['max_mae_atr'].mean():.2f}A")
    print(f"     (These are conservative stops; timing of MAE vs MFE unknown.)")

    print("\n  4. Does 0.75 ATR behave like structural SL?")
    sim75 = sims[0.75]
    unchanged = (sim75["sim_pnl"] == sim75["pnl"]).sum()
    print(f"     Trades with unchanged outcome at 0.75A: "
          f"{unchanged:,}/{len(sim75):,} ({pct(unchanged,len(sim75)):.0f}%)")

    print("\n  5. Best tradeoff: EV vs drawdown")
    all_rows = [("struct", base_df["pnl"])]
    for stop_atr, sim in sims.items():
        all_rows.append((f"{stop_atr:.2f}A", sim["sim_pnl"]))
    print(f"     {'Stop':>8}  {'EV':>8}  {'MaxDD':>10}  {'PF':>5}  {'EV/DD ratio':>12}")
    for lbl, p in all_rows:
        dd = abs(max_dd(p))
        ratio = ev(p) / (dd / 1000) if dd > 0 else float("nan")
        print(f"     {lbl:>8}  {ev(p):>+8.1f}  {-dd:>+10,.0f}  {pf(p):>5.2f}  {ratio:>12.3f}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Loading trigger_C.parquet ...")
    df_all = pd.read_parquet(RESULTS / "trigger_C.parquet")
    df_all["entry_dt"] = pd.to_datetime(df_all["entry_ts"], unit="ns", utc=True)
    df_all["orig_arch"] = df_all.apply(classify_orig, axis=1)
    df_all["ym"]        = df_all["entry_dt"].dt.to_period("M").astype(str)

    # Date filter
    mask = (df_all["entry_dt"] >= START) & (df_all["entry_dt"] <= END)
    df   = df_all[mask].copy().reset_index(drop=True)
    print(f"  Total trigger C: {len(df_all):,}  In window: {len(df):,}")
    print(f"  Window: {START.date()} to {END.date()}")

    # Baseline stats
    base_metrics = metrics(
        df.assign(sim_pnl=df["pnl"], sim_stop_hit=False,
                  sim_uncertain=False, sim_exit=df["exit_reason"],
                  sim_arch=df["orig_arch"]),
        "struct"
    )

    # Simulations
    sims:  dict[float, pd.DataFrame] = {}
    rows:  list[dict]                = [base_metrics]
    for s in STOP_SIZES:
        sim = simulate_fixed_stop(df, s)
        sims[s] = sim
        rows.append(metrics(sim, s))

    report_summary(rows)
    report_loss_win(rows)
    report_composition(df, sims)
    report_monthly(df, sims)
    report_diagnostic(df, sims)

    sep("INTERPRETATION")
    best_ev  = max(rows, key=lambda r: r["ev"])
    best_lbl = "struct" if best_ev["stop_atr"] == "struct" else f"{best_ev['stop_atr']:.2f}A"
    print(f"\n  Best EV:            {best_lbl}  ({best_ev['ev']:+.1f}/trade)")
    best_dd  = min(rows, key=lambda r: abs(r["max_dd"]))
    best_lbl2= "struct" if best_dd["stop_atr"] == "struct" else f"{best_dd['stop_atr']:.2f}A"
    print(f"  Smallest max DD:    {best_lbl2}  ({best_dd['max_dd']:+,.0f})")
    print(f"\n  FlipExpansion survival rate under each fixed stop (conservative):")
    fexp_tot = (df["orig_arch"] == "FlipExpansion").sum()
    for s, sim in sims.items():
        surv = ((sim["orig_arch"] == "FlipExpansion") & (sim["sim_exit"] == "regime_flip")).sum()
        print(f"    {s:.2f}A: {pct(surv,fexp_tot):.0f}% of FlipExpansion survive")

    sep("DONE")


if __name__ == "__main__":
    main()
