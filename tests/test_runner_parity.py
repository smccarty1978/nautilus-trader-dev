import tempfile
from pathlib import Path

import pytest

from utils.runner.checkpoint import DailyStateCheckpointer
from utils.runner.fanning import ThresholdEvaluator, ResearchTradeState
from utils.runner.progress import CausalProgressTracker
from utils.runner.registry import CompletedBarRegistry
from utils.runner.reconciler import ParityReconciler


def test_completed_bar_registry():
    registry = CompletedBarRegistry()
    
    # Registering first bar should succeed
    assert registry.register_completed_bar("NQ-1S", 1000) is True
    # Registering duplicate bar should fail
    assert registry.register_completed_bar("NQ-1S", 1000) is False
    # Registering older bar should fail
    assert registry.register_completed_bar("NQ-1S", 900) is False
    # Registering newer bar should succeed
    assert registry.register_completed_bar("NQ-1S", 1001) is True

    # Closed checks
    assert registry.is_bar_closed("NQ-1S", 1000) is True
    assert registry.is_bar_closed("NQ-1S", 1002) is False


def test_progress_tracker(capsys):
    tracker = CausalProgressTracker(report_interval_sec=0.1)
    tracker.start()
    
    # Initial update shouldn't report immediately if no interval elapsed
    tracker.update("2025-01-01", bars_increment=100)
    captured = capsys.readouterr()
    assert "[PROGRESS]" not in captured.out

    # Update with force_report=True should print metrics
    tracker.update("2025-01-01", bars_increment=100, force_report=True)
    captured = capsys.readouterr()
    assert "[PROGRESS] Day: 2025-01-01" in captured.out
    assert "Bars: 200" in captured.out


def test_checkpointer_and_manifest():
    with tempfile.TemporaryDirectory() as tmpdir:
        checkpoint_dir = Path(tmpdir)
        checkpointer = DailyStateCheckpointer(checkpoint_dir)
        
        # Manifest writing
        config_dict = {"param_a": 42, "param_b": "value"}
        checkpointer.write_manifest("2025-03-15", config_dict, {})
        
        # Manifest verification
        date = checkpointer.verify_manifest(config_dict, {})
        assert date == "2025-03-15"

        # Verification should fail with mismatched config
        assert checkpointer.verify_manifest({"param_a": 99}, {}) is None

        # Checkpoint save/load
        test_state = {"evaluators_state": {"R5": "some_state"}}
        checkpointer.save_checkpoint("2025-03-15", test_state)
        
        loaded = checkpointer.load_checkpoint("2025-03-15")
        assert loaded == test_state


def test_fanning_and_exit_mechanics():
    # Evaluate a policy configured with R5: threshold=0.62, sl=1.5 atr, pt=2.0 atr
    evalr = ThresholdEvaluator("R5", threshold=0.62, sl_atr_mult=1.5, pt_atr_mult=2.0)
    
    # 1. Candidate formed on 1m bar: price=15000, atr=20, score=0.65 (exceeds threshold)
    evalr.on_candidate(ts_event=1000, price=15000.0, atr=20.0, score=0.65, direction=-1)
    
    assert len(evalr.active_trades) == 1
    trade = evalr.active_trades[0]
    assert trade.is_open is True
    # For direction = -1 (Short):
    # SL = Entry + 1.5 * ATR = 15000 + 30 = 15030
    # PT = Entry - 2.0 * ATR = 15000 - 40 = 14960
    assert trade.sl_px == 15030.0
    assert trade.pt_px == 14960.0

    # 2. Check 1s bar update: price ranges 14980 to 15010 (no stop or target breached)
    evalr.on_bar_1s(ts_event=2000, open_px=15000.0, high=15010.0, low=14980.0, close=15000.0)
    assert trade.is_open is True
    assert trade.pending_exit is False

    # 3. Check 1s bar update: high hits 15040 (SL breach at 15030)
    # The exit must be triggered (pending_exit = True), but not yet filled! (H4 rule: next-bar open fill)
    evalr.on_bar_1s(ts_event=3000, open_px=15020.0, high=15040.0, low=15010.0, close=15030.0)
    assert trade.is_open is True
    assert trade.pending_exit is True
    assert trade.exit_reason == "SL"
    assert trade.exit_px is None  # Not filled yet

    # 4. Next bar close update: filled at open price of the next bar (H4 rule!)
    evalr.on_bar_1s(ts_event=4000, open_px=15035.0, high=15040.0, low=15020.0, close=15030.0)
    assert trade.is_open is False
    assert trade.pending_exit is False
    assert trade.exit_px == 15035.0  # Filled at next bar's open price!
    assert trade.exit_time == 4000
    # PnL: (exit_px - entry_px) * direction * qty = (15035 - 15000) * -1 * 1.0 = -35.0
    assert trade.pnl == -35.0


def test_parity_reconciler():
    rec = ParityReconciler(float_tolerance=1e-4)
    
    # Mappings that match
    assert rec.compare_dicts(
        step_id=1,
        actual={"val_a": 10.0001, "val_b": "test"},
        expected={"val_a": 10.00012, "val_b": "test"}
    ) is True
    assert len(rec.discrepancies) == 0

    # Mappings with mismatch
    assert rec.compare_dicts(
        step_id=2,
        actual={"val_a": 10.0001, "val_b": "test"},
        expected={"val_a": 10.5, "val_b": "different"}
    ) is False
    assert len(rec.discrepancies) == 1
    assert "val_a" in rec.discrepancies[0]["mismatch"]
    assert "val_b" in rec.discrepancies[0]["mismatch"]
