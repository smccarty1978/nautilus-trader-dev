"""Final comparison: live March 2025 vs schedule March 2025 vs live 2026.

Tests the hypothesis that the 2024/2025 schedule-driven NT results
were inflated by survivor bias (filtering to resolved-only rows
before execution), and that the live strategy's true economics are
~flat-to-negative on BOTH 2025 and 2026 when evaluated on the full
population.
"""

from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd


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


def compute_pnl(pos: pd.DataFrame) -> dict:
    """Raw + 1-tick slippage economics."""
    pos = pos.copy()
    pos["exit_reason"] = pos.apply(classify_exit, axis=1)
    pos["pnl_raw"] = ((pos["avg_px_close"] - pos["avg_px_open"])
                        * pos["direction"] * 20.0)
    d = pos["direction"].values
    is_pt = pos["exit_reason"].values == "pt"
    entry_slip = np.where(d == 1, 0.25, -0.25)
    exit_slip = np.where(is_pt, 0.0,
                           np.where(d == 1, -0.25, 0.25))
    pos["pnl_1tick"] = ((pos["avg_px_close"].values + exit_slip
                          - (pos["avg_px_open"].values + entry_slip))
                         * d * 20.0 - 5.0)
    s = pos["pnl_1tick"].dropna()
    wins = s[s > 0]
    losses = s[s < 0]
    pt_n = int((pos["exit_reason"] == "pt").sum())
    sl_n = int((pos["exit_reason"] == "sl").sum())
    rg_n = int((pos["exit_reason"] == "regime_exit").sum())
    return {
        "n": len(s),
        "total_raw": float(pos["pnl_raw"].sum()),
        "total_1tick": float(s.sum()),
        "mean_raw": float(pos["pnl_raw"].mean()),
        "mean_1tick": float(s.mean()),
        "win_rate": float((s > 0).mean()),
        "pf": (float(wins.sum() / abs(losses.sum()))
                if len(losses) and losses.sum() != 0
                else float("inf")),
        "pt_n": pt_n,
        "sl_n": sl_n,
        "regime_n": rg_n,
        "pt_pct": pt_n / len(pos) if len(pos) else 0,
        "regime_pct": rg_n / len(pos) if len(pos) else 0,
    }


def load_nt(positions_path: Path,
             schedule_path: Path | None = None,
             trades_path: Path | None = None,
             time_filter: tuple | None = None,
             ) -> pd.DataFrame:
    """Load positions + attach direction/atr from schedule or trades."""
    p = pd.read_parquet(positions_path)
    p = p.copy()
    p["entry_ts_ns"] = p["ts_opened"].astype("int64")

    if schedule_path is not None:
        s = pd.read_parquet(schedule_path).sort_values("entry_ts_ns")
        p = pd.merge_asof(
            p.sort_values("entry_ts_ns"),
            s[["entry_ts_ns", "direction", "atr_at_signal"]],
            on="entry_ts_ns", direction="nearest",
            tolerance=60 * 1_000_000_000,
        )
    elif trades_path is not None:
        tr = pd.read_parquet(trades_path)
        tr = tr[tr["entry_fill_price"].notna()].copy()
        tr = tr.sort_values("decision_ts_ns").reset_index(drop=True)
        p = p.sort_values("entry_ts_ns").reset_index(drop=True)
        n = min(len(p), len(tr))
        p = p.iloc[:n].copy()
        p["direction"] = tr["direction"].iloc[:n].values
        p["atr_at_signal"] = tr["atr_at_signal"].iloc[:n].values

    p = p.dropna(subset=["direction", "atr_at_signal"])
    p["direction"] = p["direction"].astype(int)

    if time_filter is not None:
        lo, hi = time_filter
        p = p[(p["entry_ts_ns"] >= lo) & (p["entry_ts_ns"] <= hi)]
    return p.reset_index(drop=True)


def _d(v):
    if pd.isna(v):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def _p(v):
    if pd.isna(v):
        return "—"
    return f"{100 * v:.1f}%"


