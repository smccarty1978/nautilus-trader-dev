from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

MODULE_PATH = Path(__file__).resolve().parents[1] / "run_replay.py"
SPEC = importlib.util.spec_from_file_location("price_response_replay", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)

BASE = 1_800_000_000_000_000_000
NS = 1_000_000_000


def bars(count: int = 500) -> pd.DataFrame:
    index = pd.to_datetime(BASE + np.arange(count, dtype=np.int64) * NS, utc=True)
    return pd.DataFrame({"open": 100.0, "high": 100.5, "low": 99.5,
                         "close": 100.0, "volume": 1.0}, index=index)


def trade(confirm_s: int = 100, scheduled_s: int = 450, direction: int = 1) -> pd.Series:
    return pd.Series({"entry_fill_ts": BASE, "entry_fill_open": 100.0,
        "entry_direction": direction, "atr_at_checkpoint": 10.0,
        "confirm_flip_ns": BASE + confirm_s * NS,
        "scheduled_exit_decision_ts": BASE + scheduled_s * NS})


def test_confirmation_uses_last_fully_completed_bar_and_strictly_later_open():
    raw = bars()
    raw.iloc[9, raw.columns.get_loc("close")] = 101.0
    raw.iloc[10, raw.columns.get_loc("close")] = 90.0
    raw.iloc[11, raw.columns.get_loc("open")] = 102.0
    gate = mod.gate_candidate(trade(), raw, 10)
    assert gate["approved"]
    assert gate["confirmation_mark_ts"] == BASE + 9 * NS
    assert gate["virtual_directional_pnl_points"] == 1.0
    assert gate["delayed_entry_fill_ts"] == BASE + 11 * NS
    assert gate["delayed_entry_fill_open"] == 102.0


def test_adverse_completed_response_is_skipped():
    raw = bars()
    raw.iloc[9, raw.columns.get_loc("close")] = 99.75
    gate = mod.gate_candidate(trade(), raw, 10)
    assert not gate["approved"]
    assert gate["skip_reason"] == "adverse_virtual_response"


def test_zero_virtual_response_is_approved():
    gate = mod.gate_candidate(trade(), bars(), 10)
    assert gate["approved"]
    assert gate["virtual_directional_pnl_points"] == 0.0


def test_regime_end_at_confirmation_rejects_before_price_gate():
    gate = mod.gate_candidate(trade(confirm_s=10), bars(), 10)
    assert not gate["approved"]
    assert gate["skip_reason"] == "regime_ended_by_confirmation"


def test_flip_inside_gap_before_delayed_open_rejects():
    raw = bars().drop(bars().index[11:15])
    gate = mod.gate_candidate(trade(confirm_s=13), raw, 10)
    assert not gate["approved"]
    assert gate["skip_reason"] == "aligning_flip_before_delayed_entry"


def test_delayed_entry_bar_has_active_fill_anchored_stop():
    raw = bars()
    raw.iloc[11, raw.columns.get_loc("open")] = 102.0
    raw.iloc[11, raw.columns.get_loc("low")] = 88.0
    gate = mod.gate_candidate(trade(), raw, 10)
    result = mod.simulate_delayed(trade(), raw, gate)
    assert result["stop_submission_ts"] == BASE + 11 * NS
    assert result["stop_active_entry_bar"]
    assert result["new_exit_fill_ts"] == BASE + 11 * NS
    assert result["new_exit_fill_px"] == 89.5
    assert result["new_exit_reason"] == "preflip_policy_stop"


def test_timeout_restarts_at_delayed_fill_and_fills_strictly_after():
    raw = bars()
    raw.iloc[312, raw.columns.get_loc("open")] = 103.0
    gate = mod.gate_candidate(trade(confirm_s=400), raw, 10)
    result = mod.simulate_delayed(trade(confirm_s=400), raw, gate)
    assert gate["delayed_entry_fill_ts"] == BASE + 11 * NS
    assert result["timeout_ts"] == BASE + 311 * NS
    assert result["new_exit_fill_ts"] == BASE + 312 * NS
    assert result["new_exit_fill_px"] == 103.0
    assert result["new_exit_reason"] == "confirmation_timeout_exit"


def test_align_exactly_at_delayed_timeout_confirms_and_relaxes_stop():
    raw = bars()
    raw.iloc[311, raw.columns.get_loc("low")] = 86.0
    gate = mod.gate_candidate(trade(confirm_s=311), raw, 10)
    result = mod.simulate_delayed(trade(confirm_s=311), raw, gate)
    assert result["new_exit_reason"] == "original_opposing_flip_exit"


def test_short_virtual_response_sign_is_directional():
    raw = bars()
    raw.iloc[9, raw.columns.get_loc("close")] = 99.0
    gate = mod.gate_candidate(trade(direction=-1), raw, 10)
    assert gate["approved"]
    assert gate["virtual_directional_pnl_points"] == 1.0
