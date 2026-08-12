"""Phase 0 -- reconcile to the predecessor and to the accepted FULL lifecycle.

Nothing new is computed here. Three things must hold before any policy runs, and
each is an ABORT rather than a caveat (SPEC section 9):

1. The predecessor's entry population reproduces: 8,379 of 8,950 arms are
   5s-aligned. The alignment classifier is IMPORTED from the predecessor, not
   reimplemented.
2. The baseline at 1.00 ATR entered at `arm_price` reproduces the accepted
   `walks.py::continuation_label` output -- label and all four metrics -- on
   every one of the 8,950 arms. This is what makes "baseline" mean the accepted
   lifecycle rather than something that resembles it.
3. The walk-A confirming-trade MAE percentiles land on the predecessor's
   references. The brief supplied these as references, explicitly NOT as
   permission to repair a discrepancy, so a miss stops the study and is
   reported.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    load_market, load_regimes,
)
from studies.p90_5s_regime_impulse.implementation import regime_5s as R5
from studies.p90_5s_regime_impulse.implementation.policy import ALIGNED, alignment_at_arm
from studies.p90_conditional_losing_5s_exit.implementation.policy import simulate

ROOT = Path(__file__).resolve().parents[3]
ARMS_PATH = (ROOT / "studies/armed_fade_score_path_progression/results"
             / "armed_regime_score_paths.parquet")
OUT = ROOT / "studies/p90_conditional_losing_5s_exit/results"

ARMED_REQUIRED = 8950
ALIGNED_REQUIRED = 8379

#: predecessor references (SPEC 9.3). References, not repair targets.
MAE_REFERENCES = {"p50": 0.330, "p75": 0.596, "p80": 0.660, "p90": 0.818, "p95": 0.907}
MAE_TOL = 0.002

FULL_LABEL_COUNTS = {
    "STOPPED_BEFORE_CONFIRM": 4245, "FINAL_FLIP_EXIT_WINNER": 2350,
    "FINAL_FLIP_EXIT_LOSER": 1359, "CONFIRMED_THEN_STOPPED": 822,
    "SESSION_EXIT": 174,
}
YEAR_TARGETS = {2021: 1828, 2022: 1825, 2023: 1763, 2024: 1771, 2025: 1763}


def load_arms() -> pl.DataFrame:
    arms = pl.read_parquet(ARMS_PATH)
    if arms.height != ARMED_REQUIRED:
        raise RuntimeError(f"armed population {arms.height} != {ARMED_REQUIRED}")
    return arms


def attach_alignment(arms: pl.DataFrame, r5) -> pl.DataFrame:
    """The predecessor's entry qualification, imported rather than restated."""
    al = [alignment_at_arm(r5, int(a), int(d))
          for a, d in zip(arms["arm_top10_ns"], arms["direction"])]
    return arms.with_columns(alignment=pl.Series(al),
                             entered=pl.Series([x == ALIGNED for x in al]))


