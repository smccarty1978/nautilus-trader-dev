from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

PATH = Path(__file__).resolve().parents[1] / "build_attribution.py"
SPEC = importlib.util.spec_from_file_location("residual", PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)

BASE, NS = 1_800_000_000_000_000_000, 1_000_000_000


def bars(count: int = 302) -> pd.DataFrame:
    index = pd.to_datetime(BASE + np.arange(count, dtype=np.int64) * NS, utc=True)
    return pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0,
                         "close": 100.0, "volume": 1.0}, index=index)


def policy_row(exit_s: int = 301, reason: str = "confirmation_timeout_exit") -> pd.Series:
    return pd.Series({"entry_fill_ts": BASE, "new_exit_fill_ts": BASE + exit_s * NS,
                      "new_exit_reason": reason})


def trade() -> pd.Series:
    return pd.Series({"entry_direction": 1, "entry_fill_open": 100.0, "atr_at_checkpoint": 10.0})


def test_align_time_bucket_boundaries_and_no_flip():
    assert mod.align_time_bucket(True, BASE + 60 * NS, BASE + 100 * NS, 60) == "0-60s"
    assert mod.align_time_bucket(True, BASE + 120 * NS, BASE + 130 * NS, 120) == "60-120s"
    assert mod.align_time_bucket(True, BASE + 300 * NS, BASE + 301 * NS, 300) == "120-300s"
    assert mod.align_time_bucket(False, BASE + 305 * NS, BASE + 310 * NS, 305) == ">300s"
    assert mod.align_time_bucket(False, BASE + 310 * NS, BASE + 305 * NS, 310) == "no_flip_before_exit"


def test_regime_w4_mfe_and_pnl_bucket_boundaries():
    assert mod.regime_age_bucket(899) == "<15m"
    assert mod.regime_age_bucket(900) == "15-30m"
    assert mod.w4_bucket(0.70) == "0.70-0.75"
    assert mod.w4_bucket(0.80) == ">=0.80"
    assert mod.mfe_bucket(0.75, True) == "0.75-1.00"
    assert mod.mfe_bucket(99, False) == "not_alive_at_timeout"
    assert mod.pnl_bucket(-0.50, True) == "-0.50-0.00"
    assert mod.pnl_bucket(0.00, True) == "0.00-0.50"


def test_entry_regime_age_is_checkpoint_age_plus_fill_delay():
    checkpoint_age_s = 899.0
    decision_ts = BASE
    entry_fill_ts = BASE + 2 * NS
    entry_age_s = checkpoint_age_s + (entry_fill_ts - decision_ts) / NS
    assert entry_age_s == 901.0
    assert mod.regime_age_bucket(checkpoint_age_s) == "<15m"
    assert mod.regime_age_bucket(entry_age_s) == "15-30m"


def test_timeout_state_uses_only_bars_strictly_before_timeout():
    raw = bars()
    raw.iloc[299, raw.columns.get_loc("high")] = 107.0
    raw.iloc[299, raw.columns.get_loc("close")] = 105.0
    raw.iloc[300, raw.columns.get_loc("high")] = 120.0
    raw.iloc[300, raw.columns.get_loc("close")] = 115.0
    state = mod.timeout_state(policy_row(), trade(), raw)
    assert state["alive_at_timeout"]
    assert state["mfe_at_timeout_atr"] == 0.7
    assert state["pnl_at_timeout_atr"] == 0.5
    assert state["timeout_mark_ts"] == BASE + 299 * NS
    assert state["timeout_mark_staleness_s"] == 0.0


def test_stop_on_timeout_bar_is_alive_but_open_exit_is_not():
    raw = bars()
    stop = mod.timeout_state(policy_row(300, "preflip_policy_stop"), trade(), raw)
    market = mod.timeout_state(policy_row(300, "original_opposing_flip_exit"), trade(), raw)
    assert stop["alive_at_timeout"]
    assert not market["alive_at_timeout"]


def test_timeout_mark_staleness_documents_raw_gap():
    raw = bars().drop(bars().index[295:300])
    state = mod.timeout_state(policy_row(), trade(), raw)
    assert state["timeout_mark_ts"] == BASE + 294 * NS
    assert state["timeout_mark_staleness_s"] == 5.0


def test_residual_loss_modes_are_mutually_exclusive():
    base = {"new_net_pnl_usd": -10.0, "reached_aligning_flip": False,
            "new_exit_reason": "preflip_policy_stop"}
    assert mod.residual_loss_mode(pd.Series(base)) == "stopped_before_alignment"
    base["new_exit_reason"] = "confirmation_timeout_exit"
    assert mod.residual_loss_mode(pd.Series(base)) == "timed_out_before_alignment"
    base.update(reached_aligning_flip=True, new_exit_reason="original_stop_after_aligned_flip")
    assert mod.residual_loss_mode(pd.Series(base)) == "reached_alignment_then_stopped"
    base["new_exit_reason"] = "original_opposing_flip_exit"
    assert mod.residual_loss_mode(pd.Series(base)) == "reached_alignment_then_planned_exit_loss"
    base["new_net_pnl_usd"] = 0.0
    assert mod.residual_loss_mode(pd.Series(base)) == "policy_non_loss"


def test_bucket_summary_metrics_and_drawdown_are_exact():
    frame = pd.DataFrame({"entry_fill_ts": [1, 2, 3], "year": [2025] * 3,
        "trade_direction": ["long_fade"] * 3, "session": ["ETH"] * 3,
        "year_direction_session": ["2025|long_fade|ETH"] * 3,
        "original_outcome_group": ["x"] * 3, "new_exit_reason": ["r"] * 3,
        "time_to_align_bucket": ["0-60s"] * 3, "regime_age_bucket": ["<15m"] * 3,
        "w4_score_bucket": ["<0.70"] * 3, "mfe_at_timeout_bucket": ["<0.25"] * 3,
        "pnl_at_timeout_bucket": ["0.00-0.50"] * 3, "residual_loss_mode": ["policy_non_loss"] * 3,
        "late_winner_timeout_bucket": ["other"] * 3,
        "new_net_pnl_usd": [10.0, -4.0, -9.0], "original_net_pnl_usd": [8.0, -5.0, -7.0],
        "net_pnl_change_usd": [2.0, 1.0, -2.0], "positive_pnl_capture_change_usd": [2.0, 0.0, 0.0]})
    row = mod.summarize(frame).query("dimension == 'direction'").iloc[0]
    assert row.total_net_pnl_usd == -3.0
    assert row.profit_factor == 10 / 13
    assert row.bucket_max_trade_sequence_drawdown_usd == 13.0
