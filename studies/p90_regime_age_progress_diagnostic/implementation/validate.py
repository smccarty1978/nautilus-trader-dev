"""Gates (SPEC 4, 8) and the mechanical D1-D5 verdict (SPEC 7).

Every gate reports `expected` / `observed` / `pass`. The verdict is COMPUTED from
the finished tables -- no branch of this module reads a narrative conclusion, and no
threshold here may be moved after seeing a result.

Thin cells (`n < 30`) are excluded from every verdict test. A verdict resting on a
5-observation cell is not a verdict.
"""
from __future__ import annotations

import polars as pl

from studies.p90_regime_age_progress_diagnostic.implementation.population import (
    THIN_CELL_N,
)

# SPEC 2.4 -- measured in Phase 0 and frozen into the SPEC before implementation.
EXPECTED = {
    "in_domain_scored_observations": 2_028_394,
    "distinct_eligible_regimes": 15_076,
    "population_a_arms": 9_189,
    "population_b_arms": 8_950,
    "n_in_both": 8_950,
    "n_same_timestamp": 8_596,
    "n_different_timestamp": 354,
    "n_only_a": 239,
    "n_only_b": 0,
}

# SPEC 7 -- the age contrast, forced by SPEC 2.5 (the two young buckets are unusable
# at n=5 and n=14). Recorded in summary.json as a substitution, not a choice.
YOUNG_BUCKET = "300-600s"
OLD_BUCKET = ">900s"


def _gate(name: str, expected, observed, ok: bool | None = None) -> dict:
    return {
        "gate": name, "expected": expected, "observed": observed,
        "pass": bool(expected == observed if ok is None else ok),
    }


def run_gates(*, scored: pl.DataFrame, comparison: dict, events: pl.DataFrame,
              tiling: dict, contract: dict) -> list[dict]:
    g: list[dict] = []

    # ---- lineage / parity -------------------------------------------------
    g.append(_gate("V_LINEAGE_scored_observations",
                   EXPECTED["in_domain_scored_observations"], scored.height))
    g.append(_gate("V_LINEAGE_eligible_regimes",
                   EXPECTED["distinct_eligible_regimes"], scored["regime_id"].n_unique()))
    g.append(_gate("V_PARITY_population_b_8950",
                   EXPECTED["population_b_arms"], comparison["n_b"]))
    g.append(_gate("V_LINEAGE_population_a",
                   EXPECTED["population_a_arms"], comparison["n_a"]))
    for k in ("n_in_both", "n_same_timestamp", "n_different_timestamp",
              "n_only_a", "n_only_b"):
        g.append(_gate(f"V_AB_{k}", EXPECTED[k], comparison[k]))

    # B must be a regime-level subset of A; a nonzero only_b means the two arming
    # calls disagree on something other than the age gate.
    g.append(_gate("V_AB_b_subset_of_a_at_regime_level", 0, comparison["n_only_b"]))

    # ---- causal contract --------------------------------------------------
    g.append(_gate("V_TILE_regime_end_is_next_start", 0, tiling["n_mismatches"]))
    g.append(_gate("V_CONTRACT_eligibility_matches_artifact",
                   True, all(r["match"] for r in contract["contract_rows"]),
                   ok=all(r["match"] for r in contract["contract_rows"])))

    g.append(_gate("V_SEALED_no_2026", True, int(events["entry_year"].max()) <= 2025,
                   ok=int(events["entry_year"].max()) <= 2025))

    # V-FROZEN: every dimension column is a pure function of at-arm score-row values.
    # Verified by reconstruction rather than by assertion of intent.
    recon = events.with_columns(
        _v=pl.col("running_mfe_atr") / (pl.col("regime_age_s") / 60.0)
    )
    vel_ok = bool(
        ((recon["_v"] - recon["velocity_atr_per_min"]).abs() < 1e-9).all()
    )
    g.append(_gate("V_FROZEN_velocity_is_at_arm_only", True, vel_ok, ok=vel_ok))

    age_ok = bool((events["regime_age_s"] > 120.0).all())
    g.append(_gate("V_FROZEN_age_above_eligibility_floor", True, age_ok, ok=age_ok))
    mfe_ok = bool((events["running_mfe_atr"] >= 1.0).all())
    g.append(_gate("V_FROZEN_running_mfe_above_eligibility_floor", True, mfe_ok, ok=mfe_ok))

    atr_ok = bool((events["atr_at_checkpoint"] > 0).all())
    g.append(_gate("V_ATR_positive_frozen_at_checkpoint", True, atr_ok, ok=atr_ok))

    # V-LABEL: no retrospective field may appear in a bucket key. Buckets are built
    # from `regime_age_s` / `running_mfe_atr` only; reconstructing them from those
    # two columns alone and matching 100% is the check.
    from studies.p90_regime_age_progress_diagnostic.implementation.population import (
        AGE_EDGES, AGE_LABELS, MFE_EDGES, MFE_LABELS, _bucket_expr,
    )
    rb = events.with_columns(
        _ab=_bucket_expr("regime_age_s", AGE_EDGES, AGE_LABELS),
        _mb=_bucket_expr("running_mfe_atr", MFE_EDGES, MFE_LABELS),
    )
    lab_ok = bool((rb["_ab"] == rb["age_bucket"]).all() and (rb["_mb"] == rb["mfe_bucket"]).all())
    g.append(_gate("V_LABEL_buckets_from_at_arm_columns_only", True, lab_ok, ok=lab_ok))

    # ---- completeness -----------------------------------------------------
    a_rows = events.filter(pl.col("population") == "A").height
    b_rows = events.filter(pl.col("population") == "B").height
    g.append(_gate("V_COMPLETE_events_A", EXPECTED["population_a_arms"], a_rows))
    g.append(_gate("V_COMPLETE_events_B", EXPECTED["population_b_arms"], b_rows))

    return g


