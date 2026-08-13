"""Phase 0 -- load and reconcile. No trade-lifecycle simulation (SPEC section 1).

Reproduces the predecessor populations exactly from already-existing
artifacts:

    armed_regime_score_paths.parquet  -> 8,950 / 4,705 CONFIRMED / 4,245 STOPPED
    observation_panel.parquet         -> 4,656 MEASURABLE CONFIRMED (49 excluded,
                                          SESSION_CLOSE_UNRESOLVED)
    p90_classification.parquet        -> the 4-cell WITH/AGAINST transition matrix

CONFIRMED is `terminal_label_full != STOPPED_BEFORE_CONFIRM` (the FULL
lifecycle definition, matching `post_confirm_forward_opportunity`'s own
`confirmed_population()`); MEASURABLE CONFIRMED is the Walk-A
`walk_a_confirm_reached_censored` definition (matching `p90_5m_regime_context`'s
`classify.py`). These are two different lifecycle definitions that reconcile
to the same 4,656 trades for this population -- itself a validated
invariant, re-asserted here rather than assumed.
"""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[3]
ARMS_PATH = (ROOT / "studies/armed_fade_score_path_progression/results"
             / "armed_regime_score_paths.parquet")
PANEL_PATH = (ROOT / "studies/post_confirm_forward_opportunity/results"
              / "observation_panel.parquet")
CLASSIFICATION_PATH = (ROOT / "studies/p90_5m_regime_context/results"
                        / "p90_classification.parquet")
OUT = ROOT / "studies/post_confirm_5m_forward_opportunity/results"

ARMED_REQUIRED = 8950
CONFIRMED_REQUIRED = 4705
STOPPED_BEFORE_CONFIRM_REQUIRED = 4245
MEASURABLE_CONFIRMED_REQUIRED = 4656
NON_MEASURABLE_REQUIRED = 49

TRANSITION_MATRIX_REQUIRED = {
    "WITH_WITH": 623, "WITH_AGAINST": 9, "AGAINST_WITH": 6, "AGAINST_AGAINST": 4018,
}
#: Verified directly against p90_classification.parquet (both a raw
#: value_counts of with_5m_at_confirm and the transition cross-tab sum agree
#: on 629/4,027). The user's SPEC draft stated 632/4,024, which does not
#: reproduce from the accepted M2 classification -- likely WITH_WITH + 9
#: (WITH_AGAINST) rather than the correct WITH_WITH + AGAINST_WITH
#: (623 + 6 = 629). Corrected here with disclosure; see SPEC.md Phase 0 note.
GROUP_TRANSITION_REQUIRED = {"WITH_5M": 629, "AGAINST_5M": 4027}
GROUP_STABLE_REQUIRED = {"WITH_5M": 623, "AGAINST_5M": 4018}


def load_arms() -> pl.DataFrame:
    arms = pl.read_parquet(ARMS_PATH)
    if arms.height != ARMED_REQUIRED:
        raise RuntimeError(f"armed population {arms.height} != {ARMED_REQUIRED}")
    return arms


def load_classification() -> pl.DataFrame:
    return pl.read_parquet(CLASSIFICATION_PATH)


def load_panel_trade_ids() -> set[str]:
    return set(pl.scan_parquet(PANEL_PATH).select("regime_id").unique()
               .collect()["regime_id"].to_list())


def build_population(arms: pl.DataFrame, classification: pl.DataFrame,
                     panel_ids: set[str]) -> pl.DataFrame:
    """One row per MEASURABLE CONFIRMED trade (4,656), both group definitions."""
    cls = classification.filter(pl.col("with_5m_at_confirm").is_not_null())
    pop = cls.join(
        arms.select("regime_id", "terminal_label_full"), on="regime_id", how="left"
    ).with_columns(
        transition=pl.when(pl.col("with_5m_at_p90") & pl.col("with_5m_at_confirm"))
        .then(pl.lit("WITH_WITH"))
        .when(pl.col("with_5m_at_p90") & ~pl.col("with_5m_at_confirm"))
        .then(pl.lit("WITH_AGAINST"))
        .when(~pl.col("with_5m_at_p90") & pl.col("with_5m_at_confirm"))
        .then(pl.lit("AGAINST_WITH"))
        .otherwise(pl.lit("AGAINST_AGAINST")),
        group_transition=pl.when(pl.col("with_5m_at_confirm"))
        .then(pl.lit("WITH_5M")).otherwise(pl.lit("AGAINST_5M")),
        in_panel=pl.col("regime_id").is_in(list(panel_ids)),
    )
    pop = pop.with_columns(
        group_stable=pl.when(pl.col("transition") == "WITH_WITH").then(pl.lit("WITH_5M"))
        .when(pl.col("transition") == "AGAINST_AGAINST").then(pl.lit("AGAINST_5M"))
        .otherwise(None)
    )
    return pop


