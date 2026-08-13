from studies.full_trade_path_builder.implementation.phase_c_strategy import trade_id_for
from studies.full_trade_path_builder.implementation.run_phase_c_months import (
    selected_state_hash,
)


def test_trade_id_is_deterministic_and_direction_sensitive():
    short = trade_id_for("NQ.XCME", "bull", 100, 200, -1)
    assert short == trade_id_for("NQ.XCME", "bull", 100, 200, -1)
    assert short != trade_id_for("NQ.XCME", "bull", 100, 200, 1)


def test_selected_state_hash_is_order_independent():
    assert selected_state_hash({"b", "a"}) == selected_state_hash({"a", "b"})
