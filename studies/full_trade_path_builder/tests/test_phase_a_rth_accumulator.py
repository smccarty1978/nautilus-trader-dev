from pathlib import Path

from studies.full_trade_path_builder.implementation.phase_a_adapter import (
    BullishFadeAdapter,
    load_ordered_features,
)
from studies.full_trade_path_builder.implementation.phase_a_core import NS

ROOT = Path(__file__).resolve().parents[3]


def test_exact_post_reset_rth_accumulation_and_end():
    adapter = BullishFadeAdapter(load_ordered_features(ROOT))
    engine = adapter.engine
    start = 1_000_000 * NS
    # Exact 08:30 checkpoint precedes this reset in the collector.
    assert engine.ohlcv._rth_active is False
    engine.reset_rth(start)
    for sec in range(5):
        te = start + sec * NS
        est = engine.update_1s(te, 100, 101, 99, 100, 10)
        engine.accumulate_regime_rth(te, 101, 99, 10, est["bar_est_delta"])
    at_083005 = engine.ohlcv.calculate(atr=10)
    assert at_083005["rth_available"] is True
    assert at_083005["rth_elapsed_seconds"] == 4
    assert at_083005["rth_vol_cum"] == 50
    # The final contained minute must accumulate before the 15:00 end.
    for sec in range(60):
        te = start + (6 * 60 * 60 + 29 * 60 + sec) * NS
        est = engine.update_1s(te, 100, 101, 99, 100, 2)
        engine.accumulate_regime_rth(te, 101, 99, 2, est["bar_est_delta"])
    before_end = engine.ohlcv.calculate(atr=10)
    assert before_end["rth_vol_cum"] == 170
    engine.end_rth()
    assert engine.ohlcv.calculate(atr=10)["rth_available"] is False
