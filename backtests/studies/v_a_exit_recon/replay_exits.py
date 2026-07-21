"""V_A exit reconciliation — mechanical exit-rule replay.

Loads the 1s trade tape from Collector V2 runs (NQ 2024+2025+2026
RTH) and replays a battery of mechanical exit rules per trade.
Compares each rule to baseline regime exit on per-year and aggregate
economics.

Cost model: $5 commission + $5 tick = $10/trade (matches NT runtime).

Mechanical rules tested:
  1. Baseline (regime exit, status quo)
  2. Fixed PT cap + regime fallback: PT in {0.5, 0.75, 1.0, 1.5, 2.0} ATR
  3. Trailing stop (after MFE > 0.5 ATR): trail at retracement
     {30%, 50%, 70%} of running MFE
  4. Break-even stop (after MFE > X ATR), then regime exit
  5. Time stop: exit at T = {120s, 300s, 600s} if PnL > 0
  6. Scale-out: exit half at 0.5 ATR, rest on regime exit

For each rule, recompute net PnL per trade using:
  net = (exit_px - entry_px) * direction * NQ_MULT - $10

Exit price comes from the tape row that triggers the rule, using
intra-bar resolution (high/low touch), conservative tie-breaking.
"""

from __future__ import annotations
import os, sys, json
from pathlib import Path
import numpy as np
import pandas as pd
import pytz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

CT = pytz.timezone("America/Chicago")
PORT = Path("collectors/collector_v2/results/with_tape")
OUT = Path("studies/v_a_exit_recon/results")
OUT.mkdir(parents=True, exist_ok=True)

NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0   # 1-tick slip
COST_RT = COMMISSION + TICK_COST   # $10 round-trip

YEARS = [2024, 2025, 2026]


def fmt_d(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100*v:.1f}%"


def max_dd(s):
    if len(s) == 0: return 0.0
    cum = pd.Series(s).cumsum().values
    peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())


def stats(pnl):
    s = pd.Series(pnl).dropna()
    n = len(s)
    if n == 0:
        return {"n": 0}
    wins = s[s > 0]; losses = s[s < 0]
    pf = (wins.sum() / abs(losses.sum())
          if len(losses) and losses.sum() != 0
          else float("inf"))
    return {
        "n": n, "wr": float((s > 0).mean()),
        "mean": float(s.mean()), "median": float(s.median()),
        "sum": float(s.sum()), "pf": float(pf),
        "max_dd": max_dd(s),
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
    }


def load_year(year: int):
    """Returns (trades_rth, tape_rth) for one year."""
    tdir = PORT / f"NQ_{year}"
    trades = pd.read_parquet(tdir / "trades.parquet")
    tape = pd.read_parquet(tdir / "trade_tape.parquet")
    rth = trades[trades["session"] == "RTH"].copy()
    rth_ids = set(rth["decision_event_id"])
    tape_rth = tape[tape["decision_event_id"].isin(rth_ids)].copy()
    print(f"  NQ {year}: {len(rth):,} RTH trades, "
          f"{len(tape_rth):,} tape rows")
    return rth, tape_rth


# ---------------- Exit rule replay ----------------
def replay_pt_cap(trades: pd.DataFrame, tape: pd.DataFrame,
                      pt_atr: float) -> pd.DataFrame:
    """Apply fixed PT cap; fall back to original regime exit if PT
    not hit during trade."""
    out = []
    tape_groups = tape.groupby("decision_event_id")
    for _, t in trades.iterrows():
        ev = t["decision_event_id"]
        if ev not in tape_groups.groups:
            # No tape rows (trade < 1s) — use original
            out.append(_use_original(t))
            continue
        tg = tape_groups.get_group(ev)
        ep = float(t["fill_price"])
        d = int(t["direction"])
        atr = float(t["atr_at_signal"])
        pt_dist = pt_atr * atr
        if d == 1:
            pt_px = ep + pt_dist
            hit_mask = tg["h"] >= pt_px
        else:
            pt_px = ep - pt_dist
            hit_mask = tg["l"] <= pt_px
        if hit_mask.any():
            first_hit_ts = tg.loc[hit_mask, "ts_init"].iloc[0]
            new_exit_px = pt_px
            new_exit_ts = int(first_hit_ts)
            reason = "pt_cap"
        else:
            # Fall back to regime exit
            new_exit_px = float(t["exit_price"])
            new_exit_ts = int(t["exit_ts"])
            reason = "regime"
        out.append(_finalize(t, new_exit_px, new_exit_ts, reason))
    return pd.DataFrame(out)


