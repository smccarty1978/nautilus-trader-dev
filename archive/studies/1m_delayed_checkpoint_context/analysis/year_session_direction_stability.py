"""Next pass — year/session/direction stability for standout groups.

Groups:
  - never_aligned   (regime_5m_flip_checkpoint is NaN, evaluate at T=0)
  - flip@120s       (flip_cp=120, evaluate at T=120)
  - flip@420s       (flip_cp=420, evaluate at T=420)
  - flip@600s       (flip_cp=600, evaluate at T=600)

Baselines:
  - ALL fillable at T=0
  - ALL fillable at T=600

Evaluation rule: each group uses ITS OWN T's checkpoint fields.
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


# ---- Group definitions ----
GROUPS = [
    # (label, filter_fn, eval_at_T)
    ("never_aligned", lambda df: df["regime_5m_flip_checkpoint"].isna(), 0),
    ("flip@120s",      lambda df: df["regime_5m_flip_checkpoint"] == 120, 120),
    ("flip@420s",      lambda df: df["regime_5m_flip_checkpoint"] == 420, 420),
    ("flip@600s",      lambda df: df["regime_5m_flip_checkpoint"] == 600, 600),
]

BASELINES = [
    ("baseline_T0",   lambda df: pd.Series(True, index=df.index), 0),
    ("baseline_T600", lambda df: pd.Series(True, index=df.index), 600),
]


def compute_group_stats(sub: pd.DataFrame, T: int) -> dict:
    """Stats for a subset at a given T. Returns dict with metrics."""
    tag = f"{T:03d}"
    fillable = sub[f"fillable_at_T_{tag}"]
    fwd_pnl = sub[f"forward_regime_pnl_dollars_T_{tag}"]
    mfe = sub[f"forward_peak_mfe_atr_T_{tag}"]
    mae = sub[f"forward_peak_mae_atr_T_{tag}"]
    fill_mask = fillable == 1
    n_total = len(sub)
    n_fill = int(fill_mask.sum())

    if n_fill == 0:
        return {
            "n": n_total, "n_fillable": 0, "wr%": np.nan,
            "avg$": np.nan, "med$": np.nan, "pf": np.nan,
            "med_mfe": np.nan, "med_mae": np.nan, "med_ratio": np.nan,
            "RTH_avg$": np.nan, "ETH_avg$": np.nan,
        }

    pnl = fwd_pnl[fill_mask]
    wr = (pnl > 0).mean() * 100
    avg = pnl.mean()
    med = pnl.median()
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = gp / gl if gl > 0 else float("inf")

    sub_mfe = mfe[fill_mask]
    sub_mae = mae[fill_mask]
    ratio = sub_mfe / sub_mae.replace(0, np.nan)

    is_rth = sub.loc[fill_mask, "is_rth"]
    rth_pnl = pnl[is_rth == 1]
    eth_pnl = pnl[is_rth == 0]
    rth_avg = rth_pnl.mean() if len(rth_pnl) > 0 else np.nan
    eth_avg = eth_pnl.mean() if len(eth_pnl) > 0 else np.nan

    return {
        "n": n_total, "n_fillable": n_fill, "wr%": wr,
        "avg$": avg, "med$": med, "pf": pf,
        "med_mfe": sub_mfe.median(),
        "med_mae": sub_mae.median(),
        "med_ratio": ratio.median(),
        "RTH_avg$": rth_avg, "ETH_avg$": eth_avg,
    }


def print_row(r, label):
    if pd.isna(r["wr%"]):
        print(f"  {label:<20} (no fillable)")
        return
    pf = r["pf"]
    pf_s = f"{pf:>5.2f}" if pf != float("inf") else "  inf"
    print(
        f"  {label:<20} "
        f"N={r['n']:>6,} nFill={r['n_fillable']:>6,} "
        f"WR={r['wr%']:>5.1f}% "
        f"Avg=${r['avg$']:>+7.1f} Med=${r['med$']:>+7.1f} "
        f"PF={pf_s} "
        f"MFE={r['med_mfe']:>4.2f} MAE={r['med_mae']:>4.2f} "
        f"R={r['med_ratio']:>4.2f} "
        f"RTH=${r['RTH_avg$']:>+7.1f} ETH=${r['ETH_avg$']:>+7.1f}"
    )


def year_stability_report(df, out_lines):
    """Year × group table."""
    out_lines.append("=" * 130)
    out_lines.append("YEAR-BY-YEAR STABILITY — 4 standout groups + 2 baselines")
    out_lines.append("  (each group evaluated at its own natural checkpoint T)")
    out_lines.append("=" * 130)
    years = sorted(df["year"].unique())

    all_rows = []
    for label, filt, T in GROUPS + BASELINES:
        out_lines.append(f"\n--- Group: {label}  (eval at T={T}s) ---")
        mask = filt(df)
        for y in years:
            sub = df[mask & (df["year"] == y)]
            r = compute_group_stats(sub, T)
            r["group"] = label
            r["year"] = str(int(y))
            r["eval_at_T"] = T
            all_rows.append(r)
            _print_year_row(out_lines, label, int(y), r)
        # Full 6-yr total for reference
        total = compute_group_stats(df[mask], T)
        total["group"] = label
        total["year"] = "6yr"
        total["eval_at_T"] = T
        all_rows.append(total)
        _print_year_row(out_lines, label, "6yr TOTAL", total)
    return all_rows


def _print_year_row(out_lines, group, year, r):
    if pd.isna(r["wr%"]):
        out_lines.append(f"  {year}  (no fillable)")
        return
    pf = r["pf"]
    pf_s = f"{pf:>5.2f}" if pf != float("inf") else "  inf"
    out_lines.append(
        f"  {str(year):>10} | "
        f"N={r['n']:>6,} nFill={r['n_fillable']:>6,} "
        f"WR={r['wr%']:>5.1f}% "
        f"Avg=${r['avg$']:>+7.1f} Med=${r['med$']:>+7.1f} "
        f"PF={pf_s} "
        f"MFE={r['med_mfe']:>4.2f} MAE={r['med_mae']:>4.2f} "
        f"R={r['med_ratio']:>4.2f} | "
        f"RTH=${r['RTH_avg$']:>+7.1f} ETH=${r['ETH_avg$']:>+7.1f}"
    )


def session_direction_report(df, out_lines):
    out_lines.append("\n" + "=" * 130)
    out_lines.append("SESSION + DIRECTION STABILITY (6yr pooled)")
    out_lines.append("=" * 130)

    all_groups = GROUPS + BASELINES

    out_lines.append("\n### SESSION split (RTH vs ETH)")
    out_lines.append(f"  {'group':<20} {'session':>8} "
                      f"{'n_fill':>7} {'wr%':>6} {'avg$':>8} "
                      f"{'pf':>5} {'med_mfe':>8} {'med_mae':>8}")
    out_lines.append("  " + "-" * 96)
    session_rows = []
    for label, filt, T in all_groups:
        mask = filt(df)
        sub_all = df[mask]
        for sess_val, sess_lbl in [(1, "RTH"), (0, "ETH")]:
            sub = sub_all[sub_all["is_rth"] == sess_val]
            r = compute_group_stats(sub, T)
            session_rows.append({
                "group": label, "eval_at_T": T, "session": sess_lbl,
                **r,
            })
            if pd.isna(r["wr%"]):
                out_lines.append(
                    f"  {label:<20} {sess_lbl:>8} (no fillable)")
                continue
            pf_s = f"{r['pf']:>5.2f}" if r["pf"] != float("inf") \
                else "  inf"
            out_lines.append(
                f"  {label:<20} {sess_lbl:>8} "
                f"{r['n_fillable']:>7,} {r['wr%']:>5.1f}% "
                f"${r['avg$']:>+7.1f} {pf_s} "
                f"{r['med_mfe']:>8.3f} {r['med_mae']:>8.3f}"
            )

    out_lines.append("\n### DIRECTION split (long vs short)")
    out_lines.append("  (for never_aligned and flip@600s only)")
    out_lines.append(f"  {'group':<20} {'dir':>5} "
                      f"{'n_fill':>7} {'wr%':>6} {'avg$':>8} {'pf':>5}")
    out_lines.append("  " + "-" * 72)
    dir_rows = []
    for label, filt, T in [GROUPS[0], GROUPS[3]]:  # never_aligned, flip@600s
        mask = filt(df)
        sub_all = df[mask]
        for d_val, d_lbl in [(1, "LONG"), (-1, "SHORT")]:
            sub = sub_all[sub_all["signal_direction"] == d_val]
            r = compute_group_stats(sub, T)
            dir_rows.append({
                "group": label, "eval_at_T": T, "direction": d_lbl,
                **r,
            })
            if pd.isna(r["wr%"]):
                out_lines.append(
                    f"  {label:<20} {d_lbl:>5} (no fillable)")
                continue
            pf_s = f"{r['pf']:>5.2f}" if r["pf"] != float("inf") \
                else "  inf"
            out_lines.append(
                f"  {label:<20} {d_lbl:>5} "
                f"{r['n_fillable']:>7,} {r['wr%']:>5.1f}% "
                f"${r['avg$']:>+7.1f} {pf_s}"
            )

    return session_rows, dir_rows


def main():
    df = pd.read_parquet(
        "studies/1m_delayed_checkpoint_context/results/trades_all.parquet")
    print(f"Loaded {len(df):,} trades")

    # --- Year stability ---
    year_lines = [f"Loaded {len(df):,} trades"]
    year_rows = year_stability_report(df, year_lines)
    year_out = "\n".join(year_lines)
    print("\n" + year_out[:2000])  # head only in console
    p1 = Path("studies/1m_delayed_checkpoint_context/results/"
              "next_pass_year_stability.log")
    p1.write_text(year_out, encoding="utf-8")
    pd.DataFrame(year_rows).to_parquet(
        "studies/1m_delayed_checkpoint_context/results/"
        "next_pass_year_stability.parquet", index=False)
    print(f"\n  Saved: {p1}")

    # --- Session + direction ---
    sd_lines = []
    sd_lines.append(f"Loaded {len(df):,} trades")
    session_rows, dir_rows = session_direction_report(df, sd_lines)
    sd_out = "\n".join(sd_lines)
    print("\n" + sd_out)
    p2 = Path("studies/1m_delayed_checkpoint_context/results/"
              "next_pass_session_direction.log")
    p2.write_text(sd_out, encoding="utf-8")
    pd.DataFrame(session_rows).to_parquet(
        "studies/1m_delayed_checkpoint_context/results/"
        "next_pass_session_rows.parquet", index=False)
    pd.DataFrame(dir_rows).to_parquet(
        "studies/1m_delayed_checkpoint_context/results/"
        "next_pass_direction_rows.parquet", index=False)
    print(f"\n  Saved: {p2}")


if __name__ == "__main__":
    main()