def check_grid_complete(cells: pl.DataFrame) -> dict:
    return _gate("V_COMPLETE_40_cell_grid", 40, cells.height)


# EVERY confirmer-denominated column emitted by `analysis.AGGS`, as
# (output_column, source_column, statistic, argument). SPEC 6.1 claims V-DENOM covers
# all of them, so this tuple must stay in step with AGGS -- gate
# `V_DENOM_coverage_is_complete` below fails if a confirmer-denominated column is
# emitted that is not listed here. Under-coverage was raised as a CRITICAL by
# lookahead-auditor pass 3: the original list held only 4 of these 10, leaving
# `p_mfe_ge_3` -- which feeds `classify()`'s primary verdict -- with no regression
# coverage against exactly the leak that had already occurred once.
CONFIRMER_DENOMINATED = (
    ("median_return_at_confirm", "return_at_confirm_atr", "median", None),
    ("mean_return_at_confirm", "return_at_confirm_atr", "mean", None),
    ("mae_to_confirm_p50", "mae_to_confirm_atr", "quantile", 0.50),
    ("mae_to_confirm_p75", "mae_to_confirm_atr", "quantile", 0.75),
    ("mae_to_confirm_p90", "mae_to_confirm_atr", "quantile", 0.90),
    ("median_secs_to_confirm", "seconds_to_confirm", "median", None),
    ("median_eventual_mfe", "eventual_max_mfe_atr", "median", None),
    ("p_mfe_ge_1", "mfe_ge_1_0", "mean", None),
    ("p_mfe_ge_2", "mfe_ge_2_0", "mean", None),
    ("p_mfe_ge_3", "mfe_ge_3_0", "mean", None),
)

# Columns AGGS emits over ALL arms or over measurable-flip rows. Listed so the
# coverage gate can tell "confirmer-denominated but unchecked" from "correctly not
# confirmer-denominated" instead of guessing from the name.
NON_CONFIRMER_DENOMINATED = frozenset({
    "n", "n_confirmed", "n_walk_invalid", "n_flip_censored", "pct_age_ge_1800s",
    "median_secs_to_flip", "p_flip_le_120s", "p_flip_le_180s", "p_flip_le_300s",
    "p_flip_le_300s_session_gated", "pct_window_crosses_close",
    "p_confirm_before_1atr", "p_stopped", "p_session_unresolved", "p_ambiguous",
    "median_age_s", "median_running_mfe", "median_velocity",
    "population", "age_bucket", "mfe_bucket", "velocity_quartile", "thin_cell",
})


def _recompute(series: pl.Series, stat: str, arg):
    if stat == "median":
        return series.median()
    if stat == "mean":
        return series.mean()
    if stat == "quantile":
        return series.quantile(arg, interpolation="linear")
    raise ValueError(f"unknown statistic {stat!r}")


