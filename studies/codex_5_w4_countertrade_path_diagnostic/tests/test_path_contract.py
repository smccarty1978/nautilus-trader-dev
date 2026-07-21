import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "build_diagnostic.py"
spec = importlib.util.spec_from_file_location("codex5_diag", MODULE_PATH)
diag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diag
spec.loader.exec_module(diag)


def test_path_extrema_are_direction_symmetric_and_nonnegative():
    highs = np.array([101.0, 103.0])
    lows = np.array([99.0, 97.0])
    long_fav, long_adv = diag.path_extrema(1, 100.0, highs, lows)
    short_fav, short_adv = diag.path_extrema(-1, 100.0, highs, lows)
    assert long_fav.tolist() == [1.0, 3.0]
    assert long_adv.tolist() == [1.0, 3.0]
    assert short_fav.tolist() == [1.0, 3.0]
    assert short_adv.tolist() == [1.0, 3.0]
    assert np.all(long_fav >= 0) and np.all(short_adv >= 0)


def test_boundary_mark_uses_completed_bar_only():
    ts = np.array([0, 1, 2], dtype=np.int64) * diag.NS
    closes = np.array([100.0, 101.0, 999.0])
    assert diag.mark_before(ts, closes, 2 * diag.NS, 90.0) == 101.0
    assert diag.mark_before(ts, closes, 0, 90.0) == 90.0


def test_boundary_open_is_explicit_next_available_open():
    ts = np.array([0, 2, 5], dtype=np.int64) * diag.NS
    opens = np.array([100.0, 102.0, 105.0])
    fill_ts, fill = diag.boundary_open(ts, opens, diag.NS)
    assert fill_ts == 2 * diag.NS and fill == 102.0


def test_delayed_flip_boundary_pnl_uses_next_open_not_stale_close():
    ts = np.array([0, 2], dtype=np.int64) * diag.NS
    opens = np.array([100.0, 110.0])
    closes = np.array([99.0, 111.0])
    fill_ts, pnl = diag.pnl_at_boundary(ts, opens, closes, diag.NS, 100.0, 1)
    assert fill_ts == 2 * diag.NS
    assert pnl == 10.0


def test_delayed_aligning_flip_checkpoint_mark_uses_next_open():
    ts = np.array([0, 2, 5], dtype=np.int64) * diag.NS
    opens = np.array([100.0, 110.0, 120.0])
    closes = np.array([99.0, 111.0, 121.0])
    mark_ts, mark, source = diag.checkpoint_mark(
        ts, opens, closes, diag.NS, 0, diag.NS, 5 * diag.NS, 100.0, 120.0)
    assert mark_ts == 2 * diag.NS
    assert mark == 110.0
    assert source == "aligning_flip_next_open"
    mfe, mae = diag.include_discrete_mark(0.2, 0.1, 1.0)
    assert mfe == 1.0 and mae == 0.1
    mfe, mae = diag.include_discrete_mark(0.2, 0.1, -1.0)
    assert mfe == 0.2 and mae == 1.0


def test_counterfactual_label_is_strictly_after_exit():
    times = pd.Series([0, 5, 10])
    exit_time = 5
    assert (times > exit_time).tolist() == [False, False, True]


def test_stop_bar_mfe_primary_excludes_unknown_intrabar_order():
    ts = np.array([0, 1], dtype=np.int64) * diag.NS
    highs = np.array([101.0, 110.0])
    lows = np.array([99.0, 80.0])
    peak, peak_bar_ts, peak_available_ts, source, upper = diag.held_peak(
        ts, highs, lows, 0, diag.NS, 1, 100.0, True, 85.0)
    assert peak == 1.0 and peak_bar_ts == 0
    assert peak_available_ts == diag.NS and source == "1s_ohlc_range"
    assert upper == 10.0


@pytest.mark.parametrize("direction,exit_fill", [(1, 110.0), (-1, 90.0)])
def test_favorable_scheduled_exit_gap_is_included_as_peak(direction, exit_fill):
    ts = np.array([0, 1], dtype=np.int64) * diag.NS
    highs = np.array([101.0, 111.0])
    lows = np.array([99.0, 89.0])
    peak, peak_bar_ts, peak_available_ts, source, upper = diag.held_peak(
        ts, highs, lows, 0, diag.NS, direction, 100.0, False, exit_fill)
    assert peak == 10.0
    assert peak_bar_ts is None
    assert peak_available_ts == diag.NS
    assert source == "scheduled_exit_open"
    assert upper == 10.0


