"""HH/LL Progression Exit OOS validation — NQ 2020-2023 RTH.

Re-applies the top 5 HH/LL rules from the in-sample study to four
unseen years. No tuning. Same rule definitions, same cost model,
same tape-replay method.

Rules tested:
  - C_lock50_30s_5  (best in-sample)
  - C_lock50_5s_20
  - B_be_30s_5
  - C_lock50_30s_3
  - C_lock25_30s_5

Output:
  HHLL_OOS_2020_2023_REPORT.md
  per-rule per-trade parquets (oos_<rule>.parquet)
"""

from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

# Reuse precomputation + replay functions from the in-sample
# script. Avoid copying logic.
from studies.v_a_exit_recon.hhll_progression import (
    precompute_progression,
    replay_family_a, replay_family_b, replay_family_c,
    _use_original, _finalize, stats, max_dd,
    fmt_d, fmt_p, fmt_pf,
)

CT = pytz.timezone("America/Chicago")
PORT = Path("collectors/collector_v2/results/with_tape")
OUT = Path("studies/v_a_exit_recon/results")
NQ_MULT = 20.0
COST_RT = 10.0

OOS_YEARS = [2020, 2021, 2022, 2023]
IS_YEARS = [2024, 2025, 2026]

RULES = [
    # (name, family_callable, kwargs)
    ("C_lock50_30s_5",
     "C", {"granularity_col": "bars_since_new_30s_buckets",
            "stall_bars": 5, "lock_pct": 0.50}),
    ("C_lock50_5s_20",
     "C", {"granularity_col": "bars_since_new_5s_buckets",
            "stall_bars": 20, "lock_pct": 0.50}),
    ("B_be_30s_5",
     "B", {"granularity_col": "bars_since_new_30s_buckets",
            "stall_bars": 5}),
    ("C_lock50_30s_3",
     "C", {"granularity_col": "bars_since_new_30s_buckets",
            "stall_bars": 3, "lock_pct": 0.50}),
    ("C_lock25_30s_5",
     "C", {"granularity_col": "bars_since_new_30s_buckets",
            "stall_bars": 5, "lock_pct": 0.25}),
]


def load_years(years: list[int]
                ) -> tuple[pd.DataFrame, pd.DataFrame]:
    all_trades = []; all_tape = []
    for yr in years:
        d = PORT / f"NQ_{yr}"
        if not (d / "trade_tape.parquet").exists():
            print(f"  NQ {yr}: NO TAPE — skipping")
            continue
        trades = pd.read_parquet(d / "trades.parquet")
        tape = pd.read_parquet(d / "trade_tape.parquet")
        rth = trades[trades["session"] == "RTH"].copy()
        rth_ids = set(rth["decision_event_id"])
        tape_rth = tape[
            tape["decision_event_id"].isin(rth_ids)].copy()
        OFFSET = yr * 1_000_000
        rth["trade_id"] = rth["decision_event_id"] + OFFSET
        tape_rth["trade_id"] = (
            tape_rth["decision_event_id"] + OFFSET)
        rth["baseline_net_pnl"] = rth["net_pnl"]
        all_trades.append(rth)
        all_tape.append(tape_rth)
        print(f"  NQ {yr}: {len(rth):,} RTH trades, "
              f"{len(tape_rth):,} tape rows")
    if not all_trades:
        return pd.DataFrame(), pd.DataFrame()
    return (pd.concat(all_trades, ignore_index=True),
            pd.concat(all_tape, ignore_index=True))


