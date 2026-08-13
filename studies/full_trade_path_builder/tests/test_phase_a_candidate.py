from studies.full_trade_path_builder.implementation.phase_a_candidate import (
    CausalBullishCandidateTracker,
)
from studies.full_trade_path_builder.implementation.phase_a_core import NS


def _tracker():
    rows, missing = [], []
    tr = CausalBullishCandidateTracker(rows.append, missing.append, lambda _: True)
    tr.on_regime_flip(0, 1, 100.0, 1.0)
    return tr, rows, missing


def test_dispatch_uses_ts_init_and_includes_completed_bar():
    tr, rows, missing = _tracker()
    for sec in range(1, 6):
        tr.on_completed_1s((sec - 1) * NS, sec * NS, 100 + sec, 100, 100 + sec)
    assert len(rows) == 1
    assert rows[0]["checkpoint_decision_ns"] == 5 * NS
    assert rows[0]["dispatch_bar_ts_event"] == 4 * NS
    assert rows[0]["running_mfe_atr"] == 5.0
    assert not missing


def test_missing_exact_callback_is_not_caught_up():
    tr, rows, missing = _tracker()
    for sec in (1, 2, 3, 4, 6):
        tr.on_completed_1s((sec - 1) * NS, sec * NS, 101, 99, 100)
    assert rows == []
    assert [x["checkpoint_decision_ns"] for x in missing] == [5 * NS]


def test_literal_timeout_key_set():
    tr, rows, missing = _tracker()
    for sec in range(1, 1801):
        tr.on_completed_1s((sec - 1) * NS, sec * NS, 102, 100, 101)
    expected = [sec * NS for sec in range(5, 1800, 5)]
    assert [x["checkpoint_decision_ns"] for x in rows] == expected
    assert rows[0]["checkpoint_index"] == 0
    assert rows[-1]["checkpoint_index"] == 358
    assert not missing
