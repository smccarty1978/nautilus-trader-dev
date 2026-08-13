from studies.full_trade_path_builder.implementation.phase_d_core import (
    build_trade_plans,
)


def test_fallback_is_strictly_after_confirm_and_opposite_direction():
    selections = [
        {"trade_id": "x", "trade_direction": 1, "confirm_flip_ns": 100}
    ]
    flips = [
        {"confirm_flip_ns": 100, "new_direction": -1},
        {"confirm_flip_ns": 200, "new_direction": -1},
    ]
    plan = build_trade_plans(selections, flips, 999)[0]
    assert plan["fallback_exit_flip_ns"] == 200
    assert plan["fallback_exit_flip_direction"] == -1
