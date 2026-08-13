"""Phase 12 control: is the RUNG the reason, or just the harvesting?

The descriptive harvest table shows a small positive delta at the >=2 ATR rungs.
This program has three times mistaken "acting earlier than a bad exit" for an
edge, so that number means nothing until it is compared against harvesting one
unit at a moment chosen for no reason at all.

Two controls, and the difference between them is itself the finding:

* LIFETIME-UNIFORM -- harvest at an index drawn uniformly from the trade's own
  post-confirmation window. Requires knowing how long the trade lives, so it is
  a benchmark, never a rule.
* LENGTH-BLIND -- harvest at an offset drawn from the frozen dense grid. If the
  offset lands past the trade's terminal there is no harvest and the position is
  held full size, exactly as a live rule would experience it.

This is NOT an architecture. The SPEC §8 gate is closed and no policy is being
manufactured; this only decides whether the rung ladder is structurally special.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    COST_POINTS, load_market, load_regimes,
)
from studies.top10_fast_confirm_runner_path.implementation.build import (
    confirmed_population,
)
from ..implementation.engine import DENSE_OFFSETS_S, HARVEST_RUNGS, TradeForward, walk

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/post_confirm_forward_opportunity/results"
SEED = 20260811
N_DRAWS = 20
N_ENTRIES = 8950


def _first(mask: np.ndarray) -> int:
    hit = np.flatnonzero(mask)
    return int(hit[0]) if hit.size else -1


def evaluate(fwd: TradeForward, rng: np.random.Generator) -> list[dict]:
    w = fwd.w
    ci, nat, unc = w.ci, w.nat_i, w.unc_i
    cost = COST_POINTS / w.atr
    full = fwd.nat_ret - cost
    rows = []
    for R in HARVEST_RUNGS:
        r = _first(w.bar_hi[:unc + 1] >= R)
        if r < 0 or r > nat:
            continue
        rung_blend = 0.5 * (w.realise(r, True) + fwd.nat_ret) - cost

        if nat > ci:
            draws = rng.integers(ci, nat, size=N_DRAWS)
        else:
            draws = np.full(N_DRAWS, ci)
        unif = np.mean([0.5 * (w.realise(int(k), True) + fwd.nat_ret) - cost
                        for k in draws])

        blind = []
        for L in rng.choice(np.array(DENSE_OFFSETS_S), size=N_DRAWS):
            j = w.index_at_offset(int(L))
            if j < 0 or j > nat:
                blind.append(full)              # no harvest; held full size
            else:
                blind.append(0.5 * (w.realise(j, True) + fwd.nat_ret) - cost)
        rows.append({
            "regime_id": fwd.meta["regime_id"],
            "entry_year": fwd.meta["entry_year"], "side": fwd.meta["side"],
            "runner_bucket": fwd.meta["runner_bucket"],
            "reached_3_0": fwd.meta["reached_3_0"],
            "rung_atr": R,
            "full_size_net_atr": float(full),
            "rung_blended_net_atr": float(rung_blend),
            "placebo_uniform_net_atr": float(unif),
            "placebo_blind_net_atr": float(blind := float(np.mean(blind))),
            "d_rung": float(rung_blend - full),
            "d_placebo_uniform": float(unif - full),
            "d_placebo_blind": float(blind - full),
        })
    return rows


def summarise(d: pl.DataFrame) -> pl.DataFrame:
    rows = []
    groups = [("POOLED", "ALL", d)]
    groups += [("SIDE", s, d.filter(pl.col("side") == s)) for s in ("LONG", "SHORT")]
    groups += [("YEAR", str(y), d.filter(pl.col("entry_year") == y))
               for y in range(2021, 2026)]
    groups += [("RUNNER", b, d.filter(pl.col("runner_bucket") == b))
               for b in ("R0", "R1", "R2", "R3")]
    for kind, name, sub in groups:
        for R in HARVEST_RUNGS:
            g = sub.filter(pl.col("rung_atr") == R)
            if g.height == 0:
                continue
            rows.append({
                "slice_kind": kind, "slice": name, "rung_atr": R,
                "n_trades": g.height,
                "full_size_net_atr": float(g["full_size_net_atr"].mean()),
                "rung_blended_net_atr": float(g["rung_blended_net_atr"].mean()),
                "d_rung_per_achieving_trade": float(g["d_rung"].mean()),
                "d_placebo_uniform": float(g["d_placebo_uniform"].mean()),
                "d_placebo_blind": float(g["d_placebo_blind"].mean()),
                "edge_over_uniform": float(
                    g["d_rung"].mean() - g["d_placebo_uniform"].mean()),
                "edge_over_blind": float(
                    g["d_rung"].mean() - g["d_placebo_blind"].mean()),
                "beats_uniform": bool(g["d_rung"].mean() > g["d_placebo_uniform"].mean()),
                "beats_blind": bool(g["d_rung"].mean() > g["d_placebo_blind"].mean()),
                "d_rung_per_original_entry": float(g["d_rung"].sum()) / N_ENTRIES,
                "d_uniform_per_original_entry": float(
                    g["d_placebo_uniform"].sum()) / N_ENTRIES,
                "d_blind_per_original_entry": float(
                    g["d_placebo_blind"].sum()) / N_ENTRIES,
                "pct_of_giveback_pool": 100.0 * float(g["d_rung"].sum()) / (
                    0.898 * N_ENTRIES),
            })
    return pl.DataFrame(rows)


def main() -> None:
    market, regimes = load_market(), load_regimes()
    conf = confirmed_population()
    rng = np.random.default_rng(SEED)
    rows = []
    for r in conf.iter_rows(named=True):
        res = walk(market, regimes, r)
        if res is None:
            continue
        rows.extend(evaluate(res[0], rng))
    d = pl.DataFrame(rows, infer_schema_length=None)
    d.write_parquet(OUT / "harvest_control_panel.parquet")
    s = summarise(d)
    s.write_parquet(OUT / "harvest_control.parquet")
    s.write_csv(OUT / "harvest_control.csv")
    print(f"  harvest_control: {s.height} rows over {d.height:,} trade-rungs")
    print(s.filter(pl.col("slice_kind") == "POOLED").select(
        "rung_atr", "n_trades", "d_rung_per_achieving_trade", "d_placebo_uniform",
        "d_placebo_blind", "edge_over_uniform", "edge_over_blind",
        "d_rung_per_original_entry", "pct_of_giveback_pool").to_pandas()
        .round(4).to_string())
    (OUT / "harvest_control_verdict.json").write_text(json.dumps({
        "seed": SEED, "draws": N_DRAWS,
        "note": "control only; SPEC 8 gate is CLOSED and no architecture was built",
        "pooled": s.filter(pl.col("slice_kind") == "POOLED").to_dicts(),
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
