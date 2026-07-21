"""Next pass — flip@600s bracket race + structural validation.

4 analyses:
  1. Bracket race on flip@600s (All/RTH/ETH/Long/Short)
  2. Year-by-year bracket stability for flip@600s
  3. Fresh flip vs already-aligned at 600s (key structural test)
  4. Micro overlay on flip@600s
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
TAG = f"{T:03d}"

BRACKETS = [
    "pt100_before_sl100",
    "pt150_before_sl100",
    "pt200_before_sl100",
    "pt300_before_sl150",
]


def bracket_stats(sub: pd.DataFrame, tag: str = TAG) -> dict:
    """Compute bracket pct + regime stats for a subset at T=600."""
    fillable = sub[f"fillable_at_T_{tag}"] == 1
    s = sub[fillable]
    n = len(s)
    if n == 0:
        return {"n": 0}

    pnl = s[f"forward_regime_pnl_dollars_T_{tag}"]
    mfe = s[f"forward_peak_mfe_atr_T_{tag}"]
    mae = s[f"forward_peak_mae_atr_T_{tag}"]

    wr = (pnl > 0).mean() * 100
    avg = pnl.mean()
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = gp / gl if gl > 0 else float("inf")

    out = {
        "n": n,
        "wr%": wr,
        "avg$": avg,
        "pf": pf,
        "med_mfe": mfe.median(),
        "med_mae": mae.median(),
    }
    for b in BRACKETS:
        col = f"forward_{b}_T_{tag}"
        # PT-first = 1, SL-first = 0, NaN = neither
        vals = s[col]
        non_nan = vals.notna().sum()
        pt_first = (vals == 1).sum()
        sl_first = (vals == 0).sum()
        if non_nan > 0:
            out[f"pt_pct_{b}"] = pt_first / n * 100
            out[f"pt_of_resolved_{b}"] = (
                pt_first / (pt_first + sl_first) * 100
                if (pt_first + sl_first) > 0 else np.nan)
        else:
            out[f"pt_pct_{b}"] = np.nan
            out[f"pt_of_resolved_{b}"] = np.nan
    return out


def fmt_pf(pf):
    if pd.isna(pf):
        return "  n/a"
    if pf == float("inf"):
        return "  inf"
    return f"{pf:>5.2f}"


def print_bracket_row(label, s):
    if s.get("n", 0) == 0:
        print(f"  {label:<16} (no fillable)")
        return
    print(
        f"  {label:<16} N={s['n']:>6,} "
        f"WR={s['wr%']:>5.1f}% Avg=${s['avg$']:>+7.1f} "
        f"PF={fmt_pf(s['pf'])} "
        f"MFE={s['med_mfe']:>4.2f} MAE={s['med_mae']:>4.2f} | "
        f"pt100={s['pt_pct_pt100_before_sl100']:>5.1f}% "
        f"pt150={s['pt_pct_pt150_before_sl100']:>5.1f}% "
        f"pt200={s['pt_pct_pt200_before_sl100']:>5.1f}% "
        f"pt300={s['pt_pct_pt300_before_sl150']:>5.1f}%"
    )


def analysis_1_bracket_race(df, out_lines):
    """Bracket race on flip@600s + splits."""
    out_lines.append("=" * 140)
    out_lines.append("ANALYSIS 1 — BRACKET RACE on flip@600s")
    out_lines.append(
        "  Population: regime_5m_flip_checkpoint == 600 AND fillable_at_T_600 = 1"
    )
    out_lines.append("=" * 140)

    base = df[df["regime_5m_flip_checkpoint"] == 600]

    splits = [
        ("ALL", base),
        ("RTH", base[base["is_rth"] == 1]),
        ("ETH", base[base["is_rth"] == 0]),
        ("LONG", base[base["signal_direction"] == 1]),
        ("SHORT", base[base["signal_direction"] == -1]),
    ]

    out_lines.append("")
    for label, sub in splits:
        s = bracket_stats(sub)
        line = _format_bracket_row(label, s)
        out_lines.append(line)

    # Resolved-only PT% for interpretation (how brackets actually race)
    out_lines.append("\n  --- Resolved-only PT% (PT vs SL, excluding neither) ---")
    for label, sub in splits:
        s = bracket_stats(sub)
        if s.get("n", 0) == 0:
            continue
        rl = (
            f"  {label:<16} "
            f"pt100_res={_pct(s['pt_of_resolved_pt100_before_sl100']):>6} "
            f"pt150_res={_pct(s['pt_of_resolved_pt150_before_sl100']):>6} "
            f"pt200_res={_pct(s['pt_of_resolved_pt200_before_sl100']):>6} "
            f"pt300_res={_pct(s['pt_of_resolved_pt300_before_sl150']):>6}"
        )
        out_lines.append(rl)


def _pct(v):
    if pd.isna(v):
        return "n/a"
    return f"{v:.1f}%"


def _format_bracket_row(label, s):
    if s.get("n", 0) == 0:
        return f"  {label:<16} (no fillable)"
    return (
        f"  {label:<16} N={s['n']:>6,} "
        f"WR={s['wr%']:>5.1f}% Avg=${s['avg$']:>+7.1f} "
        f"PF={fmt_pf(s['pf'])} "
        f"MFE={s['med_mfe']:>4.2f} MAE={s['med_mae']:>4.2f} | "
        f"pt100={s['pt_pct_pt100_before_sl100']:>5.1f}% "
        f"pt150={s['pt_pct_pt150_before_sl100']:>5.1f}% "
        f"pt200={s['pt_pct_pt200_before_sl100']:>5.1f}% "
        f"pt300={s['pt_pct_pt300_before_sl150']:>5.1f}%"
    )


def analysis_2_year_bracket(df, out_lines):
    """Year-by-year bracket stability for flip@600s."""
    out_lines.append("=" * 140)
    out_lines.append("ANALYSIS 2 — YEAR-BY-YEAR BRACKET STABILITY for flip@600s")
    out_lines.append("=" * 140)

    base = df[df["regime_5m_flip_checkpoint"] == 600]
    years = sorted(base["year"].unique())

    out_lines.append("")
    out_lines.append(
        f"  {'Year':>6} {'nFill':>6} "
        f"{'pt100%':>7} {'pt150%':>7} {'pt200%':>7} {'pt300%':>7}  "
        f"{'Avg$':>8} {'PF':>5} {'WR%':>6}"
    )
    out_lines.append("  " + "-" * 76)
    for y in years:
        sub = base[base["year"] == y]
        s = bracket_stats(sub)
        if s.get("n", 0) == 0:
            continue
        out_lines.append(
            f"  {int(y):>6} {s['n']:>6,} "
            f"{s['pt_pct_pt100_before_sl100']:>6.1f}% "
            f"{s['pt_pct_pt150_before_sl100']:>6.1f}% "
            f"{s['pt_pct_pt200_before_sl100']:>6.1f}% "
            f"{s['pt_pct_pt300_before_sl150']:>6.1f}% "
            f"${s['avg$']:>+7.1f} "
            f"{fmt_pf(s['pf'])} "
            f"{s['wr%']:>5.1f}%"
        )
    total = bracket_stats(base)
    out_lines.append("  " + "-" * 76)
    out_lines.append(
        f"  {'6yr':>6} {total['n']:>6,} "
        f"{total['pt_pct_pt100_before_sl100']:>6.1f}% "
        f"{total['pt_pct_pt150_before_sl100']:>6.1f}% "
        f"{total['pt_pct_pt200_before_sl100']:>6.1f}% "
        f"{total['pt_pct_pt300_before_sl150']:>6.1f}% "
        f"${total['avg$']:>+7.1f} "
        f"{fmt_pf(total['pf'])} "
        f"{total['wr%']:>5.1f}%"
    )

    # Also break by bracket x session x year for the best-looking bracket
    out_lines.append("\n  PT 2.0 / SL 1.0 by year + session:")
    out_lines.append(
        f"  {'Year':>6} {'RTH_N':>6} {'RTH_pt%':>8} {'RTH_avg$':>9} "
        f"{'ETH_N':>6} {'ETH_pt%':>8} {'ETH_avg$':>9}"
    )
    for y in years:
        sub = base[base["year"] == y]
        rth = bracket_stats(sub[sub["is_rth"] == 1])
        eth = bracket_stats(sub[sub["is_rth"] == 0])
        rth_str = (
            f"{rth['n']:>6,} {rth['pt_pct_pt200_before_sl100']:>7.1f}% "
            f"${rth['avg$']:>+8.1f}"
            if rth.get("n", 0) > 0 else f"{'-':>25}"
        )
        eth_str = (
            f"{eth['n']:>6,} {eth['pt_pct_pt200_before_sl100']:>7.1f}% "
            f"${eth['avg$']:>+8.1f}"
            if eth.get("n", 0) > 0 else f"{'-':>25}"
        )
        out_lines.append(f"  {int(y):>6} {rth_str} {eth_str}")


def analysis_3_fresh_vs_aligned(df, out_lines):
    """Fresh flip at 600 vs already-aligned at 600 but flipped earlier."""
    out_lines.append("=" * 140)
    out_lines.append(
        "ANALYSIS 3 — FRESH FLIP vs ALREADY-ALIGNED at T=600"
    )
    out_lines.append(
        "  A: regime_5m_flip_checkpoint == 600 (fresh flip at 600)"
    )
    out_lines.append(
        "  B: regime_5m_aligned_T_600 == 1 AND "
        "regime_5m_flip_checkpoint != 600 (aligned earlier, still aligned)"
    )
    out_lines.append("=" * 140)
    out_lines.append("")

    a = df[df["regime_5m_flip_checkpoint"] == 600]
    b = df[(df[f"regime_5m_aligned_T_{TAG}"] == 1)
           & (df["regime_5m_flip_checkpoint"] != 600)]

    for label, sub in [("A: fresh@600", a), ("B: already-aligned", b)]:
        s = bracket_stats(sub)
        out_lines.append(_format_bracket_row(label, s))

    # Full splits by session too
    out_lines.append("\n  By session:")
    for label, sub in [("A: fresh@600", a), ("B: already-aligned", b)]:
        for sess_val, sess_lbl in [(1, "RTH"), (0, "ETH")]:
            s = bracket_stats(sub[sub["is_rth"] == sess_val])
            out_lines.append(
                _format_bracket_row(f"  {label} {sess_lbl}", s))

    # Key interpretation
    a_s = bracket_stats(a)
    b_s = bracket_stats(b)
    if a_s.get("n", 0) > 0 and b_s.get("n", 0) > 0:
        out_lines.append("\n  DELTA (A - B):")
        out_lines.append(
            f"    WR: {a_s['wr%'] - b_s['wr%']:+.1f}pp | "
            f"Avg: ${a_s['avg$'] - b_s['avg$']:+.1f} | "
            f"PF: {a_s['pf'] - b_s['pf']:+.2f}"
        )
        out_lines.append(
            f"    pt200: {a_s['pt_pct_pt200_before_sl100'] - b_s['pt_pct_pt200_before_sl100']:+.1f}pp | "
            f"pt300: {a_s['pt_pct_pt300_before_sl150'] - b_s['pt_pct_pt300_before_sl150']:+.1f}pp"
        )


def analysis_4_micro_overlay(df, out_lines):
    """Micro overlay on flip@600s."""
    out_lines.append("=" * 140)
    out_lines.append("ANALYSIS 4 — MICRO OVERLAY on flip@600s")
    out_lines.append(
        "  Population: regime_5m_flip_checkpoint == 600 AND fillable_at_T_600 = 1"
    )
    out_lines.append("=" * 140)
    out_lines.append("")

    base = df[df["regime_5m_flip_checkpoint"] == 600]

    ma = base[base[f"micro_aligned_T_{TAG}"] == 1]
    mo = base[base[f"micro_opposing_T_{TAG}"] == 1]
    neither = base[
        (base[f"micro_aligned_T_{TAG}"] == 0)
        & (base[f"micro_opposing_T_{TAG}"] == 0)
    ]

    for label, sub in [
        ("micro_aligned", ma),
        ("micro_opposing", mo),
        ("neither", neither),
        ("all flip@600s", base),
    ]:
        s = bracket_stats(sub)
        out_lines.append(_format_bracket_row(label, s))


def main():
    df = pd.read_parquet(
        "studies/1m_delayed_checkpoint_context/results/trades_all.parquet")
    print(f"Loaded {len(df):,} trades")

    out_dir = Path("studies/1m_delayed_checkpoint_context/results")

    # Analysis 1
    l1 = []
    analysis_1_bracket_race(df, l1)
    out1 = "\n".join(l1)
    (out_dir / "flip600_bracket_race.log").write_text(out1, encoding="utf-8")
    print(out1)

    # Analysis 2
    l2 = []
    analysis_2_year_bracket(df, l2)
    out2 = "\n".join(l2)
    (out_dir / "flip600_year_bracket_stability.log").write_text(
        out2, encoding="utf-8")
    print("\n" + out2)

    # Analysis 3
    l3 = []
    analysis_3_fresh_vs_aligned(df, l3)
    out3 = "\n".join(l3)
    (out_dir / "flip600_fresh_vs_aligned.log").write_text(out3, encoding="utf-8")
    print("\n" + out3)

    # Analysis 4
    l4 = []
    analysis_4_micro_overlay(df, l4)
    out4 = "\n".join(l4)
    (out_dir / "flip600_micro_overlay.log").write_text(out4, encoding="utf-8")
    print("\n" + out4)

    print(f"\n  Saved all logs to {out_dir}")


if __name__ == "__main__":
    main()
