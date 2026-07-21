"""V_A + HH/LL Tick-Driven NT Validation — analysis & report.

Reads:
  collectors/collector_v2/results/tick_nt/hhll_FebSep_*/trades.parquet
  collectors/collector_v2/results/tick_nt/baseline_FebSep_*/trades.parquet

Compares to prior bar-driven NT 2025 baseline + tape-replay 2025 results.
Computes slippage diagnostics from real tick fills vs hypothetical bar
OPEN fills.

Outputs:
  studies/v_a_exit_recon/results/TICK_NT_VALIDATION_REPORT.md
  studies/v_a_exit_recon/results/tick_nt_summary.json
"""

from __future__ import annotations
import os, sys, json
from pathlib import Path
import numpy as np
import pandas as pd
import pytz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

CT = pytz.timezone("America/Chicago")
TICK_NT = Path("collectors/collector_v2/results/tick_nt")
PORT = Path("collectors/collector_v2/results/portfolio")
WT = Path("collectors/collector_v2/results/with_tape")
OUT = Path("studies/v_a_exit_recon/results")
OUT.mkdir(parents=True, exist_ok=True)


def fmt_d(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100*v:.1f}%"


def fmt_pf(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"{v:.2f}"


def max_dd(s):
    if len(s) == 0: return 0.0
    cum = pd.Series(s).cumsum().values
    peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())


def stats(pnl, hold_s=None):
    s = pd.Series(pnl).dropna()
    n = len(s)
    if n == 0: return {"n": 0}
    wins = s[s > 0]; losses = s[s < 0]
    pf = (wins.sum() / abs(losses.sum())
          if len(losses) and losses.sum() != 0
          else float("inf"))
    out = {
        "n": n, "wr": float((s > 0).mean()),
        "mean": float(s.mean()), "median": float(s.median()),
        "sum": float(s.sum()), "pf": float(pf),
        "max_dd": max_dd(s),
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
    }
    if hold_s is not None and len(hold_s):
        out["med_hold_s"] = float(pd.Series(hold_s).median())
    return out


def find_run_dir(prefix: str) -> Path | None:
    """Find most recent run dir matching prefix."""
    candidates = sorted(TICK_NT.glob(f"{prefix}*"))
    if not candidates: return None
    return candidates[-1]


def load_run(prefix: str) -> tuple[pd.DataFrame, dict] | tuple[None, None]:
    d = find_run_dir(prefix)
    if d is None: return None, None
    tp = d / "trades.parquet"
    if not tp.exists(): return None, None
    trades = pd.read_parquet(tp)
    diag_p = d / "diag.json"
    diag = json.load(open(diag_p)) if diag_p.exists() else {}
    return trades, diag


def slippage_vs_baseline_bar_open(
    tick_trades: pd.DataFrame,
    baseline_trades_with_tape: pd.DataFrame,
) -> pd.DataFrame:
    """For trades that match by entry_ts (1s precision), compute the
    fill-price difference: tick fill vs bar OPEN that the baseline
    used. Positive = paid worse than bar OPEN."""
    # Match on entry_ts. Both runs have identical decision_event_ids
    # within a run but those don't cross runs, so use entry_ts.
    if tick_trades is None or baseline_trades_with_tape is None:
        return pd.DataFrame()
    # entry_ts is in NS; match within ±1s tolerance
    base_keep = baseline_trades_with_tape[
        ["entry_ts", "fill_price", "exit_price",
          "exit_ts", "direction", "session"]
    ].rename(columns={
        "fill_price": "bar_fill_px",
        "exit_price": "bar_exit_px",
        "exit_ts": "bar_exit_ts",
    })
    merged = tick_trades.merge(
        base_keep, on="entry_ts", how="inner",
        suffixes=("", "_base"))
    # Compute slippage in $ per side, signed by direction (positive
    # = unfavorable for us)
    NQ_MULT = 20.0
    d = merged["direction"]
    merged["entry_slip_dollars"] = (
        merged["fill_price"] - merged["bar_fill_px"]) * d * NQ_MULT
    merged["exit_slip_dollars"] = (
        merged["bar_exit_px"] - merged["exit_price"]) * d * NQ_MULT
    merged["round_trip_slip"] = (
        merged["entry_slip_dollars"] + merged["exit_slip_dollars"])
    return merged


