"""Micro-fixture: document NT bar-execution fill semantics used by this study.

OBSERVED semantics (asserted below so any engine change fails loudly):
1. A FOK market order submitted while processing bar N (at its ts_init
   boundary) fills IMMEDIATELY at that boundary against the just-completed
   bar N's CLOSE — the event loop's actual executable price at decision
   time. It does NOT wait for bar N+1's open.
2. A GTC stop-market submitted in the entry-fill callback is live from the
   next processed bar onward and fills at the TRIGGER price when touched.
3. OPTIMISTIC CASE: when a bar gaps through the trigger (trigger outside the
   bar's traded range), NT still fills at the trigger price. The study's
   analysis stage conservatively reprices such fills to the fill bar's open
   (both raw and repriced economics are reported).
4. A reduce_only FOK exit arriving when the position is already flat is
   REJECTED (no fill), so stop-vs-exit races resolve to whichever filled
   first.
5. Same-bar race ("race" scenario): when a bar touches the stop, the venue
   fills the stop DURING that bar's processing, BEFORE the strategy's
   on_bar callback for it — a strategy exit decision made on that bar is
   rejected (flat). The stop therefore always wins a same-bar race; the
   strategy's cancel-stop-then-exit sequence can never preempt a stop
   trigger that has already occurred. (In the other direction — exit
   decision at a boundary before the touching bar — the exit fills
   instantly at the boundary close, a real traded price, and the untriggered
   stop is canceled: a causal decision, not optimism.)

Writes observations to audit/fill_fixture_observations.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, TimeInForce
from nautilus_trader.model.identifiers import Venue, InstrumentId
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.trading.strategy import Strategy

from studies.fable5_pre_flip_d10_reversal_entry.run_nt import create_instrument

AUDIT = Path(__file__).resolve().parent / "audit"
NS = 1_000_000_000
T0 = pd.Timestamp("2025-06-02 14:00:00", tz="UTC").value

# tape: (offset_s, o, h, l, c) — bar1 open deliberately differs from bar0
# close so the entry-fill price source is unambiguous.
TAPE = [
    (0, 100.00, 100.25, 99.75, 100.00),
    (1, 100.25, 100.50, 100.00, 100.25),   # distinct open 100.25
    (2, 100.25, 100.50, 99.00, 99.50),     # stop 99.75 triggers intrabar here
    (3, 99.50, 99.75, 99.25, 99.50),
    (4, 98.00, 98.25, 97.75, 98.00),       # gap-down open for scenario B
    (5, 98.00, 98.25, 97.75, 98.00),
    (6, 98.00, 98.25, 97.75, 98.00),
]


def make_bars(bt: BarType, inst) -> list[Bar]:
    bars = []
    for off, o, h, l, c in TAPE:
        ts_event = T0 + off * NS
        bars.append(Bar(
            bar_type=bt,
            open=Price(o, 2), high=Price(h, 2), low=Price(l, 2),
            close=Price(c, 2), volume=Quantity.from_int(100),
            ts_event=ts_event, ts_init=ts_event + NS,
        ))
    return bars


class FixtureStrategy(Strategy):
    def __init__(self, scenario: str):
        super().__init__()
        self.scenario = scenario
        self._inst = InstrumentId.from_str("NQ.XCME")
        self.events: list[dict] = []
        self._n = 0
        self._entry_id = None
        self._stop_id = None
        self._exit_id = None

    def on_start(self):
        self._bt = BarType.from_str("NQ.XCME-1-SECOND-LAST-EXTERNAL")
        self.subscribe_bars(self._bt)

    def on_bar(self, bar: Bar):
        self._n += 1
        if self._n == 1:  # submit entry while processing bar 0
            o = self.order_factory.market(
                instrument_id=self._inst, order_side=OrderSide.BUY,
                quantity=Quantity.from_int(1), time_in_force=TimeInForce.FOK)
            self._entry_id = o.client_order_id.value
            self.events.append({"ev": "submit_entry", "ts": bar.ts_init})
            self.submit_order(o)
        if self.scenario == "race" and self._n == 3:
            # bar 2 just processed: it touched the stop (low 99.00 <= 99.75)
            # and the venue filled the stop before delivering this callback
            o = self.order_factory.market(
                instrument_id=self._inst, order_side=OrderSide.SELL,
                quantity=Quantity.from_int(1),
                time_in_force=TimeInForce.FOK, reduce_only=True)
            self._exit_id = o.client_order_id.value
            self.events.append({"ev": "submit_race_exit", "ts": bar.ts_init})
            self.submit_order(o)
        if self.scenario == "flat_exit" and self._n == 4:
            # position already stopped out on bar 2; submit reduce_only exit
            o = self.order_factory.market(
                instrument_id=self._inst, order_side=OrderSide.SELL,
                quantity=Quantity.from_int(1),
                time_in_force=TimeInForce.FOK, reduce_only=True)
            self._exit_id = o.client_order_id.value
            self.events.append({"ev": "submit_flat_exit", "ts": bar.ts_init})
            self.submit_order(o)

    def on_order_filled(self, event):
        cid = event.client_order_id.value
        self.events.append({
            "ev": "fill", "cid_role": "entry" if cid == self._entry_id
            else "stop" if cid == self._stop_id else "exit",
            "px": float(event.last_px), "ts": int(event.ts_event)})
        if cid == self._entry_id:
            trigger = 99.75 if self.scenario != "gap" else 98.50
            so = self.order_factory.stop_market(
                instrument_id=self._inst, order_side=OrderSide.SELL,
                quantity=Quantity.from_int(1),
                trigger_price=Price(trigger, 2),
                time_in_force=TimeInForce.GTC, reduce_only=True)
            self._stop_id = so.client_order_id.value
            self.events.append({"ev": "submit_stop", "trigger": trigger,
                                "ts": int(event.ts_event)})
            self.submit_order(so)

    def on_order_denied(self, event):
        self.events.append({"ev": "denied", "ts": self.clock.timestamp_ns()})

    def on_order_rejected(self, event):
        self.events.append({"ev": "rejected", "ts": int(event.ts_event)})

    def on_order_canceled(self, event):
        self.events.append({"ev": "canceled", "ts": int(event.ts_event)})


def run_scenario(name: str) -> list[dict]:
    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id="FIXTURE-001",
        logging=LoggingConfig(log_level="ERROR")))
    engine.add_venue(venue=Venue("XCME"), oms_type=OmsType.NETTING,
                     account_type=AccountType.MARGIN, base_currency=USD,
                     starting_balances=[Money(1_000_000, USD)],
                     bar_execution=True,
                     bar_adaptive_high_low_ordering=True)
    inst = create_instrument()
    engine.add_instrument(inst)
    bt = BarType.from_str("NQ.XCME-1-SECOND-LAST-EXTERNAL")
    engine.add_data(make_bars(bt, inst))
    strat = FixtureStrategy(name)
    engine.add_strategy(strat)
    engine.run()
    ev = strat.events
    engine.dispose()
    return ev


def main() -> None:
    out = {}
    for name in ("normal", "gap", "flat_exit", "race"):
        ev = run_scenario(name)
        out[name] = ev
        print(f"--- {name} ---")
        for e in ev:
            rel = {k: (v - T0) / NS if k in ("ts",) and isinstance(v, int)
                   else v for k, v in e.items()}
            print("   ", rel)

    # assertions on the documented semantics
    def fills(evs, role):
        return [e for e in evs if e["ev"] == "fill" and e.get("cid_role") == role]

    n = out["normal"]
    entry = fills(n, "entry")[0]
    # fills at the decision boundary against the just-completed bar's close
    assert entry["px"] == 100.00 and (entry["ts"] - T0) / NS == 1, \
        f"entry fill semantics changed: {entry}"
    stop = fills(n, "stop")[0]
    assert stop["px"] == 99.75, f"stop fill at trigger expected: {stop}"
    assert (stop["ts"] - T0) / NS == 3, f"stop should fill on bar 2: {stop}"

    g = out["gap"]
    stop_g = fills(g, "stop")[0]
    # OPTIMISTIC: NT fills at trigger even though bar 4 gapped through it
    # (range 97.75-98.25 < 98.50). analyze.py reprices these to bar open.
    assert stop_g["px"] == 98.50, f"gap-through semantics changed: {stop_g}"

    f = out["flat_exit"]
    assert len(fills(f, "exit")) == 0, "reduce_only exit filled while flat!"

    r = out["race"]
    assert len(fills(r, "stop")) == 1 and fills(r, "stop")[0]["px"] == 99.75, \
        "race: stop should fill during bar 2 processing"
    assert len(fills(r, "exit")) == 0, \
        "race: same-bar strategy exit must lose to the already-filled stop"

    AUDIT.mkdir(exist_ok=True)
    (AUDIT / "fill_fixture_observations.json").write_text(
        json.dumps(out, indent=2, default=str))
    print("\nAll fixture assertions passed. Observations written to "
          "audit/fill_fixture_observations.json")


if __name__ == "__main__":
    main()
