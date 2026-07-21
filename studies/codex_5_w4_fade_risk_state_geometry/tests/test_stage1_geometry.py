import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

P = Path(__file__).resolve().parents[1] / "build_stage1_geometry.py"
spec = importlib.util.spec_from_file_location("riskgeo", P)
geo = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = geo
spec.loader.exec_module(geo)


@pytest.mark.parametrize("direction,floor,exit_fill", [(1, 100.0, 99.0), (-1, 100.0, 101.0)])
def test_adverse_floor_touch_is_direction_symmetric(direction, floor, exit_fill):
    highs = np.array([99.0]) if direction == 1 else np.array([99.0])
    lows = np.array([101.0]) if direction == -1 else np.array([101.0])
    assert geo.adverse_floor_touched(direction, floor, highs, lows, exit_fill)


def test_floor_touch_does_not_use_favorable_side():
    assert not geo.adverse_floor_touched(1, 100.0, np.array([110.0]), np.array([101.0]), 105.0)
    assert not geo.adverse_floor_touched(-1, 100.0, np.array([99.0]), np.array([90.0]), 95.0)


def test_gate_reads_2025_only_and_selects_smallest_preserving_candidate():
    pre = pd.DataFrame({"year": [2025] * 20 + [2026],
                        "outcome_group": ["opposite_flip_exit_winner"] * 21,
                        "pre_flip_mae_atr": [0.5] * 19 + [0.9] + [99.0]})
    post = pd.DataFrame({
        "year": [2025] * 20 + [2026],
        "outcome_group": (["opposite_flip_exit_loser"] * 10 +
                          ["opposite_flip_exit_winner"] * 10 + ["opposite_flip_exit_loser"]),
        "post_flip_giveback_to_exit_atr": [2.0] * 21,
        "post_flip_peak_mfe_atr": [1.1] * 21,
    })
    config = {"initial_geometry_p95_max_atr_2025": 1.25,
              "postflip_loser_median_giveback_min_2025": 1.0,
              "postflip_loser_reach_1atr_min_2025": 0.5,
              "postflip_winner_reach_1atr_min_2025": 0.9,
              "postflip_arm_atr": 1.0, "postflip_floor_atr": 0.25,
              "preflip_stop_candidates_atr": [0.75, 1.0, 1.25],
              "preflip_preservation_min_2025": 0.95}
    gate = geo.stage2_gate_2025(pre, post, config)
    assert gate["selected_preflip_stop_atr"] == 0.75
    assert gate["stage2_pass"]
    pre.loc[pre.year == 2026, "pre_flip_mae_atr"] = 0.0
    assert geo.stage2_gate_2025(pre, post, config) == gate


def test_hash_mutation_fails_closed():
    with pytest.raises(RuntimeError, match="hash mismatch"):
        geo.validate_hash_contract({"a": "1"}, {"a": "2"})
