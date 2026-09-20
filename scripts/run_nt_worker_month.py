# scripts/run_nt_worker_month.py
import sys
import time
import argparse
from pathlib import Path
import pandas as pd

REPO_ROOT = Path(r'c:/Users/Scott McCarty/Projects/Nautilus Trader')
WORK_DIR = REPO_ROOT / 'studies/nq_leaf4_execution_robustness/_work'
WORK_DIR.mkdir(parents=True, exist_ok=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--month', type=int, required=True)
    args = parser.parse_args()
    
    year = args.year
    month = args.month
    
    t_start = time.time()
    dt_start = pd.Timestamp(year=year, month=month, day=1, tz='UTC')
    dt_end = dt_start + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1)
    
    df_l4 = pd.read_parquet(REPO_ROOT / 'studies/nq_leaf4_runtime_validation_and_distribution_diagnostic/runtime_trade_ledger.parquet')
    df_sub = df_l4[(df_l4['checkpoint_ts'] >= dt_start.value) & (df_l4['checkpoint_ts'] < dt_end.value)].copy()
    
    out_file = WORK_DIR / f'nt_trades_{year}_{month:02d}.parquet'
    if len(df_sub) == 0:
        pd.DataFrame().to_parquet(out_file, index=False)
        print(f"[{year}-{month:02d}] 0 trades in month.")
        return

    entry_events = []
    exit_events = []
    for idx, r in df_sub.iterrows():
        c_dir = -r['direction'] # Counter direction: 1 for buy, -1 for sell
        tid = int(r['trade_id'])
        entry_events.append((int(r['checkpoint_ts']), c_dir, float(r['frozen_atr']), tid))
        exit_events.append((int(r['exit_submit_ts']), c_dir, tid))

    entry_events.sort(key=lambda x: x[0])
    exit_events.sort(key=lambda x: x[0])

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
        def __init__(self, entry_events, exit_events):
            super().__init__()
            self.entry_events = entry_events
            self.exit_events = exit_events
            self.entry_idx = 0
            self.exit_idx = 0
            self.active_positions = {}
            self.pending_exits = {}
            self.order_to_tid = {}
            self.closed_trades = []

        def on_start(self):
            self.subscribe_bars(BarType.from_str('NQ.XCME-1-SECOND-LAST-EXTERNAL'))

        def on_bar(self, bar: Bar):
            ts = bar.ts_init
            while self.entry_idx < len(self.entry_events) and self.entry_events[self.entry_idx][0] <= ts:
                sub_ts, c_dir, atr, tid = self.entry_events[self.entry_idx]
                self.entry_idx += 1
                side = OrderSide.BUY if c_dir == 1 else OrderSide.SELL
                order = self.order_factory.market(
                    instrument_id=InstrumentId.from_str('NQ.XCME'),
                    order_side=side,
                    quantity=Quantity.from_int(1),
                    time_in_force=TimeInForce.GTC
                )
                self.order_to_tid[order.client_order_id.value] = (tid, 'ENTRY', atr, c_dir, sub_ts)
                self.submit_order(order)

            while self.exit_idx < len(self.exit_events) and self.exit_events[self.exit_idx][0] <= ts:
                sub_ts, c_dir, tid = self.exit_events[self.exit_idx]
                self.exit_idx += 1
                if tid in self.active_positions:
                    close_side = OrderSide.SELL if c_dir == 1 else OrderSide.BUY
                    order = self.order_factory.market(
                        instrument_id=InstrumentId.from_str('NQ.XCME'),
                        order_side=close_side,
                        quantity=Quantity.from_int(1),
                        time_in_force=TimeInForce.GTC
                    )
                    self.order_to_tid[order.client_order_id.value] = (tid, 'EXIT', 0.0, c_dir, sub_ts)
                    self.submit_order(order)
                else:
                    self.pending_exits[tid] = (c_dir, sub_ts)

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
                    if tid in self.pending_exits:
                        p_dir, p_sub_ts = self.pending_exits.pop(tid)
                        close_side = OrderSide.SELL if p_dir == 1 else OrderSide.BUY
                        order = self.order_factory.market(
                            instrument_id=InstrumentId.from_str('NQ.XCME'),
                            order_side=close_side,
                            quantity=Quantity.from_int(1),
                            time_in_force=TimeInForce.GTC
                        )
                        self.order_to_tid[order.client_order_id.value] = (tid, 'EXIT', 0.0, p_dir, p_sub_ts)
                        self.submit_order(order)

                elif role == 'EXIT':
                    pos = self.active_positions.pop(tid)
                    exit_px = float(event.last_px)
                    gross_pts = pos['c_dir'] * (exit_px - pos['entry_px'])
                    comm_tot = pos['entry_comm'] + float(event.commission)
                    net_pts = gross_pts - (comm_tot / 20.0)
                    self.closed_trades.append({
                        'trade_id': tid,
                        'entry_signal_ts': pos['submit_ts'],
                        'entry_submit_ts_nt': pos['submit_ts'],
                        'entry_fill_ts_nt': event.ts_event,
                        'entry_fill_gross_nt': pos['entry_px'] - (0.25 if pos['c_dir'] == 1 else -0.25),
                        'entry_fill_net_nt': pos['entry_px'],
                        'exit_submit_ts_nt': sub_ts,
                        'exit_fill_ts_nt': event.ts_event,
                        'exit_fill_gross_nt': exit_px + (0.25 if pos['c_dir'] == 1 else -0.25),
                        'exit_fill_net_nt': exit_px,
                        'nt_closed_net_pts': net_pts,
                        'nt_closed_net_dollars': net_pts * 20.0,
                        'nt_closed_net_atr': net_pts / pos['atr']
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
    strat = Leaf4HedgingStrategy(entry_events, exit_events)
    engine.add_strategy(strat)

    engine.run()
    elapsed = time.time() - t_start
    res = strat.closed_trades
    engine.dispose()
    
    df_res = pd.DataFrame(res)
    df_res.to_parquet(out_file, index=False)
    print(f"[{year}-{month:02d}] Live NT BacktestEngine executed {len(df_res)} / {len(df_sub)} trades in {elapsed:.1f}s -> {out_file.name}")

if __name__ == '__main__':
    main()
