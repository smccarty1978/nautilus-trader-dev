from types import SimpleNamespace

import pandas as pd
import pytest

from research_workflow import generic_collector as gc
from backtests.nt_runtime.compiled_study_loader import CompiledStudyData
from backtests.nt_runtime.data_plan import DataPlan
from backtests.nt_runtime.run_plan import RunPlan, RunStage
from backtests.nt_runtime.telemetry import CausalTelemetry
from research.schemas.study_spec import StudySpec
from research_workflow.output_manager import OutputManager


def _collector(monkeypatch):
    monkeypatch.setattr(gc, "is_in_session", lambda *_: True)
    monkeypatch.setattr(gc, "session_close_ns", lambda *_: 10_000 * gc.NS)
    c = gc.FlipPredictionCollector.__new__(gc.FlipPredictionCollector)
    c._diagnostic_enabled = True
    c._diagnostic_thresholds = {"LONG": 0.5, "SHORT": 0.5}
    c._diagnostic_score_columns = {"LONG": "long_score", "SHORT": "short_score"}
    c._diagnostic_anchors = {}
    c.diagnostic_records = []
    c.cfg = SimpleNamespace(session="RTH")
    c.active_regime_dir = 1
    c.is_both_directions = True
    c.target_dir = -1
    c.pending_candidates = []
    c.regime_start_close = 1.0
    c.regime_frozen_atr = 1.0
    c.highest_high_since_flip = 1.0
    c.lowest_low_since_flip = 1.0
    c.mfe_progress_previous_extreme = 0.0
    c.mfe_progress_last_extreme_ts = None
    c.mfe_progress_count = 0
    c.next_checkpoint_index = 0
    c._diagnostic_score = lambda snapshot, direction: (
        snapshot.get("score"), snapshot.get("score") is not None,
        "VALID" if snapshot.get("score") is not None else "SCORE_UNAVAILABLE",
    )
    return c


def test_inclusive_first_fire_continues_after_eligibility_and_finishes_on_canonical_flip(monkeypatch):
    c = _collector(monkeypatch)
    c.regime_start_ns = 100 * gc.NS
    c._diagnostic_checkpoint(105 * gc.NS, 1, True, {"score": 0.5})
    c._diagnostic_checkpoint(110 * gc.NS, 1, False, {"score": 0.2})
    assert len(c._diagnostic_anchors) == 1
    c._on_regime_flip(-1, 112 * gc.NS, 1.0, 1.0, 1.0)
    assert [r["offset_s"] for r in c.diagnostic_records] == [0, 5]
    assert {r["terminal_reason"] for r in c.diagnostic_records} == {"ACCEPTED_OPPOSING_FLIP"}
    assert {r["market_path_status"] for r in c.diagnostic_records} == {"OBSERVED"}


def test_missing_score_censors_only_score_path_and_deadline_resolves_market(monkeypatch):
    c = _collector(monkeypatch)
    c.regime_start_ns = 1 * gc.NS
    c._diagnostic_checkpoint(5 * gc.NS, 1, True, {"score": 0.7})
    c._diagnostic_checkpoint(10 * gc.NS, 1, False, {"score": None})
    c._diagnostic_checkpoint(605 * gc.NS, 1, False, {"score": 0.1})
    assert len(c.diagnostic_records) == 3
    assert {r["terminal_reason"] for r in c.diagnostic_records} == {"NO_FLIP_BEFORE_DEADLINE"}
    assert {r["market_path_status"] for r in c.diagnostic_records} == {"OBSERVED"}
    assert {r["score_path_status"] for r in c.diagnostic_records} == {"CENSORED"}


def test_on_stop_market_censors_unterminated_anchor(monkeypatch):
    c = _collector(monkeypatch)
    c.regime_start_ns = 1 * gc.NS
    c._diagnostic_checkpoint(5 * gc.NS, 1, True, {"score": 0.7})
    c.pending_candidates = []
    c.last_ts_seen = 6 * gc.NS
    c._sweep_elapsed_horizons = lambda *args, **kwargs: None
    c.on_stop()
    assert c.diagnostic_records[0]["terminal_reason"] == "MARKET_OR_DATA_CENSOR"
    assert c.diagnostic_records[0]["market_path_status"] == "CENSORED"


def test_output_manager_persists_diagnostic_only_for_diagnostic_operation(tmp_path):
    spec = StudySpec.model_validate({
        "study": {"id": "diag", "type": "flip_prediction", "risk_tier": 1, "description": "x"},
        "operation": {"kind": "diagnostic_followup"}, "instrument": {"symbol": "NQ", "venue": "XCME"},
        "population": {"type": "regime_state", "prevailing_regime": "both", "session": "RTH"},
        "target": {"type": "flip", "event": "x", "direction": "both", "horizon_seconds": 600},
        "features": {"metadata_columns": ["observation_ts", "regime_start_ns", "checkpoint_index"]},
        "chronology": {"diagnostic": [2024], "prohibited": [2025, 2026]},
        "execution": {"runtime": "nautilustrader", "strategy_class": "x", "bounded": True},
    })
    sd = CompiledStudyData("diag", tmp_path, "flip_prediction", spec, spec.compute_sha256(), {}, {})
    start = pd.Timestamp("2024-01-02", tz="UTC")
    dp = DataPlan("NQ", "XCME", "NQ.XCME", "20", "0.25", tmp_path, "1s", "1m", start, start + pd.Timedelta(days=1), 0, start, "OPEN_STAMPED", 1, 1)
    mgr = OutputManager(sd, dp, RunPlan(RunStage.DAY, "2024-01-02", "2024-01-02"), output_base_dir=tmp_path / "runs")
    telemetry = CausalTelemetry(); telemetry.start()
    diag = pd.DataFrame([{"regime_start_ns": 1, "direction": "LONG", "anchor_ts": 5, "scheduled_ts": 5, "offset_s": 0,
                          "score": .5, "score_valid": True, "score_reason": "VALID", "terminal_reason": "NO_FLIP_BEFORE_DEADLINE",
                          "terminal_ts": 605, "market_path_status": "OBSERVED", "score_path_status": "OBSERVED"}])
    mgr.persist_collection(pd.DataFrame(columns=["observation_ts", "regime_start_ns", "checkpoint_index"]),
                           pd.DataFrame(columns=["observation_ts", "regime_start_ns", "checkpoint_index"]), telemetry.stop(), diagnostic_df=diag)
    assert (mgr.collection_dir / "diagnostic_followup.parquet").is_file()
    with pytest.raises(ValueError, match="DIAGNOSTIC_OUTPUT_OPERATION_MISMATCH"):
        spec.operation.kind = "train_evaluate"
        mgr.persist_collection(pd.DataFrame(columns=["observation_ts", "regime_start_ns", "checkpoint_index"]),
                               pd.DataFrame(columns=["observation_ts", "regime_start_ns", "checkpoint_index"]), telemetry, diagnostic_df=diag)