def per_year_summary(rule: str, df: pd.DataFrame,
                          tape: pd.DataFrame,
                          years: list[int]) -> dict:
    out = {"rule": rule}
    for yr in years:
        sub = df[df["year"] == yr]
        s = stats(sub["net_pnl"])
        out[f"y{yr}_n"] = s.get("n", 0)
        out[f"y{yr}_mean"] = s.get("mean")
        out[f"y{yr}_pf"] = s.get("pf")
        out[f"y{yr}_total"] = s.get("sum")
        out[f"y{yr}_dd"] = s.get("max_dd")
        out[f"y{yr}_wr"] = s.get("wr")
        out[f"y{yr}_avg_win"] = s.get("avg_win")
        out[f"y{yr}_avg_loss"] = s.get("avg_loss")
    s_all = stats(df["net_pnl"])
    out["all_n"] = s_all.get("n", 0)
    out["all_mean"] = s_all.get("mean")
    out["all_pf"] = s_all.get("pf")
    out["all_total"] = s_all.get("sum")
    out["all_dd"] = s_all.get("max_dd")
    out["all_wr"] = s_all.get("wr")
    out["med_hold_s"] = float(df["hold_s"].median())
    out["pct_fired"] = float(df["fired_rule"].mean())
    diff = df["net_pnl"] - df["baseline_net_pnl"]
    bw = df["baseline_net_pnl"] > 0
    bl = df["baseline_net_pnl"] < 0
    out["pct_baseline_winners_cut"] = float(
        ((diff < 0) & bw).sum() / max(bw.sum(), 1))
    out["pct_baseline_losers_improved"] = float(
        ((diff > 0) & bl).sum() / max(bl.sum(), 1))
    s = df["net_pnl"].sort_values(ascending=False)
    top1 = s.head(max(1, int(len(s) * 0.01))).sum()
    total = s.sum()
    out["top1_share"] = (
        float(top1 / total) if total != 0 else float("nan"))
    return out


def replay_one(name, family, kwargs, trades, tape):
    if family == "A":
        return replay_family_a(trades, tape, **kwargs)
    elif family == "B":
        return replay_family_b(trades, tape, **kwargs)
    elif family == "C":
        return replay_family_c(trades, tape, **kwargs)
    raise ValueError(family)