def full_lifecycle_parity(arms: pl.DataFrame, market, regimes, r5) -> dict:
    """Gate V2: reproduce the accepted FULL lifecycle exactly, on every arm."""
    mism = {"label": 0, "gross": 0, "net": 0, "mfe": 0, "mae": 0}
    examples: list[dict] = []
    n = 0
    for r in arms.iter_rows(named=True):
        res = simulate(market, regimes, r5, int(r["arm_top10_ns"]),
                       int(r["direction"]), float(r["arm_atr"]), 1.00,
                       entry_price_override=float(r["arm_price"]),
                       conditional=False)
        if res is None:
            continue
        n += 1
        checks = {
            "label": res["outcome"] != r["terminal_label_full"],
            "gross": abs(res["gross_atr"] - r["full_gross_atr"]) > 1e-9,
            "net": abs(res["net_atr"] - r["full_net_atr"]) > 1e-9,
            "mfe": abs(res["mfe_atr"] - r["full_mfe_atr"]) > 1e-9,
            "mae": abs(res["mae_atr"] - r["full_mae_atr"]) > 1e-9,
        }
        for k, bad in checks.items():
            if bad:
                mism[k] += 1
                if len(examples) < 5:
                    examples.append({"regime_id": r["regime_id"], "field": k,
                                     "observed": res.get({"label": "outcome"}.get(k, f"{k}_atr")),
                                     "expected": r.get(
                                         "terminal_label_full" if k == "label" else f"full_{k}_atr")})
    return {"arms_compared": n, "mismatches": mism,
            "exact": all(v == 0 for v in mism.values()), "examples": examples}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    arms = load_arms()
    market, regimes = load_market(), load_regimes()
    r5 = R5.load()
    arms = attach_alignment(arms, r5)

    n_entered = int(arms["entered"].sum())
    conf = arms.filter(pl.col("walk_a_confirm_reached_censored"))
    mae = conf["walk_a_mae_to_confirm_atr"]
    observed_mae = {k: float(mae.quantile(float(k[1:]) / 100)) for k in MAE_REFERENCES}
    label_counts = {r["terminal_label_full"]: int(r["len"]) for r in
                    arms.group_by("terminal_label_full").len().iter_rows(named=True)}
    years = {int(r["entry_year"]): int(r["len"])
             for r in arms.group_by("entry_year").len().iter_rows(named=True)}

    print("running FULL-lifecycle parity over 8,950 arms ...", flush=True)
    parity = full_lifecycle_parity(arms, market, regimes, r5)

    checks = {
        "armed_population": {"expected": ARMED_REQUIRED, "observed": arms.height,
                             "match": arms.height == ARMED_REQUIRED},
        "aligned_entries": {"expected": ALIGNED_REQUIRED, "observed": n_entered,
                            "match": n_entered == ALIGNED_REQUIRED},
        "entry_coverage": {"expected": round(ALIGNED_REQUIRED / ARMED_REQUIRED, 6),
                           "observed": round(n_entered / arms.height, 6),
                           "match": n_entered == ALIGNED_REQUIRED},
        "arms_by_year": {"expected": YEAR_TARGETS, "observed": years,
                         "match": years == YEAR_TARGETS},
        "arms_by_side": {
            "expected": {"LONG": 4048, "SHORT": 4902},
            "observed": {s: int((arms["side"] == s).sum()) for s in ("LONG", "SHORT")},
            "match": int((arms["side"] == "LONG").sum()) == 4048
                     and int((arms["side"] == "SHORT").sum()) == 4902},
        "full_lifecycle_labels": {"expected": FULL_LABEL_COUNTS,
                                  "observed": label_counts,
                                  "match": label_counts == FULL_LABEL_COUNTS},
        "full_lifecycle_parity_exact": {"expected": True,
                                        "observed": parity["exact"],
                                        "match": parity["exact"],
                                        "detail": parity},
        "walk_a_confirming_mae": {
            "expected": MAE_REFERENCES, "observed": observed_mae,
            "match": all(abs(observed_mae[k] - v) <= MAE_TOL
                         for k, v in MAE_REFERENCES.items()),
            "tolerance": MAE_TOL,
            "note": ("predecessor references; a miss STOPS the study and is "
                     "explained -- it is not permission to repair a discrepancy"),
        },
    }
    failed = [k for k, v in checks.items() if not v["match"]]

    payload = {
        "study": "p90_conditional_losing_5s_exit",
        "phase": 0,
        "predecessor": "studies/p90_5s_regime_impulse",
        "baseline_lifecycle": "FULL (hold through confirmation -> opposing flip)",
        "baseline_lifecycle_source":
            "armed_fade_score_path_progression/implementation/walks.py::continuation_label",
        "checks": checks,
        "all_reproduced": not failed,
        "failed": failed,
        "accepted_full_lifecycle_economics": {
            "mean_gross_atr": float(arms["full_gross_atr"].mean()),
            "mean_net_atr": float(arms["full_net_atr"].mean()),
            "median_net_atr": float(arms["full_net_atr"].median()),
            "win_rate": float((arms["full_net_atr"] > 0).mean()),
            "mean_mfe_atr": float(arms["full_mfe_atr"].mean()),
        },
        "walk_a_reference": {
            "confirm_rate_censored": float(arms["walk_a_confirm_reached_censored"].mean()),
            "n_confirming": conf.height,
            "median_return_at_confirm": float(conf["walk_a_return_at_confirm_atr"].median()),
        },
    }
    (OUT / "lineage_reconciliation.json").write_text(json.dumps(payload, indent=2))
    arms.select("regime_id", "alignment", "entered").write_parquet(
        ROOT / "studies/p90_conditional_losing_5s_exit/_work/entry_population.parquet")

    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "detail"}
                      for k, v in checks.items()}, indent=2, default=str))
    if failed:
        raise RuntimeError(f"SPEC section 9 ABORT -- Phase 0 failed: {failed}")
    print("Phase 0 OK -- predecessor and accepted FULL lifecycle both reproduced")


if __name__ == "__main__":
    main()


