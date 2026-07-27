import polars as pl

from studies.full_trade_path_builder.analysis.analyze_post_confirmation_mfe_and_model_exits import (
    apply_event,
    price_event,
)


def test_price_floor_uses_prior_completed_bar_mfe():
    paths = pl.DataFrame(
        {
            "trade_id": ["x", "x", "x"],
            "timestamp_close_ns": [1, 2, 3],
            "confirm_flip_ns": [1, 1, 1],
            "prior_mfe_atr": [0.0, 0.5, 1.0],
            "adverse_intrabar_extreme_atr": [-0.1, 0.1, 0.2],
            "candidate_fill_ns": [1, 2, 3],
            "candidate_fill_price": [100.0, 100.0, 100.0],
            "running_mfe_atr": [0.5, 1.0, 1.0],
            "running_mae_atr": [-0.1, -0.1, -0.1],
        }
    )
    event = price_event(paths, "fixed_floor", 1.0, 0.25)
    assert event["candidate_touch_ns"].to_list() == [3]


def test_same_bar_activation_cannot_trigger_giveback():
    paths = pl.DataFrame(
        {
            "trade_id": ["x", "x"],
            "timestamp_close_ns": [1, 2],
            "confirm_flip_ns": [1, 1],
            "prior_mfe_atr": [0.0, 0.5],
            "adverse_intrabar_extreme_atr": [-0.1, 0.0],
            "candidate_fill_ns": [1, 2],
            "candidate_fill_price": [100.0, 100.0],
            "running_mfe_atr": [0.5, 1.5],
            "running_mae_atr": [-0.1, -0.1],
        }
    )
    assert price_event(paths, "giveback", 1.0, 0.5).is_empty()


def test_combined_candidate_collision_is_ambiguous():
    base = pl.DataFrame(
        {
            "trade_id": ["x"], "initial_stop_atr": [1.0], "model_id": ["m"],
            "trade_direction_name": ["LONG"], "year": [2025], "entry_timestamp": [0],
            "confirmation_timestamp": [1], "final_event_timestamp": [10],
            "stop_touch_ns": [None], "opposing_flip_exit_timestamp": [10],
            "baseline_outcome": ["REGIME-FLIP EXIT FOR PROFIT"],
            "baseline_return_atr": [1.0], "baseline_mfe_atr": [2.0],
            "entry_price": [100.0], "trade_direction": [1], "entry_atr": [10.0],
        }
    )
    event = pl.DataFrame(
        {
            "trade_id": ["x"], "candidate_touch_ns": [5], "candidate_fill_ns": [6],
            "candidate_fill_price": [101.0], "candidate_mfe_atr": [1.0],
            "candidate_mae_atr": [-0.2], "candidate_floor_atr": [0.25],
            "candidate_collision": [True],
        }
    )
    out = apply_event(base, event, "combined", "p", "PRICE MANAGEMENT EXIT")
    assert out["terminal_outcome"].item() == "AMBIGUOUS EVENT ORDER"
    assert out["realized_return_atr"].item() is None


def test_absent_baseline_stop_does_not_suppress_candidate_exit():
    base = pl.DataFrame(
        {
            "trade_id": ["x"], "initial_stop_atr": [1.0], "model_id": ["m"],
            "trade_direction_name": ["LONG"], "year": [2025], "entry_timestamp": [0],
            "confirmation_timestamp": [1], "final_event_timestamp": [10],
            "stop_touch_ns": [None], "opposing_flip_exit_timestamp": [10],
            "baseline_outcome": ["REGIME-FLIP EXIT FOR PROFIT"],
            "baseline_return_atr": [1.0], "baseline_mfe_atr": [2.0],
            "entry_price": [100.0], "trade_direction": [1], "entry_atr": [10.0],
        }
    )
    event = pl.DataFrame(
        {
            "trade_id": ["x"], "candidate_touch_ns": [5], "candidate_fill_ns": [6],
            "candidate_fill_price": [101.0], "candidate_mfe_atr": [1.0],
            "candidate_mae_atr": [-0.2], "candidate_floor_atr": [0.25],
        }
    )
    out = apply_event(base, event, "price", "p", "PRICE MANAGEMENT EXIT")
    assert out["terminal_outcome"].item() == "PRICE MANAGEMENT EXIT"
    assert out["candidate_exit_won"].item()
