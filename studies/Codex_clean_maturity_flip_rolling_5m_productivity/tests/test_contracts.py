from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.contracts import (
    TERMINAL_LABELS,
    classify_terminal,
    expected_directional_cells,
    expected_pooled_cells,
)


def test_exact_required_reporting_grid_is_predeclared():
    assert len(expected_directional_cells()) == 18
    assert len(expected_pooled_cells()) == 9


def test_every_terminal_label_is_reachable_from_directional_evidence_inputs():
    outcomes = {
        classify_terminal(
            audit_clean=audit_clean, broad_improvement=broad, young_improvement=young,
            timing_only=timing, economic_tail_only=economic, rolling_adds_nothing=rolling,
        )
        for audit_clean in (False, True)
        for broad in (False, True)
        for young in (False, True)
        for timing in (False, True)
        for economic in (False, True)
        for rolling in (False, True)
    }
    assert set(TERMINAL_LABELS) <= outcomes
