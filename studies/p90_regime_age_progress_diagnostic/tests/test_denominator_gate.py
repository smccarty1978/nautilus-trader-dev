"""Direct tests for gate V-DENOM -- does it FAIL when the leak returns?

A gate that only ever runs inside the full pipeline, on data that currently passes,
proves nothing: it could be a tautology and nobody would know. These tests feed
`check_denominators` a deliberately leaked cell table and assert it fails, which is
the only evidence that the gate has teeth.

The leak being reproduced is the real one (lookahead-auditor pass 2): a
`STOPPED_BEFORE_CONFIRM` trade still carries a non-null `return_at_confirm_atr`,
because `measure_to_confirm` fills those fields whenever the confirming flip was
reached inside the window -- so pooling does not show up as a null.
"""
from __future__ import annotations

import polars as pl

from studies.p90_regime_age_progress_diagnostic.implementation.analysis import (
    AGGS, cell_table,
)
from studies.p90_regime_age_progress_diagnostic.implementation.validate import (
    CONFIRMER_DENOMINATED, NON_CONFIRMER_DENOMINATED, check_denominators,
)


def _events() -> pl.DataFrame:
    """Four trades in one cell: 2 confirmers, 2 stopped-but-flip-reached.

    The stopped rows carry deliberately extreme `return_at_confirm_atr` / MAE values,
    so pooling them moves the cell statistic far enough to be unmissable.
    """
    rows = []
    for i, (conf, ret, mae, secs, mfe) in enumerate([
        (True, 1.00, 0.30, 100.0, 3.0),
        (True, 1.20, 0.40, 120.0, 4.0),
        (False, -5.00, 1.50, 900.0, None),   # stopped, but flip was reached
        (False, -6.00, 1.60, 950.0, None),
    ]):
        rows.append({
            "regime_id": f"R{i}", "population": "A",
            "age_bucket": "300-600s", "mfe_bucket": "1-2 ATR",
            "velocity_quartile": "Q1_slowest", "entry_year": 2023, "side": "LONG",
            "confirmed": conf, "walk_valid": True, "flip_censored": False,
            "ambiguous": False, "age_ge_1800s": False,
            "terminal_label": "CONFIRMED" if conf else "STOPPED_BEFORE_CONFIRM",
            "seconds_to_prevailing_flip": 200.0,
            "flip_le_120s": False, "flip_le_180s": False, "flip_le_300s": True,
            "flip_le_300s_session_gated": True,
            "flip_window_crosses_session_close": False,
            "return_at_confirm_atr": ret, "mae_to_confirm_atr": mae,
            "seconds_to_confirm": secs,
            "eventual_max_mfe_atr": mfe,
            "mfe_ge_1_0": None if mfe is None else mfe >= 1.0,
            "mfe_ge_2_0": None if mfe is None else mfe >= 2.0,
            "mfe_ge_3_0": None if mfe is None else mfe >= 3.0,
            "regime_age_s": 400.0, "running_mfe_atr": 1.5,
            "velocity_atr_per_min": 0.225,
        })
    return pl.DataFrame(rows, infer_schema_length=None)


def test_gate_passes_on_correctly_filtered_cells():
    events = _events()
    gates = check_denominators(events, cell_table(events))
    assert all(g["pass"] for g in gates), [g for g in gates if not g["pass"]]


def test_gate_fails_when_the_confirmer_filter_is_dropped():
    """THE test: rebuild the cells WITHOUT `.filter(confirmed)` and require a failure.

    If the gate still passed here it would be a tautology, and the pass-2 CRITICAL
    could recur undetected.
    """
    events = _events()
    leaked = events.group_by(["population", "age_bucket", "mfe_bucket"]).agg([
        pl.len().alias("n"),
        pl.col("confirmed").sum().alias("n_confirmed"),
        # the defect, verbatim: no `.filter(CONFIRMER)`
        pl.col("return_at_confirm_atr").median().alias("median_return_at_confirm"),
        pl.col("mae_to_confirm_atr").quantile(0.50, interpolation="linear")
          .alias("mae_to_confirm_p50"),
        pl.col("mfe_ge_3_0").mean().alias("p_mfe_ge_3"),
    ])
    failed = {g["gate"] for g in check_denominators(events, leaked) if not g["pass"]}
    assert "V_DENOM_median_return_at_confirm_is_confirmers_only" in failed
    assert "V_DENOM_mae_to_confirm_p50_is_confirmers_only" in failed


def test_gate_covers_every_confirmer_denominated_column_that_aggs_emits():
    """SPEC 6.1 claims V-DENOM covers them ALL. Hold the claim to the actual AGGS list.

    Raised as a CRITICAL by lookahead-auditor pass 3: the gate covered 4 of 10, and
    `p_mfe_ge_3` -- which feeds the primary verdict -- was among the uncovered.
    """
    emitted = {a.meta.output_name() for a in AGGS}
    covered = {c for c, _, _, _ in CONFIRMER_DENOMINATED}
    unclassified = emitted - covered - NON_CONFIRMER_DENOMINATED
    assert not unclassified, f"columns with no declared denominator: {sorted(unclassified)}"
    assert covered <= emitted, f"gate lists columns AGGS does not emit: {covered - emitted}"


def test_p_mfe_ge_3_is_covered_because_the_verdict_depends_on_it():
    assert "p_mfe_ge_3" in {c for c, _, _, _ in CONFIRMER_DENOMINATED}