def test_score_lookup_is_backward_only_and_staleness_limited():
    scores = pd.DataFrame({
        "regime_start_ns": [0, 0],
        "observation_time": np.array([5, 10], dtype=np.int64) * diag.NS,
        "w4_score": [0.4, 0.8], "direction_threshold": [0.7, 0.7],
        "score_valid": [True, True],
    })
    lookup = diag.ScoreLookup(scores, 5)
    assert lookup.latest(0, 9 * diag.NS).score == 0.4
    assert lookup.latest(0, 4 * diag.NS) is None
    assert lookup.latest(0, 16 * diag.NS) is None


def test_post_flip_warning_never_uses_exit_boundary_score():
    scores = pd.DataFrame({
        "regime_start_ns": [10, 10, 10], "observation_time": [10, 15, 20],
        "w4_score": [0.2, 0.8, 0.9], "direction_threshold": [0.7] * 3,
        "score_valid": [True] * 3,
    })
    lookup = diag.ScoreLookup(scores, 5)
    warning = lookup.first_at_or_above(10, 10, 20)
    assert warning.observation_time == 15
    only_exit = diag.ScoreLookup(scores.iloc[[0, 2]], 5)
    assert only_exit.first_at_or_above(10, 10, 20) is None


def test_active_regime_changes_at_flip_boundary():
    starts = np.array([10, 20, 30], dtype=np.int64)
    assert diag.active_regime_start(starts, 19) == 10
    assert diag.active_regime_start(starts, 20) == 20


def test_outcome_group_uses_net_pnl_for_planned_exit():
    winner = pd.Series({"exit_reason": "opposite_flip_against_countertrade", "net_pnl_usd": 1.0})
    loser = pd.Series({"exit_reason": "opposite_flip_against_countertrade", "net_pnl_usd": 0.0})
    assert diag.outcome_group(winner) == "opposite_flip_exit_winner"
    assert diag.outcome_group(loser) == "opposite_flip_exit_loser"


def test_delayed_scheduled_fill_uses_exit_decision_for_w4_boundary():
    planned = pd.Series({"exit_reason": "opposite_flip_against_countertrade",
                         "scheduled_exit_decision_ts": 20 * diag.NS,
                         "exit_fill_ts": 26 * diag.NS})
    stopped = pd.Series({"exit_reason": "stop_after_aligned_flip",
                         "scheduled_exit_decision_ts": 40 * diag.NS,
                         "exit_fill_ts": 26 * diag.NS})
    assert diag.w4_exit_boundary(planned) == 20 * diag.NS
    assert diag.w4_exit_boundary(stopped) == 26 * diag.NS
    scores = pd.DataFrame({"regime_start_ns": [10 * diag.NS],
                           "observation_time": [15 * diag.NS], "w4_score": [0.8],
                           "direction_threshold": [0.7], "score_valid": [True]})
    lookup = diag.ScoreLookup(scores, 5)
    assert lookup.latest(10 * diag.NS, diag.w4_exit_boundary(planned)).score == 0.8
    assert lookup.latest(10 * diag.NS, planned.exit_fill_ts) is None


def test_named_times_include_fixed_and_event_checkpoints():
    trade = pd.Series({"entry_fill_ts": 0, "confirm_flip_ns": 100 * diag.NS,
                       "exit_fill_ts": 200 * diag.NS})
    config = {"entry_offsets_seconds": [30, 60, 120, 300],
              "post_flip_offsets_seconds": [60, 120], "grid_seconds": 5}
    times, names = diag.named_times(trade, 50 * diag.NS, config, 500 * diag.NS)
    assert 300 * diag.NS in times
    assert "countertrade_peak_mfe" in names[50 * diag.NS]
    assert "aligning_flip_plus_120s" in names[220 * diag.NS]


def test_named_time_collisions_accumulate_instead_of_overwrite():
    trade = pd.Series({"entry_fill_ts": 0, "confirm_flip_ns": 100 * diag.NS,
                       "exit_fill_ts": 200 * diag.NS})
    config = {"entry_offsets_seconds": [30], "post_flip_offsets_seconds": [60],
              "grid_seconds": 5}
    _, names = diag.named_times(trade, 0, config, 300 * diag.NS)
    assert names[0] == ["entry", "countertrade_peak_mfe"]


