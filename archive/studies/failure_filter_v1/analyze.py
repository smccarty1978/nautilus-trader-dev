"""Build failure-filter sweep economic + outcome-mix report."""

from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("studies/failure_filter_v1/results")
NT_ROOT = ROOT / "nt_runs"

YEARS = [2024, 2026]
LEVELS = ["baseline", "excl_top5", "excl_top10",
          "excl_top20", "excl_top30"]
STRATA = ["all", "long", "short",
          "T_0_90", "T_90_180", "T_180_300",
          "T_300_450", "T_450_600"]


def classify_exit(row, tol=0.05):
    d = row["direction"]
    atr = row["atr_at_signal"]
    if atr <= 0:
        return "unknown"
    m = (row["avg_px_close"] - row["avg_px_open"]) * d / atr
    if m >= 1.0 - tol:
        return "pt"
    if m <= -(1.0 - tol):
        return "sl"
    return "regime_exit"


def cost_adjusted(pos: pd.DataFrame) -> pd.Series:
    d = pos["direction"].values
    entry = pos["avg_px_open"].astype(float).values
    exit_ = pos["avg_px_close"].astype(float).values
    reason = pos["exit_reason"].values
    entry_slip = np.where(d == 1, 0.25, -0.25)
    slip_mask = np.isin(reason, ["sl", "regime_exit", "unknown"])
    exit_slip = np.where(slip_mask,
                           np.where(d == 1, -0.25, 0.25), 0.0)
    pnl = (((exit_ + exit_slip) - (entry + entry_slip))
             * d * 20.0 - 5.0)
    return pd.Series(pnl, index=pos.index)


def load_run(year: int, level: str) -> pd.DataFrame | None:
    d = NT_ROOT / f"{year}_{level}"
    pp = d / "positions.parquet"
    tp = d / "strategy_trades.parquet"
    if not pp.exists() or not tp.exists():
        return None
    pos = pd.read_parquet(pp).copy()
    tr = pd.read_parquet(tp)
    tr = tr[tr["entry_fill_price"].notna()].copy()
    tr = tr.sort_values("decision_ts_ns").reset_index(drop=True)
    pos["entry_ts_ns"] = pos["ts_opened"].astype("int64")
    pos = pos.sort_values("entry_ts_ns").reset_index(drop=True)
    n = min(len(pos), len(tr))
    pos = pos.iloc[:n].copy()
    pos["direction"] = tr["direction"].iloc[:n].values
    pos["atr_at_signal"] = tr["atr_at_signal"].iloc[:n].values
    pos["score"] = tr["score"].iloc[:n].values
    pos["checkpoint_s"] = tr["checkpoint_s"].iloc[:n].values
    pos["exit_reason"] = pos.apply(classify_exit, axis=1)
    pos["pnl_1tick"] = cost_adjusted(pos)
    return pos


def metrics(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) == 0:
        return {"n": 0}
    wins = s[s > 0]
    losses = s[s < 0]
    k = int(len(s) * 0.05)
    trim = (s.sort_values().iloc[k:len(s) - k].mean()
             if k * 2 < len(s) else np.nan)
    return {
        "n": len(s),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "trimmed": float(trim),
        "sum": float(s.sum()),
        "win_rate": float((s > 0).mean()),
        "pf": (float(wins.sum() / abs(losses.sum()))
                if len(losses) and losses.sum() != 0
                else float("inf")),
    }


def outcome_mix(df: pd.DataFrame) -> dict:
    if len(df) == 0:
        return {"pt_pct": np.nan, "sl_pct": np.nan,
                 "regime_pct": np.nan, "unknown_pct": np.nan}
    n = len(df)
    return {
        "pt_pct": (df["exit_reason"] == "pt").sum() / n,
        "sl_pct": (df["exit_reason"] == "sl").sum() / n,
        "regime_pct": (df["exit_reason"] == "regime_exit").sum() / n,
        "unknown_pct": (df["exit_reason"] == "unknown").sum() / n,
    }


def stratify(df: pd.DataFrame, stratum: str) -> pd.DataFrame:
    if stratum == "all":
        return df
    if stratum == "long":
        return df[df["direction"] == 1]
    if stratum == "short":
        return df[df["direction"] == -1]
    if stratum.startswith("T_"):
        lo, hi = stratum.split("_")[1:3]
        lo, hi = int(lo), int(hi)
        return df[(df["checkpoint_s"] >= lo)
                   & (df["checkpoint_s"] < hi if hi < 600
                       else df["checkpoint_s"] <= 600)]
    raise ValueError(stratum)


