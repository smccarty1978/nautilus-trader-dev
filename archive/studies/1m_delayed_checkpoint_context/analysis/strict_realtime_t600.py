"""Path 3 — strict real-time T=600 filter analysis.

All groups evaluated using ONLY information knowable at T=600 observation
or before. Forward metrics from T=600 fill (signal_time + 630s).

Groups:
  G1: aligned@600 (regime_5m_aligned_T_600 == 1) — all candidates
  G2: aligned@600 AND fillable_at_T_600 == 1 — actually entered
  G3: NOT aligned@600 AND fillable_at_T_600 == 1
  G4: never aligned T=0..600 AND fillable_at_T_600 == 1
  G5: baseline — fillable_at_T_600 == 1 (everyone who entered at 630s)

For survivors: split by RTH/ETH, LONG/SHORT, micro_aligned/opposing/neither.
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

T = 600
TAG = "600"


def stats(sub: pd.DataFrame, require_fillable: bool = True) -> dict:
    """Compute N, WR, avg$, PF, MFE, MAE, pt200%, pt300% for a subset.

    If require_fillable, only fillable trades contribute to forward metrics
    (non-fillable have NaN forward fields by design).
    """
    n_total = len(sub)
    if require_fillable:
        s = sub[sub[f"fillable_at_T_{TAG}"] == 1]
    else:
        s = sub
    n_fill = int((sub[f"fillable_at_T_{TAG}"] == 1).sum())
    n = len(s)
    if n == 0:
        return {
            "n_total": n_total, "n_fill": n_fill, "n": 0,
            "wr%": np.nan, "avg$": np.nan, "pf": np.nan,
            "med_mfe": np.nan, "med_mae": np.nan,
            "pt200%": np.nan, "pt300%": np.nan,
        }
    pnl = s[f"forward_regime_pnl_dollars_T_{TAG}"]
    mfe = s[f"forward_peak_mfe_atr_T_{TAG}"]
    mae = s[f"forward_peak_mae_atr_T_{TAG}"]
    wr = (pnl > 0).mean() * 100
    avg = pnl.mean()
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = gp / gl if gl > 0 else float("inf")
    pt200 = (s[f"forward_pt200_before_sl100_T_{TAG}"] == 1).sum() / n * 100
    pt300 = (s[f"forward_pt300_before_sl150_T_{TAG}"] == 1).sum() / n * 100
    return {
        "n_total": n_total, "n_fill": n_fill, "n": n,
        "wr%": wr, "avg$": avg, "pf": pf,
        "med_mfe": mfe.median(), "med_mae": mae.median(),
        "pt200%": pt200, "pt300%": pt300,
    }


def fmt_pf(pf):
    if pd.isna(pf):
        return "  n/a"
    if pf == float("inf"):
        return "  inf"
    return f"{pf:>5.2f}"


def fmt_row(label, s):
    if s["n"] == 0:
        return f"  {label:<42} N_total={s['n_total']:>6,}  (no fillable)"
    return (
        f"  {label:<42} "
        f"N_total={s['n_total']:>6,} N_fill={s['n_fill']:>6,} "
        f"WR={s['wr%']:>5.1f}% Avg=${s['avg$']:>+7.1f} "
        f"PF={fmt_pf(s['pf'])} "
        f"MFE={s['med_mfe']:>4.2f} MAE={s['med_mae']:>4.2f} "
        f"pt200={s['pt200%']:>5.1f}% pt300={s['pt300%']:>5.1f}%"
    )


def get_groups(df: pd.DataFrame):
    aligned_at_600 = df[f"regime_5m_aligned_T_{TAG}"] == 1
    fillable = df[f"fillable_at_T_{TAG}"] == 1
    # Never aligned through 600: all checkpoints T=0..600 != 1
    cp_cols = [f"regime_5m_aligned_T_{T:03d}" for T in range(0, 601, 30)]
    never_aligned_thru_600 = df[cp_cols].ne(1).all(axis=1)

    return [
        ("G1: aligned@600 (all candidates)",
            df[aligned_at_600]),
        ("G2: aligned@600 AND fillable",
            df[aligned_at_600 & fillable]),
        ("G3: NOT aligned@600 AND fillable",
            df[~aligned_at_600 & fillable]),
        ("G4: NEVER aligned T=0..600 AND fillable",
            df[never_aligned_thru_600 & fillable]),
        ("G5: baseline (all fillable @ 600)",
            df[fillable]),
    ]


def main():
    df = pd.read_parquet(
        "studies/1m_delayed_checkpoint_context/results/trades_all.parquet")
    print(f"Loaded {len(df):,} trades")

    out_lines = []
    out_lines.append("=" * 150)
    out_lines.append(
        "PATH 3 — STRICT REAL-TIME T=600 ANALYSIS")
    out_lines.append(
        "  All entry conditions evaluated using ONLY information "
        "knowable at T=600 observation. No flip_cp filter.")
    out_lines.append(
        "  Forward metrics from T=600 fill (signal_time + 630s). "
        "Stats use fillable trades only.")
    out_lines.append("=" * 150)
    out_lines.append("")

    groups = get_groups(df)
    out_lines.append("--- Top-level groups ---")
    for label, sub in groups:
        s = stats(sub, require_fillable=True)
        out_lines.append(fmt_row(label, s))

    # Identify positive groups for splits
    out_lines.append("")
    out_lines.append("=" * 150)
    out_lines.append("SPLITS — for groups with potential edge")
    out_lines.append("=" * 150)

    # G2 (the candidate strict signal) split by session/dir/micro
    aligned_at_600 = df[f"regime_5m_aligned_T_{TAG}"] == 1
    fillable = df[f"fillable_at_T_{TAG}"] == 1
    g2 = df[aligned_at_600 & fillable]

    out_lines.append("\n--- G2 (aligned@600 + fillable) splits ---")
    splits_g2 = [
        ("ALL", g2),
        ("RTH", g2[g2["is_rth"] == 1]),
        ("ETH", g2[g2["is_rth"] == 0]),
        ("LONG", g2[g2["signal_direction"] == 1]),
        ("SHORT", g2[g2["signal_direction"] == -1]),
        ("micro_aligned", g2[g2[f"micro_aligned_T_{TAG}"] == 1]),
        ("micro_opposing", g2[g2[f"micro_opposing_T_{TAG}"] == 1]),
        ("micro_neither",
            g2[(g2[f"micro_aligned_T_{TAG}"] == 0)
                & (g2[f"micro_opposing_T_{TAG}"] == 0)]),
    ]
    for label, sub in splits_g2:
        s = stats(sub, require_fillable=False)  # already filtered
        out_lines.append(fmt_row(label, s))

    # G2 by year (stability check)
    out_lines.append("\n--- G2 year stability ---")
    years = sorted(g2["year"].unique())
    for y in years:
        sub = g2[g2["year"] == y]
        s = stats(sub, require_fillable=False)
        out_lines.append(fmt_row(f"{int(y)}", s))

    # Diagnostic — what fraction of all candidates does G2 represent?
    out_lines.append("")
    out_lines.append("=" * 150)
    out_lines.append("CONTEXT — population sizing")
    out_lines.append("=" * 150)
    n_all = len(df)
    n_g1 = aligned_at_600.sum()
    n_g2 = (aligned_at_600 & fillable).sum()
    n_g5 = fillable.sum()
    out_lines.append(f"  Total trades:                 {n_all:>7,}")
    out_lines.append(f"  Fillable @ 600 (G5):          {n_g5:>7,}  "
                      f"({n_g5/n_all*100:.1f}% of all)")
    out_lines.append(f"  Aligned @ 600 (G1):           {n_g1:>7,}  "
                      f"({n_g1/n_all*100:.1f}% of all)")
    out_lines.append(f"  Aligned @ 600 + fillable (G2):{n_g2:>7,}  "
                      f"({n_g2/n_g1*100:.1f}% of G1, "
                      f"{n_g2/n_all*100:.2f}% of all)")
    out_lines.append("")
    out_lines.append("  G2 is the only strict real-time analog to flip@600s.")
    out_lines.append("  If G2 has no edge, the original flip@600s edge "
                      "was a look-ahead artifact.")

    out = "\n".join(out_lines)
    print(out)

    log_path = Path("studies/1m_delayed_checkpoint_context/results/"
                     "strict_realtime_t600.log")
    log_path.write_text(out, encoding="utf-8")
    print(f"\n  Saved: {log_path}")


if __name__ == "__main__":
    main()