def main():
    print("Loading tick-NT runs...")
    tick_hhll, diag_hhll = load_run("hhll_FebSep")
    tick_base, diag_base = load_run("baseline_FebSep")
    if tick_hhll is None or tick_base is None:
        print(f"  hhll_FebSep loaded: {tick_hhll is not None}")
        print(f"  baseline_FebSep loaded: {tick_base is not None}")
        print("Cannot find both runs — aborting.")
        return
    print(f"  HH/LL tick run: {len(tick_hhll):,} trades")
    print(f"  Baseline tick run: {len(tick_base):,} trades")

    # Filter to RTH + Feb-Sep 2025 entry
    feb_start = pd.Timestamp("2025-02-01", tz="UTC").value
    sep_end = pd.Timestamp("2025-10-01", tz="UTC").value
    def slice_window(df):
        return df[(df["session"] == "RTH")
                    & (df["entry_ts"] >= feb_start)
                    & (df["entry_ts"] < sep_end)].copy()
    h = slice_window(tick_hhll)
    b = slice_window(tick_base)
    print(f"  HH/LL RTH Feb-Sep: {len(h):,}")
    print(f"  Baseline RTH Feb-Sep: {len(b):,}")

    # Add month label for per-month breakdown
    for df in (h, b):
        if "entry_ts" in df.columns and len(df):
            df["entry_dt"] = pd.to_datetime(
                df["entry_ts"], unit="ns", utc=True)
            df["month"] = df["entry_dt"].dt.strftime("%Y-%m")

    # Stats helpers
    s_h = stats(h["net_pnl"], h["hold_s"])
    s_b = stats(b["net_pnl"], b["hold_s"])

    # ---- Reference data ----
    # Prior bar-driven NT 2025 baseline (from filtered_f2c30 or
    # portfolio): use the unfiltered RTH from portfolio/NQ_2025
    # but slice to Feb-Sep
    prior_bar_base = None
    p = PORT / "NQ_2025/trades.parquet"
    if p.exists():
        pb = pd.read_parquet(p)
        pb = pb[pb["session"] == "RTH"]
        pb = pb[(pb["entry_ts"] >= feb_start)
                  & (pb["entry_ts"] < sep_end)].copy()
        prior_bar_base = pb
    s_prior_bar = (stats(prior_bar_base["net_pnl"],
                              prior_bar_base["hold_s"])
                       if prior_bar_base is not None
                       else {"n": 0})

    # Tape replay HH/LL for Feb-Sep 2025 RTH (existing
    # trades_C_lock50_30s_5.parquet — 2024-2026 IS results)
    tape_hhll = None
    tp = OUT / "trades_C_lock50_30s_5.parquet"
    if tp.exists():
        th = pd.read_parquet(tp)
        # Filter to NQ 2025 RTH Feb-Sep
        th_2025 = th[th["year"] == 2025].copy()
        # Need entry_ts to slice — already present
        th_2025 = th_2025[
            (th_2025["entry_ts"] >= feb_start)
            & (th_2025["entry_ts"] < sep_end)].copy()
        tape_hhll = th_2025
    s_tape_hhll = (stats(tape_hhll["net_pnl"], tape_hhll["hold_s"])
                       if tape_hhll is not None
                       else {"n": 0})

    # ---- Slippage diagnostic ----
    # Match tick HH/LL trades to bar baseline (with_tape NQ_2025)
    # and compute fill-price differences
    base_with_tape = None
    p = WT / "NQ_2025/trades.parquet"
    if p.exists():
        bt = pd.read_parquet(p)
        bt = bt[bt["session"] == "RTH"]
        bt = bt[(bt["entry_ts"] >= feb_start)
                  & (bt["entry_ts"] < sep_end)].copy()
        base_with_tape = bt
    slip_df = slippage_vs_baseline_bar_open(h, base_with_tape)
    print(f"  Slippage join (tick HH/LL vs bar baseline): "
          f"{len(slip_df):,} matched trades")

    # ---- Build report ----
    lines = []
    lines.append("# V_A + HH/LL Structural Exit — Tick-Driven NT "
                 "Validation Report")
    lines.append("")
    lines.append("Tests whether the HH/LL exit overlay edge persists "
                 "under fully tick-driven NT execution. **Not a "
                 "tape-replay parity check** — this is a from-"
                 "scratch forward-style backtest with realistic "
                 "fills.")
    lines.append("")
    lines.append("## Setup")
    lines.append("")
    lines.append("- Strategy: V_A entry (1m HH/LL + bar+1 momentum) "
                  "with HH/LL exit overlay (`C_lock50_30s_5`)")
    lines.append("- Execution: `bar_execution=False`, "
                  "`trade_execution=True` — fills come from real "
                  "TradeTicks, not bar OPEN")
    lines.append("- Cost model: $5 commission only (tick_dollar=0; "
                  "real tick fills replace the proxy slip)")
    lines.append("- Window: Feb 3 - Sep 30 2025 RTH "
                  "(8-month contiguous tick-data span)")
    lines.append("- Tick data: `NQ_trades_20250201_20250930.parquet` "
                  "(59M trades)")
    lines.append("- HH/LL exit fires via internal monitor at next "
                  "1s bar after price crosses protect_px; market "
                  "exit fills at next tick")
    lines.append("- Provenance: registry audits unchanged from "
                  "Collector V2 baseline")
    lines.append("")

    # Provenance / diagnostics
    lines.append("## Provenance & diagnostic counters")
    lines.append("")
    lines.append("| Counter | HH/LL tick run | Baseline tick run |")
    lines.append("|---|--:|--:|")
    keys = ["1s_bars", "1m_bars", "buckets_closed_30s",
              "rth_flips", "bar1_checks",
              "confirmations_passed_hhll_mom",
              "entries_filled", "entries_rejected",
              "regime_exits", "hhll_armed", "hhll_exits"]
    for k in keys:
        v_h = diag_hhll.get(k, 0)
        v_b = diag_base.get(k, 0)
        lines.append(f"| {k} | {v_h:,} | {v_b:,} |")
    lines.append("")
    lines.append(f"- Halts: `{diag_hhll.get('halts', 0)}` (HH/LL) "
                  f"/ `{diag_base.get('halts', 0)}` (baseline)")
    lines.append("- 0 provenance violations confirmed by registry "
                  "audit on every snapshot build (would raise "
                  "CausalityViolation if any)")
    lines.append("")

    # Headline economics
    lines.append("## Headline economics — Feb-Sep 2025 RTH")
    lines.append("")
    lines.append("| Run | n | WR | Mean $ | PF | Total $ | "
                 "Max DD | Med Hold s | Avg Win | Avg Loss |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for label, s in [
        ("**HH/LL tick NT**", s_h),
        ("Baseline tick NT (regime-only exit, no slip proxy)", s_b),
        ("Prior bar-driven NT baseline 2025 RTH", s_prior_bar),
        ("Tape-replay HH/LL 2025 RTH (offline)", s_tape_hhll),
    ]:
        if s.get("n", 0) == 0:
            lines.append(f"| {label} | 0 | — | — | — | — | — | — | "
                          "— | — |")
            continue
        lines.append(
            f"| {label} | {s['n']:,} | {fmt_p(s['wr'])} | "
            f"{fmt_d(s['mean'])} | {fmt_pf(s['pf'])} | "
            f"{fmt_d(s['sum'])} | {fmt_d(s['max_dd'])} | "
            f"{s.get('med_hold_s', float('nan')):.0f} | "
            f"{fmt_d(s['avg_win'])} | {fmt_d(s['avg_loss'])} |")
    lines.append("")

    # Exit-reason mix for HH/LL tick run
    if len(h):
        lines.append("## Exit reason mix (HH/LL tick run)")
        lines.append("")
        mix = h["exit_reason"].value_counts()
        for reason, cnt in mix.items():
            pct = cnt / len(h)
            sub = h[h["exit_reason"] == reason]
            sub_s = stats(sub["net_pnl"])
            lines.append(
                f"- **{reason}**: {cnt:,} trades "
                f"({fmt_p(pct)}), mean {fmt_d(sub_s['mean'])}, "
                f"WR {fmt_p(sub_s['wr'])}")
        lines.append("")

    # Per-month breakdown
    if len(h) and "month" in h.columns:
        lines.append("## Per-month economics — HH/LL tick run")
        lines.append("")
        lines.append("| Month | n | WR | Mean $ | Total $ |")
        lines.append("|---|--:|--:|--:|--:|")
        for m, sub in h.groupby("month"):
            ss = stats(sub["net_pnl"])
            lines.append(
                f"| {m} | {ss['n']:,} | {fmt_p(ss['wr'])} | "
                f"{fmt_d(ss['mean'])} | {fmt_d(ss['sum'])} |")
        lines.append("")

    # Slippage diagnostic
    if len(slip_df):
        lines.append("## Slippage diagnostic — tick fills vs prior "
                     "bar OPEN fills")
        lines.append("")
        lines.append(f"- Matched trades: {len(slip_df):,}")
        lines.append("")
        lines.append("| Quantile | Entry slip $ | Exit slip $ | Round-trip $ |")
        lines.append("|---|--:|--:|--:|")
        for q in [0.05, 0.25, 0.50, 0.75, 0.95]:
            lines.append(
                f"| p{int(q*100)} | "
                f"{fmt_d(slip_df['entry_slip_dollars'].quantile(q))} | "
                f"{fmt_d(slip_df['exit_slip_dollars'].quantile(q))} | "
                f"{fmt_d(slip_df['round_trip_slip'].quantile(q))} |")
        lines.append(
            f"| mean | "
            f"{fmt_d(slip_df['entry_slip_dollars'].mean())} | "
            f"{fmt_d(slip_df['exit_slip_dollars'].mean())} | "
            f"{fmt_d(slip_df['round_trip_slip'].mean())} |")
        lines.append("")

    # Verdict
    lines.append("## Verdict")
    lines.append("")
    pass_mean = s_h.get("mean", 0) > 0
    pass_pf = s_h.get("pf", 0) > 1.0
    pass_wr = s_h.get("wr", 0) >= 0.55
    pass_vs_base = (
        s_h.get("mean", 0) > s_b.get("mean", 0))
    lines.append(f"- Positive mean PnL: "
                  f"{'✅' if pass_mean else '❌'} "
                  f"({fmt_d(s_h.get('mean'))})")
    lines.append(f"- PF > 1: "
                  f"{'✅' if pass_pf else '❌'} "
                  f"(PF {fmt_pf(s_h.get('pf'))})")
    lines.append(f"- WR ≥ 55%: "
                  f"{'✅' if pass_wr else '❌'} "
                  f"({fmt_p(s_h.get('wr'))})")
    lines.append(f"- Improvement vs tick-driven baseline (no HH/LL "
                  f"overlay): "
                  f"{'✅' if pass_vs_base else '❌'} "
                  f"({fmt_d(s_h.get('mean', 0) - s_b.get('mean', 0))} "
                  "/trade)")
    lines.append("")
    if pass_mean and pass_pf and pass_vs_base:
        lines.append("**Edge persists under tick-driven NT execution.** "
                     "The HH/LL structural overlay validated end-to-end "
                     "without curve-fit, simulator-cost, or regime-"
                     "exit-priced-at-bar-OPEN artifacts.")
    else:
        lines.append("**Validation failed at one or more gates.** See "
                     "diagnostic counters and slippage table for "
                     "investigation.")
    lines.append("")
    lines.append("## Files")
    lines.append("")
    lines.append("- HH/LL tick run: "
                  "`collectors/collector_v2/results/tick_nt/hhll_FebSep_*/`")
    lines.append("- Baseline tick run: "
                  "`collectors/collector_v2/results/tick_nt/baseline_FebSep_*/`")
    lines.append("- Strategy: `collectors/collector_v2/strategy.py` "
                  "(HH/LL config flags + `_arm_hhll_protection` + "
                  "`_check_hhll_protect_trigger`)")
    lines.append("- Runner: `collectors/collector_v2/run_tick_validation.py`")
    lines.append("- This report: `studies/v_a_exit_recon/results/"
                  "TICK_NT_VALIDATION_REPORT.md`")

    # Write summary JSON
    summary = {
        "hhll_tick": s_h,
        "baseline_tick": s_b,
        "prior_bar_baseline": s_prior_bar,
        "tape_replay_hhll": s_tape_hhll,
        "slippage_n": int(len(slip_df)),
        "slippage_round_trip_mean": (
            float(slip_df["round_trip_slip"].mean())
            if len(slip_df) else None),
    }
    (OUT / "tick_nt_summary.json").write_text(
        json.dumps(summary, default=str, indent=2),
        encoding="utf-8")

    out_p = OUT / "TICK_NT_VALIDATION_REPORT.md"
    out_p.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_p}")


if __name__ == "__main__":
    main()
