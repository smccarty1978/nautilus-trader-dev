"""Phase 4 -- converts CLAUDE.md invariant 4 ("1s bars process before their
parent 1m bar") from an asserted prose convention into a tested proof.

The one existing fixture that constructs both bar types
(`fable5_nt_short_rth_policy_a/tests/test_policy_a_fixture.py::make_1m`)
gives its synthetic 1m bar `ts_init = ts_event` (minute-OPEN), which never
actually ties with the coincident 1s bar's `ts_init` (minute-close) --
confirmed by reading that file directly (`make_1m` docstring: "1m ts_init
= ts_event; close at +60s"). It therefore never exercises NT's tie-break
behavior when both bar types share an IDENTICAL `ts_init`, which is what
production catalog data actually does (Databento timestamps bars at OPEN;
`ts_init_delta` shifts `ts_init` to CLOSE for both 1s and 1m bars, so a
1m bar's `ts_init` exactly equals its last child 1s bar's `ts_init`).

This test builds exactly that coincident case and asserts, via a logging
strategy, that NT delivers the 1s bar's `on_bar` before the 1m bar's
`on_bar` when both share the same `ts_init`.

**CRITICAL correction (completion-gate audit, `audit/audit.md`):** the
first version of this test presented that result as a proven NT-native,
type-aware tie-break. It is NOT. `BacktestEngine.add_data(data,
sort=True)` re-sorts the entire accumulated stream by `ts_init` on every
call using a STABLE sort; at a coincident `ts_init`, the tie is broken
purely by which stream's elements were already in the pre-sort array
first -- i.e. by which `add_data()` call happened first in the calling
script, not by any bar-type-aware priority inside NT itself. Reproduced
directly: reversing the two `add_data()` calls (1m added before 1s)
flips the observed order at the coincident timestamp from `["1s",
"1m"]` to `["1m", "1s"]` -- see
`test_add_data_call_order_determines_the_tie_break` below, which makes
this a permanent, documented regression check rather than a one-off
adversarial finding that could be forgotten. The correct framing is:
**"1s before 1m" is a calling-convention requirement every NT study
loading both timeframes must follow (call `add_data(bars_1s)` before
`add_data(bars_1m)`) -- it is not automatically guaranteed by NT.** Use
`add_bars_causal_order()` below in any future NT study instead of raw
`engine.add_data()` calls, to make the convention structurally
impossible to get backwards.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

from studies.fable5_pre_flip_d10_reversal_entry.run_nt import create_instrument

NS = 1_000_000_000
T0 = pd.Timestamp("2025-06-02 14:00:00", tz="UTC").value  # RTH
BT_1S = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
BT_1M = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"


def bar(bt: str, o: float, h: float, l: float, c: float, ts_event: int, ts_init: int) -> Bar:
    return Bar(bar_type=BarType.from_str(bt),
               open=Price(o, 2), high=Price(h, 2), low=Price(l, 2),
               close=Price(c, 2), volume=Quantity.from_int(100),
               ts_event=ts_event, ts_init=ts_init)


def make_1s_minute(minute_start: int) -> list[Bar]:
    """60 completed 1s bars for [minute_start, minute_start+60s), each
    ts_init = ts_event + 1s (production convention: 1s needs no
    ts_init_delta shift beyond its own 1-second close)."""
    bars = []
    for s in range(60):
        ts_event = minute_start + s * NS
        bars.append(bar(BT_1S, 100.0, 100.5, 99.5, 100.0, ts_event, ts_event + NS))
    return bars


def make_coincident_1m(minute_start: int) -> Bar:
    """The 1m bar covering [minute_start, minute_start+60s) with
    `ts_init` shifted to CLOSE (production `ts_init_delta` convention,
    CLAUDE.md invariant 3) -- identical to the last child 1s bar's
    `ts_init` (minute_start + 60s), the genuine coincident case."""
    return bar(BT_1M, 100.0, 100.5, 99.5, 100.0, minute_start, minute_start + 60 * NS)


class OrderLogConfig(StrategyConfig, frozen=True):
    pass


class OrderLogStrategy(Strategy):
    """Subscribes to both bar types and logs arrival order; places no orders."""

    def __init__(self, config: OrderLogConfig) -> None:
        super().__init__(config=config)
        self.arrivals: list[tuple[int, str]] = []

    def on_start(self) -> None:
        self.subscribe_bars(BarType.from_str(BT_1S))
        self.subscribe_bars(BarType.from_str(BT_1M))

    def on_bar(self, bar: Bar) -> None:
        bt = str(bar.bar_type)
        kind = "1s" if "SECOND" in bt else "1m"
        self.arrivals.append((bar.ts_init, kind))


def add_bars_causal_order(engine: BacktestEngine, bars_1s: list[Bar], bars_1m: list[Bar]) -> None:
    """The ONLY safe way to load coincident 1s+1m data into a `BacktestEngine`
    for any NT study in this repo. `add_data()`'s tie-break at equal
    `ts_init` is determined purely by call order (see this module's
    docstring and `test_add_data_call_order_determines_the_tie_break`) --
    NOT an NT-native, type-aware guarantee. Always add the finer
    timeframe first."""
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)


_LOG_GUARD = None  # shared across successive BacktestEngine instances in this
# process -- matches the pattern already established in
# `nt_pure_flip_trigger_poc_and_mirrored_long_model/phase2/run_nt.py`'s
# `run_one(..., log_guard=None)`: re-initializing NT's Rust-backed logging
# per engine, across multiple engines in one process, is unreliable
# (observed hanging/crashing this test at exit 127 when the second of two
# sequential engines in one pytest session created its own fresh guard).


def _run_and_get_coincident_arrivals(minute_start: int, reverse_add_order: bool) -> list[tuple[int, str]]:
    global _LOG_GUARD
    bars_1s = make_1s_minute(minute_start)
    bar_1m = make_coincident_1m(minute_start)

    trader_id = "COINCIDENT-ORDER-TEST-REV" if reverse_add_order else "COINCIDENT-ORDER-TEST-FWD"
    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id=trader_id, logging=LoggingConfig(log_level="ERROR")))
    if _LOG_GUARD is None:
        _LOG_GUARD = engine.get_log_guard()
    engine.add_venue(venue=Venue("XCME"), oms_type=OmsType.NETTING,
                     account_type=AccountType.MARGIN, base_currency=USD,
                     starting_balances=[Money(1_000_000, USD)],
                     bar_execution=True, bar_adaptive_high_low_ordering=True)
    engine.add_instrument(create_instrument())
    if reverse_add_order:
        engine.add_data([bar_1m])
        engine.add_data(bars_1s)
    else:
        add_bars_causal_order(engine, bars_1s, [bar_1m])
    strat = OrderLogStrategy(config=OrderLogConfig())
    engine.add_strategy(strat)
    engine.run()
    arrivals = list(strat.arrivals)
    engine.dispose()

    coincident_ts = minute_start + 60 * NS
    return [a for a in arrivals if a[0] == coincident_ts]


def test_1s_bar_processes_before_coincident_1m_bar_when_added_in_causal_order():
    """Following the required calling convention (`add_bars_causal_order`:
    1s added before 1m) produces the correct, causal delivery order."""
    coincident_arrivals = _run_and_get_coincident_arrivals(T0, reverse_add_order=False)
    assert len(coincident_arrivals) == 2, (
        f"expected exactly one 1s and one 1m bar at the coincident ts_init, "
        f"got {coincident_arrivals}")
    kinds_in_order = [k for _, k in coincident_arrivals]
    assert kinds_in_order == ["1s", "1m"], (
        f"CLAUDE.md invariant 4 violated under the required calling "
        f"convention: expected 1s bar before the coincident 1m bar, got "
        f"arrival order {kinds_in_order}")


def test_add_data_call_order_determines_the_tie_break_not_nt_native():
    """CRITICAL finding (audit/audit.md), converted into a permanent
    regression check: reversing the add_data() call order (1m before 1s)
    flips the coincident-timestamp arrival order to ["1m", "1s"]. This
    proves the ordering is a calling-convention artifact of `add_data`'s
    stable re-sort, NOT a genuine NT-native, bar-type-aware tie-break --
    so every future NT study MUST use `add_bars_causal_order()` (or
    replicate its call order manually) rather than assume NT enforces
    this automatically."""
    reversed_arrivals = _run_and_get_coincident_arrivals(T0, reverse_add_order=True)
    kinds_in_order = [k for _, k in reversed_arrivals]
    assert kinds_in_order == ["1m", "1s"], (
        "expected reversing add_data() call order to flip the coincident "
        f"arrival order to ['1m', '1s'] (proving call-order-dependence), "
        f"got {kinds_in_order} -- if this now reads ['1s', '1m'], NT's "
        f"tie-break behavior has changed and the calling-convention "
        f"requirement documented in this module may no longer apply; "
        f"re-investigate before relying on either ordering.")