def check_denominators(events: pl.DataFrame, cells: pl.DataFrame) -> list[dict]:
    """Gate V-DENOM: every confirmer-denominated cell equals an INDEPENDENT recompute.

    This gate exists because the aggregation is NOT self-evidently confirmers-only.
    `measure_to_confirm` populates `seconds/mae/return_to_confirm` whenever the
    confirming flip was reached inside the window -- including trades stopped out
    first -- so 4,186 of 4,427 population-A non-confirmers carry a non-null
    `return_at_confirm_atr`. A missing `.filter(confirmed)` therefore does NOT show up
    as a null, it silently pools two populations: it deflated the >900s median return
    from 0.833 to 0.558 and inflated its MAE p50 from 0.329 to 0.891, in
    `primary_matrix.csv` itself. Found by lookahead-auditor pass 2 (CRITICAL).

    The recompute is independent in the sense that matters: it reads the raw event
    frame and applies the filter itself, so it does NOT pass if `analysis.AGGS` drops
    its filter. `tests/test_denominator_gate.py` proves that directly by feeding the
    gate a deliberately leaked cell table and asserting it fails.

    `stat` is matched to how AGGS computes each column (median / mean / linear
    quantile); using `median()` to check a `quantile(0.50)` is what surfaced the
    polars interpolation-default mismatch on the first re-run.
    """
    out: list[dict] = []
    # A column absent from `cells` cannot be compared. Absence is itself reported by
    # V_DENOM_all_columns_present below rather than silently skipped -- otherwise
    # deleting a column from AGGS would make its gate vacuously pass.
    present = [t for t in CONFIRMER_DENOMINATED if t[0] in cells.columns]
    missing = [t[0] for t in CONFIRMER_DENOMINATED if t[0] not in cells.columns]
    totals = {col: 0 for col, _, _, _ in present}
    checked = 0

    for row in cells.iter_rows(named=True):
        if row["n_confirmed"] == 0:
            continue
        sub = events.filter(
            (pl.col("population") == row["population"])
            & (pl.col("age_bucket") == row["age_bucket"])
            & (pl.col("mfe_bucket") == row["mfe_bucket"])
            & pl.col("confirmed")
        )
        checked += 1
        for col, src, stat, arg in present:
            expected = _recompute(sub[src].cast(pl.Float64), stat, arg)
            observed = row[col]
            if expected is None and observed is None:
                continue
            if expected is None or observed is None or abs(expected - observed) > 1e-9:
                totals[col] += 1

    for col, _, _, _ in present:
        g = _gate(f"V_DENOM_{col}_is_confirmers_only", 0, totals[col])
        g["n_cells_checked"] = checked
        out.append(g)

    out.append(_gate("V_DENOM_all_columns_present", [], missing, ok=not missing))

    # Coverage: any emitted column that is neither checked above nor explicitly
    # declared non-confirmer-denominated is an unenforced invariant, which is the
    # defect pass 3 raised. Fail loudly rather than silently under-cover.
    known = {c for c, _, _, _ in CONFIRMER_DENOMINATED} | NON_CONFIRMER_DENOMINATED
    unclassified = sorted(set(cells.columns) - known)
    g = _gate("V_DENOM_coverage_is_complete", [], unclassified, ok=not unclassified)
    g["n_confirmer_columns_checked"] = len(CONFIRMER_DENOMINATED)
    out.append(g)

    # The leak is only invisible when the source column is non-null on non-confirmers.
    # Record that count so the gate's necessity is visible rather than implied.
    leak = events.filter(
        ~pl.col("confirmed") & pl.col("return_at_confirm_atr").is_not_null()
    ).height
    g = _gate("V_DENOM_leak_surface_is_disclosed", True, leak >= 0, ok=True)
    g["n_nonconfirmers_with_a_return_at_confirm_value"] = leak
    out.append(g)
    return out


def _cell(cells: pl.DataFrame, age: str, metric: str) -> float | None:
    """Population-A, age-bucket-level value, pooled over progress buckets.

    Pooled by re-aggregating the underlying events, not by averaging cell medians --
    an average of medians weighted by nothing is not a median.
    """
    row = cells.filter((pl.col("population") == "A") & (pl.col("age_bucket") == age))
    if row.height != 1:
        return None
    v = row[metric][0]
    return None if v is None else float(v)


def age_contrast(events: pl.DataFrame) -> pl.DataFrame:
    """Population-A metrics by age bucket, pooled over progress (verdict input)."""
    from studies.p90_regime_age_progress_diagnostic.implementation.analysis import (
        AGGS, _complete,
    )
    from studies.p90_regime_age_progress_diagnostic.implementation.population import (
        AGE_LABELS,
    )
    agg = (events.filter(pl.col("population") == "A")
           .group_by(["population", "age_bucket"]).agg(AGGS))
    return _complete(agg, {"population": ("A",), "age_bucket": AGE_LABELS})


