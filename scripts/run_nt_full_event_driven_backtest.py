# scripts/run_nt_full_event_driven_backtest.py
import os
import sys
import time
import json
import hashlib
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

REPO_ROOT = Path(r'c:/Users/Scott McCarty/Projects/Nautilus Trader')
STUDY_DIR = REPO_ROOT / 'studies/nq_leaf4_execution_robustness'
STUDY_DIR.mkdir(parents=True, exist_ok=True)

def run_month_nt_engine(year, month):
    t_start = time.time()
    dt_start = pd.Timestamp(year=year, month=month, day=1, tz='UTC')
    dt_end = dt_start + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1)
    
    df_l4 = pd.read_parquet(REPO_ROOT / 'studies/nq_leaf4_runtime_validation_and_distribution_diagnostic/runtime_trade_ledger.parquet')
    df_sub = df_l4[(df_l4['checkpoint_ts'] >= dt_start.value) & (df_l4['checkpoint_ts'] < dt_end.value)].copy()
    if len(df_sub) == 0:
        return []
        
    entries = defaultdict(list)
    exits = defaultdict(list)
    for idx, r in df_sub.iterrows():
        c_dir = -r['direction']
        tid = int(r['trade_id'])
        entries[int(r['checkpoint_ts'])].append((c_dir, float(r['frozen_atr']), tid))
        exits[int(r['exit_submit_ts'])].append((c_dir, tid))

    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, TimeInForce
    from nautilus_trader.model.identifiers import Venue, InstrumentId
    from nautilus_trader.model.objects import Money, Quantity
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    from nautilus_trader.trading.strategy import Strategy
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.backtest.models import OneTickSlippageFillModel, PerContractFeeModel

    class Leaf4HedgingStrategy(Strategy):
        def __init__(self, entries, exits):
            super().__init__()
            self.entries = entries
            self.exits = exits
            self.active_positions = {}
            self.order_to_tid = {}
            self.closed_trades = []

        def on_start(self):
            self.subscribe_bars(BarType.from_str('NQ.XCME-1-SECOND-LAST-EXTERNAL'))

        def on_bar(self, bar: Bar):
            ts = bar.ts_init
            if ts in self.entries:
                for c_dir, atr, tid in self.entries[ts]:
                    side = OrderSide.BUY if c_dir == 1 else OrderSide.SELL
                    order = self.order_factory.market(
                        instrument_id=InstrumentId.from_str('NQ.XCME'),
                        order_side=side,
                        quantity=Quantity.from_int(1),
                        time_in_force=TimeInForce.GTC
                    )
                    self.order_to_tid[order.client_order_id.value] = (tid, 'ENTRY', atr, c_dir, ts)
                    self.submit_order(order)
                
            if ts in self.exits:
                for c_dir, tid in self.exits[ts]:
                    if tid in self.active_positions:
                        close_side = OrderSide.SELL if c_dir == 1 else OrderSide.BUY
                        order = self.order_factory.market(
                            instrument_id=InstrumentId.from_str('NQ.XCME'),
                            order_side=close_side,
                            quantity=Quantity.from_int(1),
                            time_in_force=TimeInForce.GTC
                        )
                        self.order_to_tid[order.client_order_id.value] = (tid, 'EXIT', 0.0, c_dir, ts)
                        self.submit_order(order)

        def on_order_filled(self, event):
            cid = event.client_order_id.value
            if cid in self.order_to_tid:
                tid, role, atr, c_dir, sub_ts = self.order_to_tid[cid]
                if role == 'ENTRY':
                    self.active_positions[tid] = {
                        'entry_ts': event.ts_event,
                        'entry_px': float(event.last_px),
                        'entry_comm': float(event.commission),
                        'c_dir': c_dir,
                        'atr': atr,
                        'submit_ts': sub_ts
                    }
                elif role == 'EXIT':
                    pos = self.active_positions.pop(tid)
                    exit_px = float(event.last_px)
                    gross_pts = pos['c_dir'] * (exit_px - pos['entry_px'])
                    comm_tot = pos['entry_comm'] + float(event.commission)
                    net_pts = gross_pts - (comm_tot / 20.0)
                    self.closed_trades.append({
                        'trade_id': tid,
                        'year': str(year),
                        'direction': pos['c_dir'],
                        'frozen_atr': pos['atr'],
                        'nt_decision_ts': pos['submit_ts'],
                        'nt_entry_submit_ts': pos['submit_ts'],
                        'nt_entry_fill_ts': pos['entry_ts'],
                        'nt_entry_gross_px': pos['entry_px'] - (0.25 if pos['c_dir'] == 1 else -0.25),
                        'nt_entry_fill_px': pos['entry_px'],
                        'nt_exit_signal_ts': sub_ts,
                        'nt_exit_submit_ts': sub_ts,
                        'nt_exit_fill_ts': event.ts_event,
                        'nt_exit_gross_px': exit_px + (0.25 if pos['c_dir'] == 1 else -0.25),
                        'nt_exit_fill_px': exit_px,
                        'nt_gross_pnl_pts': gross_pts,
                        'nt_gross_pnl_dollars': gross_pts * 20.0,
                        'nt_gross_pnl_atr': gross_pts / pos['atr'],
                        'nt_net_pnl_pts': net_pts,
                        'nt_net_pnl_dollars': net_pts * 20.0,
                        'nt_net_pnl_atr': net_pts / pos['atr'],
                        'nt_transaction_costs_dollars': comm_tot
                    })

    catalog = ParquetDataCatalog(str(REPO_ROOT / 'data/catalog/NQ_v0_2020_2026'))
    bars = catalog.bars(
        bar_types=['NQ.XCME-1-SECOND-LAST-EXTERNAL'],
        start=dt_start,
        end=dt_end
    )

    inst = catalog.instruments()[0]
    engine = BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(log_level='ERROR')))
    engine.add_venue(
        venue=Venue('XCME'),
        oms_type=OmsType.HEDGING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(10_000_000, USD)],
        fill_model=OneTickSlippageFillModel(),
        fee_model=PerContractFeeModel(commission=Money(2.50, USD)),
        bar_execution=True
    )
    engine.add_instrument(inst)
    engine.add_data(bars)
    strat = Leaf4HedgingStrategy(entries, exits)
    engine.add_strategy(strat)

    engine.run()
    elapsed = time.time() - t_start
    res = strat.closed_trades
    engine.dispose()
    print(f'[{year}-{month:02d}] Executed {len(res)} / {len(df_sub)} trades in {elapsed:.1f}s')
    return res
