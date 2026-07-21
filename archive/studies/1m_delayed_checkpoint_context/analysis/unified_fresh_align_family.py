"""Study 2 — Unified real-time fresh 5m flip-to-align family.

For each root 1m signal, find the FIRST T in {60, 120, ..., 600} where:
  - regime_5m_aligned_T == 1
  - regime_5m_aligned at prior T (T-60, or T=0 for T=60) == 0
  - fillable_at_T == 1 (implies alive_at_T)

If no such T exists by 600s, no trade.

Primary bracket: PT=1.0 / SL=1.0
Secondary bracket: PT=1.5 / SL=1.0

Reports: pooled stats, year split, session split, direction split, checkpoint
distribution.
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

CHECKPOINTS = [60, 120, 180, 240, 300, 360, 420, 480, 540, 600]
# For T=60 the "prior" is T=0 (signal time). For others, prior is T-60.
PRIOR = {T: (T - 60 if T > 60 else 0) for T in CHECKPOINTS}


def build_entry_table(df: pd.DataFrame) -> pd.DataFrame:
    """For each trade, find entry T (first fresh-align event) or NaN.

    Returns df indexed by trade with columns:
      entry_T, entry_pt100, entry_pt150, entry_pt200, entry_pt300,
      entry_mfe, entry_mae, entry_pnl, plus context columns.
    """
    n = len(df)
    entry_T = np.full(n, np.nan)
    # Track which trades already have an entry
    assigned = np.zeros(n, dtype=bool)

    for T in CHECKPOINTS:
        tag = f"{T:03d}"
        prior_tag = f"{PRIOR[T]:03d}"
        mask = (
            (df[f"regime_5m_aligned_T_{tag}"] == 1)
            & (df[f"regime_5m_aligned_T_{prior_tag}"] == 0)
            & (df[f"fillable_at_T_{tag}"] == 1)
        )
        new = mask.values & ~assigned
        entry_T[new] = T
        assigned |= new

    # Build result df
    res = df.copy()
    res["entry_T"] = entry_T

    # Pull the bracket/MFE/MAE/PnL from the entry_T checkpoint
    for col_base in [
        "forward_pt100_before_sl100",
        "forward_pt150_before_sl100",
        "forward_pt200_before_sl100",
        "forward_pt300_before_sl150",
        "forward_peak_mfe_atr",
        "forward_peak_mae_atr",
        "forward_regime_pnl_dollars",
    ]:
        out = np.full(n, np.nan)
        for T in CHECKPOINTS:
            tag = f"{T:03d}"
            sel = res["entry_T"].values == T
            if sel.any():
                out[sel] = df[f"{col_base}_T_{tag}"].values[sel]
        res[f"entry_{col_base}"] = out

    # micro_aligned / micro_opposing at entry T (for context)
    for feat in ["micro_aligned", "micro_opposing"]:
        out = np.full(n, np.nan)
        for T in CHECKPOINTS:
            tag = f"{T:03d}"
            sel = res["entry_T"].values == T
            if sel.any():
                out[sel] = df[f"{feat}_T_{tag}"].values[sel]
        res[f"entry_{feat}"] = out

    return res


def bracket_stats(sub: pd.DataFrame) -> dict:
    n = len(sub)
    if n == 0:
        return {"n": 0}
    pnl = sub["entry_forward_regime_pnl_dollars"]
    mfe = sub["entry_forward_peak_mfe_atr"]
    mae = sub["entry_forward_peak_mae_atr"]
    ratio = mfe / mae.replace(0, np.nan)

    wr = (pnl > 0).mean() * 100
    avg = pnl.mean()
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = gp / gl if gl > 0 else float("inf")

    pt100 = (sub["entry_forward_pt100_before_sl100"] == 1).sum() / n * 100
    pt150 = (sub["entry_forward_pt150_before_sl100"] == 1).sum() / n * 100
    pt200 = (sub["entry_forward_pt200_before_sl100"] == 1).sum() / n * 100
    pt300 = (sub["entry_forward_pt300_before_sl150"] == 1).sum() / n * 100

    return {
        "n": n,
        "wr%": wr, "avg$": avg, "pf": pf,
        "med_mfe": mfe.median(), "med_mae": mae.median(),
        "med_ratio": ratio.median(),
        "pt100%": pt100, "pt150%": pt150,
        "pt200%": pt200, "pt300%": pt300,
    }


def ev_per_trade(pt_pct, pt_atr, sl_atr, neither_avg_dollars,
                 atr_dollars):
    """Naive EV: pt_atr × pt% - sl_atr × sl% for resolved trades,
    plus neither_avg for unresolved. Returns dollars per trade (gross).
    atr_dollars = average ATR in $ per R.
    """
    # Fraction neither
    # Not available from this func; caller should use bracket_stats + pnl data.
    pass  # simpler to compute inline below


def fmt_pf(pf):
    if pd.isna(pf):
        return " n/a"
    if pf == float("inf"):
        return " inf"
    return f"{pf:>4.2f}"


def fmt_row(label, s, width=28):
    if s["n"] == 0:
        return f"  {label:<{width}} (n=0)"
    return (
        f"  {label:<{width}} "
        f"N={s['n']:>6,} WR={s['wr%']:>5.1f}% "
        f"Avg=${s['avg$']:>+7.1f} PF={fmt_pf(s['pf'])} "
        f"| pt100={s['pt100%']:>5.1f}% pt150={s['pt150%']:>5.1f}% "
        f"pt200={s['pt200%']:>5.1f}% "
        f"| MFE={s['med_mfe']:>4.2f} MAE={s['med_mae']:>4.2f} "
        f"R={s['med_ratio']:>4.2f}"
    )


def main():
    df = pd.read_parquet(
        "studies/1m_delayed_checkpoint_context/results/trades_all.parquet")
    print(f"Loaded {len(df):,} trades")

    entry = build_entry_table(df)
    fam = entry[entry["entry_T"].notna()].copy()
    n_total = len(df)
    n_fam = len(fam)
    print(f"  Fresh-align family members: {n_fam:,} "
          f"({n_fam/n_total*100:.2f}% of all signals)")

    out_lines = []
    out_lines.append("=" * 160)
    out_lines.append(
        "STUDY 2 — UNIFIED REAL-TIME FRESH 5m FLIP-TO-ALIGN FAMILY")
    out_lines.append(
        "  Entry = first T in {60,120,...,600} where aligned_T=1 AND "
        "aligned_prior_T=0 AND fillable_T=1")
    out_lines.append(
        f"  Population: {n_fam:,} of {n_total:,} "
        f"({n_fam/n_total*100:.2f}%)")
    out_lines.append("=" * 160)

    # Section 1: Total sample
    out_lines.append("\n--- 1. TOTAL SAMPLE ---")
    s = bracket_stats(fam)
    out_lines.append(fmt_row("FRESH-ALIGN FAMILY", s))

    # Section 2: Year-by-year
    out_lines.append("\n--- 2. YEAR-BY-YEAR ---")
    out_lines.append(
        f"  {'Year':>6} {'n':>6} {'WR%':>6} {'Avg$':>8} {'PF':>5} "
        f"{'pt100%':>7} {'pt150%':>7} {'MFE':>5} {'MAE':>5}")
    for y in sorted(fam["year"].unique()):
        sub = fam[fam["year"] == y]
        r = bracket_stats(sub)
        out_lines.append(
            f"  {int(y):>6} {r['n']:>6,} {r['wr%']:>5.1f}% "
            f"${r['avg$']:>+7.1f} {fmt_pf(r['pf'])} "
            f"{r['pt100%']:>6.1f}% {r['pt150%']:>6.1f}% "
            f"{r['med_mfe']:>5.2f} {r['med_mae']:>5.2f}")

    # Section 3: Session split
    out_lines.append("\n--- 3. SESSION SPLIT ---")
    for sess_val, sess_lbl in [(1, "RTH"), (0, "ETH")]:
        sub = fam[fam["is_rth"] == sess_val]
        r = bracket_stats(sub)
        out_lines.append(fmt_row(sess_lbl, r, width=8))

    # Section 4: Direction split
    out_lines.append("\n--- 4. DIRECTION SPLIT ---")
    for d_val, d_lbl in [(1, "LONG"), (-1, "SHORT")]:
        sub = fam[fam["signal_direction"] == d_val]
        r = bracket_stats(sub)
        out_lines.append(fmt_row(d_lbl, r, width=8))

    # Section 5: Checkpoint distribution
    out_lines.append("\n--- 5. CHECKPOINT DISTRIBUTION (descriptive) ---")
    out_lines.append(
        f"  {'T':>4} {'n':>6} {'%pop':>6} "
        f"{'WR%':>6} {'Avg$':>8} {'PF':>5} "
        f"{'pt100%':>7} {'pt150%':>7}")
    for T in CHECKPOINTS:
        sub = fam[fam["entry_T"] == T]
        r = bracket_stats(sub)
        if r["n"] == 0:
            out_lines.append(f"  {T:>3}s (none)")
            continue
        out_lines.append(
            f"  {T:>3}s {r['n']:>6,} {r['n']/n_fam*100:>5.1f}% "
            f"{r['wr%']:>5.1f}% ${r['avg$']:>+7.1f} {fmt_pf(r['pf'])} "
            f"{r['pt100%']:>6.1f}% {r['pt150%']:>6.1f}%")

    # Bracket EV summary
    out_lines.append("\n--- BRACKET EV SUMMARY ---")
    out_lines.append(
        "  Naive EV per trade (PT% × PT_atr − SL% × SL_atr) for resolved "
        "trades.")
    out_lines.append(
        "  Gross R: pt100/sl100 @ 1:1, pt150/sl100 @ 1.5:1")
    s_all = bracket_stats(fam)
    for bracket_label, pt_col, pt_r, sl_r in [
        ("PT=1.0/SL=1.0", "pt100%", 1.0, 1.0),
        ("PT=1.5/SL=1.0", "pt150%", 1.5, 1.0),
    ]:
        pt_pct = s_all[pt_col] / 100
        # For unresolved (neither), conservatively use regime-exit avg
        # bracket-only EV (excluding neither):
        # EV_R = pt_r × pt_pct − sl_r × (resolved_fraction − pt_pct)
        # But we don't know sl_pct directly; compute from raw:
        col_pt = "entry_forward_pt100_before_sl100" if pt_col == "pt100%" \
            else "entry_forward_pt150_before_sl100"
        pt_first = (fam[col_pt] == 1).sum()
        sl_first = (fam[col_pt] == 0).sum()
        neither = fam[col_pt].isna().sum()
        total = pt_first + sl_first + neither
        resolved = pt_first + sl_first
        if resolved > 0:
            ev_resolved_R = (
                pt_r * pt_first / resolved - sl_r * sl_first / resolved)
        else:
            ev_resolved_R = np.nan
        ev_all_R = (pt_r * pt_first - sl_r * sl_first) / total
        out_lines.append(
            f"  {bracket_label}: "
            f"pt_first={pt_first:>5,} sl_first={sl_first:>5,} "
            f"neither={neither:>5,} "
            f"| EV_resolved={ev_resolved_R:>+5.3f}R "
            f"EV_all={ev_all_R:>+5.3f}R")
        out_lines.append(
            f"    (neither trades resolve at regime exit; their PnL is "
            f"captured in regime_exit avg$ above)")

    # Save
    out = "\n".join(out_lines)
    print(out)

    log_path = Path("studies/1m_delayed_checkpoint_context/results/"
                     "unified_fresh_align_family.log")
    log_path.write_text(out, encoding="utf-8")

    # Save family parquet for drill-downs
    fam.to_parquet(
        "studies/1m_delayed_checkpoint_context/results/"
        "unified_fresh_align_family.parquet", index=False)

    print(f"\n  Saved log:     {log_path}")
    print(f"  Saved parquet: unified_fresh_align_family.parquet")


if __name__ == "__main__":
    main()
