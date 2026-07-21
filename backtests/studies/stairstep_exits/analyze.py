"""Stair-step exit matrix — metrics & the key question.

Applies the cost model (gross / primary / stress) to the replayed ideal fills,
then reports per-version metrics + the loser-tail vs runner-tail comparison that
answers: can stair-step protection cut the loser tail WITHOUT cutting the
+2/+3 ATR runner tail?

    python studies/stairstep_exits/analyze.py
"""
from __future__ import annotations
import os, sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root)); os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np, pandas as pd

RES = Path("studies/stairstep_exits/results")
YEARS = (2021, 2022, 2023, 2024)
MULT = 20.0
TICK = 0.25
TICK_VAL = TICK * MULT          # $ per tick = 5
COMMISSION = 5.0
# slippage (ticks) by exit reason; entry slippage = 0 (primary)
SLIP_PRIMARY = {"stop": 0.5, "regime": 0.5, "gate30": 0.5, "gate60": 0.5,
                "pt": 0.0, "end_of_data": 0.5}
SLIP_STRESS = {k: (0.0 if k == "pt" else 1.0) for k in SLIP_PRIMARY}
VERSION_ORDER = ["V0_regime", "BR10", "BR15", "V1_ladder", "V2_gate_ladder",
                 "V3_struct_1m", "V3_struct_5s", "V4D1_ma_1m", "V4D1_ma_5s",
                 "V4D2_ma_1m", "V4D2_ma_5s", "V5_hybrid_1m", "V5_hybrid_5s"]
OUT = []
def P(s=""): OUT.append(str(s)); print(s)


def load():
    parts = []
    for y in YEARS:
        p = RES / f"exit_outcomes_{y}.parquet"
        if p.exists():
            parts.append(pd.read_parquet(p))
    df = pd.concat(parts, ignore_index=True)
    df["gross_pts"] = df["direction"] * (df["exit_px_ideal"] - df["entry_px"])
    df["gross_atr"] = df["gross_pts"] / df["atr_at_entry"]
    df["mfe_atr"] = df["max_mfe_pts"] / df["atr_at_entry"]
    df["reached2"] = df["mfe_atr"] >= 2.0
    for tag, slip in [("primary", SLIP_PRIMARY), ("stress", SLIP_STRESS)]:
        s = df["exit_reason"].map(slip).fillna(0.5)
        df[f"net_{tag}"] = (df["gross_pts"] * MULT
                            - s * TICK_VAL - COMMISSION)
    df["gross_dol"] = df["gross_pts"] * MULT
    return df


def pf(x):
    w = x[x > 0].sum(); ls = -x[x < 0].sum()
    return (w / ls) if ls > 0 else np.inf


def max_dd(pnl_series):
    eq = np.cumsum(pnl_series)
    peak = np.maximum.accumulate(eq)
    return float((eq - peak).min()) if len(eq) else 0.0


def metrics(g):
    net = g["net_primary"].to_numpy()
    g = g.sort_values("entry_ts")
    capt = g["gross_atr"]
    mfe_pos = g[g["max_mfe_pts"] > 0]
    cap_ratio = (mfe_pos["gross_pts"] / mfe_pos["max_mfe_pts"]).median()
    return {
        "n": len(g),
        "net_total": g["net_primary"].sum(),
        "net_per_tr": g["net_primary"].mean(),
        "gross_per_tr": g["gross_dol"].mean(),
        "stress_per_tr": g["net_stress"].mean(),
        "gross_PF": pf(g["gross_dol"]),
        "net_PF": pf(g["net_primary"]),
        "mean_atr": capt.mean(),
        "med_atr": capt.median(),
        "max_dd": max_dd(g.sort_values("entry_ts")["net_primary"].to_numpy()),
        "avg_hold_s": g["hold_s"].mean(),
        "pct_stop": (g.exit_reason == "stop").mean(),
        "pct_regime": (g.exit_reason == "regime").mean(),
        "pct_pt": (g.exit_reason == "pt").mean(),
        "pct_gate": g.exit_reason.isin(["gate30", "gate60"]).mean(),
        "reach2": g["reached2"].mean(),
        "capt2": (g["gross_atr"] >= 2.0).mean(),
        "capt3": (g["gross_atr"] >= 3.0).mean(),
        "mfe_capture": cap_ratio,
        "med_giveback_atr": ((g["max_mfe_pts"] - g["gross_pts"]) / g["atr_at_entry"]).median(),
        # tails
        "loser_p5_atr": capt.quantile(0.05),
        "loser_bot10_atr": capt[capt <= capt.quantile(0.10)].mean(),
        "runner_top10_atr": capt[capt >= capt.quantile(0.90)].mean(),
    }


