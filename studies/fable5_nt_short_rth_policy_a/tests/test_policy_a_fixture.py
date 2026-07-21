"""End-to-end micro-fixtures for Policy A short-RTH management in NT.

Deterministic tapes with no bearish regime flip (regime held long by rising 1m
closes), so alignment never fires and we isolate: entry-fill parity, pre-stop
placement/trigger, the 300s timeout, and short-side PnL sign. Alignment /
opposing-flip / post-stop paths are validated by the full-year reconciliation
against the 807-trade offline benchmark, not here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money, Price, Quantity

from studies.fable5_pre_flip_d10_reversal_entry.run_nt import create_instrument
from studies.fable5_nt_short_rth_policy_a.strategy import (
    PolicyAShortRTHConfig, PolicyAShortRTHStrategy,
)

NS = 1_000_000_000
T0 = pd.Timestamp("2025-06-02 14:00:00", tz="UTC").value  # RTH
BT_1S = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
BT_1M = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
ATR = 10.0
ENTRY_OFFSET_S = 130          # entry after two 1m closes
DURATION_S = 480


def bar(bt, o, h, l, c, ts_event):
    return Bar(bar_type=BarType.from_str(bt),
               open=Price(o, 2), high=Price(h, 2), low=Price(l, 2),
               close=Price(c, 2), volume=Quantity.from_int(100),
               ts_event=ts_event, ts_init=ts_event + NS)


def make_1s(price_at):
    bars = []
    for s in range(DURATION_S):
        ts = T0 + s * NS
        o, h, l, c = price_at(s)
        bars.append(bar(BT_1S, o, h, l, c, ts))
    return bars


def make_1m():
    # rising closes -> regime engine goes/stays long (+1), never bearish,
    # so the short never aligns and can only pre-stop or time out.
    bars = []
    for m in range(DURATION_S // 60):
        ts_event = T0 + m * 60 * NS
        base = 100.0 + m  # rising
        bars.append(bar(BT_1M, base, base + 0.5, base - 0.5, base + 0.4,
                        ts_event - NS))  # 1m ts_init = ts_event; close at +60s
    return bars


def run(tmp_path, price_at) -> list[dict]:
    sched = pd.DataFrame([{
        "regime_start_ns": T0, "signal_decision_ts": T0 + (ENTRY_OFFSET_S - 1) * NS,
        "target_fill_ts": T0 + ENTRY_OFFSET_S * NS, "offline_entry_open": 100.0,
        "entry_direction": -1, "atr_at_checkpoint": ATR,
        "recon_confirm_flip_ns": 0, "recon_scheduled_exit_ts": 0, "year": 2025}])
    sched_path = tmp_path / "sched.parquet"
    sched.to_parquet(sched_path, index=False)

    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id="SRTH-FIX", logging=LoggingConfig(log_level="ERROR")))
    engine.add_venue(venue=Venue("XCME"), oms_type=OmsType.NETTING,
                     account_type=AccountType.MARGIN, base_currency=USD,
                     starting_balances=[Money(1_000_000, USD)],
                     bar_execution=True, bar_adaptive_high_low_ordering=True)
    engine.add_instrument(create_instrument())
    engine.add_data(make_1s(price_at))
    engine.add_data(make_1m())
    strat = PolicyAShortRTHStrategy(config=PolicyAShortRTHConfig(
        year=2025, schedule_path=str(sched_path), timeout_s=300, cost_rt=10.0))
    engine.add_strategy(strat)
    engine.run()
    trades = list(strat.trades)
    engine.dispose()
    return trades


def test_timeout_exit(tmp_path):
    trades = run(tmp_path, lambda s: (100.0, 100.0, 100.0, 100.0))
    assert len(trades) == 1
    t = trades[0]
    assert t["entry_ts"] == T0 + ENTRY_OFFSET_S * NS       # entry ts parity
    assert t["entry_px"] == 100.0                          # fills at bar close
    assert t["pre_stop_px"] == 112.5                       # entry + 1.25*ATR
    assert not t["aligned"]
    assert t["exit_reason"] == "confirmation_timeout"
    # exit on the first 1s boundary strictly after entry+300s
    assert t["exit_ts"] > t["timeout_ts"]
    assert t["exit_ts"] - t["timeout_ts"] <= 2 * NS
    assert t["net_pnl"] == pytest.approx(-10.0)            # flat, only cost


def test_pre_alignment_stop(tmp_path):
    stop_at_s = ENTRY_OFFSET_S + 50

    def price_at(s):
        if s == stop_at_s:
            return (100.0, 113.0, 100.0, 100.0)   # high pierces 112.5 stop
        return (100.0, 100.0, 100.0, 100.0)
    trades = run(tmp_path, price_at)
    assert len(trades) == 1
    t = trades[0]
    assert t["exit_reason"] == "stop_before_flip"
    assert t["exit_px"] == pytest.approx(112.5)           # fills at trigger
    # short: gross = (112.5 - 100) * (-1) * 20 = -250 ; net = -260
    assert t["gross_pnl"] == pytest.approx(-250.0)
    assert t["net_pnl"] == pytest.approx(-260.0)
    assert t["exit_ts"] == T0 + stop_at_s * NS + NS       # stop fill ts_init
