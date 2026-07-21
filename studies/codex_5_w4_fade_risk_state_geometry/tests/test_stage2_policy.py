import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

P = Path(__file__).resolve().parents[1] / "run_stage2_policy.py"
spec = importlib.util.spec_from_file_location("riskpolicy", P)
policy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = policy
spec.loader.exec_module(policy)


def raw(rows):
    idx = pd.to_datetime([r[0] for r in rows], unit="s", utc=True)
    return pd.DataFrame({"open": [r[1] for r in rows], "high": [r[2] for r in rows],
                         "low": [r[3] for r in rows], "close": [r[4] for r in rows],
                         "volume": 1.0}, index=idx)


def trade(direction=1):
    return pd.Series({"entry_fill_open": 100.0, "entry_direction": direction,
                      "atr_at_checkpoint": 10.0, "stop_px": 85.0 if direction == 1 else 115.0,
                      "confirm_flip_ns": 0, "scheduled_exit_decision_ts": 3 * policy.NS,
                      "exit_fill_ts": 3 * policy.NS, "exit_fill_px": 105.0 if direction == 1 else 95.0})


def rule():
    return {"arm_postflip_entry_anchored_mfe_atr": 1.0, "retained_profit_floor_atr": 0.25}


def test_arm_bar_does_not_activate_floor_until_next_bar():
    data = raw([(0, 100, 111, 101, 110), (1, 110, 111, 101, 102),
                (2, 102, 103, 101, 102), (3, 105, 106, 104, 105)])
    got = policy.simulate_from_align(trade(), data, rule())
    assert got["armed"] and got["arm_available_ts"] == policy.NS
    assert got["new_exit_fill_ts"] == policy.NS
    assert got["new_exit_fill_px"] == 102.5


def test_arm_and_original_stop_same_bar_is_loss_first():
    data = raw([(0, 100, 111, 84, 90), (1, 90, 91, 89, 90),
                (2, 90, 91, 89, 90), (3, 105, 106, 104, 105)])
    got = policy.simulate_from_align(trade(), data, rule())
    assert got["new_exit_reason"] == "original_stop_after_aligned_flip"
    assert got["new_exit_fill_px"] == 85.0


def test_gap_through_active_floor_fills_at_open_long_and_short():
    long_data = raw([(0, 100, 111, 100, 110), (1, 90, 91, 89, 90),
                     (2, 90, 91, 89, 90), (3, 105, 106, 104, 105)])
    short_data = raw([(0, 100, 100, 89, 90), (1, 110, 111, 109, 110),
                      (2, 110, 111, 109, 110), (3, 95, 96, 94, 95)])
    assert policy.simulate_from_align(trade(1), long_data, rule())["new_exit_fill_px"] == 90.0
    assert policy.simulate_from_align(trade(-1), short_data, rule())["new_exit_fill_px"] == 110.0


def test_scheduled_exit_boundary_precedes_its_bar_range():
    data = raw([(0, 100, 105, 95, 101), (1, 101, 105, 95, 102),
                (2, 102, 105, 95, 103), (3, 105, 110, 80, 90)])
    got = policy.simulate_from_align(trade(), data, rule())
    assert got["new_exit_reason"] == "original_opposing_flip_exit"
    assert got["new_exit_fill_px"] == 105.0


def test_optional_arm_timestamp_preserves_nanoseconds_above_2pow53():
    exact = 1_735_775_485_000_000_001
    frame = policy.records_frame(
        [{"arm_available_ts": exact}, {"arm_available_ts": None}],
        ("arm_available_ts",),
    )
    assert str(frame.arm_available_ts.dtype) == "Int64"
    assert int(frame.loc[0, "arm_available_ts"]) == exact
    assert pd.isna(frame.loc[1, "arm_available_ts"])
