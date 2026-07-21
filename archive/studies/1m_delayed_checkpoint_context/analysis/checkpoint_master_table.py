"""Analysis B — Master checkpoint performance table.

One row per checkpoint, for All / RTH / ETH.
Population: fillable_at_T = 1 (actual valid candidate entries).
All metrics evaluated from checkpoint_entry_fill_price_T, never T0.

% confirmed_hhll is OMITTED: all trades are confirmed by construction
in the v3 collector (unconfirmed flips are not in the output).
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

CHECKPOINT_TS = list(range(0, 601, 30))


def compute_cp_row(T: int, df: pd.DataFrame) -> dict:
    tag = f"{T:03d}"
    alive = df[f"alive_at_T_{tag}"]
    fillable = df[f"fillable_at_T_{tag}"]
    fwd_pnl = df[f"forward_regime_pnl_dollars_T_{tag}"]
    fwd_pnl_atr = df[f"forward_regime_pnl_atr_T_{tag}"]
    peak_mfe = df[f"forward_peak_mfe_atr_T_{tag}"]
    peak_mae = df[f"forward_peak_mae_atr_T_{tag}"]
    reg_remaining = df[f"forward_regime_remaining_s_T_{tag}"]
    reg30_aligned = df[f"regime_30s_aligned_T_{tag}"]
    reg5m_aligned = df[f"regime_5m_aligned_T_{tag}"]
    micro_aligned = df[f"micro_aligned_T_{tag}"]
    micro_opposing = df[f"micro_opposing_T_{tag}"]
    flip_cp = df["regime_5m_flip_checkpoint"]

    n_all = len(df)
    alive_mask = (alive == 1)
    fill_mask = (fillable == 1)
    n_alive = alive_mask.sum()
    n_fill = fill_mask.sum()

    if n_fill == 0:
        return {
            "T": T, "n_alive": int(n_alive), "n_fillable": 0,
            "fillable%_of_all": 0.0, "fillable%_of_alive": 0.0,
            "wr_regime_exit%": np.nan, "avg_pnl$": np.nan,
            "median_pnl$": np.nan, "pf_regime_exit": np.nan,
            "avg_peak_mfe": np.nan, "median_peak_mfe": np.nan,
            "avg_peak_mae": np.nan, "median_peak_mae": np.nan,
            "median_mfe_mae_ratio": np.nan,
            "avg_regime_remaining_s": np.nan,
            "30s_aligned%": np.nan, "5m_aligned%": np.nan,
            "micro_aligned%": np.nan, "micro_opposing%": np.nan,
            "5m_fresh_flip_here%": np.nan,
        }

    pnl = fwd_pnl[fill_mask]
    n_win = (pnl > 0).sum()
    wr = n_win / n_fill * 100
    avg = pnl.mean()
    med = pnl.median()
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = gp / gl if gl > 0 else float("inf")

    sub_mfe = peak_mfe[fill_mask]
    sub_mae = peak_mae[fill_mask]
    # Safe ratio
    ratio = sub_mfe / sub_mae.replace(0, np.nan)

    sub_30 = reg30_aligned[fill_mask]
    sub_5m = reg5m_aligned[fill_mask]
    sub_ma = micro_aligned[fill_mask]
    sub_mo = micro_opposing[fill_mask]

    # Fresh flip = regime_5m_flip_checkpoint == this T (root-level match)
    fresh_flip_here = (flip_cp == T) & fill_mask
    fresh_flip_pct = fresh_flip_here.sum() / n_fill * 100

    return {
        "T": T,
        "n_alive": int(n_alive),
        "n_fillable": int(n_fill),
        "fillable%_of_all": n_fill / n_all * 100,
        "fillable%_of_alive": n_fill / n_alive * 100 if n_alive else 0,
        "wr_regime_exit%": wr,
        "avg_pnl$": avg,
        "median_pnl$": med,
        "pf_regime_exit": pf,
        "avg_peak_mfe": sub_mfe.mean(),
        "median_peak_mfe": sub_mfe.median(),
        "avg_peak_mae": sub_mae.mean(),
        "median_peak_mae": sub_mae.median(),
        "median_mfe_mae_ratio": ratio.median(),
        "avg_regime_remaining_s": reg_remaining[fill_mask].mean(),
        "30s_aligned%": (sub_30 == 1).mean() * 100,
        "5m_aligned%": (sub_5m == 1).mean() * 100,
        "micro_aligned%": (sub_ma == 1).mean() * 100,
        "micro_opposing%": (sub_mo == 1).mean() * 100,
        "5m_fresh_flip_here%": fresh_flip_pct,
    }


def print_table(rows, label):
    print(f"\n{'='*140}")
    print(f"TABLE B — Master Checkpoint Performance — {label}")
    print(f"(fillable_at_T=1 only; all metrics from "
          f"checkpoint_entry_fill_price_T, never T0)")
    print(f"{'='*140}")
    print(
        f"  {'T':>4} {'nFill':>7} {'f%all':>6} {'f%alv':>6} "
        f"{'WR%':>5} {'Avg$':>7} {'Med$':>7} {'PF':>4} "
        f"{'mfe':>5} {'mae':>5} {'ratio':>5} {'remain':>7}  "
        f"{'30s%':>5} {'5m%':>5} {'mA%':>5} {'mO%':>5} {'frsh%':>6}"
    )
    print("  " + "-" * 138)
    for r in rows:
        if pd.isna(r["wr_regime_exit%"]):
            print(f"  {r['T']:>3}s (no fillable trades)")
            continue
        pf = r["pf_regime_exit"]
        pf_s = f"{pf:>4.2f}" if pf != float("inf") else " inf"
        print(
            f"  {r['T']:>3}s {r['n_fillable']:>7,} "
            f"{r['fillable%_of_all']:>5.1f}% "
            f"{r['fillable%_of_alive']:>5.1f}% "
            f"{r['wr_regime_exit%']:>4.1f}% "
            f"${r['avg_pnl$']:>+6.1f} "
            f"${r['median_pnl$']:>+6.1f} "
            f"{pf_s} "
            f"{r['avg_peak_mfe']:>5.2f} "
            f"{r['avg_peak_mae']:>5.2f} "
            f"{r['median_mfe_mae_ratio']:>5.2f} "
            f"{r['avg_regime_remaining_s']:>6.0f}s  "
            f"{r['30s_aligned%']:>4.1f}% "
            f"{r['5m_aligned%']:>4.1f}% "
            f"{r['micro_aligned%']:>4.1f}% "
            f"{r['micro_opposing%']:>4.1f}% "
            f"{r['5m_fresh_flip_here%']:>5.1f}%"
        )


def main():
    df = pd.read_parquet(
        "studies/1m_delayed_checkpoint_context/results/trades_all.parquet")
    print(f"Loaded {len(df):,} trades × {len(df.columns)} cols")
    print(f"  (% confirmed_hhll = 100% by construction — omitted from table)")

    splits = [
        ("ALL", df),
        ("RTH", df[df["is_rth"] == 1]),
        ("ETH", df[df["is_rth"] == 0]),
    ]

    all_rows = {}
    for label, sub in splits:
        print(f"\n  {label}: N={len(sub):,}")
        rows = [compute_cp_row(T, sub) for T in CHECKPOINT_TS]
        all_rows[label] = rows
        print_table(rows, label)

    # Save each split
    out_dir = Path("studies/1m_delayed_checkpoint_context/results")
    for label, rows in all_rows.items():
        tdf = pd.DataFrame(rows)
        fn = out_dir / f"checkpoint_master_table_{label.lower()}.parquet"
        tdf.to_parquet(fn, index=False)
        print(f"\n  Saved: {fn}")


if __name__ == "__main__":
    main()
