from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

MODULE_PATH = Path(__file__).resolve().parents[1] / "run_study.py"
SPEC = importlib.util.spec_from_file_location("confirmation_clock", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)

BASE = 1_800_000_000_000_000_000
NS = 1_000_000_000
POLICY_A = {"policy_id": "A", "preflip_stop_atr": 1.25, "mfe_qualification_atr": None}
POLICY_B = {"policy_id": "B", "preflip_stop_atr": 1.25, "mfe_qualification_atr": 0.75,
            "protected_profit_atr": 0.75}
POLICY_C = {"policy_id": "C", "preflip_stop_atr": 1.0, "mfe_qualification_atr": None}


def bars(count: int = 401) -> pd.DataFrame:
    index = pd.to_datetime(BASE + np.arange(count, dtype=np.int64) * NS, utc=True)
    return pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0,
                         "close": 100.0, "volume": 1.0}, index=index)


def trade(confirm_s: int = 350, exit_s: int = 400, exit_px: float = 100.0) -> pd.Series:
    return pd.Series({"entry_fill_ts": BASE, "entry_fill_open": 100.0,
        "entry_direction": 1, "atr_at_checkpoint": 10.0,
        "confirm_flip_ns": BASE + confirm_s * NS,
        "scheduled_exit_decision_ts": BASE + exit_s * NS,
        "exit_fill_ts": BASE + exit_s * NS, "exit_fill_px": exit_px,
        "exit_reason": "opposite_flip_against_countertrade"})


def test_baseline_uses_original_stop_and_scheduled_boundary_open():
    raw = bars()
    result = mod.simulate(trade(), raw, None)
    assert result["new_exit_fill_ts"] == BASE + 400 * NS
    assert result["new_exit_reason"] == "original_opposing_flip_exit"
    assert result["new_net_pnl_usd"] == -10.0


def test_scheduled_decision_gap_fills_at_stored_next_available_open():
    raw = bars().drop(bars().index[400])
    extra_index = pd.to_datetime([BASE + 405 * NS], utc=True)
    extra = pd.DataFrame({"open": [103.0], "high": [104.0], "low": [102.0],
                          "close": [103.0], "volume": [1.0]}, index=extra_index)
    raw = pd.concat([raw, extra]).sort_index()
    t = trade(exit_s=400, exit_px=103.0)
    t["exit_fill_ts"] = BASE + 405 * NS
    result = mod.simulate(t, raw, None)
    assert result["new_exit_fill_ts"] == BASE + 405 * NS
    assert result["new_exit_fill_px"] == 103.0


def test_policy_a_timeout_fills_strictly_after_five_minutes():
    raw = bars()
    raw.iloc[301, raw.columns.get_loc("open")] = 102.0
    result = mod.simulate(trade(), raw, POLICY_A)
    assert result["new_exit_fill_ts"] == BASE + 301 * NS
    assert result["new_exit_fill_px"] == 102.0
    assert result["new_exit_reason"] == "confirmation_timeout_exit"


def test_policy_a_stop_remains_active_on_timeout_bar_before_market_fill():
    raw = bars()
    raw.iloc[300, raw.columns.get_loc("low")] = 87.0
    result = mod.simulate(trade(), raw, POLICY_A)
    assert result["new_exit_fill_ts"] == BASE + 300 * NS
    assert result["new_exit_fill_px"] == 87.5
    assert result["new_exit_reason"] == "preflip_policy_stop"


def test_flip_exactly_at_timeout_counts_as_confirmed_and_relaxes_stop():
    raw = bars()
    raw.iloc[300, raw.columns.get_loc("low")] = 86.0  # through 1.25, not through 1.50
    result = mod.simulate(trade(confirm_s=300), raw, POLICY_A)
    assert result["new_exit_fill_ts"] == BASE + 400 * NS
    assert result["new_exit_reason"] == "original_opposing_flip_exit"


