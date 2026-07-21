"""Phase 3b — Tradeability sanity check.

For top-decile / top-quintile / top-half / all predictions on TEST
(RTH-only baseline model), compute:
  - median forward MFE / MAE / ratio (from each row's decision T)
  - bracket pt100/pt150/pt200/pt300 hit rates
  - simulated dollar PnL per bracket using per-trade ATR

Primary question: does predicting imminent 5m flip map to better trade
economics?

DESCRIPTIVE ONLY — this is NOT a trading simulation. It uses
collector-recorded forward fields that assume regime-exit resolution
for unresolved trades.

Reads:  trades_all.parquet + ml_5m_flip_baseline_preds_test.parquet
Writes: ml_5m_flip_tradeability_sanity.log
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

TRADES_PATH = ("studies/1m_delayed_checkpoint_context/results/"
                "trades_all.parquet")
PREDS_PATH = ("studies/ml_5m_flip_prediction/results/"
              "ml_5m_flip_baseline_preds_test.parquet")
OUT_LOG = Path("studies/ml_5m_flip_prediction/results/"
                "ml_5m_flip_tradeability_sanity.log")

NQ_MULT = 20.0
COMMISSION = 5.0


def join_forward_fields(preds: pd.DataFrame, trades: pd.DataFrame):
    """For each prediction row, pull forward_* fields from trades_all
    at the decision_checkpoint_s (per-row T_d)."""
    # Build merge key: trades_all has signal_ts as event_id
    trades_idx = trades.set_index("signal_ts")

    # For each row, pull fields at its T_d
    n = len(preds)
    out = preds.copy()
    cols_to_fetch = [
        "forward_peak_mfe_atr",
        "forward_peak_mae_atr",
        "forward_regime_pnl_dollars",
        "forward_pt100_before_sl100",
        "forward_pt150_before_sl100",
        "forward_pt200_before_sl100",
        "forward_pt300_before_sl150",
    ]

    # Vectorize per T_d
    for c in cols_to_fetch:
        out[c] = np.nan

    for T_d in sorted(out["decision_checkpoint_s"].unique()):
        tag = f"{int(T_d):03d}"
        sel = out["decision_checkpoint_s"] == T_d
        event_ids = out.loc[sel, "event_id"].values
        for c in cols_to_fetch:
            src = f"{c}_T_{tag}"
            if src in trades_idx.columns:
                out.loc[sel, c] = trades_idx[src].reindex(event_ids).values
            else:
                print(f"  WARN: {src} not in trades_all")
    return out


def stats_bracket(sub: pd.DataFrame, pt_r: float, sl_r: float,
                   bracket_col: str) -> dict:
    """Simulated $ PnL using per-trade ATR.

    Uses atr_at_signal from preds (passed through); commission $5 for
    resolved trades, regime-exit PnL for unresolved (already has $5
    commission baked in by collector).
    """
    n = len(sub)
    if n == 0:
        return {"n": 0}
    atr = sub["atr_at_signal"].values
    bracket = sub[bracket_col].values
    regime_pnl = sub["forward_regime_pnl_dollars"].values

    pnl = np.full(n, np.nan)
    pt_first = bracket == 1
    sl_first = bracket == 0
    neither = pd.isna(bracket)

    pnl[pt_first] = (pt_r * atr[pt_first] * NQ_MULT) - COMMISSION
    pnl[sl_first] = (-sl_r * atr[sl_first] * NQ_MULT) - COMMISSION
    pnl[neither] = regime_pnl[neither]

    wr = (pnl > 0).mean() * 100
    avg = pnl.mean()
    total = pnl.sum()
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = gp / gl if gl > 0 else float("inf")
    pt_pct = pt_first.sum() / n * 100
    sl_pct = sl_first.sum() / n * 100
    neither_pct = neither.sum() / n * 100

    return {
        "n": n, "wr%": wr, "avg$": avg, "total$": total, "pf": pf,
        "pt%": pt_pct, "sl%": sl_pct, "neither%": neither_pct,
    }


def stats_forward(sub: pd.DataFrame) -> dict:
    n = len(sub)
    if n == 0:
        return {"n": 0}
    mfe = sub["forward_peak_mfe_atr"]
    mae = sub["forward_peak_mae_atr"]
    ratio = mfe / mae.replace(0, np.nan)
    pnl = sub["forward_regime_pnl_dollars"]
    return {
        "n": n,
        "med_mfe": mfe.median(),
        "med_mae": mae.median(),
        "med_ratio": ratio.median(),
        "regime_wr%": (pnl > 0).mean() * 100,
        "regime_avg$": pnl.mean(),
    }


def fmt_pf(pf):
    if pd.isna(pf):
        return " n/a"
    if pf == float("inf"):
        return " inf"
    return f"{pf:>4.2f}"


def main():
    print("Loading preds + trades_all...")
    preds = pd.read_parquet(PREDS_PATH)
    trades = pd.read_parquet(TRADES_PATH)
    print(f"  preds: {len(preds):,} rows, trades: {len(trades):,}")
    # trades_all has 129 duplicate signal_ts pairs from collector warmup
    # overlap at year boundaries. Dedupe before join.
    n_before = len(trades)
    trades = trades.drop_duplicates(subset=["signal_ts"], keep="first")
    print(f"  Dedup trades by signal_ts: {n_before:,} → {len(trades):,} "
          f"({n_before - len(trades)} duplicates removed)")

    print("Joining forward fields by (event_id, decision_checkpoint_s)...")
    joined = join_forward_fields(preds, trades)

    # Drop rows where join failed (should be rare — e.g., if preds has
    # a signal_ts not in trades_all, which shouldn't happen)
    missing_pnl = joined["forward_regime_pnl_dollars"].isna().sum()
    print(f"  Joined. Rows missing forward_regime_pnl_dollars: "
          f"{missing_pnl:,}")
    joined = joined[joined["forward_regime_pnl_dollars"].notna()].copy()

    lines = []
    lines.append("=" * 140)
    lines.append(
        "ML 5m FLIP PREDICTION — TRADEABILITY SANITY CHECK (TEST set, RTH)")
    lines.append(
        "  DESCRIPTIVE ONLY. Bracket outcomes from collector; 'neither' "
        "uses regime-exit PnL.")
    lines.append(
        f"  TEST rows joined: {len(joined):,}")
    lines.append("=" * 140)

    # Rank by pred, pick buckets
    j = joined.sort_values("pred", ascending=False).reset_index(drop=True)
    n = len(j)
    buckets = [
        ("ALL (100%)", j),
        ("TOP 50%", j.iloc[:n // 2]),
        ("TOP 25%", j.iloc[:n // 4]),
        ("TOP DECILE (10%)", j.iloc[:n // 10]),
        ("TOP 5%", j.iloc[:n // 20]),
        ("BOTTOM DECILE", j.iloc[-(n // 10):]),
    ]

    # Section 1: forward MFE/MAE/ratio + regime PnL
    lines.append("\n--- 1. FORWARD METRICS BY SCORE BUCKET ---")
    lines.append(
        f"  {'Bucket':<18} {'N':>6} {'med_MFE':>8} {'med_MAE':>8} "
        f"{'med_ratio':>10} {'regime_WR':>10} {'regime_avg$':>12}")
    lines.append("  " + "-" * 78)
    for lbl, sub in buckets:
        s = stats_forward(sub)
        if s["n"] == 0:
            continue
        lines.append(
            f"  {lbl:<18} {s['n']:>6,} {s['med_mfe']:>7.2f}  "
            f"{s['med_mae']:>7.2f}  {s['med_ratio']:>9.2f}  "
            f"{s['regime_wr%']:>9.1f}% ${s['regime_avg$']:>+10.1f}")

    # Section 2: bracket outcomes
    lines.append("\n--- 2. BRACKET OUTCOMES BY SCORE BUCKET ---")
    for pt_r, sl_r, col, lbl_br in [
        (1.0, 1.0, "forward_pt100_before_sl100", "PT=1.0/SL=1.0"),
        (1.5, 1.0, "forward_pt150_before_sl100", "PT=1.5/SL=1.0"),
        (2.0, 1.0, "forward_pt200_before_sl100", "PT=2.0/SL=1.0"),
        (3.0, 1.5, "forward_pt300_before_sl150", "PT=3.0/SL=1.5"),
    ]:
        lines.append(f"\n  {lbl_br}:")
        lines.append(
            f"    {'Bucket':<18} {'N':>6} {'pt%':>6} {'sl%':>6} "
            f"{'nth%':>6} {'WR':>6} {'Avg$':>8} {'PF':>5} "
            f"{'Total$':>11}")
        lines.append("    " + "-" * 80)
        for bucket_lbl, sub in buckets:
            s = stats_bracket(sub, pt_r, sl_r, col)
            if s["n"] == 0:
                continue
            lines.append(
                f"    {bucket_lbl:<18} {s['n']:>6,} "
                f"{s['pt%']:>5.1f}% {s['sl%']:>5.1f}% "
                f"{s['neither%']:>5.1f}% {s['wr%']:>5.1f}% "
                f"${s['avg$']:>+7.1f} {fmt_pf(s['pf'])} "
                f"${s['total$']:>+10,.0f}")

    # Section 3: direction split within top decile
    lines.append("\n--- 3. TOP DECILE BY DIRECTION ---")
    top = j.iloc[:n // 10]
    for d_val, d_lbl in [(1, "LONG"), (-1, "SHORT")]:
        sub_d = top[top["signal_direction"] == d_val]
        lines.append(f"\n  {d_lbl}:  n={len(sub_d):,}")
        sf = stats_forward(sub_d)
        lines.append(
            f"    forward: MFE={sf['med_mfe']:.2f}  MAE={sf['med_mae']:.2f}  "
            f"ratio={sf['med_ratio']:.2f}  "
            f"regime: WR={sf['regime_wr%']:.1f}%  "
            f"avg=${sf['regime_avg$']:+.1f}")
        for pt_r, sl_r, col, lbl_br in [
            (1.0, 1.0, "forward_pt100_before_sl100", "PT=1.0/SL=1.0"),
            (1.5, 1.0, "forward_pt150_before_sl100", "PT=1.5/SL=1.0"),
        ]:
            s = stats_bracket(sub_d, pt_r, sl_r, col)
            lines.append(
                f"    {lbl_br}: pt%={s['pt%']:.1f} sl%={s['sl%']:.1f} "
                f"WR={s['wr%']:.1f}% Avg=${s['avg$']:+.1f} "
                f"PF={fmt_pf(s['pf'])} Total=${s['total$']:+,.0f}")

    # Section 4: by decision checkpoint within top decile
    lines.append("\n--- 4. TOP DECILE BY DECISION T ---")
    top = j.iloc[:n // 10]
    lines.append(
        f"  {'T_d':>4} {'n':>5} {'med_MFE':>8} {'med_MAE':>8} "
        f"{'pt100%':>7} {'pt150%':>7} {'reg_avg$':>10}")
    lines.append("  " + "-" * 58)
    for T_d in sorted(top["decision_checkpoint_s"].unique()):
        sub_t = top[top["decision_checkpoint_s"] == T_d]
        sf = stats_forward(sub_t)
        sb100 = stats_bracket(
            sub_t, 1.0, 1.0, "forward_pt100_before_sl100")
        sb150 = stats_bracket(
            sub_t, 1.5, 1.0, "forward_pt150_before_sl100")
        lines.append(
            f"  {int(T_d):>3}s {sf['n']:>5,} "
            f"{sf['med_mfe']:>7.2f}  {sf['med_mae']:>7.2f}  "
            f"{sb100['pt%']:>6.1f}% {sb150['pt%']:>6.1f}% "
            f"${sf['regime_avg$']:>+9.1f}")

    out = "\n".join(lines)
    print(out)
    OUT_LOG.write_text(out, encoding="utf-8")
    print(f"\n  Saved: {OUT_LOG}")


if __name__ == "__main__":
    main()
