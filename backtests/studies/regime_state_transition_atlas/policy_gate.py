"""Strict deployment gate for the Regime State Transition Atlas policy.

A configuration PASSES only if, out-of-sample (walk-forward thresholds, next-open
fills, $7.50 primary cost/trade):
  - total OOS net PnL > 0
  - 2025 net PnL > 0 AND 2026 net PnL > 0 (each year individually)
  - OOS profit factor > 1.05
  - holds under FIRST-ENTRY-ONLY (one entry per regime; no re-entry)

Evaluated for both re-entry and first-entry-only modes; the official gate is the
first-entry-only column. Tick/NT parity is only worth building if something
passes here (parity can only reduce edge, never create it).

    python studies/regime_state_transition_atlas/policy_gate.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from prototype_policy import get_regime_causal_prices, run_policy_backtest  # noqa: E402

OUT = Path("studies/regime_state_transition_atlas/results")
COST = 7.50
OOS_YEARS = [2025, 2026]
SCORE_COLS = ["score_opportunity", "score_payoff", "score_cost_aware"]
PCTS = [90, 95, 98, 99]  # Top 10/5/2/1%


def year_net(trades, yr):
    return sum(t["gross_pnl"] - COST for t in trades if t["year"] == yr)


def pf_of(trades):
    g = pd.Series([t["gross_pnl"] - COST for t in trades])
    if len(g) == 0:
        return 0.0
    win = g[g > 0].sum(); loss = -g[g < 0].sum()
    return float(win / loss) if loss > 0 else (np.inf if win > 0 else 0.0)


def run_mode(df_scored, causal_map, score_col, pct, first_entry_only):
    oos_trades = []
    for year in OOS_YEARS:
        train_years = [y for y in [2021, 2022, 2023, 2024, 2025] if y < year]
        df_train = df_scored[df_scored["year"].isin(train_years)]
        if len(df_train) == 0:
            continue
        enter_thr = np.percentile(df_train[score_col].values, pct)
        exit_thr = np.percentile(df_train[score_col].values, 50)
        df_year = df_scored[df_scored["year"] == year]
        if len(df_year) == 0:
            continue
        df_year_sorted = df_year.sort_values("bar_ts").copy()
        oos_trades += run_policy_backtest(df_year_sorted, causal_map, enter_thr,
                                          exit_thr, score_col, first_entry_only=first_entry_only)
    net = sum(t["gross_pnl"] - COST for t in oos_trades)
    n25, n26 = year_net(oos_trades, 2025), year_net(oos_trades, 2026)
    pf = pf_of(oos_trades)
    n = len(oos_trades)
    avg = net / n if n else 0.0
    passed = (net > 0) and (n25 > 0) and (n26 > 0) and (pf > 1.05)
    return dict(trades=n, net=net, net_2025=n25, net_2026=n26, pf=pf, avg=avg, passed=passed)


def main():
    p = OUT / "scored_state_rows.parquet"
    if not p.exists():
        print("scored_state_rows.parquet missing — run analyze_state_memory.py first."); return
    df = pd.read_parquet(p)
    print(f"Loaded {len(df):,} scored rows. OOS rows: {int((df['year']>=2025).sum()):,}")
    causal_map = get_regime_causal_prices(df)

    rows = []
    for fe in (False, True):
        for sc in SCORE_COLS:
            for pct in PCTS:
                r = run_mode(df, causal_map, sc, pct, fe)
                r.update(score=sc, pct=pct, mode=("first-entry" if fe else "re-entry"))
                rows.append(r)

    L = ["# Policy Strict Gate — OOS (2025 & 2026)", "",
         f"Gate: OOS net>0 AND 2025 net>0 AND 2026 net>0 AND PF>1.05, next-open fills, "
         f"${COST:.2f}/trade. Official gate = **first-entry-only** mode.", "",
         "| Mode | Score | Top% | Trades | Net OOS | Net 2025 | Net 2026 | PF | Avg/tr | PASS |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in sorted(rows, key=lambda x: (x["mode"], -x["net"])):
        L.append(f"| {r['mode']} | {r['score']} | {100-r['pct']}% | {r['trades']:,} | "
                 f"${r['net']:,.0f} | ${r['net_2025']:,.0f} | ${r['net_2026']:,.0f} | "
                 f"{r['pf']:.2f} | ${r['avg']:.2f} | {'✅' if r['passed'] else '❌'} |")
    passers = [r for r in rows if r["passed"]]
    fe_passers = [r for r in rows if r["passed"] and r["mode"] == "first-entry"]
    L += ["", f"**Configs passing the full gate: {len(passers)}** "
          f"(first-entry-only: {len(fe_passers)})."]
    if fe_passers:
        b = max(fe_passers, key=lambda x: x["net"])
        L.append(f"Best first-entry passer: {b['score']} Top {100-b['pct']}% — net OOS ${b['net']:,.0f}, "
                 f"2025 ${b['net_2025']:,.0f}, 2026 ${b['net_2026']:,.0f}, PF {b['pf']:.2f}. "
                 "-> proceed to tick/NT parity.")
    else:
        L.append("No configuration passes the strict gate under first-entry-only. Tick/NT parity "
                 "is moot (parity only reduces edge); the policy is not deployable.")
    (OUT / "policy_gate_results.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[4:]))
    print("\nWrote results/policy_gate_results.md")


if __name__ == "__main__":
    main()
