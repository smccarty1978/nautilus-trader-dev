"""Conditioned winner-harvest exit-rule replay.

5 rules × 3 checkpoints (T = 300s, 600s, 900s) = 15 variants
plus baseline (regime exit) and time_winner_600s reference.

Each rule fires ONLY when pnl > 0 at checkpoint T. Conditions:
  A: no new MFE peak in last 120s
  B: last 60s net move against trade direction
  C: MFE >= 1.0 ATR AND giveback from MFE >= 0.50 ATR
  D: MFE >= 1.0 ATR AND time since MFE peak >= 120s
  E: 30s regime flipped against trade OR last-60s directional
     efficiency against trade >= 0.30

Inputs: existing trade tape from collectors/collector_v2/results/
with_tape/NQ_<year>/. No new NT runs.

Cost model: $5 commission + $5 tick = $10/round-trip.

Per-rule outputs:
  - mean $, PF, total $, max DD per year + aggregate
  - % trades exited early (vs fell through to regime)
  - damage to original winners (sum of pnl reduction on baseline-positive trades)
  - improvement to original losers (sum of pnl gain on baseline-negative trades)
  - top-1% contribution
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
COST_RT = 10.0
YEARS = [2024, 2025, 2026]
CHECKPOINTS = [300, 600, 900]


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
    }


# ---------------- Tape pre-computation ----------------
def precompute_tape_helpers(tape: pd.DataFrame) -> pd.DataFrame:
    """Add per-trade derived columns:
      - row_idx (within trade)
      - mfe_peak_ts: ts at which current running mfe_pts was first set
      - 60s lookback close, 120s lookback mfe
      - 60s signed sum + abs sum (last 60 1s deltas, in trade dir)
    Operates per-trade group. Uses sort_values to ensure
    chronological order."""
    tape = tape.sort_values(
        ["trade_id", "ts_init"]).reset_index(drop=True)
    out_groups = []
    for ev, g in tape.groupby("trade_id", sort=False):
        g = g.copy().reset_index(drop=True)
        g["row_idx"] = np.arange(len(g))

        # mfe_peak_ts: first ts where mfe_pts equals its running max
        # (running max of mfe_pts is mfe_pts itself, since mfe_pts
        #  is monotone non-decreasing per trade)
        # So the LAST row where mfe was strictly increased is the
        # peak update; for ANY row, the peak ts is the most recent
        # row where mfe_pts changed value.
        g["mfe_diff"] = g["mfe_pts"].diff().fillna(g["mfe_pts"])
        # rows where mfe increased (or seeded)
        peak_update_mask = g["mfe_diff"] > 0
        # Forward-fill the ts of the most recent update
        update_ts = g["ts_init"].where(peak_update_mask)
        g["mfe_peak_ts"] = update_ts.ffill().fillna(g["ts_init"])

        # 60s and 120s lookback by elapsed_s (1s steps mostly)
        # use elapsed_s directly. searchsorted into elapsed_s
        elapsed = g["elapsed_s"].values
        c = g["c"].values
        mfe = g["mfe_pts"].values
        # close 60s ago
        idx_60 = np.searchsorted(elapsed, elapsed - 60.0,
                                       side="right") - 1
        idx_60 = np.clip(idx_60, 0, len(elapsed) - 1)
        g["close_60s_ago"] = c[idx_60]
        # mfe 120s ago
        idx_120 = np.searchsorted(elapsed, elapsed - 120.0,
                                        side="right") - 1
        idx_120 = np.clip(idx_120, 0, len(elapsed) - 1)
        g["mfe_120s_ago"] = mfe[idx_120]

        # 60s directional efficiency: signed sum of 1s c-c[i-1]
        # divided by abs sum, computed over rolling-60s window.
        # Use 1s diffs (they're per-second since tape rows are
        # roughly 1s apart in continuous trade time).
        diffs = np.diff(c, prepend=c[0])
        d_int = int(g["direction"].iloc[0])
        signed = diffs * d_int
        # rolling 60-row window (approximates 60s)
        s_signed = pd.Series(signed)
        s_abs = pd.Series(np.abs(diffs))
        roll_signed = s_signed.rolling(60, min_periods=10).sum()
        roll_abs = s_abs.rolling(60, min_periods=10).sum()
        eff = roll_signed / roll_abs.replace(0, np.nan)
        g["dir_eff_60s"] = eff.fillna(0).values

        out_groups.append(g)
    return pd.concat(out_groups, ignore_index=True)


# ---------------- Rule evaluation ----------------
def find_checkpoint_row(g: pd.DataFrame,
                            T: float) -> pd.Series | None:
    """Return the first tape row at elapsed_s >= T, else None."""
    mask = g["elapsed_s"] >= T
    if not mask.any(): return None
    return g[mask].iloc[0]


def eval_rule_a(row, g, T) -> bool:
    """Winner + no new MFE peak in last 120s."""
    if row["pnl_pts"] <= 0: return False
    return float(row["mfe_pts"]) <= float(row["mfe_120s_ago"])


def eval_rule_b(row, g, T) -> bool:
    """Winner + last 60s net move against trade direction."""
    if row["pnl_pts"] <= 0: return False
    d = int(row["direction"])
    last_60s_net = (float(row["c"])
                       - float(row["close_60s_ago"])) * d
    return last_60s_net < 0


def eval_rule_c(row, g, T) -> bool:
    """Winner + MFE >= 1.0 ATR + giveback from MFE >= 0.50 ATR."""
    if row["pnl_pts"] <= 0: return False
    atr = float(row["atr_at_signal"])
    mfe_atr = float(row["mfe_pts"]) / atr
    if mfe_atr < 1.0: return False
    giveback_atr = (float(row["mfe_pts"])
                       - float(row["pnl_pts"])) / atr
    return giveback_atr >= 0.50


def eval_rule_d(row, g, T) -> bool:
    """Winner + MFE >= 1.0 ATR + time since MFE peak >= 120s."""
    if row["pnl_pts"] <= 0: return False
    atr = float(row["atr_at_signal"])
    mfe_atr = float(row["mfe_pts"]) / atr
    if mfe_atr < 1.0: return False
    time_since_peak_ns = (int(row["ts_init"])
                            - int(row["mfe_peak_ts"]))
    return time_since_peak_ns >= 120 * 1_000_000_000


def eval_rule_e(row, g, T,
                   regime_30s_at_T: int) -> bool:
    """Winner + 30s regime flipped against trade OR last-60s
    directional efficiency <= -0.30."""
    if row["pnl_pts"] <= 0: return False
    d = int(row["direction"])
    regime_against = (regime_30s_at_T != 0
                          and regime_30s_at_T != d)
    if regime_against: return True
    return float(row["dir_eff_60s"]) <= -0.30


def replay_rule(trades: pd.DataFrame, tape: pd.DataFrame,
                  rule_name: str, T: float,
                  regime_30s_lookup: dict | None = None
                  ) -> pd.DataFrame:
    """Replay a single conditioned rule. Returns per-trade results
    with new exit + reason."""
    out = []
    tape_groups = tape.groupby("trade_id", sort=False)
    for _, t in trades.iterrows():
        ev = int(t["trade_id"])
        if ev not in tape_groups.groups:
            out.append(_use_original(t, T))
            continue
        g = tape_groups.get_group(ev)
        row = find_checkpoint_row(g, T)
        if row is None:
            # Trade ended before checkpoint — keep original
            out.append(_use_original(t, T))
            continue
        # Evaluate rule condition
        if rule_name == "A_no_new_mfe_120s":
            fired = eval_rule_a(row, g, T)
        elif rule_name == "B_adverse_60s_momentum":
            fired = eval_rule_b(row, g, T)
        elif rule_name == "C_giveback_from_mfe":
            fired = eval_rule_c(row, g, T)
        elif rule_name == "D_stalled_after_mfe":
            fired = eval_rule_d(row, g, T)
        elif rule_name == "E_ltf_deterioration":
            r30 = (regime_30s_lookup.get((ev, T))
                   if regime_30s_lookup else 0)
            fired = eval_rule_e(row, g, T, r30 if r30 is not None
                                       else 0)
        else:
            raise ValueError(f"unknown rule: {rule_name}")

        if fired:
            new_exit_px = float(row["c"])
            new_exit_ts = int(row["ts_init"])
            reason = f"{rule_name}_T{int(T)}"
            out.append(_finalize(t, new_exit_px, new_exit_ts,
                                       reason, fired_rule=True))
        else:
            out.append(_use_original(t, T))
    return pd.DataFrame(out)


def _use_original(t, T):
    return _finalize(t, float(t["exit_price"]),
                       int(t["exit_ts"]), "regime",
                       fired_rule=False)


def _finalize(t, exit_px, exit_ts, reason, fired_rule):
    d = int(t["direction"])
    ep = float(t["fill_price"])
    gross = (exit_px - ep) * d * NQ_MULT
    net = gross - COST_RT
    return {
        "trade_id": int(t.get("trade_id",
                                  t.get("decision_event_id", -1))),
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
        "fired_rule": bool(fired_rule),
        "baseline_net_pnl": float(t["baseline_net_pnl"]),
    }


# ---------------- Reporting helpers ----------------
def attribution_summary(rule_df: pd.DataFrame) -> dict:
    """Decompose Δ vs baseline into damage + improvement."""
    # rule_df has both new net_pnl and baseline_net_pnl per trade
    d = rule_df["net_pnl"] - rule_df["baseline_net_pnl"]
    # Damage to original winners: baseline > 0 AND new < baseline
    base_win_mask = rule_df["baseline_net_pnl"] > 0
    base_loss_mask = rule_df["baseline_net_pnl"] < 0
    damage_to_winners = float(
        d[base_win_mask & (d < 0)].sum())
    improvement_to_losers = float(
        d[base_loss_mask & (d > 0)].sum())
    return {
        "delta_total": float(d.sum()),
        "damage_to_orig_winners": damage_to_winners,
        "improvement_to_orig_losers": improvement_to_losers,
    }


def per_year_summary(rule_label: str,
                          df: pd.DataFrame) -> dict:
    out = {"rule": rule_label}
    for yr in YEARS:
        sub = df[df["year"] == yr]
        s = stats(sub["net_pnl"])
        out[f"y{yr}_n"] = s.get("n", 0)
        out[f"y{yr}_mean"] = s.get("mean")
        out[f"y{yr}_pf"] = s.get("pf")
        out[f"y{yr}_total"] = s.get("sum")
        out[f"y{yr}_dd"] = s.get("max_dd")
        attr = attribution_summary(sub)
        out[f"y{yr}_damage"] = attr["damage_to_orig_winners"]
        out[f"y{yr}_improve"] = attr["improvement_to_orig_losers"]
    s_all = stats(df["net_pnl"])
    out["all_n"] = s_all.get("n", 0)
    out["all_mean"] = s_all.get("mean")
    out["all_pf"] = s_all.get("pf")
    out["all_total"] = s_all.get("sum")
    out["all_dd"] = s_all.get("max_dd")
    out["pct_fired"] = float(df["fired_rule"].mean())
    # top-1% contribution
    s = df["net_pnl"].sort_values(ascending=False)
    top1 = s.head(max(1, int(len(s) * 0.01))).sum()
    total = s.sum()
    out["top1_pct_share"] = (
        float(top1 / total) if total != 0 else float("nan"))
    return out


def fmt_pf(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"{v:.2f}"


# ---------------- Main ----------------
def main():
    print("Loading 3 years of trades + tape + path_checkpoints...")
    all_trades = []; all_tape = []
    regime_30s_lookup: dict = {}
    for yr in YEARS:
        d = PORT / f"NQ_{yr}"
        trades = pd.read_parquet(d / "trades.parquet")
        tape = pd.read_parquet(d / "trade_tape.parquet")
        snaps = pd.read_parquet(d / "snapshots.parquet")
        rth = trades[trades["session"] == "RTH"].copy()
        rth_ids = set(rth["decision_event_id"])
        tape_rth = tape[tape["decision_event_id"].isin(rth_ids)].copy()
        # Globally-unique trade_id (decision_event_id is per-run
        # counter and collides across years)
        OFFSET = yr * 1_000_000
        rth["trade_id"] = rth["decision_event_id"] + OFFSET
        tape_rth["trade_id"] = (
            tape_rth["decision_event_id"] + OFFSET)
        # path_checkpoints with regime_30s
        cp = snaps[snaps["kind"] == "path_checkpoint"].copy()
        cp = cp[cp["trade_event_id"].isin(rth_ids)]
        cp["trade_id"] = cp["trade_event_id"] + OFFSET
        for tid in rth["trade_id"]:
            ev_cp = cp[cp["trade_id"] == tid]
            if len(ev_cp) == 0: continue
            for T in CHECKPOINTS:
                gap = (ev_cp["elapsed_s"] - T).abs()
                if gap.min() > 35:
                    continue
                idx = gap.idxmin()
                regime_30s_lookup[(int(tid), T)] = int(
                    ev_cp.loc[idx, "regime_30s"])
        rth["baseline_net_pnl"] = rth["net_pnl"]
        all_trades.append(rth)
        all_tape.append(tape_rth)
        print(f"  NQ {yr}: {len(rth):,} RTH trades, "
              f"{len(tape_rth):,} tape rows, "
              f"{(cp['trade_event_id'].isin(rth_ids)).sum():,} cp")
    trades = pd.concat(all_trades, ignore_index=True)
    tape = pd.concat(all_tape, ignore_index=True)
    print(f"\nTotal: {len(trades):,} trades, {len(tape):,} tape rows")
    print(f"regime_30s lookup: {len(regime_30s_lookup):,} entries")

    # Pre-compute tape helpers
    print("\nPre-computing tape helpers (mfe_peak_ts, lookbacks, "
          "60s eff)...")
    tape = precompute_tape_helpers(tape)
    print(f"Tape now has {len(tape.columns)} columns")

    # Replay all 5 rules x 3 checkpoints
    rules_summary = []
    rules_data = {}
    print("\nReplaying conditioned-harvest rules...")

    # Baseline (for reference)
    baseline_rows = [
        _finalize(t, float(t["exit_price"]),
                   int(t["exit_ts"]), "regime",
                   fired_rule=False)
        for _, t in trades.iterrows()
    ]
    base_df = pd.DataFrame(baseline_rows)
    rules_summary.append(per_year_summary(
        "BASELINE_regime", base_df))
    rules_data["BASELINE_regime"] = base_df

    # time_winner_600s reference. decision_event_id is NOT unique
    # across years (per-run counter), so join on entry_ts instead.
    print("  loading time_winner_600s reference...")
    ref = pd.read_parquet(
        OUT / "trades_04_time_winner_600s.parquet")
    ts_to_baseline = (
        trades.set_index("entry_ts")["baseline_net_pnl"]
        .to_dict())
    ref["baseline_net_pnl"] = ref["entry_ts"].map(ts_to_baseline)
    ref["fired_rule"] = (ref["exit_reason"] == "time_stop_w")
    rules_summary.append(per_year_summary(
        "REF_time_winner_600s", ref))
    rules_data["REF_time_winner_600s"] = ref

    rule_names = [
        "A_no_new_mfe_120s",
        "B_adverse_60s_momentum",
        "C_giveback_from_mfe",
        "D_stalled_after_mfe",
        "E_ltf_deterioration",
    ]
    for rule in rule_names:
        for T in CHECKPOINTS:
            label = f"{rule}_T{T}"
            df = replay_rule(trades, tape, rule, T,
                                  regime_30s_lookup=regime_30s_lookup)
            df.to_parquet(OUT / f"trades_{label}.parquet",
                            index=False)
            rules_summary.append(per_year_summary(label, df))
            rules_data[label] = df
            print(f"  {label}: fired on "
                  f"{df['fired_rule'].sum():,}/{len(df):,} trades, "
                  f"mean ${df['net_pnl'].mean():.2f}")

    # Save summary
    summ_df = pd.DataFrame(rules_summary)
    summ_df.to_parquet(
        OUT / "conditioned_harvest_summary.parquet", index=False)

    # ---------------- Markdown report ----------------
    lines = []
    lines.append("# Conditioned Winner-Harvest Exit Rules — "
                 "NQ 2024-2026 RTH")
    lines.append("")
    lines.append("Five conditioned exit rules tested at three "
                 "checkpoints (T=300s, 600s, 900s) using the "
                 "existing trade tape. Rule fires only when "
                 "`pnl > 0` at checkpoint AND rule-specific "
                 "condition holds. Otherwise fall through to "
                 "regime exit.")
    lines.append("")
    lines.append("**Rules**:")
    lines.append("- **A**: no new MFE peak in last 120s")
    lines.append("- **B**: last 60s net move against trade direction")
    lines.append("- **C**: MFE ≥ 1.0 ATR AND giveback from MFE ≥ 0.50 ATR")
    lines.append("- **D**: MFE ≥ 1.0 ATR AND time since MFE peak ≥ 120s")
    lines.append("- **E**: 30s regime flipped against trade OR "
                 "rolling 60s directional efficiency ≤ -0.30")
    lines.append("")
    lines.append("Reference rows: baseline regime exit + "
                 "`04_time_winner_600s` (the blunt prior winner).")
    lines.append("")

    lines.append("## Per-rule per-year scoreboard")
    lines.append("")
    lines.append("| Rule | %fired | "
                 "2024 mean / total / dmg→winners / impr→losers | "
                 "2025 mean / total / dmg / impr | "
                 "2026 mean / total / dmg / impr | "
                 "All mean | All total | All PF | Top-1% share |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for r in rules_summary:
        lines.append(
            f"| {r['rule']} | {fmt_p(r.get('pct_fired', 0))} | "
            f"{fmt_d(r.get('y2024_mean'))} / "
            f"{fmt_d(r.get('y2024_total'))} / "
            f"{fmt_d(r.get('y2024_damage'))} / "
            f"{fmt_d(r.get('y2024_improve'))} | "
            f"{fmt_d(r.get('y2025_mean'))} / "
            f"{fmt_d(r.get('y2025_total'))} / "
            f"{fmt_d(r.get('y2025_damage'))} / "
            f"{fmt_d(r.get('y2025_improve'))} | "
            f"{fmt_d(r.get('y2026_mean'))} / "
            f"{fmt_d(r.get('y2026_total'))} / "
            f"{fmt_d(r.get('y2026_damage'))} / "
            f"{fmt_d(r.get('y2026_improve'))} | "
            f"{fmt_d(r['all_mean'])} | "
            f"{fmt_d(r['all_total'])} | "
            f"{fmt_pf(r['all_pf'])} | "
            f"{fmt_p(r['top1_pct_share'])} |")
    lines.append("")

    # Δ vs baseline regime
    base = next(r for r in rules_summary
                  if r["rule"] == "BASELINE_regime")
    lines.append("## Δ vs baseline regime exit")
    lines.append("")
    lines.append("| Rule | Δ 2024 | Δ 2025 | Δ 2026 | "
                 "Δ All | Δ All total |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    for r in rules_summary:
        if r["rule"] == "BASELINE_regime": continue
        d24 = r["y2024_mean"] - base["y2024_mean"]
        d25 = r["y2025_mean"] - base["y2025_mean"]
        d26 = r["y2026_mean"] - base["y2026_mean"]
        dall = r["all_mean"] - base["all_mean"]
        dtot = r["all_total"] - base["all_total"]
        lines.append(
            f"| {r['rule']} | {fmt_d(d24)} | {fmt_d(d25)} | "
            f"{fmt_d(d26)} | {fmt_d(dall)} | {fmt_d(dtot)} |")
    lines.append("")

    # Years positive
    lines.append("## Years positive per rule")
    lines.append("")
    lines.append("| Rule | Yrs +mean | 2024 ✓? | 2025 ✓? | 2026 ✓? |")
    lines.append("|---|--:|---|---|---|")
    for r in rules_summary:
        yrs_pos = sum(1 for yr in YEARS
                          if r.get(f"y{yr}_mean") is not None
                          and r[f"y{yr}_mean"] > 0)
        marks = ["✅" if r.get(f"y{yr}_mean", 0) > 0 else "❌"
                  for yr in YEARS]
        lines.append(f"| {r['rule']} | {yrs_pos}/3 | "
                      + " | ".join(marks) + " |")
    lines.append("")

    out_p = OUT / "CONDITIONED_HARVEST_REPORT.md"
    out_p.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_p}")


if __name__ == "__main__":
    main()