def matrix_table(df, title):
    P(f"\n## {title}\n")
    rows = []
    for v in VERSION_ORDER:
        g = df[df.version == v]
        if len(g) == 0:
            continue
        m = metrics(g); m["version"] = v; rows.append(m)
    M = pd.DataFrame(rows).set_index("version")
    cols = ["n", "net_per_tr", "gross_per_tr", "stress_per_tr", "net_PF",
            "gross_PF", "med_atr", "max_dd", "avg_hold_s", "pct_stop",
            "pct_regime", "pct_pt", "pct_gate", "reach2", "capt2", "capt3",
            "mfe_capture", "med_giveback_atr", "loser_bot10_atr",
            "runner_top10_atr"]
    hdr = ["version"] + cols
    P("| " + " | ".join(hdr) + " |")
    P("| " + " | ".join("---" for _ in hdr) + " |")
    for v, r in M.iterrows():
        def f(x, k):
            if k in ("n",): return f"{int(x):,}"
            if k in ("net_per_tr", "gross_per_tr", "stress_per_tr"): return f"{x:+.1f}"
            if k in ("net_total", "max_dd"): return f"{x:+,.0f}"
            if k in ("net_PF", "gross_PF", "mfe_capture"): return f"{x:.2f}"
            if k in ("med_atr", "med_giveback_atr", "loser_bot10_atr", "runner_top10_atr"): return f"{x:+.2f}"
            if k in ("avg_hold_s",): return f"{x:.0f}"
            if k.startswith("pct_") or k in ("reach2", "capt2", "capt3"): return f"{x:.0%}"
            return f"{x:.2f}"
        P("| " + v + " | " + " | ".join(f(r[k], k) for k in cols) + " |")
    return M


def main():
    df = load()
    P("# Stair-Step Exit Comparison — Results\n")
    P(f"NQ `NQ.v.0` 2021-2024, 1s-OHLC execution, safe-replay fills (0 phantom "
      f"by construction). Cost: PRIMARY = entry 0 / exit 0.5 tick / PT 0 / $5 RT. "
      f"STRESS = exit 1.0 tick. Warmed entries only.\n")
    df = df[df.warmed_up].copy()
    n_entries = df.drop_duplicates("entry_id").shape[0]
    P(f"Entries: {n_entries:,} (A={df[df.population=='A'].drop_duplicates('entry_id').shape[0]:,}, "
      f"B={df[df.population=='B'].drop_duplicates('entry_id').shape[0]:,}). "
      f"cat-invalid-at-entry (V0): {df[df.version=='V0_regime']['cat_invalid_at_entry'].mean():.1%}.\n")

    matrix_table(df[df.population == "A"], "Population A (raw flips) — all sides")
    matrix_table(df[df.population == "B"], "Population B (bar1-confirmed) — all sides")

    P("\n## The key question: loser tail vs runner tail (Population A)\n")
    P("Cut the loser tail (bottom-10% mean, less negative = better) WITHOUT "
      "cutting the runner tail (% captured +2/+3 ATR, top-10% mean)?\n")
    base = metrics(df[(df.population == "A") & (df.version == "V0_regime")])
    P("| version | net/tr | loser bot10 (ATR) | capt+2 | capt+3 | runner top10 (ATR) | giveback (ATR) |")
    P("| --- | --- | --- | --- | --- | --- | --- |")
    for v in VERSION_ORDER:
        g = df[(df.population == "A") & (df.version == v)]
        if len(g) == 0: continue
        m = metrics(g)
        P(f"| {v} | {m['net_per_tr']:+.1f} | {m['loser_bot10_atr']:+.2f} | "
          f"{m['capt2']:.0%} | {m['capt3']:.0%} | {m['runner_top10_atr']:+.2f} | "
          f"{m['med_giveback_atr']:+.2f} |")

    # long-only and per-year cuts for the leaders
    P("\n## Long-only cut (Population A)\n")
    matrix_table(df[(df.population == "A") & (df.direction == 1)],
                 "Population A — LONG only")

    P("\n## Per-year net $/tr (Population A, primary cost)\n")
    piv = (df[df.population == "A"].groupby(["version", "year"])["net_primary"]
           .mean().unstack())
    piv = piv.reindex([v for v in VERSION_ORDER if v in piv.index])
    P("| version | " + " | ".join(str(y) for y in piv.columns) + " |")
    P("| " + " | ".join("---" for _ in range(len(piv.columns) + 1)) + " |")
    for v, r in piv.iterrows():
        P(f"| {v} | " + " | ".join(f"{x:+.1f}" for x in r) + " |")

    out = RES / "stairstep_results.md"
    out.write_text("\n".join(OUT), encoding="utf-8")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