def main():
    MARCH_START = pd.Timestamp("2025-03-01", tz="UTC").value
    MARCH_END = pd.Timestamp("2025-03-31 23:59:59", tz="UTC").value

    # 1) Schedule-driven March 2025 (the "good" result)
    sched = load_nt(
        Path("backtests/good_entry_v2_bracket/results/"
              "fr_nt_runs/2025_top_15/positions.parquet"),
        schedule_path=Path(
            "backtests/good_entry_v2_bracket/results/fr_schedules/"
            "schedule_2025_top_15.parquet"),
        time_filter=(MARCH_START, MARCH_END),
    )
    m_sched = compute_pnl(sched)

    # 2) Live March 2025 (full-population)
    live_pos_path = Path(
        "studies/bracket_entry_v2/validation_2026/reconciliation_2025/"
        "nt_run_march2025/positions.parquet")
    live_tr_path = Path(
        "studies/bracket_entry_v2/validation_2026/reconciliation_2025/"
        "nt_run_march2025/strategy_trades.parquet")
    live = load_nt(
        live_pos_path,
        trades_path=live_tr_path,
    )
    m_live = compute_pnl(live)

    # 3) Live 2026 YTD (for reference)
    live_26 = load_nt(
        Path("studies/bracket_entry_v2/validation_2026/results/"
              "nt_run_t600gate/positions.parquet"),
        trades_path=Path(
            "studies/bracket_entry_v2/validation_2026/results/"
            "nt_run_t600gate/strategy_trades.parquet"),
    )
    m_26 = compute_pnl(live_26)

    lines: list[str] = []
    lines.append("# The Survivor-Bias Finding")
    lines.append("")
    lines.append("Same model, same catalog, same period (March 2025). "
                  "Only the EVALUATION protocol differs.")
    lines.append("")
    lines.append("## Comparison table")
    lines.append("")
    lines.append("| Run | n | Mean $ (1-tick) | PF | Win% | "
                  "PT% | Regime-exit% | Total $ |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    for label, m in [
        ("Mar 2025 — SCHEDULE-driven (resolved-only)", m_sched),
        ("Mar 2025 — LIVE (full population)", m_live),
        ("2026 YTD — LIVE (full population)", m_26),
    ]:
        lines.append(
            f"| {label} | {m['n']:,} | {_d(m['mean_1tick'])} | "
            f"{m['pf']:.2f} | {_p(m['win_rate'])} | "
            f"{_p(m['pt_pct'])} | {_p(m['regime_pct'])} | "
            f"{_d(m['total_1tick'])} |")
    lines.append("")

    lines.append("## Interpretation")
    lines.append("")
    if m_live["pf"] < 1.10 and m_sched["pf"] > 1.15:
        lines.append("- **Confirmed survivor bias.** The "
                      "schedule-driven Mar 2025 backtest showed "
                      f"PF {m_sched['pf']:.2f} ({_d(m_sched['mean_1tick'])} "
                      "/trade) while the live Mar 2025 evaluation — "
                      "which trades the full population the same "
                      f"model would see in deployment — shows PF "
                      f"{m_live['pf']:.2f} ({_d(m_live['mean_1tick'])} "
                      "/trade).")
        lines.append(
            "- The gap is because the schedule-driven eval "
            "pre-filtered to RESOLVED rows only. The full population "
            "includes unresolved events (bracket doesn't complete "
            "before regime flip). Those trades dominate the live "
            "path's regime-exit rate and drag down aggregate "
            "economics.")
        lines.append(
            f"- Live Mar 2025 PF ({m_live['pf']:.2f}) is similar to "
            f"Live 2026 YTD PF ({m_26['pf']:.2f}). The 2026 'failure' "
            "is not a regime shift — it's the deployment-style "
            "evaluation revealing what schedule-driven eval was "
            "masking all along.")
    elif m_live["pf"] > 1.15:
        lines.append(
            "- Live Mar 2025 still positive — not a pure "
            "survivor-bias story. 2026 is different.")
    else:
        lines.append(
            "- Mixed signal. Need more analysis.")

    out = Path("studies/bracket_entry_v2/validation_2026/"
                "reconciliation_2025/SURVIVOR_BIAS_FINDING.md")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report: {out}")

    print()
    print(f"{'Run':<55} {'n':>6} {'Mean$':>10} {'PF':>6} "
           f"{'Win%':>6} {'PT%':>6} {'Reg%':>6} {'Total$':>12}")
    for label, m in [
        ("Mar 2025 SCHEDULE (resolved-only)", m_sched),
        ("Mar 2025 LIVE (full population)", m_live),
        ("2026 YTD LIVE (full population)", m_26),
    ]:
        print(f"{label:<55} {m['n']:>6} {m['mean_1tick']:>10.2f} "
               f"{m['pf']:>6.2f} {100*m['win_rate']:>6.1f} "
               f"{100*m['pt_pct']:>6.1f} {100*m['regime_pct']:>6.1f} "
               f"{m['total_1tick']:>12,.0f}")


if __name__ == "__main__":
    main()