def classify(age_tbl: pl.DataFrame, velocity: pl.DataFrame,
             comparison_tbl: pl.DataFrame) -> dict:
    """Mechanical D1-D5 (SPEC 7). Multiple verdicts may co-fire; order is fixed."""
    def val(age: str, metric: str):
        return _cell(age_tbl, age, metric)

    young_n = val(YOUNG_BUCKET, "n") or 0
    old_n = val(OLD_BUCKET, "n") or 0
    usable = young_n >= THIN_CELL_N and old_n >= THIN_CELL_N

    y_flip, o_flip = val(YOUNG_BUCKET, "p_flip_le_300s"), val(OLD_BUCKET, "p_flip_le_300s")
    y_conf, o_conf = val(YOUNG_BUCKET, "p_confirm_before_1atr"), val(OLD_BUCKET, "p_confirm_before_1atr")
    y_mfe, o_mfe = val(YOUNG_BUCKET, "median_eventual_mfe"), val(OLD_BUCKET, "median_eventual_mfe")
    y_r3, o_r3 = val(YOUNG_BUCKET, "p_mfe_ge_3"), val(OLD_BUCKET, "p_mfe_ge_3")

    def rel(a, b):
        if a is None or b is None or b == 0:
            return None
        return abs(a - b) / abs(b)

    fired: list[str] = []
    facts = {
        "usable_contrast": usable,
        "young_bucket": YOUNG_BUCKET, "old_bucket": OLD_BUCKET,
        "young_n": young_n, "old_n": old_n,
        "p_flip_le_300s": {"young": y_flip, "old": o_flip, "rel_diff": rel(y_flip, o_flip)},
        "p_confirm_before_1atr": {"young": y_conf, "old": o_conf, "rel_diff": rel(y_conf, o_conf)},
        "median_eventual_mfe": {"young": y_mfe, "old": o_mfe},
        "p_mfe_ge_3": {"young": y_r3, "old": o_r3},
    }

    if usable and None not in (y_flip, o_flip, y_conf, o_conf, y_mfe, o_mfe):
        d_mfe = y_mfe - o_mfe
        if (rel(y_flip, o_flip) or 1) < 0.25 and (rel(y_conf, o_conf) or 1) < 0.25 \
                and abs(d_mfe) < 0.25:
            fired.append("D1_WORKS_ACROSS_MATURITY")
        if o_flip > y_flip and (rel(y_flip, o_flip) or 0) >= 0.25 and d_mfe > -0.25:
            fired.append("D2_STALE_REGIME_TERMINATION_DETECTOR")
        if y_flip < o_flip and (d_mfe >= 0.25 or
                                (y_r3 is not None and o_r3 is not None and y_r3 - o_r3 >= 0.05)):
            fired.append("D3_YOUNGER_TRADES_BETTER")

    # D4 -- velocity orders an outcome monotonically across all four quartiles.
    vq = velocity.filter((pl.col("population") == "A") & ~pl.col("thin_cell"))
    if vq.height == 4:
        for m in ("p_flip_le_300s", "median_eventual_mfe"):
            s = [v for v in vq[m].to_list() if v is not None]
            if len(s) == 4 and (all(x < y for x, y in zip(s, s[1:]))
                                or all(x > y for x, y in zip(s, s[1:]))):
                fired.append("D4_AGE_PROGRESS_INTERACTION")
                facts["monotone_velocity_metric"] = m
                facts["velocity_series"] = s
                break

    # D5 -- A and B are the same population for practical purposes.
    ca = comparison_tbl.filter(pl.col("population") == "A")
    cb = comparison_tbl.filter(pl.col("population") == "B")
    if ca.height == 1 and cb.height == 1:
        d_flip = abs((ca["p_flip_le_300s"][0] or 0) - (cb["p_flip_le_300s"][0] or 0))
        d_conf = abs((ca["p_confirm_before_1atr"][0] or 0) - (cb["p_confirm_before_1atr"][0] or 0))
        d_mfe_ab = abs((ca["median_eventual_mfe"][0] or 0) - (cb["median_eventual_mfe"][0] or 0))
        facts["ab_deltas"] = {"p_flip_le_300s": d_flip,
                              "p_confirm_before_1atr": d_conf,
                              "median_eventual_mfe": d_mfe_ab}
        if d_flip <= 0.02 and d_conf <= 0.02 and d_mfe_ab <= 0.15:
            fired.append("D5_NOTHING_CHANGES")

    # D0 is NOT an alias for D5. Aliasing them would let a run in which the age
    # contrast diverges AND populations A/B disagree beyond tolerance be written to
    # summary.json as "nothing changes" -- a manufactured null on this study's
    # headline deliverable. The D1-D3 conditions are deliberately not exhaustive
    # (e.g. "old flips more AND runs further" satisfies neither D2 nor D3), so the
    # unclassified case is real and must be labelled as itself. Found by
    # lookahead-auditor pass 1 (CRITICAL).
    return {
        "verdicts_fired": fired,
        "primary_verdict": fired[0] if fired else "D0_UNCLASSIFIED",
        "unclassified": not fired,
        "age_contrast_substitution": (
            f"SPEC 7's young/old contrast uses {YOUNG_BUCKET} vs {OLD_BUCKET}. The "
            f"brief's 120-240s and 240-300s buckets carry n=5 and n=14 and are barred "
            f"from every inferential test by the thin-cell rule (SPEC 6.1)."
        ),
        "facts": facts,
    }