def test_policy_b_does_not_take_profit_when_threshold_first_reached():
    raw = bars()
    raw.iloc[100, raw.columns.get_loc("high")] = 108.0
    result = mod.simulate(trade(), raw, POLICY_B)
    assert result["mfe_qualified_continuation"]
    assert result["new_exit_fill_ts"] > BASE + 100 * NS


def test_policy_b_protection_is_active_on_timeout_bar():
    raw = bars()
    raw.iloc[100, raw.columns.get_loc("high")] = 108.0
    raw.iloc[300, raw.columns.get_loc("low")] = 107.0
    result = mod.simulate(trade(), raw, POLICY_B)
    assert result["new_exit_fill_ts"] == BASE + 300 * NS
    assert result["new_exit_fill_px"] == 100.0  # timeout-bar open already through 107.5 floor
    assert result["new_exit_reason"] == "mfe_protected_stop"


def test_policy_b_protected_stop_persists_after_late_aligning_flip():
    raw = bars()
    raw.iloc[100, raw.columns.get_loc("high")] = 108.0
    raw.loc[raw.index[300:330], "open"] = 108.0
    raw.loc[raw.index[300:330], "low"] = 107.8
    raw.loc[raw.index[300:330], "high"] = 108.2
    raw.loc[raw.index[300:330], "close"] = 108.0
    raw.iloc[330, raw.columns.get_loc("open")] = 108.0
    raw.iloc[330, raw.columns.get_loc("low")] = 107.0
    result = mod.simulate(trade(confirm_s=320), raw, POLICY_B)
    assert result["new_exit_fill_ts"] == BASE + 330 * NS
    assert result["new_exit_fill_px"] == 107.5
    assert result["new_exit_reason"] == "mfe_protected_stop"


def test_stop_is_loss_first_over_same_bar_qualification_excursion():
    raw = bars()
    raw.iloc[100, raw.columns.get_loc("high")] = 108.0
    raw.iloc[100, raw.columns.get_loc("low")] = 87.0
    result = mod.simulate(trade(), raw, POLICY_B)
    assert result["new_exit_fill_ts"] == BASE + 100 * NS
    assert not result["mfe_qualified_continuation"]
    assert result["mfe_at_timeout_atr"] < 0.75


def test_optional_policy_c_is_the_single_one_atr_stop_variant():
    raw = bars()
    raw.iloc[50, raw.columns.get_loc("low")] = 89.0
    a = mod.simulate(trade(), raw, POLICY_A)
    c = mod.simulate(trade(), raw, POLICY_C)
    assert a["new_exit_reason"] == "confirmation_timeout_exit"
    assert c["new_exit_reason"] == "preflip_policy_stop"
    assert c["new_exit_fill_px"] == 90.0


def test_path_diagnostic_excludes_timeout_bar_from_mfe_qualification():
    raw = bars()
    raw.iloc[299, raw.columns.get_loc("high")] = 107.0
    raw.iloc[300, raw.columns.get_loc("high")] = 110.0
    t = trade()
    t["year"] = 2025
    t["session"] = "ETH"
    t["exit_reason"] = "opposite_flip_against_countertrade"
    t["net_pnl_usd"] = -10.0
    diagnostic = mod.path_diagnostic(t, raw, "2025_00000")
    assert diagnostic["mfe_through_5m_atr"] == 0.7
    assert not diagnostic["mfe_0p75_qualified_at_5m"]


def test_stop_on_timeout_label_is_alive_at_decision_but_open_exit_is_not():
    raw = bars()
    t = trade()
    t["year"] = 2025
    t["session"] = "ETH"
    t["net_pnl_usd"] = -10.0
    t["exit_fill_ts"] = BASE + 300 * NS
    t["exit_reason"] = "stop_before_aligned_flip"
    assert mod.path_diagnostic(t, raw, "stop")["baseline_alive_at_5m"]
    t["exit_reason"] = "opposite_flip_against_countertrade"
    assert not mod.path_diagnostic(t, raw, "open_exit")["baseline_alive_at_5m"]
