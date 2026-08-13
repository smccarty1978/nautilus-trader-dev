from studies.full_trade_path_builder.analysis.analyze_top2_5_stop_and_regime_exit import (
    _independent_outcome,
)


def _summary(**overrides):
    base = {
        "confirm_flip_ns": 3,
        "fallback_exit_flip_ns": 6,
        "path_is_complete": True,
        "fallback_exit_mark_return_points": 1.0,
    }
    return base | overrides


def _rows(adverse):
    return [
        {
            "timestamp_open_ns": i,
            "timestamp_close_ns": i + 1,
            "adverse_intrabar_extreme_atr": value,
        }
        for i, value in enumerate(adverse)
    ]


def test_stop_before_confirmation_uses_next_bar_fill():
    assert _independent_outcome(_summary(), _rows([-1.3, -0.1, -0.2]), 1.25) == (
        "STOPPED BEFORE CONFIRMATION"
    )


def test_stop_after_confirmation():
    assert _independent_outcome(_summary(), _rows([-0.1, -0.2, -0.3, -1.3, -0.1]), 1.25) == (
        "STOPPED AFTER CONFIRMATION"
    )


def test_same_bar_confirmation_is_ambiguous():
    assert _independent_outcome(_summary(), _rows([-0.1, -0.2, -1.3, -0.1]), 1.25) == (
        "AMBIGUOUS EVENT ORDER"
    )


def test_final_bar_touch_is_censored():
    assert _independent_outcome(_summary(), _rows([-0.1, -0.2, -0.3, -1.3]), 1.25) == (
        "CENSORED / UNRESOLVED"
    )


def test_flip_profit_loss_and_flat():
    rows = _rows([-0.1] * 6)
    assert _independent_outcome(_summary(), rows, 1.25) == "REGIME-FLIP EXIT FOR PROFIT"
    assert _independent_outcome(
        _summary(fallback_exit_mark_return_points=-1.0), rows, 1.25
    ) == "REGIME-FLIP EXIT FOR LOSS"
    assert _independent_outcome(
        _summary(fallback_exit_mark_return_points=0.1), rows, 1.25
    ) == "REGIME-FLIP EXIT FLAT"
