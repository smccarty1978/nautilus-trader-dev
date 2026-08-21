import json

import polars as pl

from studies.Codex_structural_regime_geometry_maturity.implementation.finalize_artifacts import terminal_summary


def _write_workflow(tmp_path, *, evidence, economics, validation="PASS"):
    out, study = tmp_path / "results", tmp_path / "study"
    out.mkdir(parents=True); (study / "audit").mkdir(parents=True)
    for name in ("status.json", "contract_status.json"):
        (study / "audit" / name).write_text(json.dumps({"critical": 0, "verdict": "PASS"}))
    (study / "audit" / "lint.json").write_text(json.dumps({"critical": 0, "warning": 0}))
    (out / "phase0_contract.json").write_text(json.dumps({"status": "PASS"}))
    rows, timing, crossings = [], [], []
    for direction, bucket in evidence:
        rows += [
            {"model_set": "TOP25", "direction": direction, "maturity_bucket": bucket, "n": 10, "positives": 2, "roc_auc": 0.50},
            {"model_set": "TOP25_PLUS_STRUCTURAL", "direction": direction, "maturity_bucket": bucket, "n": 10, "positives": 2, "roc_auc": 0.51},
        ]
    if not rows:
        rows = [
            {"model_set": "TOP25", "direction": "SHORT", "maturity_bucket": "300-600s", "n": 10, "positives": 2, "roc_auc": 0.50},
            {"model_set": "TOP25_PLUS_STRUCTURAL", "direction": "SHORT", "maturity_bucket": "300-600s", "n": 10, "positives": 2, "roc_auc": 0.50},
        ]
    cells = {(row["direction"], row["maturity_bucket"]) for row in rows}
    for direction, bucket in cells:
        timing += [
            {"model_set": "TOP25", "direction": direction, "maturity_bucket": bucket, "spearman_score_pct_vs_neg_secs_to_flip": 0.1, "median_top_score_secs_to_flip": 100.0},
            {"model_set": "TOP25_PLUS_STRUCTURAL", "direction": direction, "maturity_bucket": bucket, "spearman_score_pct_vs_neg_secs_to_flip": 0.1, "median_top_score_secs_to_flip": 100.0},
        ]
        a_confirm, a_mfe, b_confirm, b_mfe = (0.5, 1.0, 0.6, 1.1) if economics else (0.5, 1.0, 0.4, 0.9)
        crossings += [
            {"model_set": "TOP25", "direction": direction, "maturity_bucket": bucket, "threshold_quantile": 0.9, "p_confirm_before_1atr": a_confirm, "median_eventual_opposite_mfe_atr": a_mfe},
            {"model_set": "TOP25_PLUS_STRUCTURAL", "direction": direction, "maturity_bucket": bucket, "threshold_quantile": 0.9, "p_confirm_before_1atr": b_confirm, "median_eventual_opposite_mfe_atr": b_mfe},
        ]
    pl.DataFrame(rows).write_csv(out / "oos_row_metrics.csv")
    pl.DataFrame(timing).write_csv(out / "oos_timing_metrics.csv")
    pl.DataFrame(crossings).write_csv(out / "oos_crossing_metrics.csv")
    (out / "validation_report.json").write_text(json.dumps({"status": validation}))
    return out, study


def test_terminal_summary_exercises_every_frozen_label_from_real_artifacts(tmp_path):
    scenarios = {
        "S1_STRUCTURAL_GEOMETRY_ADDS_REAL_INFORMATION": ([('SHORT', '300-600s'), ('LONG', '600-900s')], True, "PASS"),
        "S2_YOUNGER_REGIMES_SPECIFICALLY": ([('SHORT', '300-600s'), ('LONG', '300-600s')], True, "PASS"),
        "S3_CLASSIFICATION_ONLY": ([('SHORT', '300-600s'), ('LONG', '600-900s')], False, "PASS"),
        "S4_ECONOMIC_TAIL_ONLY": ([], True, "PASS"),
        "S5_NO_MATERIAL_INCREMENTAL_INFORMATION": ([], False, "PASS"),
        "ABORT_CONTRACT_OR_CAUSAL_FAILURE": ([], False, "FAIL"),
    }
    observed = set()
    for index, (label, (evidence, economics, validation)) in enumerate(scenarios.items()):
        out, study = _write_workflow(tmp_path / str(index), evidence=evidence, economics=economics, validation=validation)
        observed.add(terminal_summary(out, study)["terminal_label"])
    assert observed == set(scenarios)


def test_terminal_summary_aborts_on_failed_phase0_or_lint(tmp_path):
    for index, (path, payload) in enumerate((("phase0_contract.json", {"status": "FAIL"}), ("lint.json", {"critical": 0, "warning": 1}))):
        out, study = _write_workflow(tmp_path / str(index), evidence=[], economics=False)
        target = out / path if path == "phase0_contract.json" else study / "audit" / path
        target.write_text(json.dumps(payload))
        assert terminal_summary(out, study)["terminal_label"] == "ABORT_CONTRACT_OR_CAUSAL_FAILURE"