def replay_trailing(trades: pd.DataFrame, tape: pd.DataFrame,
                       activate_atr: float,
                       trail_pct: float) -> pd.DataFrame:
    """Trailing stop: after MFE >= activate_atr * atr, exit when
    pnl retraces by trail_pct of running MFE.

    Implementation: for each trade, walk the tape. Track
    running_mfe_pts. Once running_mfe_pts >= activate_atr * atr,
    arm the trail. Exit at first row where pnl_pts <= mfe_pts *
    (1 - trail_pct). Exit price = current close.

    If never armed or never triggered, fall back to regime exit."""
    out = []
    tape_groups = tape.groupby("decision_event_id")
    for _, t in trades.iterrows():
        ev = t["decision_event_id"]
        if ev not in tape_groups.groups:
            out.append(_use_original(t))
            continue
        tg = tape_groups.get_group(ev)
        atr = float(t["atr_at_signal"])
        activate_pts = activate_atr * atr
        mfe = tg["mfe_pts"].values
        pnl = tg["pnl_pts"].values
        c = tg["c"].values
        ts = tg["ts_init"].values
        triggered_idx = -1
        armed = False
        for i in range(len(tg)):
            if not armed and mfe[i] >= activate_pts:
                armed = True
            if armed:
                # Exit if pnl drops below mfe_at_arm_or_later *
                # (1 - trail_pct). Use the running mfe (always
                # increasing).
                if pnl[i] <= mfe[i] * (1 - trail_pct):
                    triggered_idx = i; break
        if triggered_idx >= 0:
            ep = float(t["fill_price"])
            d = int(t["direction"])
            new_exit_px = float(c[triggered_idx])
            new_exit_ts = int(ts[triggered_idx])
            reason = "trail"
        else:
            new_exit_px = float(t["exit_price"])
            new_exit_ts = int(t["exit_ts"])
            reason = "regime"
        out.append(_finalize(t, new_exit_px, new_exit_ts, reason))
    return pd.DataFrame(out)


def replay_be_then_regime(trades: pd.DataFrame, tape: pd.DataFrame,
                              activate_atr: float) -> pd.DataFrame:
    """Move stop to break-even after MFE >= activate_atr * atr.
    Once armed, exit at break-even if price retraces to entry.
    Otherwise regime exit."""
    out = []
    tape_groups = tape.groupby("decision_event_id")
    for _, t in trades.iterrows():
        ev = t["decision_event_id"]
        if ev not in tape_groups.groups:
            out.append(_use_original(t))
            continue
        tg = tape_groups.get_group(ev)
        ep = float(t["fill_price"])
        d = int(t["direction"])
        atr = float(t["atr_at_signal"])
        activate_pts = activate_atr * atr
        mfe = tg["mfe_pts"].values
        h = tg["h"].values; l = tg["l"].values
        ts = tg["ts_init"].values
        triggered_idx = -1
        armed = False
        for i in range(len(tg)):
            if not armed and mfe[i] >= activate_pts:
                armed = True; continue
            if armed:
                if d == 1 and l[i] <= ep:
                    triggered_idx = i; break
                if d == -1 and h[i] >= ep:
                    triggered_idx = i; break
        if triggered_idx >= 0:
            new_exit_px = float(ep)   # exit at break-even
            new_exit_ts = int(ts[triggered_idx])
            reason = "be_stop"
        else:
            new_exit_px = float(t["exit_price"])
            new_exit_ts = int(t["exit_ts"])
            reason = "regime"
        out.append(_finalize(t, new_exit_px, new_exit_ts, reason))
    return pd.DataFrame(out)


def replay_time_stop_if_winning(trades: pd.DataFrame,
                                     tape: pd.DataFrame,
                                     time_s: float) -> pd.DataFrame:
    """At elapsed_s = time_s, if pnl > 0 exit at the bar's close.
    Otherwise hold to regime exit."""
    out = []
    tape_groups = tape.groupby("decision_event_id")
    for _, t in trades.iterrows():
        ev = t["decision_event_id"]
        if ev not in tape_groups.groups:
            out.append(_use_original(t))
            continue
        tg = tape_groups.get_group(ev)
        # Find first row with elapsed_s >= time_s
        mask = tg["elapsed_s"] >= time_s
        if not mask.any():
            new_exit_px = float(t["exit_price"])
            new_exit_ts = int(t["exit_ts"])
            reason = "regime"
        else:
            row = tg[mask].iloc[0]
            if row["pnl_pts"] > 0:
                new_exit_px = float(row["c"])
                new_exit_ts = int(row["ts_init"])
                reason = "time_stop_w"
            else:
                new_exit_px = float(t["exit_price"])
                new_exit_ts = int(t["exit_ts"])
                reason = "regime"
        out.append(_finalize(t, new_exit_px, new_exit_ts, reason))
    return pd.DataFrame(out)


