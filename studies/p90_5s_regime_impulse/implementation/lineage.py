"""Phase 0 -- reproduce the accepted P90 lifecycle before anything new is run.

Nothing in this module is new work. It reads the frozen arm artifact, restates
benchmark A under both fill conventions, and checks every SPEC section 2.2 target
with an explicit `expected` / `observed` / `match` triple. If any target misses,
the study ABORTS (SPEC section 8, stop condition 1) rather than producing a
result on a lineage that does not reproduce.

The MAE distribution is emitted for **two** populations, censored and uncensored,
because they answer different questions and reporting only one is the defect in
`censored_population_cannot_answer_its_own_premise`. The censored population is
bounded below 1.00 ATR *by construction* -- it was selected by surviving that
stop -- so it may only carry the conditional question "of trades that survive
1.00, what share does 0.75 kill?".
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    ExitPolicy, load_market, load_regimes, simulate,
)

ROOT = Path(__file__).resolve().parents[3]
ARMS_PATH = (ROOT / "studies/armed_fade_score_path_progression/results"
             / "armed_regime_score_paths.parquet")
OUT = ROOT / "studies/p90_5s_regime_impulse/results"

ARMED_REQUIRED = 8950
STOP_ATR = 1.00

#: SPEC section 2.2, measured from the frozen artifact BEFORE the SPEC was
#: written. Tolerances are 1e-4 on rates and returns -- these are reproductions,
#: not estimates.
TARGETS = {
    "arms": 8950,
    "arms_long": 4048,
    "arms_short": 4902,
    "confirm_rate_censored": 0.5202,
    "stop_before_confirm_rate": 0.4743,
    "session_unresolved_rate": 0.0055,
    "median_return_at_confirm": 0.8541,
    "median_mfe_to_confirm": 1.0347,
    "median_mae_to_confirm": 0.3302,
}
TOL = 1e-4
YEAR_TARGETS = {2021: 1828, 2022: 1825, 2023: 1763, 2024: 1771, 2025: 1763}
TIMING_TARGETS = {"<=60": 1174, "61-120": 1206, "121-300": 1525, ">300": 751}


def load_arms() -> pl.DataFrame:
    arms = pl.read_parquet(ARMS_PATH)
    if arms.height != ARMED_REQUIRED:
        raise RuntimeError(f"armed population {arms.height} != {ARMED_REQUIRED}")
    if not bool(arms["valid"].all()):
        raise RuntimeError("armed artifact contains invalid rows")
    return arms


def timing_buckets(seconds: np.ndarray) -> dict[str, int]:
    s = seconds[np.isfinite(seconds)]
    return {
        "<=60": int((s <= 60).sum()),
        "61-120": int(((s > 60) & (s <= 120)).sum()),
        "121-300": int(((s > 120) & (s <= 300)).sum()),
        ">300": int((s > 300).sum()),
    }


def mae_table(arms: pl.DataFrame) -> pl.DataFrame:
    """Censored AND uncensored confirming-trade MAE, by side. SPEC 2.3."""
    rows = []
    pops = {
        "censored": pl.col("walk_a_confirm_reached_censored"),
        "uncensored": pl.col("walk_a_confirm_reached_uncensored"),
    }
    for pop, pred in pops.items():
        base = arms.filter(pred)
        for side in ("ALL", "LONG", "SHORT"):
            d = base if side == "ALL" else base.filter(pl.col("side") == side)
            v = d["walk_a_mae_to_confirm_atr"].drop_nulls()
            if v.len() == 0:
                continue
            rows.append({
                "population": pop, "side": side, "n": v.len(),
                "mean": float(v.mean()),
                **{f"p{int(q*100)}": float(v.quantile(q))
                   for q in (0.50, 0.75, 0.80, 0.90, 0.95)},
                "pct_mae_gt_075": float((v > 0.75).mean()),
                "bounded_by_construction": pop == "censored",
            })
    return pl.DataFrame(rows)


def benchmark_a(arms: pl.DataFrame, fill: str) -> pl.DataFrame:
    """The accepted P90 lifecycle: 1.00 ATR stop, exit at the confirming flip.

    `fill="reference"` uses `checkpoint_reference_price` at the arm dispatch --
    the accepted lineage convention, and the parity anchor.
    `fill="next_open"` uses the open of the first 1s bar after the arm, which is
    the convention S1/S075 enter on. B and C are only comparable against A when A
    is restated this way (SPEC 4.3).
    """
    market, regimes = load_market(), load_regimes()
    policy = ExitPolicy(stop_atr=STOP_ATR, hold_to_opposing_flip=False,
                        name=f"A_LIFECYCLE_{fill}")
    rows = []
    for r in arms.iter_rows(named=True):
        arm_ns, d, atr = int(r["arm_top10_ns"]), int(r["direction"]), float(r["arm_atr"])
        start = market.index_strictly_after(arm_ns)
        if start >= market.n or not np.isfinite(atr) or atr <= 0:
            continue
        px = float(r["arm_price"]) if fill == "reference" else float(market.open_[start])
        t = simulate(market, regimes, arm_ns, d, px, atr, policy)
        rows.append({
            "regime_id": r["regime_id"], "side": r["side"], "direction": d,
            "entry_year": int(r["entry_year"]), "arm_ns": arm_ns,
            "entry_price": px, "exit_ns": t.exit_ns, "exit_price": t.exit_price,
            "atr": atr, "outcome": t.outcome, "gross_atr": t.gross_atr,
            "net_atr": t.net_atr, "mfe_atr": t.mfe_atr, "mae_atr": t.mae_atr,
            "ambiguous": t.ambiguous, "fill_convention": fill,
        })
    return pl.DataFrame(rows)


def reconcile(arms: pl.DataFrame) -> dict:
    conf_c = arms.filter(pl.col("walk_a_confirm_reached_censored"))
    observed = {
        "arms": arms.height,
        "arms_long": int((arms["side"] == "LONG").sum()),
        "arms_short": int((arms["side"] == "SHORT").sum()),
        "confirm_rate_censored": float(arms["walk_a_confirm_reached_censored"].mean()),
        "stop_before_confirm_rate": float(arms["walk_a_stop_before_confirm"].mean()),
        "session_unresolved_rate": float(arms["walk_a_session_close_unresolved"].mean()),
        "median_return_at_confirm": float(conf_c["walk_a_return_at_confirm_atr"].median()),
        "median_mfe_to_confirm": float(conf_c["walk_a_mfe_to_confirm_atr"].median()),
        "median_mae_to_confirm": float(conf_c["walk_a_mae_to_confirm_atr"].median()),
    }
    checks = {}
    for k, exp in TARGETS.items():
        obs = observed[k]
        ok = abs(obs - exp) <= (0 if isinstance(exp, int) else TOL)
        checks[k] = {"expected": exp, "observed": obs, "match": bool(ok)}

    years = {int(r["entry_year"]): int(r["len"])
             for r in arms.group_by("entry_year").len().iter_rows(named=True)}
    checks["arms_by_year"] = {
        "expected": YEAR_TARGETS, "observed": years,
        "match": years == YEAR_TARGETS,
    }
    timing = timing_buckets(conf_c["walk_a_seconds_to_confirm"].to_numpy())
    checks["confirmation_timing_censored"] = {
        "expected": TIMING_TARGETS, "observed": timing,
        "match": timing == TIMING_TARGETS,
    }
    checks["mean_return_at_confirm"] = {
        "expected": None,
        "observed": float(conf_c["walk_a_return_at_confirm_atr"].mean()),
        "match": True,
    }
    checks["mean_mfe_to_confirm"] = {
        "expected": None,
        "observed": float(conf_c["walk_a_mfe_to_confirm_atr"].mean()),
        "match": True,
    }
    checks["mean_mae_to_confirm"] = {
        "expected": None,
        "observed": float(conf_c["walk_a_mae_to_confirm_atr"].mean()),
        "match": True,
    }
    return checks


def confirmation_timing_table(arms: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for pop, pred in (("censored", pl.col("walk_a_confirm_reached_censored")),
                      ("uncensored", pl.col("walk_a_confirm_reached_uncensored"))):
        d = arms.filter(pred)
        s = d["walk_a_seconds_to_confirm"].to_numpy()
        total = int(np.isfinite(s).sum())
        masks = {
            "<=60": s <= 60, "61-120": (s > 60) & (s <= 120),
            "121-300": (s > 120) & (s <= 300), ">300": s > 300,
        }
        for bucket, m in masks.items():
            m = m & np.isfinite(s)
            sub = d.filter(pl.Series(m))
            rows.append({
                "population": pop, "bucket": bucket, "n": int(m.sum()),
                "pct": float(m.sum() / total) if total else float("nan"),
                "median_return_atr": (float(sub["walk_a_return_at_confirm_atr"].median())
                                      if sub.height else float("nan")),
                "median_mfe_atr": (float(sub["walk_a_mfe_to_confirm_atr"].median())
                                   if sub.height else float("nan")),
                "median_mae_atr": (float(sub["walk_a_mae_to_confirm_atr"].median())
                                   if sub.height else float("nan")),
            })
    return pl.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    arms = load_arms()
    print(f"loaded {arms.height:,} arms", flush=True)

    checks = reconcile(arms)
    failed = [k for k, v in checks.items() if not v["match"]]

    print("restating benchmark A under both fill conventions ...", flush=True)
    a_ref = benchmark_a(arms, "reference")
    a_open = benchmark_a(arms, "next_open")
    a_ref.write_parquet(OUT / "benchmark_a_reference.parquet")
    a_open.write_parquet(OUT / "benchmark_a_next_open.parquet")

    def summarise(df: pl.DataFrame) -> dict:
        # CENSORED arms have no reachable fill bar inside their own session, so
        # they carry a null exit price and a NaN return. They are excluded from
        # the per-trade means and counted explicitly, but they still contribute
        # 0.0 to the per-ARM denominator -- the denominator stays 8,950 whatever
        # happens to an individual arm (SPEC 4.6).
        real = df.filter(pl.col("gross_atr").is_finite())
        return {
            "n": df.height,
            "n_resolved": real.height,
            "n_censored_no_fill_bar": df.height - real.height,
            "mean_gross_atr": float(real["gross_atr"].mean()),
            "mean_net_atr": float(real["net_atr"].mean()),
            "median_net_atr": float(real["net_atr"].median()),
            "win_rate": float((real["net_atr"] > 0).mean()),
            "net_atr_per_arm": float(real["net_atr"].sum() / ARMED_REQUIRED),
            "outcomes": {k: int(v) for k, v in
                         zip(*[df["outcome"].value_counts().sort("outcome")[c].to_list()
                               for c in ("outcome", "count")])},
        }

    payload = {
        "study": "p90_5s_regime_impulse",
        "phase": 0,
        "armed_population_source": str(ARMS_PATH.relative_to(ROOT)),
        "p90_equals_top10": {
            "note": "p80_p90_opportunity_continuation_ml/SPEC.md:76 maps P90 -> top_10",
            "bullish_threshold": 0.43167249785595935,
            "bearish_threshold": 0.44559149246408103,
        },
        "checks": checks,
        "all_targets_reproduced": not failed,
        "failed_targets": failed,
        "benchmark_a": {
            "reference_fill": summarise(a_ref),
            "next_open_fill": summarise(a_open),
            "note": ("reference_fill is the accepted lineage parity anchor "
                     "(checkpoint_reference_price); next_open_fill is the "
                     "convention S1/S075 enter on and is the only one B and C "
                     "may be compared against (SPEC 4.3)"),
        },
    }
    (OUT / "lineage_reconciliation.json").write_text(json.dumps(payload, indent=2))
    mae_table(arms).write_csv(OUT / "confirming_trade_mae.csv")
    confirmation_timing_table(arms).write_csv(OUT / "confirmation_timing.csv")

    print(json.dumps({k: v for k, v in checks.items()
                      if k in ("arms", "confirm_rate_censored",
                               "median_return_at_confirm")}, indent=2))
    print(f"benchmark A  reference fill: {payload['benchmark_a']['reference_fill']}")
    print(f"benchmark A  next-open fill: {payload['benchmark_a']['next_open_fill']}")
    if failed:
        raise RuntimeError(f"SPEC section 8 ABORT -- lineage targets failed: {failed}")
    print("Phase 0 OK -- every lineage target reproduced")


if __name__ == "__main__":
    main()