def test_ohlc_peak_named_checkpoint_uses_close_availability_boundary():
    ts = np.array([0, 1], dtype=np.int64) * diag.NS
    peak, bar_ts, available_ts, _, _ = diag.held_peak(
        ts, np.array([101.0, 100.0]), np.array([99.0, 99.0]),
        0, diag.NS, 1, 100.0, True, 85.0)
    assert peak == 1.0 and bar_ts == 0 and available_ts == diag.NS
    trade = pd.Series({"entry_fill_ts": 0, "confirm_flip_ns": 10 * diag.NS,
                       "exit_fill_ts": 20 * diag.NS})
    config = {"entry_offsets_seconds": [30], "post_flip_offsets_seconds": [60],
              "grid_seconds": 5}
    _, names = diag.named_times(trade, available_ts, config, 100 * diag.NS)
    assert "countertrade_peak_mfe" not in names[0]
    assert "countertrade_peak_mfe" in names[diag.NS]


def test_invalid_direction_fails_closed():
    with pytest.raises(RuntimeError, match="exact"):
        diag.path_extrema(0, 100.0, np.array([101.0]), np.array([99.0]))


def _minimal_reconciliation_frames(config):
    entry, align, exit_ts, peak = 0, 10 * diag.NS, 20 * diag.NS, 5 * diag.NS
    horizon = 30 * diag.NS
    times = np.arange(entry, horizon + 1, 5 * diag.NS, dtype=np.int64)
    labels = {entry: ["grid_5s", "entry"], align: ["grid_5s", "aligning_flip"],
              exit_ts: ["grid_5s", "final_exit"], peak: ["grid_5s", "countertrade_peak_mfe"],
              30 * diag.NS: ["grid_5s", "plus_30s"],
              15 * diag.NS: ["grid_5s", "aligning_flip_plus_5s"]}
    path = pd.DataFrame({"trade_id": "t", "checkpoint_time": times,
                         "checkpoint_labels": ["|".join(labels.get(int(t), ["grid_5s"])) for t in times],
                         "counterfactual_after_exit": times > exit_ts,
                         "w4_observation_time": [None] * len(times)})
    diagnostics = pd.DataFrame([{"trade_id": "t", "entry_fill_ts": entry,
                                 "aligning_flip_ts": align, "exit_fill_ts": exit_ts,
                                 "holding_peak_available_ts": peak}])
    trades = pd.DataFrame([{"trade_id": "t"}])
    return path, diagnostics, trades


def test_reconciliation_rejects_dropped_grid_endpoint_and_misplaced_label():
    config = {"grid_seconds": 5, "entry_offsets_seconds": [30],
              "post_flip_offsets_seconds": [5]}
    path, diagnostics, trades = _minimal_reconciliation_frames(config)
    diag.validate_outputs(path, diagnostics, trades, config)
    with pytest.raises(RuntimeError, match="incomplete 5-second grid"):
        diag.validate_outputs(path.iloc[1:].copy(), diagnostics, trades, config)
    bad = path.copy()
    bad.loc[bad["checkpoint_time"] == 30 * diag.NS, "checkpoint_labels"] = "grid_5s"
    bad.loc[bad["checkpoint_time"] == 25 * diag.NS, "checkpoint_labels"] += "|plus_30s"
    with pytest.raises(RuntimeError, match="misplaced named checkpoint"):
        diag.validate_outputs(bad, diagnostics, trades, config)


def test_optional_nanosecond_columns_preserve_values_above_2pow53():
    exact = 1_735_775_485_000_000_001
    frame = diag.records_frame(
        [{"w4_observation_time": exact}, {"w4_observation_time": None}],
        ("w4_observation_time",),
    )
    assert str(frame["w4_observation_time"].dtype) == "Int64"
    assert int(frame.loc[0, "w4_observation_time"]) == exact
    assert pd.isna(frame.loc[1, "w4_observation_time"])


def test_imported_code_dependency_mutation_fails_hash_gate():
    expected = {"policy": "p", "code_dependencies": {"repair_runner": "a"}}
    current = {"policy": "p", "code_dependencies": {"repair_runner": "changed"}}
    with pytest.raises(RuntimeError, match="hash mismatch"):
        diag.validate_hash_contract(expected, current)


@pytest.mark.parametrize(
    "direction,baseline,mark",
    [(1, 105.0, 110.0), (-1, 95.0, 90.0)],
)
def test_boundary_gap_mark_can_set_old_prevailing_new_extreme(direction, baseline, mark):
    highs = np.array([104.0])
    lows = np.array([96.0])
    assert not diag.prevailing_new_extreme(direction, baseline, highs, lows)
    assert diag.prevailing_new_extreme(direction, baseline, highs, lows, mark)