def _use_original(t):
    """No-op: keep original regime exit."""
    return _finalize(t, float(t["exit_price"]),
                      int(t["exit_ts"]), "regime_orig")


def _finalize(t, exit_px, exit_ts, reason):
    d = int(t["direction"])
    ep = float(t["fill_price"])
    gross = (exit_px - ep) * d * NQ_MULT
    net = gross - COST_RT
    return {
        "decision_event_id": int(t["decision_event_id"]),
        "year": int(pd.Timestamp(int(t["entry_ts"]),
                                       tz="UTC").tz_convert(CT).year),
        "entry_ts": int(t["entry_ts"]),
        "exit_ts": int(exit_ts),
        "fill_price": float(ep),
        "exit_price": float(exit_px),
        "direction": d,
        "atr_at_signal": float(t["atr_at_signal"]),
        "gross_pnl": float(gross),
        "net_pnl": float(net),
        "hold_s": (exit_ts - int(t["entry_ts"])) / 1e9,
        "exit_reason": reason,
    }


# ---------------- Analysis ----------------
def per_year_summary(rule_name: str, df: pd.DataFrame) -> dict:
    out = {"rule": rule_name}
    for yr in YEARS:
        sub = df[df["year"] == yr]
        s = stats(sub["net_pnl"])
        out[f"yr_{yr}_n"] = s.get("n", 0)
        out[f"yr_{yr}_wr"] = s.get("wr")
        out[f"yr_{yr}_mean"] = s.get("mean")
        out[f"yr_{yr}_pf"] = s.get("pf")
        out[f"yr_{yr}_total"] = s.get("sum")
        out[f"yr_{yr}_dd"] = s.get("max_dd")
    s_all = stats(df["net_pnl"])
    out["all_n"] = s_all.get("n", 0)
    out["all_wr"] = s_all.get("wr")
    out["all_mean"] = s_all.get("mean")
    out["all_pf"] = s_all.get("pf")
    out["all_total"] = s_all.get("sum")
    out["all_dd"] = s_all.get("max_dd")
    out["med_hold_s"] = float(df["hold_s"].median())
    return out


