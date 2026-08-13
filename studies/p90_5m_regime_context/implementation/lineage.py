"""Phase 0 -- load and reconcile. Nothing is simulated here (SPEC section 1).

`armed_regime_score_paths.parquet` already carries the FULL-lifecycle
economics (`full_*`) and Walk-A confirmation fields (`walk_a_*`) as native
columns for all 8,950 arms -- verified by reading
`p90_conditional_losing_5s_exit/implementation/lineage.py`, which reads them
directly off the loaded parquet rather than computing them. This module's job
is strictly to load, count, and diff against the frozen references the
predecessor established; a mismatch on any of them is an ABORT (SPEC section
9), not something to repair.
"""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[3]
ARMS_PATH = (ROOT / "studies/armed_fade_score_path_progression/results"
             / "armed_regime_score_paths.parquet")
OUT = ROOT / "studies/p90_5m_regime_context/results"

ARMED_REQUIRED = 8950
CONFIRM_RATE_REF = 0.5202
N_CONFIRMING_REF = 4656

FULL_LABEL_COUNTS = {
    "STOPPED_BEFORE_CONFIRM": 4245, "FINAL_FLIP_EXIT_WINNER": 2350,
    "FINAL_FLIP_EXIT_LOSER": 1359, "CONFIRMED_THEN_STOPPED": 822,
    "SESSION_EXIT": 174,
}
YEAR_TARGETS = {2021: 1828, 2022: 1825, 2023: 1763, 2024: 1771, 2025: 1763}
SIDE_TARGETS = {"LONG": 4048, "SHORT": 4902}

#: predecessor references (p90_conditional_losing_5s_exit SPEC 9.3).
#: References, not repair targets.
MAE_REFERENCES = {"p50": 0.330, "p75": 0.596, "p80": 0.660, "p90": 0.818, "p95": 0.907}
MAE_TOL = 0.002


def load_arms() -> pl.DataFrame:
    arms = pl.read_parquet(ARMS_PATH)
    if arms.height != ARMED_REQUIRED:
        raise RuntimeError(f"armed population {arms.height} != {ARMED_REQUIRED}")
    return arms


def reconcile(arms: pl.DataFrame) -> dict:
    label_counts = {r["terminal_label_full"]: int(r["len"]) for r in
                    arms.group_by("terminal_label_full").len().iter_rows(named=True)}
    years = {int(r["entry_year"]): int(r["len"])
             for r in arms.group_by("entry_year").len().iter_rows(named=True)}
    sides = {s: int((arms["side"] == s).sum()) for s in ("LONG", "SHORT")}

    conf = arms.filter(pl.col("walk_a_confirm_reached_censored"))
    confirm_rate = float(arms["walk_a_confirm_reached_censored"].mean())
    mae = conf["walk_a_mae_to_confirm_atr"]
    observed_mae = {k: float(mae.quantile(float(k[1:]) / 100)) for k in MAE_REFERENCES}

    checks = {
        "armed_population": {"expected": ARMED_REQUIRED, "observed": arms.height,
                             "match": arms.height == ARMED_REQUIRED},
        "full_lifecycle_labels": {"expected": FULL_LABEL_COUNTS,
                                  "observed": label_counts,
                                  "match": label_counts == FULL_LABEL_COUNTS},
        "arms_by_year": {"expected": YEAR_TARGETS, "observed": years,
                         "match": years == YEAR_TARGETS},
        "arms_by_side": {"expected": SIDE_TARGETS, "observed": sides,
                         "match": sides == SIDE_TARGETS},
        "confirm_rate": {"expected": CONFIRM_RATE_REF, "observed": round(confirm_rate, 4),
                         "match": abs(confirm_rate - CONFIRM_RATE_REF) <= 0.0005},
        "n_confirming": {"expected": N_CONFIRMING_REF, "observed": conf.height,
                         "match": conf.height == N_CONFIRMING_REF},
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
    return {
        "study": "p90_5m_regime_context",
        "phase": 0,
        "source": str(ARMS_PATH.relative_to(ROOT)),
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
            "confirm_rate_censored": confirm_rate,
            "n_confirming": conf.height,
            "median_return_at_confirm": float(conf["walk_a_return_at_confirm_atr"].median()),
        },
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    arms = load_arms()
    payload = reconcile(arms)
    (OUT / "lineage_reconciliation.json").write_text(json.dumps(payload, indent=2))
    print(json.dumps({k: v for k, v in payload.items()
                      if k not in ("accepted_full_lifecycle_economics", "walk_a_reference")},
                     indent=2, default=str))
    if payload["failed"]:
        raise RuntimeError(f"SPEC section 9 ABORT -- Phase 0 failed: {payload['failed']}")
    print("Phase 0 OK -- population and accepted FULL/Walk-A lineage reproduced")


if __name__ == "__main__":
    main()
