"""Phase 2a — Label base rates (RTH primary, ETH / pooled appendix).

Reads: studies/ml_5m_flip_prediction/results/ml_5m_flip_prediction_dataset.parquet
Writes: studies/ml_5m_flip_prediction/results/ml_5m_flip_label_base_rates.log
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np

HORIZONS = [120, 180, 300, 600]
CHECKPOINTS = [0, 60, 120, 180, 240, 300, 360, 420, 480, 540, 600]
DATASET = ("studies/ml_5m_flip_prediction/results/"
            "ml_5m_flip_prediction_dataset.parquet")
OUT_LOG = Path("studies/ml_5m_flip_prediction/results/"
                "ml_5m_flip_label_base_rates.log")


def rate(series: pd.Series) -> tuple:
    pos = (series == 1).sum()
    neg = (series == 0).sum()
    total = pos + neg
    r = pos / total * 100 if total > 0 else np.nan
    return int(pos), int(neg), int(total), r


def fmt_rate(pos, neg, total, r):
    if total == 0:
        return f"(no valid rows)"
    return f"N={total:>7,} pos={pos:>6,} neg={neg:>6,} rate={r:>5.1f}%"


def main():
    df = pd.read_parquet(DATASET)
    n = len(df)
    print(f"Loaded {n:,} rows")

    lines = []
    lines.append("=" * 130)
    lines.append("ML 5m FLIP PREDICTION — LABEL BASE RATES")
    lines.append(f"  Dataset rows: {n:,}")
    lines.append(
        "  Primary lens: RTH. ETH and pooled reported for comparison.")
    lines.append("=" * 130)

    # ---- Session x horizon grid ----
    lines.append("\n--- 1. SESSION × HORIZON BASE RATES ---")
    lines.append(
        f"  {'Session':>8} {'Horizon':>8}  "
        f"{'N_valid':>9} {'pos':>7} {'neg':>7} {'rate%':>6}")
    lines.append("  " + "-" * 60)
    for sess_lbl, mask in [
        ("RTH", df["is_rth"] == 1),
        ("ETH", df["is_rth"] == 0),
        ("POOLED", pd.Series(True, index=df.index)),
    ]:
        sub = df[mask]
        for h in HORIZONS:
            col = f"target_5m_flip_within_{h}s"
            pos, neg, total, r = rate(sub[col])
            lines.append(
                f"  {sess_lbl:>8} {h:>6}s  "
                f"{total:>9,} {pos:>7,} {neg:>7,} "
                f"{r:>5.1f}%" if total > 0 else
                f"  {sess_lbl:>8} {h:>6}s  (no valid rows)"
            )
        lines.append("")

    # ---- RTH primary: 300s by year ----
    lines.append("\n--- 2. RTH — 300s TARGET BY YEAR ---")
    rth = df[df["is_rth"] == 1]
    lines.append(
        f"  {'Year':>6} {'N_valid':>9} {'pos':>7} {'neg':>7} {'rate%':>6}")
    lines.append("  " + "-" * 48)
    for y in sorted(rth["year"].unique()):
        sub = rth[rth["year"] == y]
        pos, neg, total, r = rate(sub["target_5m_flip_within_300s"])
        lines.append(
            f"  {int(y):>6} {total:>9,} {pos:>7,} {neg:>7,} {r:>5.1f}%"
            if total > 0 else
            f"  {int(y):>6} (no valid rows)"
        )

    # ---- RTH primary: 300s by decision T ----
    lines.append("\n--- 3. RTH — 300s TARGET BY DECISION T ---")
    lines.append(
        f"  {'T_d':>4} {'N_valid':>9} {'pos':>7} {'neg':>7} {'rate%':>6}")
    lines.append("  " + "-" * 48)
    for T in CHECKPOINTS:
        sub = rth[rth["decision_checkpoint_s"] == T]
        pos, neg, total, r = rate(sub["target_5m_flip_within_300s"])
        if total == 0:
            lines.append(f"  {T:>3}s (no valid rows)")
            continue
        lines.append(
            f"  {T:>3}s {total:>9,} {pos:>7,} {neg:>7,} {r:>5.1f}%")

    # ---- RTH: 300s by direction ----
    lines.append("\n--- 4. RTH — 300s TARGET BY DIRECTION ---")
    for d, lbl in [(1, "LONG"), (-1, "SHORT")]:
        sub = rth[rth["signal_direction"] == d]
        pos, neg, total, r = rate(sub["target_5m_flip_within_300s"])
        lines.append(f"  {lbl:>6}: {fmt_rate(pos, neg, total, r)}")

    # ---- RTH: 300s by year × decision T (heatmap style) ----
    lines.append("\n--- 5. RTH — 300s BASE RATE YEAR × DECISION T ---")
    years = sorted(rth["year"].unique())
    Ts_valid = [T for T in CHECKPOINTS if T <= 300]
    header = f"  {'Year':>6} | " + " ".join(
        [f"{T:>5}s" for T in Ts_valid]) + " | All"
    lines.append(header)
    lines.append("  " + "-" * (len(header)))
    for y in years:
        row = f"  {int(y):>6} |"
        for T in Ts_valid:
            sub = rth[(rth["year"] == y)
                       & (rth["decision_checkpoint_s"] == T)]
            _, _, total, r = rate(sub["target_5m_flip_within_300s"])
            if total > 0:
                row += f" {r:>5.1f}"
            else:
                row += f"   -- "
        # all T
        sub = rth[rth["year"] == y]
        _, _, total, r = rate(sub["target_5m_flip_within_300s"])
        row += f" | {r:>4.1f}% (N={total:,})"
        lines.append(row)

    # ---- POOLED horizons summary (for reference) ----
    lines.append("\n--- 6. POOLED — ALL HORIZONS SUMMARY ---")
    lines.append(f"  {'Horizon':>8} {'N_valid':>9} {'rate%':>6}")
    lines.append("  " + "-" * 30)
    for h in HORIZONS:
        col = f"target_5m_flip_within_{h}s"
        pos, neg, total, r = rate(df[col])
        lines.append(
            f"  {h:>6}s {total:>9,} {r:>5.1f}%" if total > 0 else
            f"  {h:>6}s (no valid rows)"
        )

    out = "\n".join(lines)
    print(out)
    OUT_LOG.write_text(out, encoding="utf-8")
    print(f"\nSaved: {OUT_LOG}")


if __name__ == "__main__":
    main()