def fmt_pf(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"{v:.2f}"


def main():
    print("Loading 3 years of trades + tape...")
    all_trades = []
    all_tape = []
    for yr in YEARS:
        rth, tape_rth = load_year(yr)
        all_trades.append(rth)
        all_tape.append(tape_rth)
    trades = pd.concat(all_trades, ignore_index=True)
    tape = pd.concat(all_tape, ignore_index=True)
    print(f"\nTotal: {len(trades):,} trades, "
          f"{len(tape):,} tape rows")

    # ---- Build rule list ----
    print("\nReplaying mechanical exit rules...")
    rules = {}

    # Baseline = original regime exits, recomputed using same cost
    baseline_rows = [
        _finalize(t, float(t["exit_price"]),
                   int(t["exit_ts"]), "regime")
        for _, t in trades.iterrows()
    ]
    rules["00_baseline_regime"] = pd.DataFrame(baseline_rows)
    print("  baseline done")

    for pt in [0.50, 0.75, 1.00, 1.50, 2.00]:
        rules[f"01_pt_cap_{pt:.2f}atr"] = replay_pt_cap(
            trades, tape, pt)
        print(f"  pt_cap {pt} done")

    for act in [0.50, 1.00]:
        for pct in [0.30, 0.50, 0.70]:
            rules[
                f"02_trail_act{act:.2f}_pct{pct:.2f}"
            ] = replay_trailing(trades, tape, act, pct)
        print(f"  trail act={act} done")

    for act in [0.50, 1.00, 1.50]:
        rules[f"03_be_stop_act{act:.2f}"] = replay_be_then_regime(
            trades, tape, act)
    print("  be_stop done")

    for tsec in [120, 300, 600]:
        rules[
            f"04_time_winner_{tsec}s"
        ] = replay_time_stop_if_winning(trades, tape, tsec)
    print("  time_stop_winner done")

    # ---- Build summary ----
    summary_rows = []
    for name, df in rules.items():
        df["year"] = df["year"].astype(int)
        summary_rows.append(per_year_summary(name, df))
    summ = pd.DataFrame(summary_rows)
    summ.to_parquet(OUT / "exit_rules_summary.parquet",
                       index=False)

    # Save per-rule trade results
    for name, df in rules.items():
        df.to_parquet(OUT / f"trades_{name}.parquet", index=False)

    # ---- Report markdown ----
    lines = []
    lines.append("# V_A Exit Reconciliation — Mechanical Rules vs "
                 "Regime Exit")
    lines.append("")
    lines.append("Tests whether any mechanical exit rule outperforms "
                 "the lagging regime-flip exit on the V_A trade "
                 "population (NQ 2024+2025+2026 RTH).")
    lines.append("")
    lines.append(f"- Population: {len(trades):,} unfiltered V_A "
                  "trades (NQ 2024+2025+2026 RTH)")
    lines.append(f"- Tape: {len(tape):,} per-1s-bar rows during "
                  "open trades")
    lines.append("- Cost: $5 commission + $5 tick = $10 round-trip")
    lines.append("- Each rule re-uses the SAME entry. Only exit "
                  "logic changes.")
    lines.append("- Exit-rule precedence: rule fires first → use "
                  "rule's exit. Otherwise → fall back to regime exit.")
    lines.append("")

    lines.append("## Rule scoreboard — per-year mean $/trade")
    lines.append("")
    lines.append("| Rule | n | Med Hold s | "
                 "2024 mean / total | "
                 "2025 mean / total | "
                 "2026 mean / total | "
                 "All mean | All total | All PF | All WR |")
    lines.append(
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for r in summary_rows:
        lines.append(
            f"| {r['rule']} | {r['all_n']:,} | "
            f"{r['med_hold_s']:.0f} | "
            f"{fmt_d(r.get('yr_2024_mean'))} / "
            f"{fmt_d(r.get('yr_2024_total'))} | "
            f"{fmt_d(r.get('yr_2025_mean'))} / "
            f"{fmt_d(r.get('yr_2025_total'))} | "
            f"{fmt_d(r.get('yr_2026_mean'))} / "
            f"{fmt_d(r.get('yr_2026_total'))} | "
            f"{fmt_d(r['all_mean'])} | "
            f"{fmt_d(r['all_total'])} | "
            f"{fmt_pf(r['all_pf'])} | "
            f"{fmt_p(r['all_wr'])} |")
    lines.append("")

    # Δ vs baseline
    base = next(r for r in summary_rows
                  if r["rule"] == "00_baseline_regime")
    lines.append("## Δ vs baseline (rule – baseline)")
    lines.append("")
    lines.append("| Rule | Δ 2024 mean | Δ 2025 mean | Δ 2026 mean | "
                 "Δ All mean | Δ All total |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    for r in summary_rows:
        if r["rule"] == "00_baseline_regime": continue
        d24 = r.get("yr_2024_mean", 0) - base.get("yr_2024_mean", 0)
        d25 = r.get("yr_2025_mean", 0) - base.get("yr_2025_mean", 0)
        d26 = r.get("yr_2026_mean", 0) - base.get("yr_2026_mean", 0)
        dall = r.get("all_mean", 0) - base.get("all_mean", 0)
        dtot = r.get("all_total", 0) - base.get("all_total", 0)
        lines.append(
            f"| {r['rule']} | {fmt_d(d24)} | {fmt_d(d25)} | "
            f"{fmt_d(d26)} | {fmt_d(dall)} | {fmt_d(dtot)} |")
    lines.append("")

    # Years positive count
    lines.append("## Years positive per rule")
    lines.append("")
    lines.append("| Rule | Yrs +mean | 2024 ✓? | 2025 ✓? | 2026 ✓? |")
    lines.append("|---|--:|---|---|---|")
    for r in summary_rows:
        yrs_pos = sum(
            1 for yr in YEARS
            if r.get(f"yr_{yr}_mean") is not None
            and r[f"yr_{yr}_mean"] > 0)
        marks = []
        for yr in YEARS:
            v = r.get(f"yr_{yr}_mean")
            marks.append("✅" if v is not None and v > 0 else "❌")
        lines.append(f"| {r['rule']} | {yrs_pos}/3 | "
                      + " | ".join(marks) + " |")
    lines.append("")

    # Best rule by aggregate
    best = max([r for r in summary_rows if r["all_n"] > 0],
                key=lambda r: r["all_total"])
    base_total = base["all_total"]
    best_delta = best["all_total"] - base_total
    lines.append("## Best rule by 3-year aggregate total $")
    lines.append("")
    lines.append(f"- **{best['rule']}**: total {fmt_d(best['all_total'])} "
                  f"(Δ vs baseline {fmt_d(best_delta)})")
    lines.append(f"- Baseline (regime exit): total "
                  f"{fmt_d(base_total)}")
    lines.append("")

    out_p = OUT / "EXIT_RECON_REPORT.md"
    out_p.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_p}")


if __name__ == "__main__":
    main()
