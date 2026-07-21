"""Component-level tests for the checkpoint/resume mechanics added to
candidate_tracker.py/reduced_feature_engine.py/strategy.py/run_nt.py.

Deliberately does NOT invoke BacktestEngine or run_nt.py's main() -- these
changes have NOT been exercised end-to-end yet (see run_nt.py's own
docstring caveat). This file validates the picklability and state-fidelity
of the individual pieces a checkpoint is built from, which is what CAN be
tested without a live run.
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

IMPL = Path(__file__).resolve().parents[1] / "implementation"
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(IMPL) not in sys.path:
    sys.path.insert(0, str(IMPL))

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from candidate_tracker import CandidateTracker, is_rth_minute_of_day  # noqa: E402
import run_nt as run_nt_module  # noqa: E402
from strategy import _calendar_day_key  # noqa: E402

NS = 1_000_000_000


def test_candidate_tracker_pickle_excludes_callbacks():
    tracker = CandidateTracker(on_candidate=lambda c: None, is_rth_fn=is_rth_minute_of_day)
    tracker.on_regime_flip(ts_ns=0, new_direction=1, flip_close=100.0, atr_val=1.0)
    for t in range(1, 130):
        tracker.on_1s_bar(ts_ns=t * NS, high=105.0, low=100.0, close=105.0, minute_of_day=600)

    blob = pickle.dumps(tracker)
    assert len(blob) < 5000, "unexpectedly large pickle -- may have leaked an unrelated object graph"
    restored = pickle.loads(blob)
    assert restored._on_candidate is None
    assert restored._is_rth_fn is None


def test_candidate_tracker_pickle_preserves_active_regime_state():
    emitted = []
    tracker = CandidateTracker(on_candidate=emitted.append, is_rth_fn=is_rth_minute_of_day)
    tracker.on_regime_flip(ts_ns=0, new_direction=1, flip_close=100.0, atr_val=1.0)
    for t in range(1, 130):
        tracker.on_1s_bar(ts_ns=t * NS, high=105.0, low=100.0, close=105.0, minute_of_day=600)

    pre_idx = tracker._active.next_checkpoint_index
    pre_high = tracker._active.highest_high_since_flip
    pre_progress = tracker._active._progress_count

    restored = pickle.loads(pickle.dumps(tracker))
    assert restored._active is not None, "active regime state must survive pickling"
    assert restored._active.next_checkpoint_index == pre_idx
    assert restored._active.highest_high_since_flip == pre_high
    assert restored._active._progress_count == pre_progress


def test_candidate_tracker_resumes_identically_after_restore():
    """A restored (and rebound) tracker fed the SAME subsequent bars as an
    unrestored twin must emit IDENTICAL candidates -- proves the checkpoint
    is not just structurally present but functionally equivalent."""
    def make_and_run(n_bars):
        emitted = []
        tracker = CandidateTracker(on_candidate=emitted.append, is_rth_fn=is_rth_minute_of_day)
        tracker.on_regime_flip(ts_ns=0, new_direction=1, flip_close=100.0, atr_val=1.0)
        for t in range(1, n_bars):
            tracker.on_1s_bar(ts_ns=t * NS, high=105.0, low=100.0, close=105.0, minute_of_day=600)
        return tracker, emitted

    baseline_tracker, baseline_emitted = make_and_run(200)

    checkpoint_tracker, checkpoint_emitted = make_and_run(130)
    restored = pickle.loads(pickle.dumps(checkpoint_tracker))
    restored._on_candidate = checkpoint_emitted.append
    restored._is_rth_fn = is_rth_minute_of_day
    for t in range(130, 200):
        restored.on_1s_bar(ts_ns=t * NS, high=105.0, low=100.0, close=105.0, minute_of_day=600)

    baseline_keys = [(e["regime_start_ns"], e["checkpoint_index"]) for e in baseline_emitted]
    resumed_keys = [(e["regime_start_ns"], e["checkpoint_index"]) for e in checkpoint_emitted]
    assert baseline_keys == resumed_keys, "resumed run must emit the identical candidate sequence"


def test_reduced_feature_engine_pickle_round_trip():
    from reduced_feature_engine import ReducedFeatureEngine
    feat_sets_path = (ROOT / "studies" / "runtime_constrained_f3_feature_reduction"
                      / "results" / "candidate_feature_sets.json")
    if not feat_sets_path.exists():
        pytest.skip("requires runtime_constrained_f3_feature_reduction candidate_feature_sets.json")
    feat_list = json.loads(feat_sets_path.read_text())["F3_top25_gbt_v1"]["features"]

    engine = ReducedFeatureEngine(feat_list)
    for i in range(200):
        engine.update_1s(i * NS, 100.0 + i * 0.01, 100.5 + i * 0.01, 99.5 + i * 0.01, 100.2 + i * 0.01, 10.0)
        engine.accumulate_regime_rth(i * NS, 100.5 + i * 0.01, 99.5 + i * 0.01, 10.0, 0.5)

    restored = pickle.loads(pickle.dumps(engine))
    vec1, _, _ = engine.ordered_vector(199 * NS, 102.0, 5.0)
    vec2, _, _ = restored.ordered_vector(199 * NS, 102.0, 5.0)
    assert vec1 == vec2


def test_regime_engine_pickle_round_trip():
    from studies.fable5_pre_flip_d10_reversal_entry.strategy import RegimeEngine
    engine = RegimeEngine()
    for i in range(20):
        engine.update(100.0 + i, 99.0 + i, 99.5 + i)
    restored = pickle.loads(pickle.dumps(engine))
    assert restored.atr == engine.atr
    assert restored.regime == engine.regime


def test_calendar_day_key_boundaries():
    day1_end = int(pd.Timestamp("2025-03-01T23:59:59", tz="UTC").value)
    day2_start = int(pd.Timestamp("2025-03-02T00:00:00", tz="UTC").value)
    assert _calendar_day_key(day1_end) == "2025-03-01"
    assert _calendar_day_key(day2_start) == "2025-03-02"


def test_find_resume_state_returns_none_when_no_checkpoint(tmp_path, monkeypatch):
    import common as C
    monkeypatch.setattr(C, "WORK", tmp_path)
    ckpt_path, last_day = run_nt_module._find_resume_state("nonexistent_tag", "R5")
    assert ckpt_path is None
    assert last_day is None
