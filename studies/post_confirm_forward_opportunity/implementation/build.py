"""Build the five panels this study aggregates from (Phases 0-2, 3-4, 11, 12).

Nothing downstream recomputes a path. Every table in `analysis/` is an
aggregation of one of these panels, so a descriptive table can never disagree
with the causal walk that produced it.

The confirmed population is imported from the accepted study rather than
re-derived. Re-deriving it would be a second chance to get the `arm_top10_ns`
clock or the integer-nanosecond cohort edges wrong, and both have already cost
this program a population error.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    COST_POINTS, NS, load_market, load_regimes,
)
from studies.top10_fast_confirm_runner_path.implementation.build import (
    confirmed_population,
)
from studies.top10_fast_confirm_runner_path.implementation.engine import STOP_ATR
from .engine import (
    DENSE_MAX_S, DENSE_OFFSETS_S, HARVEST_RUNGS, REQUIRED_OFFSETS_S,
    SPARSE_OFFSETS_S, TradeForward, trade_meta, walk,
)
from .geometry import N_PLACEBO, SEED, harvest, placebo

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
ARMED = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"
OUT = ROOT / "studies/post_confirm_forward_opportunity/results"

ACCEPTED = {"entries": 8950, "confirmed": 4705, "stopped_before": 4245,
            "measurable": 4656, "non_measurable": 49,
            "pool_per_entry": 0.898, "baseline_per_entry": -0.0765}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    print("loading market/regimes ...", flush=True)
    market, regimes = load_market(), load_regimes()
    conf = confirmed_population()
    print(f"  confirmed rows: {conf.height:,}", flush=True)
    assert conf.height == ACCEPTED["confirmed"], conf.height

    # 2026 must never enter. Enforced at the source, not asserted after the fact.
    years = sorted(conf["entry_year"].unique().to_list())
    assert 2026 not in years, f"2026 leaked into the population: {years}"

    rng = np.random.default_rng(SEED)
    trades, dense, sparse, harv, plac, dropped = [], [], [], [], [], []
    for n, r in enumerate(conf.iter_rows(named=True), 1):
        res = walk(market, regimes, r)
        if res is None:
            dropped.append({"regime_id": r["regime_id"],
                            "terminal_label": r["terminal_label"],
                            "entry_year": r["entry_year"]})
            continue
        fwd, meta, d_rows, s_rows = res
        trades.append(meta)
        dense.extend(d_rows)
        sparse.extend(s_rows)

        # placebo + harvest reuse the SAME window object the observations came
        # from, so a diagnostic can never see a different set of bars.
        key = {k: meta[k] for k in ("regime_id", "entry_year", "side",
                                    "runner_bucket", "eventual_max_mfe_atr",
                                    "natural_kind", "confirmation_speed_s")}
        plac.append({**key, **placebo(fwd, rng)})
        for hr in harvest(fwd):
            harv.append({**key, **hr})
        if n % 1000 == 0:
            print(f"  {n:,}/{conf.height:,}  ({time.time() - t0:.0f}s)", flush=True)

    td = pl.DataFrame(trades, infer_schema_length=None)
    od = pl.DataFrame(dense, infer_schema_length=None)
    xd = pl.DataFrame(sparse, infer_schema_length=None)
    hd = pl.DataFrame(harv, infer_schema_length=None)
    pd_ = pl.DataFrame(plac, infer_schema_length=None)

    td.write_parquet(OUT / "trade_panel.parquet")
    od.write_parquet(OUT / "observation_panel.parquet")
    xd.write_parquet(OUT / "extended_horizon.parquet")
    hd.write_parquet(OUT / "harvest_panel.parquet")
    pd_.write_parquet(OUT / "placebo_panel.parquet")

    print(f"  trades {td.height:,} · dense obs {od.height:,} · sparse {xd.height:,}"
          f" · harvest {hd.height:,} · placebo {pd_.height:,}"
          f"  ({time.time() - t0:.0f}s)", flush=True)

    armed = pl.read_parquet(ARMED).filter(pl.col("valid"))
    (OUT / "partition_manifest.json").write_text(json.dumps({
        "study": "post_confirm_forward_opportunity",
        "predecessor": "top10_fast_confirm_runner_path (verdict C)",
        "inputs": {"armed_paths": str(ARMED.relative_to(ROOT)),
                   "store": str(STORE.relative_to(ROOT))},
        "original_top10_entries": int(armed.height),
        "confirmed_rows": int(conf.height),
        "measurable_confirmed": int(td.height),
        "non_measurable_confirmed": len(dropped),
        "non_measurable_by_label": (pl.DataFrame(dropped)["terminal_label"]
                                    .value_counts().to_dicts() if dropped else []),
        "dense_observations": int(od.height),
        "sparse_observations": int(xd.height),
        "dense_offsets_s": list(DENSE_OFFSETS_S),
        "sparse_offsets_s": list(SPARSE_OFFSETS_S),
        "required_offsets_s": list(REQUIRED_OFFSETS_S),
        "dense_max_s": DENSE_MAX_S,
        "harvest_rungs_atr": list(HARVEST_RUNGS),
        "stop_atr": STOP_ATR,
        "cost_points_round_turn": COST_POINTS,
        "cost_convention": "one round turn PER UNIT EXIT; per-unit cost is "
                           "identical for full size and a 2-unit scale-out",
        "placebo_seed": SEED,
        "placebo_draws": N_PLACEBO,
        "grid_track": "UNCONSTRAINED (SPEC D1/D2) -- observations exist only "
                      "while the trade is alive on the stop-released path",
        "economics_track": "cv_stop_live PRIMARY, cv_unconstrained secondary",
        "model_score_stream": "raw causal -- EXPLORATORY_OUT_OF_DOMAIN",
        "threshold_overlap_disclosure": "2025 is NOT threshold-OOS; waiver "
            "studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json",
        "years": years,
        "note_2026": "sealed; never read",
        "build_seconds": round(time.time() - t0, 1),
    }, indent=2, default=str))
    print("  wrote partition_manifest.json", flush=True)


if __name__ == "__main__":
    main()
