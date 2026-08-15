from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.contracts import expected_directional_cells, expected_pooled_cells
from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.validation import build_validation, derive_terminal_label, promotion_gate, validate_score_grid


def _drow(key):
    model, direction, maturity_bucket = key
    return {"model": model, "direction": direction, "maturity_bucket": maturity_bucket, "n": 1, "positives": 1, "roc_auc": .5, "pr_auc": .5, "brier": .25, "timing_metric": 0,
            "auc_delta_vs_baseline": 0.0, "economics_nonworse": True,
            "economic_tail_improves": False, "rolling_delta_vs_structural": 0.0}


def test_validation_requires_exact_directional_and_pooled_grid():
    directional = [_drow(key) for key in expected_directional_cells()]
    pooled = [{"model": model, "maturity_bucket": bucket} for model, bucket in expected_pooled_cells()]
    assert validate_score_grid(directional, pooled)["pass"]
    assert not validate_score_grid(directional[:-1], pooled)["pass"]
    assert not validate_score_grid(directional + [directional[0]], pooled)["pass"]


def test_empty_or_incomplete_evidence_is_abort_not_r5():
    assert derive_terminal_label({"pass": True}, []) == "ABORT_CONTRACT_OR_CAUSAL_FAILURE"


def test_promotion_refuses_callerless_missing_materialized_evidence(tmp_path):
    assert promotion_gate(tmp_path)["status"] == "BLOCKED"


def test_validation_builder_refuses_missing_material_evidence(tmp_path):
    report = build_validation(tmp_path)
    assert not report["pass"]
    assert set(report["checks"])
