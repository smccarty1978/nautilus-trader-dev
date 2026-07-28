"""Stage 2 refinement and Stage 3 composites.

Stage 1 found exactly one entry family with positive gross expectancy at every
threshold tested (`reexpansion`) and one exit that turns gross positive
(`direction_flip`). This stage tests whether they compose, and whether the
result survives the 2024 selection year and the 2025 descriptive holdout.

A candidate is rejected if its advantage is an isolated spike rather than a
plateau across neighbouring settings.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from .candidates import THRESHOLDS, load_scored, reexpansion, age_conditioned, first_qualifying
from .engine import ExitPolicy, load_market, load_regimes, simulate
from .screen import attach_meta, summarize

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "studies/model_driven_entry_exit_discovery/results"

DISCOVERY = (2021, 2022, 2023)
SELECTION = (2024,)
HOLDOUT = (2025,)

# Stage 2: neighbourhood around the one family that showed a plateau.
ENTRIES = {
    f"reexpansion_{p}_{t}": (lambda s, t=t, p=p: reexpansion(s, t, p))
    for t in ("top_20", "top_10", "top_5", "top_2_5", "top_1")
    for p in (0.03, 0.05, 0.08)
}
ENTRIES["age_300_1800_top_5"] = lambda s: age_conditioned(s, "top_5", 300.0, 1800.0)
ENTRIES["first_qualifying_top_10"] = lambda s: first_qualifying(s, "top_10")

# Stage 3: the exits that were best or structurally distinct in Stage 1.
EXITS = {
    "direction_flip": ExitPolicy(stop_atr=1.0, hold_to_opposing_flip=False),
    "direction_flip_be0.5": ExitPolicy(
        stop_atr=1.0, breakeven_at_atr=0.5, hold_to_opposing_flip=False
    ),
    "direction_flip_give0.33": ExitPolicy(
        stop_atr=1.0, giveback_frac=0.33, mfe_floor_atr=0.5, hold_to_opposing_flip=False
    ),
    "direction_flip_stop0.75": ExitPolicy(stop_atr=0.75, hold_to_opposing_flip=False),
    "direction_flip_stop1.5": ExitPolicy(stop_atr=1.5, hold_to_opposing_flip=False),
    "breakeven0.5": ExitPolicy(stop_atr=1.0, breakeven_at_atr=0.5),
    "target1.0": ExitPolicy(stop_atr=1.0, target_atr=1.0),
}


def evaluate(market, regimes, entries: pl.DataFrame, policy: ExitPolicy) -> dict:
    trades = [
        simulate(
            market, regimes, r["checkpoint_decision_ns"], r["direction"],
            r["checkpoint_reference_price"], r["atr_at_checkpoint"], policy,
        )
        for r in entries.iter_rows(named=True)
    ]
    attach_meta(entries, trades)
    return summarize(trades, entries)


def main() -> None:
    print("loading ...", flush=True)
    market = load_market()
    regimes = load_regimes()
    scored_all = load_scored()
    print(f"  {market.n:,} RTH bars, {scored_all.height:,} in-domain checkpoints\n",
          flush=True)

    rows = []
    print("STAGE 2/3 - composite screen on discovery years 2021-2023")
    print(f"{'entry':28s}{'exit':24s}{'n':>7s}{'net':>9s}{'gross':>9s}{'win':>7s}{'dd':>8s}")
    for ename, efn in ENTRIES.items():
        base = efn(scored_all)
        disc = base.filter(pl.col("entry_year").is_in(list(DISCOVERY)))
        if disc.height < 100:
            continue
        for xname, policy in EXITS.items():
            r = evaluate(market, regimes, disc, policy)
            if not r.get("resolved"):
                continue
            r["entry"], r["exit"], r["period"] = ename, xname, "discovery"
            rows.append(r)
            print(f"{ename:28s}{xname:24s}{r['resolved']:>7,}{r['net_atr']:>+9.4f}"
                  f"{r['gross_atr']:>+9.4f}{r['win_rate']:>7.3f}"
                  f"{r['max_drawdown_atr']:>8.1f}", flush=True)

    rows.sort(key=lambda r: -r["net_atr"])
    top = rows[:6]

    print("\nCARRY TOP 6 TO 2024 SELECTION AND 2025 HOLDOUT")
    print(f"{'entry':28s}{'exit':24s}{'period':11s}{'n':>7s}{'net':>9s}{'gross':>9s}")
    carried = []
    for r in top:
        efn = ENTRIES[r["entry"]]
        base = efn(scored_all)
        for period, years in (("discovery", DISCOVERY), ("selection_2024", SELECTION),
                              ("holdout_2025", HOLDOUT)):
            sub = base.filter(pl.col("entry_year").is_in(list(years)))
            if sub.height < 20:
                continue
            out = evaluate(market, regimes, sub, EXITS[r["exit"]])
            out["entry"], out["exit"], out["period"] = r["entry"], r["exit"], period
            carried.append(out)
            print(f"{r['entry']:28s}{r['exit']:24s}{period:11s}{out['resolved']:>7,}"
                  f"{out['net_atr']:>+9.4f}{out['gross_atr']:>+9.4f}", flush=True)

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "stage3_composite.json").write_text(
        json.dumps({"screen": rows, "carried": carried}, indent=2, default=str)
    )
    print(f"\nwrote {(RESULTS / 'stage3_composite.json').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
