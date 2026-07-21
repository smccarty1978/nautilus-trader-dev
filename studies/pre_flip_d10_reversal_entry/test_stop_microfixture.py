"""Deterministic NT contract test: can a post-entry-fill stop see entry-bar OHLC?"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, StrategyConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.trading.strategy import Strategy

from studies._shared_exit_mgmt.nt_runner import create_nq
from studies.pre_flip_d10_reversal_entry.common import AUDIT, year_catalog


class FixtureConfig(StrategyConfig, frozen=True):
    trigger_price: float


class Fixture(Strategy):
    def __init__(self, config):
        super().__init__(config); self.cfg=config; self.n=0; self.entry_id=None; self.stop_id=None; self.events=[]

    def on_start(self):
        self.subscribe_bars(BarType.from_str("NQ.XCME-1-SECOND-LAST-EXTERNAL"))

    def on_bar(self, bar):
        self.n += 1
        self.events.append({"kind":"bar","ts_event":int(bar.ts_event),"open":float(bar.open),"low":float(bar.low),"high":float(bar.high)})
        if self.n == 1:
            o=self.order_factory.market(InstrumentId.from_str("NQ.XCME"),OrderSide.BUY,Quantity.from_int(1),TimeInForce.FOK)
            self.entry_id=o.client_order_id.value; self.submit_order(o)

    def on_order_filled(self,event):
        cid=event.client_order_id.value
        self.events.append({"kind":"fill","order":cid,"ts_event":int(event.ts_event),"price":float(event.last_px)})
        if cid == self.entry_id:
            o=self.order_factory.stop_market(
                InstrumentId.from_str("NQ.XCME"),OrderSide.SELL,Quantity.from_int(1),
                Price(self.cfg.trigger_price,2),TimeInForce.GTC,reduce_only=True)
            self.stop_id=o.client_order_id.value; self.submit_order(o)


def main():
    catalog=ParquetDataCatalog(str(year_catalog(2025)))
    start=pd.Timestamp("2025-03-03 23:00:00",tz="UTC"); end=start+pd.Timedelta(hours=2)
    bars=catalog.bars(bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],start=start,end=end)
    chosen=None
    for i in range(len(bars)-1):
        b=bars[i+1]
        if float(b.low) <= float(b.open)-0.25:
            chosen=i; break
    if chosen is None: raise RuntimeError("no fixture bar with >=1 tick downside range")
    sample=bars[chosen:chosen+4]; entry_bar=sample[1]; trigger=float(entry_bar.open)-0.25
    engine=BacktestEngine(BacktestEngineConfig(trader_id="D10-MICRO",logging=LoggingConfig(log_level="WARNING")))
    engine.add_venue(venue=Venue("XCME"),oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,base_currency=USD,
        starting_balances=[Money(1_000_000,USD)],bar_execution=True)
    engine.add_instrument(create_nq()); engine.add_data(sample)
    s=Fixture(FixtureConfig(trigger_price=trigger)); engine.add_strategy(s); engine.run(); engine.dispose()
    stop_fills=[x for x in s.events if x["kind"]=="fill" and x["order"]==s.stop_id]
    result={"entry_bar_ts":int(entry_bar.ts_event),"entry_bar_open":float(entry_bar.open),
            "entry_bar_low":float(entry_bar.low),"trigger":trigger,"stop_fill_events":stop_fills,
            "same_entry_bar_stop_filled":bool(stop_fills and stop_fills[0]["ts_event"]==int(entry_bar.ts_event)),
            "events":s.events}
    (AUDIT/"stop_entry_bar_microfixture.json").write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
    if not result["same_entry_bar_stop_filled"]:
        raise RuntimeError("NT does not match a newly submitted stop on the entry bar")


if __name__=="__main__": main()
