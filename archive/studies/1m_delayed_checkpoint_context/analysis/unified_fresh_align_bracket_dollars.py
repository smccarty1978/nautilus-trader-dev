"""Unified fresh-align family — per-trade bracket dollar simulation.

Uses actual atr_at_signal per trade (not averaged) to simulate bracket
outcomes in dollars. No approximation of ATR.

Rules:
  - If bracket resolved: pnl = ±pt_R × atr × $20 for PT-first / SL-first
  - If not resolved (neither): use forward_regime_pnl_dollars_T (actual
    regime-exit PnL recorded by the collector)
  - Commission: $5/trade round-trip (already deducted in regime PnL;
    also deduct for bracket-resolved trades)
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

NQ_MULT = 20.0
COMMISSION = 5.0


def simulate_bracket(fam: pd.DataFrame, pt_r: float, sl_r: float,
                      bracket_col: str) -> pd.Series:
    """Return per-trade $ PnL for a bracket.

    pt_r, sl_r: bracket sizes in ATR units
    bracket_col: e.g. 'entry_forward_pt100_before_sl100'
    """
    atr = fam["atr_at_signal"].values
    bracket = fam[bracket_col].values
    regime_pnl = fam["entry_forward_regime_pnl_dollars"].values

    pnl = np.full(len(fam), np.nan)
    pt_first = bracket == 1
    sl_first = bracket == 0
    neither = pd.isna(bracket)

    pnl[pt_first] = (pt_r * atr[pt_first] * NQ_MULT) - COMMISSION
    pnl[sl_first] = (-sl_r * atr[sl_first] * NQ_MULT) - COMMISSION
    pnl[neither] = regime_pnl[neither]  # already includes commission
    return pd.Series(pnl, index=fam.index)


def stats(pnl: pd.Series) -> dict:
    n = len(pnl)
    if n == 0:
        return {"n": 0}
    wr = (pnl > 0).mean() * 100
    avg = pnl.mean()
    total = pnl.sum()
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = gp / gl if gl > 0 else float("inf")
    return {"n": n, "wr%": wr, "avg$": avg, "pf": pf, "total$": total}


def fmt_pf(pf):
    if pf == float("inf"):
        return " inf"
    return f"{pf:>4.2f}"


def fmt_row(lbl, s, width=22):
    if s["n"] == 0:
        return f"  {lbl:<{width}} (n=0)"
    return (
        f"  {lbl:<{width}} N={s['n']:>6,} WR={s['wr%']:>5.1f}% "
        f"Avg=${s['avg$']:>+7.1f} PF={fmt_pf(s['pf'])} "
        f"Total=${s['total$']:>+9,.0f}"
    )


def main():
    fam = pd.read_parquet(
        "studies/1m_delayed_checkpoint_context/results/"
        "unified_fresh_align_family.parquet")
    print(f"Fresh-align family: {len(fam):,} trades")
    print(f"ATR: median {fam['atr_at_signal'].median():.2f} pts, "
          f"mean {fam['atr_at_signal'].mean():.2f} pts")

    brackets = [
        ("PT=1.0/SL=1.0", 1.0, 1.0, "entry_forward_pt100_before_sl100"),
        ("PT=1.5/SL=1.0", 1.5, 1.0, "entry_forward_pt150_before_sl100"),
        ("PT=2.0/SL=1.0", 2.0, 1.0, "entry_forward_pt200_before_sl100"),
        ("PT=3.0/SL=1.5", 3.0, 1.5, "entry_forward_pt300_before_sl150"),
    ]

    out_lines = []
    out_lines.append("=" * 110)
    out_lines.append(
        "FRESH-ALIGN FAMILY — per-trade bracket $ simulation")
    out_lines.append(
        f"  N={len(fam):,}  ATR median={fam['atr_at_signal'].median():.2f}"
        f"pts  mean={fam['atr_at_signal'].mean():.2f}pts")
    out_lines.append(
        "  Resolved trades: ±R × atr × $20 − $5. Unresolved: "
        "collector regime-exit PnL (already net of commission).")
    out_lines.append("=" * 110)

    for lbl, pt_r, sl_r, col in brackets:
        pnl = simulate_bracket(fam, pt_r, sl_r, col)
        s = stats(pnl)
        out_lines.append("")
        out_lines.append(f"--- {lbl} ---")
        out_lines.append(fmt_row("POOLED", s))

        # Year
        out_lines.append(f"  {'Year':>6} {'N':>5} {'WR%':>6} "
                          f"{'Avg$':>8} {'PF':>5} {'Total$':>11}")
        for y in sorted(fam["year"].unique()):
            mask = fam["year"] == y
            r = stats(pnl[mask])
            out_lines.append(
                f"  {int(y):>6} {r['n']:>5,} {r['wr%']:>5.1f}% "
                f"${r['avg$']:>+7.1f} {fmt_pf(r['pf'])} "
                f"${r['total$']:>+10,.0f}")

        # Session + direction + checkpoint
        out_lines.append("  Splits:")
        for val, lbl2 in [(1, "RTH"), (0, "ETH")]:
            r = stats(pnl[fam["is_rth"] == val])
            out_lines.append(fmt_row(f"  {lbl2}", r))
        for val, lbl2 in [(1, "LONG"), (-1, "SHORT")]:
            r = stats(pnl[fam["signal_direction"] == val])
            out_lines.append(fmt_row(f"  {lbl2}", r))

        # RTH x LONG intersection
        rth_long = (fam["is_rth"] == 1) & (fam["signal_direction"] == 1)
        r = stats(pnl[rth_long])
        out_lines.append(fmt_row("  RTH × LONG", r))

    # Checkpoint distribution for PT=1.0/SL=1.0 and PT=1.5/SL=1.0
    out_lines.append("")
    out_lines.append("=" * 110)
    out_lines.append("CHECKPOINT DISTRIBUTION — PT=1.0/SL=1.0 bracket")
    out_lines.append("=" * 110)
    pnl_100 = simulate_bracket(
        fam, 1.0, 1.0, "entry_forward_pt100_before_sl100")
    out_lines.append(
        f"  {'T':>4} {'N':>5} {'WR%':>6} {'Avg$':>8} {'PF':>5} "
        f"{'Total$':>11}")
    for T in [60, 120, 180, 240, 300, 360, 420, 480, 540, 600]:
        r = stats(pnl_100[fam["entry_T"] == T])
        if r["n"] > 0:
            out_lines.append(
                f"  {T:>3}s {r['n']:>5,} {r['wr%']:>5.1f}% "
                f"${r['avg$']:>+7.1f} {fmt_pf(r['pf'])} "
                f"${r['total$']:>+10,.0f}")

    out_lines.append("")
    out_lines.append("=" * 110)
    out_lines.append("CHECKPOINT DISTRIBUTION — PT=1.5/SL=1.0 bracket")
    out_lines.append("=" * 110)
    pnl_150 = simulate_bracket(
        fam, 1.5, 1.0, "entry_forward_pt150_before_sl100")
    out_lines.append(
        f"  {'T':>4} {'N':>5} {'WR%':>6} {'Avg$':>8} {'PF':>5} "
        f"{'Total$':>11}")
    for T in [60, 120, 180, 240, 300, 360, 420, 480, 540, 600]:
        r = stats(pnl_150[fam["entry_T"] == T])
        if r["n"] > 0:
            out_lines.append(
                f"  {T:>3}s {r['n']:>5,} {r['wr%']:>5.1f}% "
                f"${r['avg$']:>+7.1f} {fmt_pf(r['pf'])} "
                f"${r['total$']:>+10,.0f}")

    out = "\n".join(out_lines)
    print(out)

    log_path = Path("studies/1m_delayed_checkpoint_context/results/"
                     "unified_fresh_align_bracket_dollars.log")
    log_path.write_text(out, encoding="utf-8")
    print(f"\n  Saved: {log_path}")


if __name__ == "__main__":
    main()