def reconcile(arms: pl.DataFrame, classification: pl.DataFrame,
             panel_ids: set[str], pop: pl.DataFrame) -> dict:
    confirmed = arms.filter(pl.col("terminal_label_full") != "STOPPED_BEFORE_CONFIRM")
    stopped = arms.filter(pl.col("terminal_label_full") == "STOPPED_BEFORE_CONFIRM")
    measurable_confirmed = int(arms["regime_id"].is_in(list(panel_ids)).sum())
    walk_a_confirmed = int(arms["walk_a_confirm_reached_censored"].sum())

    tmatrix = {r["transition"]: int(r["len"]) for r in
              pop.group_by("transition").len().iter_rows(named=True)}
    gtrans = {r["group_transition"]: int(r["len"]) for r in
             pop.group_by("group_transition").len().iter_rows(named=True)}
    gstable = {r["group_stable"]: int(r["len"]) for r in
              pop.filter(pl.col("group_stable").is_not_null())
              .group_by("group_stable").len().iter_rows(named=True)}

    checks = {
        "armed_population": {"expected": ARMED_REQUIRED, "observed": arms.height,
                             "match": arms.height == ARMED_REQUIRED},
        "confirmed": {"expected": CONFIRMED_REQUIRED, "observed": confirmed.height,
                     "match": confirmed.height == CONFIRMED_REQUIRED},
        "stopped_before_confirm": {"expected": STOPPED_BEFORE_CONFIRM_REQUIRED,
                                   "observed": stopped.height,
                                   "match": stopped.height == STOPPED_BEFORE_CONFIRM_REQUIRED},
        "measurable_confirmed_by_panel_membership": {
            "expected": MEASURABLE_CONFIRMED_REQUIRED, "observed": measurable_confirmed,
            "match": measurable_confirmed == MEASURABLE_CONFIRMED_REQUIRED},
        "measurable_confirmed_by_walk_a": {
            "expected": MEASURABLE_CONFIRMED_REQUIRED, "observed": walk_a_confirmed,
            "match": walk_a_confirmed == MEASURABLE_CONFIRMED_REQUIRED,
            "note": "cross-check: FULL-lifecycle panel membership vs Walk-A confirm flag must agree"},
        "panel_trade_count": {"expected": MEASURABLE_CONFIRMED_REQUIRED,
                              "observed": len(panel_ids),
                              "match": len(panel_ids) == MEASURABLE_CONFIRMED_REQUIRED},
        "panel_classification_100pct_overlap": {
            "expected": True,
            "observed": panel_ids == set(
                classification.filter(pl.col("with_5m_at_confirm").is_not_null())
                ["regime_id"].to_list()),
            "match": panel_ids == set(
                classification.filter(pl.col("with_5m_at_confirm").is_not_null())
                ["regime_id"].to_list())},
        "transition_matrix": {"expected": TRANSITION_MATRIX_REQUIRED,
                              "observed": tmatrix, "match": tmatrix == TRANSITION_MATRIX_REQUIRED},
        "group_transition": {"expected": GROUP_TRANSITION_REQUIRED, "observed": gtrans,
                             "match": gtrans == GROUP_TRANSITION_REQUIRED},
        "group_stable": {"expected": GROUP_STABLE_REQUIRED, "observed": gstable,
                         "match": gstable == GROUP_STABLE_REQUIRED},
    }
    failed = [k for k, v in checks.items() if not v["match"]]
    return {
        "study": "post_confirm_5m_forward_opportunity",
        "phase": 0,
        "checks": checks,
        "all_reproduced": not failed,
        "failed": failed,
        "non_measurable_confirmed": confirmed.height - measurable_confirmed,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    arms = load_arms()
    classification = load_classification()
    panel_ids = load_panel_trade_ids()
    pop = build_population(arms, classification, panel_ids)
    payload = reconcile(arms, classification, panel_ids, pop)
    (OUT / "lineage_reconciliation.json").write_text(json.dumps(payload, indent=2, default=str))

    # group_transition is keyed on with_5m_at_confirm alone: WITH_WITH and
    # AGAINST_WITH both land WITH_5M (confirmed WITH), the other two AGAINST_5M.
    GROUP_TRANSITION_LABEL = {
        "WITH_WITH": "WITH_5M", "AGAINST_WITH": "WITH_5M",
        "WITH_AGAINST": "AGAINST_5M", "AGAINST_AGAINST": "AGAINST_5M",
    }
    GROUP_STABLE_LABEL = {"WITH_WITH": "WITH_5M", "AGAINST_AGAINST": "AGAINST_5M"}
    tm_rows = []
    for t, n in payload["checks"]["transition_matrix"]["observed"].items():
        tm_rows.append({"transition": t, "n": n,
                        "group_transition_label": GROUP_TRANSITION_LABEL[t],
                        "group_stable_label": GROUP_STABLE_LABEL.get(t)})
    pl.DataFrame(tm_rows).write_csv(OUT / "transition_matrix.csv")
    pop.write_parquet(OUT / "_population_frame.parquet")

    print(json.dumps({k: v for k, v in payload.items()}, indent=2, default=str))
    if payload["failed"]:
        raise RuntimeError(f"SPEC section 8 ABORT -- Phase 0 failed: {payload['failed']}")
    print("Phase 0 OK -- population, transition matrix, both group definitions reproduced")


if __name__ == "__main__":
    main()