def main():
    print("Loading 4 OOS years (2020-2023)...")
    trades, tape = load_years(OOS_YEARS)
    if not len(trades):
        print("No data loaded; aborting.")
        return
    print(f"OOS total: {len(trades):,} trades, "
          f"{len(tape):,} tape rows")

    print("\nPre-computing progression on OOS tape...")
    tape = precompute_progression(tape)
    print(f"Tape now has {len(tape.columns)} columns")

    rules_summary = []

    # Baseline OOS
    base_rows = [_use_original(t) for _, t in trades.iterrows()]
    base_df = pd.DataFrame(base_rows)
    rules_summary.append(per_year_summary(
        "BASELINE_regime", base_df, tape, OOS_YEARS))
    print("  BASELINE done")

    # The 5 rules
    for name, family, kwargs in RULES:
        print(f"  Replaying {name}...", flush=True)
        df = replay_one(name, family, kwargs, trades, tape)
        df.to_parquet(OUT / f"oos_{name}.parquet", index=False)
        rules_summary.append(per_year_summary(
            name, df, tape, OOS_YEARS))
        print(f"    fired {df['fired_rule'].sum():,}/"
              f"{len(df):,} ({df['fired_rule'].mean()*100:.1f}%), "
              f"mean ${df['net_pnl'].mean():.2f}")

    # ---- Load IS comparison results for the same 5 rules ----
    is_compare = {}
    for name, _, _ in RULES:
        is_p = OUT / f"trades_{name}.parquet"
        if is_p.exists():
            is_df = pd.read_parquet(is_p)
            is_stats = {}
            for yr in IS_YEARS:
                sub = is_df[is_df["year"] == yr]
                s = stats(sub["net_pnl"])
                is_stats[yr] = s
            s_all = stats(is_df["net_pnl"])
            is_stats["ALL"] = s_all
            is_compare[name] = is_stats

    summ_df = pd.DataFrame(rules_summary)
    summ_df.to_parquet(OUT / "hhll_oos_summary.parquet",
                          index=False)

    # ---- Markdown report ----
    lines = []
    lines.append("# V_A HH/LL Progression Exit Study — "
                 "OOS Validation 2020-2023")
    lines.append("")
    lines.append("Re-applies the top 5 HH/LL exit rules from the "
                 "in-sample study (NQ 2024+2025+2026) to four "
                 "unseen years (NQ 2020+2021+2022+2023 RTH). "
                 "Same rule definitions, same cost model, same "
                 "tape-replay method. **No tuning.**")
    lines.append("")
    lines.append(f"- OOS population: {len(trades):,} V_A trades "
                  "(NQ 2020-2023 RTH)")
    lines.append(f"- OOS tape: {len(tape):,} per-1s-bar rows")
    lines.append("- Cost: $10 round-trip")
    lines.append("")

    lines.append("## OOS scoreboard — per-year stats")
    lines.append("")
    lines.append("| Rule | %fired | Med Hold s | "
                 "2020 mean / total / WR | "
                 "2021 mean / total / WR | "
                 "2022 mean / total / WR | "
                 "2023 mean / total / WR | "
                 "All mean | All total | All PF | "
                 "%base-W cut | %base-L improved | "
                 "Top-1% share |")
    lines.append("|" + "|".join(["---"] * 12) + "|")
    for r in rules_summary:
        cells = [
            r["rule"],
            fmt_p(r.get("pct_fired", 0)),
            f"{r['med_hold_s']:.0f}",
        ]
        for yr in OOS_YEARS:
            cells.append(
                f"{fmt_d(r.get(f'y{yr}_mean'))} / "
                f"{fmt_d(r.get(f'y{yr}_total'))} / "
                f"{fmt_p(r.get(f'y{yr}_wr'))}")
        cells += [
            fmt_d(r["all_mean"]),
            fmt_d(r["all_total"]),
            fmt_pf(r["all_pf"]),
            fmt_p(r.get("pct_baseline_winners_cut", 0)),
            fmt_p(r.get("pct_baseline_losers_improved", 0)),
            fmt_p(r.get("top1_share", 0)),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    # Δ vs baseline
    base = next(r for r in rules_summary
                  if r["rule"] == "BASELINE_regime")
    lines.append("## Δ vs OOS baseline regime exit")
    lines.append("")
    lines.append("| Rule | Δ 2020 | Δ 2021 | Δ 2022 | Δ 2023 | "
                 "Δ All mean | Δ All total |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|")
    for r in rules_summary:
        if r["rule"] == "BASELINE_regime": continue
        deltas = []
        for yr in OOS_YEARS:
            deltas.append(r[f"y{yr}_mean"] - base[f"y{yr}_mean"])
        dall = r["all_mean"] - base["all_mean"]
        dtot = r["all_total"] - base["all_total"]
        lines.append(
            f"| {r['rule']} | "
            + " | ".join(fmt_d(d) for d in deltas)
            + f" | {fmt_d(dall)} | {fmt_d(dtot)} |")
    lines.append("")

    lines.append("## Years positive per rule")
    lines.append("")
    lines.append("| Rule | Yrs +mean OOS | "
                 + " | ".join(f"{yr} ✓?" for yr in OOS_YEARS)
                 + " |")
    lines.append("|---|--:|" + "|".join(["---"] * len(OOS_YEARS)) + "|")
    for r in rules_summary:
        yrs_pos = sum(1 for yr in OOS_YEARS
                          if r.get(f"y{yr}_mean") is not None
                          and r[f"y{yr}_mean"] > 0)
        marks = ["✅" if r.get(f"y{yr}_mean", 0) > 0 else "❌"
                  for yr in OOS_YEARS]
        lines.append(
            f"| {r['rule']} | {yrs_pos}/{len(OOS_YEARS)} | "
            + " | ".join(marks) + " |")
    lines.append("")

    # Cross-period IS vs OOS comparison
    if is_compare:
        lines.append("## In-sample (2024-26) vs OOS (2020-23) "
                     "side-by-side")
        lines.append("")
        lines.append("| Rule | IS All Mean | IS All Total | "
                     "IS PF | IS Yrs+ | OOS All Mean | "
                     "OOS All Total | OOS PF | OOS Yrs+ |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
        for r in rules_summary:
            if r["rule"] == "BASELINE_regime":
                # Baseline IS stats from existing file or
                # recompute on the fly
                continue
            ic = is_compare.get(r["rule"])
            if not ic: continue
            is_yrs_pos = sum(
                1 for yr in IS_YEARS
                if ic[yr].get("mean") is not None
                and ic[yr]["mean"] > 0)
            oos_yrs_pos = sum(
                1 for yr in OOS_YEARS
                if r.get(f"y{yr}_mean") is not None
                and r[f"y{yr}_mean"] > 0)
            lines.append(
                f"| {r['rule']} | "
                f"{fmt_d(ic['ALL']['mean'])} | "
                f"{fmt_d(ic['ALL']['sum'])} | "
                f"{fmt_pf(ic['ALL']['pf'])} | "
                f"{is_yrs_pos}/{len(IS_YEARS)} | "
                f"{fmt_d(r['all_mean'])} | "
                f"{fmt_d(r['all_total'])} | "
                f"{fmt_pf(r['all_pf'])} | "
                f"{oos_yrs_pos}/{len(OOS_YEARS)} |")
        lines.append("")

    out_p = OUT / "HHLL_OOS_2020_2023_REPORT.md"
    out_p.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_p}")


if __name__ == "__main__":
    main()