def _d(v):
    if v is None or pd.isna(v):
        return "—"
    if isinstance(v, float) and np.isinf(v):
        return "∞"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def _p(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{100 * v:.1f}%"


def main():
    rows = []
    for year in YEARS:
        for level in LEVELS:
            df = load_run(year, level)
            if df is None:
                rows.append({"year": year, "level": level,
                              "status": "missing"})
                continue
            for stratum in STRATA:
                sub = stratify(df, stratum)
                if len(sub) == 0:
                    continue
                m = metrics(sub["pnl_1tick"])
                mix = outcome_mix(sub)
                long_n = int((sub["direction"] == 1).sum())
                short_n = int((sub["direction"] == -1).sum())
                rows.append({
                    "year": year, "level": level,
                    "stratum": stratum,
                    **m, **mix,
                    "long_n": long_n, "short_n": short_n,
                    "long_pct": (long_n / m["n"]
                                  if m["n"] else np.nan),
                })

    df = pd.DataFrame(rows)
    df.to_parquet(ROOT / "filter_sweep_summary.parquet",
                    index=False)

    # Build report
    lines = []
    lines.append("# Failure-Filter Sweep — Final Report")
    lines.append("")
    lines.append("Label: `is_failure = 1 iff mfe_300s_atr<0.25 AND "
                  "pt100!=1` (SL/regime/unresolved with no traction).")
    lines.append("Mode: `exclude` — skip trades when failure score >= "
                  "threshold (val percentile).")
    lines.append("Cost model: $5 commission + 1-tick adverse entry + "
                  "1-tick exit slip on SL/regime.")
    lines.append("")

    for year in YEARS:
        lines.append(f"## {year} OOS — economics by filter level (ALL stratum)")
        lines.append("")
        lines.append("| Level | n | Mean $ | Median $ | Trim 5% | "
                      "PF | Win% | PT% | SL% | Regime% | Total $ |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
        for level in LEVELS:
            r = df[(df["year"] == year)
                    & (df["level"] == level)
                    & (df["stratum"] == "all")]
            if len(r) == 0 or r.iloc[0].get("n", 0) == 0:
                lines.append(f"| {level} | MISSING |")
                continue
            r = r.iloc[0]
            lines.append(
                f"| {level} | {int(r['n']):,} | {_d(r['mean'])} | "
                f"{_d(r['median'])} | {_d(r['trimmed'])} | "
                f"{r['pf']:.2f} | {_p(r['win_rate'])} | "
                f"{_p(r['pt_pct'])} | {_p(r['sl_pct'])} | "
                f"{_p(r['regime_pct'])} | {_d(r['sum'])} |")
        lines.append("")

    # Outcome mix shift comparison
    lines.append("## Outcome-mix shift — does the filter reduce "
                  "failures?")
    lines.append("")
    lines.append("Compare baseline vs each exclusion level on PT% / "
                  "SL% / Regime% — improvement means PT% rises and "
                  "SL%/Regime% drops.")
    lines.append("")
    for year in YEARS:
        lines.append(f"### {year}")
        lines.append("")
        lines.append("| Level | n | PT% | SL% | Regime% | "
                      "Δ PT pp | Δ SL pp | Δ Regime pp |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
        base = df[(df["year"] == year)
                   & (df["level"] == "baseline")
                   & (df["stratum"] == "all")]
        if len(base):
            base = base.iloc[0]
            for level in LEVELS:
                r = df[(df["year"] == year)
                        & (df["level"] == level)
                        & (df["stratum"] == "all")]
                if len(r) == 0:
                    continue
                r = r.iloc[0]
                d_pt = (r["pt_pct"] - base["pt_pct"]) * 100
                d_sl = (r["sl_pct"] - base["sl_pct"]) * 100
                d_re = (r["regime_pct"] - base["regime_pct"]) * 100
                lines.append(
                    f"| {level} | {int(r['n']):,} | "
                    f"{_p(r['pt_pct'])} | {_p(r['sl_pct'])} | "
                    f"{_p(r['regime_pct'])} | "
                    f"{d_pt:+.1f} | {d_sl:+.1f} | {d_re:+.1f} |")
        lines.append("")

    # Stratified
    lines.append("## Stratified — best filter per stratum × year")
    lines.append("")
    for year in YEARS:
        lines.append(f"### {year}")
        lines.append("")
        lines.append("| Stratum | Best level | n | Mean $ | "
                      "PF | Total $ |")
        lines.append("|---|---|--:|--:|--:|--:|")
        for stratum in STRATA:
            sub = df[(df["year"] == year)
                      & (df["stratum"] == stratum)]
            if len(sub) == 0:
                continue
            sub = sub[sub["n"].notna() & (sub["n"] > 0)]
            if len(sub) == 0:
                continue
            best = sub.loc[sub["mean"].idxmax()]
            lines.append(
                f"| {stratum} | {best['level']} | "
                f"{int(best['n']):,} | {_d(best['mean'])} | "
                f"{best['pf']:.2f} | {_d(best['sum'])} |")
        lines.append("")

    # Verdict
    lines.append("## Verdict")
    lines.append("")
    # Was the filter helpful? Compare best non-baseline mean to baseline mean
    any_better = False
    for year in YEARS:
        base_r = df[(df["year"] == year)
                     & (df["level"] == "baseline")
                     & (df["stratum"] == "all")]
        if not len(base_r):
            continue
        base_mean = base_r.iloc[0]["mean"]
        for level in LEVELS:
            if level == "baseline":
                continue
            r = df[(df["year"] == year)
                    & (df["level"] == level)
                    & (df["stratum"] == "all")]
            if not len(r):
                continue
            r = r.iloc[0]
            if r["mean"] > base_mean and r["pf"] > 1.10:
                any_better = True
                lines.append(
                    f"- {year} {level}: PF {r['pf']:.2f} "
                    f"({_d(r['mean'])}/trade) "
                    f"beats baseline ({_d(base_mean)}/trade)")
    if any_better:
        lines.append("")
        lines.append("**Filter shows positive effect on at least one "
                      "year. Worth deeper analysis.**")
    else:
        lines.append("**Filter does not produce profitable strategy "
                      "on either year. The signal exists in classification "
                      "but doesn't translate to economic improvement after "
                      "costs.**")

    out = ROOT / "FINAL_REPORT.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report: {out}")

    print()
    print("=== Quick console summary ===")
    print(df[df["stratum"] == "all"][
        ["year", "level", "n", "mean", "pf", "win_rate",
          "pt_pct", "regime_pct", "sum"]].to_string(
        index=False, float_format=lambda x: f"{x:.4f}"))


if __name__ == "__main__":
    main()
