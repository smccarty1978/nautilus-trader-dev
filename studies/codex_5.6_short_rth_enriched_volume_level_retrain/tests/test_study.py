"""Focused synthetic contract tests; production surfaces are never read."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PATH = Path(__file__).parents[1] / "run_study.py"
SPEC = importlib.util.spec_from_file_location("retrain_study", PATH)
study = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(study)


def test_frozen_cutoff_ignores_future_distribution():
    dev_scores = np.array([.1, .2, .8, .9])
    cutoff = study.derive_cutoff(dev_scores, .5)
    original_scores = np.array([.05, .25, .81, .95])
    df = pd.DataFrame({"regime_start_ns": [1, 2, 3, 4], "observation_time": [1, 1, 1, 1]})
    kept, _ = study.apply_cutoff(df, original_scores, cutoff)
    extended = np.r_[original_scores, [-999.0, 999.0]]
    assert (original_scores >= cutoff).tolist() == (extended[:4] >= cutoff).tolist()
    assert kept.regime_start_ns.tolist() == [3, 4]


def test_exit_order_drawdown_has_leading_zero():
    rows = pd.DataFrame({"exit_ts": [2, 1], "regime_start_ns": [2, 1], "observation_time": [2, 1],
                         "net_pnl": [100., -50.], "exit_reason": ["confirmation_timeout_exit"] * 2,
                         "_label": ["confirmation_timeout"] * 2})
    assert study.economic(rows)["dd"] == 50.


def test_labels_and_categorical_unknown_fail_closed():
    df = pd.DataFrame({"label_available": [True] * 5, "entry_direction": [-1] * 5,
        "exit_reason": ["original_opposing_flip_exit", "original_opposing_flip_exit", "preflip_policy_stop", "confirmation_timeout_exit", "original_stop_after_aligned_flip"],
        "net_pnl": [1., -1., -1., -1., -1.]})
    assert set(study.label_frame(df)) == set(study.CLASSES)
    with pytest.raises(RuntimeError):
        study.matrix(pd.DataFrame({"x": [1.], "p": ["BAD"]}), ["x", "p__ABOVE", "p__BELOW", "p__TOUCH", "p__UNAVAILABLE"], ["p"])


def _temporal_row(entry_ct: str) -> pd.DataFrame:
    observation = int(pd.Timestamp("2025-01-02 14:29:55", tz="UTC").value)
    entry = int(pd.Timestamp(entry_ct, tz="America/Chicago").tz_convert("UTC").value)
    return pd.DataFrame({"regime_start_ns": [observation - 60_000_000_000], "observation_time": [observation],
        "observation_ts": [observation], "entry_ts": [entry], "exit_ts": [entry + 1_000_000_000],
        "latest_source_ts_used": [observation], "latest_1s_bar_close_ts_used": [observation],
        "latest_1m_bar_close_ts_used": [observation - 55_000_000_000]})


def test_gap_snap_and_fill_time_rth():
    study.validate_temporal_population(_temporal_row("2025-01-02 08:30:00"), 2025)
    with pytest.raises(RuntimeError):
        study.validate_temporal_population(_temporal_row("2025-01-02 15:00:00"), 2025)


class FakeModel:
    classes_ = np.array(study.CLASSES)
    def predict_proba(self, x):
        base = np.array([.2, .2, .2, .2, .2])
        return np.tile(base, (len(x), 1))


def test_attribution_and_diagnostics_are_json_records():
    baseline = pd.DataFrame({"regime_start_ns": [1], "net_pnl": [-10.], "exit_reason": ["preflip_policy_stop"], "entry_fill_ts": [2], "exit_ts": [3]})
    selected = pd.DataFrame({"regime_start_ns": [1], "net_pnl": [-4.], "exit_reason": ["preflip_policy_stop"], "entry_ts": [2], "exit_ts": [3]})
    attribution, _, _ = study.exact_attribution(selected, baseline)
    assert attribution["stop_savings_exact"] == 6.
    y = pd.Series(list(study.CLASSES) * 2)
    diagnostics, calibration = study.diagnostics(FakeModel(), np.zeros((10, 1)), y, np.linspace(-1, 1, 10))
    json.dumps({"diagnostics": diagnostics, "calibration": calibration})
    assert calibration and all(isinstance(row, dict) for row in calibration)


def test_empty_breakdowns_and_96_schedule_contract():
    meta = {"schedule_id": "x", "feature_set": "F0", "model": "logistic", "band": .5, "split": "2025"}
    months, exits = study.schedule_breakdowns(pd.DataFrame(columns=["exit_ts", "net_pnl", "exit_reason"]), meta)
    assert months[0]["month_ct"] == "NO_TRADES"
    assert len(exits) == 4 and sum(row["count"] for row in exits) == 0
    ids = {(f"F{f}__{m}__r{b}", year) for f in range(4) for m in ("logistic", "hist") for b in study.BANDS for year in (2025, 2026)}
    assert len(ids) == 96


def test_nonempty_monthly_breakdown_uses_stable_public_column_name():
    exit_ts = int(pd.Timestamp("2025-03-04 15:00:00", tz="UTC").value)
    rows = pd.DataFrame({"exit_ts": [exit_ts], "net_pnl": [12.5], "exit_reason": ["original_opposing_flip_exit"]})
    meta = {"schedule_id": "x", "feature_set": "F0", "model": "logistic", "band": .5, "split": "2025"}
    months, exits = study.schedule_breakdowns(rows, meta)
    assert months == [{**meta, "month_ct": "2025-03", "trades": 1, "net_pnl": 12.5}]
    assert exits[0]["count"] == 1


def test_all_exact_decision_labels_are_reachable():
    chosen = {"feature_set": "F1", "checks": 3}
    good = {"winner_clipping_exact": True, "net_positive": True}
    assert study.final_decision(False, chosen, 1, good) == "ENRICHED_RETRAIN_PARITY_FAIL"
    assert study.final_decision(True, None, None, good) == "ENRICHED_RETRAIN_REJECT"
    assert study.final_decision(True, {"feature_set": "F0", "checks": 3}, 1, good) == "ENRICHED_RETRAIN_BASELINE_STILL_BEST"
    assert study.final_decision(True, chosen, 1, {"winner_clipping_exact": False}) == "ENRICHED_RETRAIN_CLIPS_WINNERS"
    assert study.final_decision(True, chosen, 1, {"winner_clipping_exact": True, "net_positive": False}) == "ENRICHED_RETRAIN_OVERFITS_2025"
    assert study.final_decision(True, chosen, 1, good) == "ENRICHED_RETRAIN_PROMISING"


def test_json_safe_and_recovery_candidate_contract():
    assert study.json_safe(float("inf")) == "Infinity"
    assert study.json_safe(float("-inf")) == "-Infinity"
    assert study.json_safe(float("nan")) == "NaN"
    baseline = {"per_trade": 23., "pf": 1.1, "dd": 18_000., "prestop": .3, "oppflip_pnl": 105_000.}
    rows = []
    for f in range(4):
        for model in ("logistic", "hist"):
            for band in study.BANDS:
                row = {"schedule_id": f"F{f}__{model}__rband{band:g}", "feature_set": f"F{f}", "model": model,
                       "band": band, "cutoff": float("-inf") if band == 1 else 0., "trades": 10,
                       "net": 100., "per_trade": 30., "pf": 1.2, "dd": 10_000., "prestop_rate": .2,
                       "oppflip_pnl": 100_000.}
                row["checks"] = study.checks(row, baseline)
                rows.append(row)
    candidates, chosen, leader = study.validate_recovery_candidates(pd.DataFrame(rows), baseline)
    assert len(candidates) == 48 and chosen is not None and leader is not None
