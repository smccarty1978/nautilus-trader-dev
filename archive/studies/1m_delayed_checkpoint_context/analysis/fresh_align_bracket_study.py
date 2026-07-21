"""Study 1 — Real-time fresh 5m flip-to-align, bracket-first evaluation.

Population per checkpoint T in {30, 60, ..., 600}:
  - regime_5m_aligned_T == 1 (aligned now)
  - regime_5m_aligned at ALL prior checkpoints (0..T-30) == 0 (never aligned before)
  - alive_at_T == 1 (implied by fillable)
  - fillable_at_T == 1 (entered at T+30s fill time)

This isolates the FIRST real-time 5m flip-to-align event for each trade —
strictly no look-ahead.

Metrics (bracket-first):
  n_fillable
  % pt100_before_sl100  (of fillable)
  % pt150_before_sl100
  % pt200_before_sl100
  % pt300_before_sl150
  median forward_peak_mfe_atr
  median forward_peak_mae_atr
  median mfe/mae ratio
  regime-exit avg$ (secondary context)
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np

CHECKPOINTS = list(range(30, 601, 30))  # 30, 60, ..., 600


def build_fresh_align_mask(df: pd.DataFrame, T: int) -> pd.Series:
    """Mask for trades that FIRST align at T.

    - regime_5m_aligned_T == 1
    - regime_5m_aligned at all priors (0..T-30) == 0 (strict)
    - fillable_at_T == 1
    """
    tag = f"{T:03d}"
    aligned_now = df[f"regime_5m_aligned_T_{tag}"] == 1
    fillable = df[f"fillable_at_T_{tag}"] == 1

    prior_Ts = list(range(0, T, 30))
    prior_cols = [f"regime_5m_aligned_T_{p:03d}" for p in prior_Ts]
    # Require strict 0 at all priors (no NaN, no 1).
    # Since fillable@T=1 implies alive all the way, priors shouldn't be NaN.
    never_before = (df[prior_cols] == 0).all(axis=1)

    return aligned_now & never_before & fillable


def fresh_align_stats(sub: pd.DataFrame, T: int) -> dict:
    """Bracket-first stats for the fresh-align population at T."""
    tag = f"{T:03d}"
    n = len(sub)
    if n == 0:
        return {
            "T": T, "n": 0,
            "pt100%": np.nan, "pt150%": np.nan,
            "pt200%": np.nan, "pt300%": np.nan,
            "med_mfe": np.nan, "med_mae": np.nan, "med_ratio": np.nan,
            "regime_avg$": np.nan, "regime_wr%": np.nan,
            "regime_pf": np.nan,
        }

    pt100 = (sub[f"forward_pt100_before_sl100_T_{tag}"] == 1).sum() / n * 100
    pt150 = (sub[f"forward_pt150_before_sl100_T_{tag}"] == 1).sum() / n * 100
    pt200 = (sub[f"forward_pt200_before_sl100_T_{tag}"] == 1).sum() / n * 100
    pt300 = (sub[f"forward_pt300_before_sl150_T_{tag}"] == 1).sum() / n * 100

    mfe = sub[f"forward_peak_mfe_atr_T_{tag}"]
    mae = sub[f"forward_peak_mae_atr_T_{tag}"]
    ratio = mfe / mae.replace(0, np.nan)

    pnl = sub[f"forward_regime_pnl_dollars_T_{tag}"]
    wr = (pnl > 0).mean() * 100
    avg = pnl.mean()
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = gp / gl if gl > 0 else float("inf")

    return {
        "T": T, "n": n,
        "pt100%": pt100, "pt150%": pt150,
        "pt200%": pt200, "pt300%": pt300,
        "med_mfe": mfe.median(),
        "med_mae": mae.median(),
        "med_ratio": ratio.median(),
        "regime_avg$": avg,
        "regime_wr%": wr,
        "regime_pf": pf,
    }


def baseline_stats(df: pd.DataFrame, T: int) -> dict:
    """Baseline: all fillable at T (no alignment filter) — for context."""
    tag = f"{T:03d}"
    sub = df[df[f"fillable_at_T_{tag}"] == 1]
    return fresh_align_stats(sub, T)


def fmt_pf(pf):
    if pd.isna(pf):
        return "  n/a"
    if pf == float("inf"):
        return "  inf"
    return f"{pf:>5.2f}"


def main():
    df = pd.read_parquet(
        "studies/1m_delayed_checkpoint_context/results/trades_all.parquet")
    print(f"Loaded {len(df):,} trades")

    out_lines = []
    out_lines.append("=" * 155)
    out_lines.append("STUDY 1 — FRESH REAL-TIME 5m FLIP-TO-ALIGN (T=30..600)")
    out_lines.append(
        "  Population: aligned@T=1, ALL prior checkpoints @0, "
        "fillable@T=1, first such event")
    out_lines.append(
        "  Bracket-first evaluation. regime-exit avg$ shown as context only.")
    out_lines.append("=" * 155)
    out_lines.append("")

    # Fresh-align table
    rows_fa = []
    rows_bl = []
    for T in CHECKPOINTS:
        mask = build_fresh_align_mask(df, T)
        sub = df[mask]
        r_fa = fresh_align_stats(sub, T)
        rows_fa.append(r_fa)
        r_bl = baseline_stats(df, T)
        rows_bl.append(r_bl)

    # Header
    out_lines.append(
        f"  {'T':>4} {'n':>6}  "
        f"{'pt100%':>7} {'pt150%':>7} {'pt200%':>7} {'pt300%':>7}  "
        f"{'mfe':>5} {'mae':>5} {'ratio':>5}  "
        f"{'reg_WR%':>7} {'reg_avg$':>9} {'reg_PF':>6}"
    )
    out_lines.append("  FRESH-ALIGN population:")
    out_lines.append("  " + "-" * 109)
    for r in rows_fa:
        if r["n"] == 0:
            out_lines.append(f"  {r['T']:>4}s (n=0)")
            continue
        out_lines.append(
            f"  {r['T']:>3}s {r['n']:>6,}  "
            f"{r['pt100%']:>6.1f}% {r['pt150%']:>6.1f}% "
            f"{r['pt200%']:>6.1f}% {r['pt300%']:>6.1f}%  "
            f"{r['med_mfe']:>5.2f} {r['med_mae']:>5.2f} "
            f"{r['med_ratio']:>5.2f}  "
            f"{r['regime_wr%']:>6.1f}% "
            f"${r['regime_avg$']:>+8.1f} "
            f"{fmt_pf(r['regime_pf'])}"
        )

    out_lines.append("")
    out_lines.append("  BASELINE (all fillable @ T, for contrast):")
    out_lines.append("  " + "-" * 109)
    for r in rows_bl:
        out_lines.append(
            f"  {r['T']:>3}s {r['n']:>6,}  "
            f"{r['pt100%']:>6.1f}% {r['pt150%']:>6.1f}% "
            f"{r['pt200%']:>6.1f}% {r['pt300%']:>6.1f}%  "
            f"{r['med_mfe']:>5.2f} {r['med_mae']:>5.2f} "
            f"{r['med_ratio']:>5.2f}  "
            f"{r['regime_wr%']:>6.1f}% "
            f"${r['regime_avg$']:>+8.1f} "
            f"{fmt_pf(r['regime_pf'])}"
        )

    # Delta (fresh-align - baseline)
    out_lines.append("")
    out_lines.append(
        "  DELTA vs baseline (fresh-align MINUS baseline, positive = edge):")
    out_lines.append("  " + "-" * 109)
    for fa, bl in zip(rows_fa, rows_bl):
        if fa["n"] == 0:
            continue
        out_lines.append(
            f"  {fa['T']:>3}s {fa['n']:>6,}  "
            f"{fa['pt100%']-bl['pt100%']:>+6.1f}pp "
            f"{fa['pt150%']-bl['pt150%']:>+6.1f}pp "
            f"{fa['pt200%']-bl['pt200%']:>+6.1f}pp "
            f"{fa['pt300%']-bl['pt300%']:>+6.1f}pp   "
            f"{fa['med_mfe']-bl['med_mfe']:>+5.2f} "
            f"{fa['med_mae']-bl['med_mae']:>+5.2f} "
            f"{fa['med_ratio']-bl['med_ratio']:>+5.2f}  "
            f"{fa['regime_wr%']-bl['regime_wr%']:>+6.1f}pp "
            f"${fa['regime_avg$']-bl['regime_avg$']:>+8.1f}"
        )

    # Save
    out = "\n".join(out_lines)
    print(out)
    log_path = Path("studies/1m_delayed_checkpoint_context/results/"
                     "fresh_align_bracket_study.log")
    log_path.write_text(out, encoding="utf-8")

    # Also save parquet for drill-downs later
    pd.DataFrame(rows_fa).to_parquet(
        "studies/1m_delayed_checkpoint_context/results/"
        "fresh_align_by_T.parquet", index=False)
    pd.DataFrame(rows_bl).to_parquet(
        "studies/1m_delayed_checkpoint_context/results/"
        "fresh_align_baseline_by_T.parquet", index=False)

    print(f"\n  Saved log: {log_path}")


if __name__ == "__main__":
    main()
