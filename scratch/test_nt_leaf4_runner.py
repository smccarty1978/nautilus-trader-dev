import sys
sys.path.insert(0, '.')
import time
from pathlib import Path
import numpy as np
import pandas as pd
from datetime import datetime, timezone

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, StrategyConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId, Venue, ClientOrderId
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.objects import Money, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.data import Bar, BarType

from features.trackers.regime_dual_ema import DualEmaRegimeTracker

# Create instrument
inst = TestInstrumentProvider.future(symbol='NQ', underlying='NQ', venue='XCME', exchange='XCME')
d = inst.to_dict(inst)
d['activation_ns'] = pd.Timestamp('2019-01-01', tz='UTC').value
d['expiration_ns'] = pd.Timestamp('2027-12-31 23:59:59', tz='UTC').value
d['ts_event'] = d['ts_init'] = pd.Timestamp('2019-01-01', tz='UTC').value
d['multiplier'] = '20'
d['price_increment'] = '0.25'
d['price_precision'] = 2
inst_nq = FuturesContract.from_dict(d)

class NQLeaf4TestStrategy(Strategy):
    def __init__(self, config: StrategyConfig):
        super().__init__(config)
        self._inst_id = InstrumentId.from_str('NQ.XCME')
        self._bt_1s = BarType.from_str('NQ.XCME-1-SECOND-LAST-EXTERNAL')
        self._bt_1m = BarType.from_str('NQ.XCME-1-MINUTE-LAST-EXTERNAL')
        
        self._tracker = DualEmaRegimeTracker(timeframe='1m')
        self._roll_15m = [] # list of (close_ts, high, low)
        self._cur_regime = 0
        self._prior_regime_mfe = None
        self._regime_mfe_price = None
        self._regime_start_ts = None
        self._frozen_atr = 10.0
        self._in_pullback = False
        self._cur_1m_atr = 10.0
        
        self.trades = []
        self._open_trades = []
        
    def on_start(self):
        self.subscribe_bars(self._bt_1s)
        self.subscribe_bars(self._bt_1m)
        
    def on_bar(self, bar: Bar):
        if bar.bar_type == self._bt_1m:
            self._on_1m_bar(bar)
        elif bar.bar_type == self._bt_1s:
            self._on_1s_bar(bar)
            
    def _on_1m_bar(self, bar: Bar):
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)
        ts = bar.ts_init # close_ts
        
        up = self._tracker.observe(h, l, c)
        self._cur_1m_atr = up.atr if up.atr is not None and up.atr > 0 else 10.0
        
        # Maintain rolling 15m high/low
        self._roll_15m.append((ts, h, l))
        # Keep last 15 bars
        if len(self._roll_15m) > 15:
            self._roll_15m.pop(0)
            
        if up.flipped:
            # Previous regime ends
            old_dir = self._cur_regime
            if old_dir != 0:
                self._prior_regime_mfe = self._regime_mfe_price
                
                # Check open trades for R1 transition or R2 fallback exit
                for tr in list(self._open_trades):
                    if tr['state'] == 'IN_R0':
                        # Transition to R1
                        tr['state'] = 'IN_R1'
                        tr['r1_start_ts'] = ts
                        tr['r1_dir'] = up.regime
                        tr['r1_mfe_px'] = h if up.regime == 1 else l
                    elif tr['state'] == 'IN_R1':
                        # R1 ended without H050_1 -> R2 fallback exit!
                        tr['state'] = 'EXIT_PENDING'
                        tr['exit_source'] = 'R2_FALLBACK'
                        tr['exit_signal_ts'] = ts
                        side = OrderSide.BUY if tr['trade_dir'] == 1 else OrderSide.SELL
                        order = self.order_factory.market(
                            instrument_id=self._inst_id,
                            order_side=side,
                            quantity=Quantity.from_int(1),
                            time_in_force=TimeInForce.FOK
                        )
                        tr['exit_order_id'] = order.client_order_id.value
                        self.submit_order(order)
                        
            # New regime
            self._cur_regime = up.regime
            self._regime_start_ts = ts
            self._frozen_atr = self._cur_1m_atr
            self._regime_mfe_price = h if up.regime == 1 else l
            self._in_pullback = False
            
    def _on_1s_bar(self, bar: Bar):
        ts = bar.ts_event
        c = float(bar.close)
        h = float(bar.high)
        l = float(bar.low)
        
        # 1. Update R1 MFE and check for H050_1 opposing exits on open trades
        for tr in list(self._open_trades):
            if tr['state'] == 'IN_R1':
                r1_d = tr['r1_dir']
                r1_frozen_atr = tr['r1_frozen_atr'] if 'r1_frozen_atr' in tr else self._cur_1m_atr
                if r1_d == 1:
                    if h > tr['r1_mfe_px']:
                        tr['r1_mfe_px'] = h
                        tr['r1_in_pullback'] = False
                    pb = tr['r1_mfe_px'] - c
                else:
                    if l < tr['r1_mfe_px']:
                        tr['r1_mfe_px'] = l
                        tr['r1_in_pullback'] = False
                    pb = c - tr['r1_mfe_px']
                    
                if not tr.get('r1_in_pullback', False) and (pb / r1_frozen_atr >= 0.50):
                    tr['r1_in_pullback'] = True
                    # Opposing H050_1 triggered!
                    tr['state'] = 'EXIT_PENDING'
                    tr['exit_source'] = 'H050_1'
                    tr['exit_signal_ts'] = ts
                    side = OrderSide.BUY if tr['trade_dir'] == 1 else OrderSide.SELL
                    order = self.order_factory.market(
                        instrument_id=self._inst_id,
                        order_side=side,
                        quantity=Quantity.from_int(1),
                        time_in_force=TimeInForce.FOK
                    )
                    tr['exit_order_id'] = order.client_order_id.value
                    self.submit_order(order)
                    
        # 2. Check current regime running MFE and H050_0 emission
        if self._cur_regime == 0:
            return
            
        d = self._cur_regime
        if d == 1:
            if h > self._regime_mfe_price:
                self._regime_mfe_price = h
                self._in_pullback = False
            pb = self._regime_mfe_price - c
        else:
            if l < self._regime_mfe_price:
                self._regime_mfe_price = l
                self._in_pullback = False
            pb = c - self._regime_mfe_price
            
        pb_atr = pb / self._frozen_atr
        if not self._in_pullback and pb_atr >= 0.50:
            self._in_pullback = True
            
            # Check RTH
            dt_ct = pd.to_datetime(ts, unit='ns', utc=True).tz_convert('America/Chicago')
            tot_min = dt_ct.hour * 60 + dt_ct.minute + dt_ct.second / 60.0
            min_from_rth_open = tot_min - 510.0
            
            if 0.0 <= min_from_rth_open < 405.0: # RTH: 08:30 to 15:15 CT
                # Realized range 15m
                if self._roll_15m:
                    r15_h = max(x[1] for x in self._roll_15m)
                    r15_l = min(x[2] for x in self._roll_15m)
                    realized_range_15m_atr = (r15_h - r15_l) / self._frozen_atr
                else:
                    realized_range_15m_atr = 2.0
                    
                # Current price from prior MFE
                p_mfe = self._prior_regime_mfe if self._prior_regime_mfe is not None else c
                dist_prior_mfe_atr = (d * (c - p_mfe)) / self._cur_1m_atr
                
                # Check Leaf 4
                is_leaf4 = (
                    (min_from_rth_open <= 380.649994) and
                    (realized_range_15m_atr <= 9.344128) and
                    (dist_prior_mfe_atr <= 1.738367)
                )
                
                if is_leaf4:
                    c_dir = -d
                    order_side = OrderSide.BUY if c_dir == 1 else OrderSide.SELL
                    order = self.order_factory.market(
                        instrument_id=self._inst_id,
                        order_side=order_side,
                        quantity=Quantity.from_int(1),
                        time_in_force=TimeInForce.FOK
                    )
                    trade_record = {
                        'checkpoint_ts': ts,
                        'regime_id': self._regime_start_ts,
                        'direction': d,
                        'counter_direction': c_dir,
                        'frozen_atr': self._frozen_atr,
                        'minutes_from_rth_open': min_from_rth_open,
                        'realized_range_15m_atr': realized_range_15m_atr,
                        'current_price_from_prior_mfe_atr__tf_1m': dist_prior_mfe_atr,
                        'leaf4_membership': True,
                        'entry_decision_ts': ts,
                        'entry_order_id': order.client_order_id.value,
                        'trade_dir': c_dir,
                        'state': 'ENTRY_PENDING',
                    }
                    self._open_trades.append(trade_record)
                    self.submit_order(order)
                    
    def on_order_filled(self, event):
        cid = event.client_order_id.value
        px = float(event.last_px)
        ts = event.ts_event
        
        # Check entry fill
        for tr in self._open_trades:
            if tr.get('entry_order_id') == cid and tr['state'] == 'ENTRY_PENDING':
                tr['state'] = 'IN_R0'
                tr['entry_fill_ts'] = ts
                tr['entry_fill_price'] = px
                return
                
        # Check exit fill
        for tr in list(self._open_trades):
            if tr.get('exit_order_id') == cid and tr['state'] == 'EXIT_PENDING':
                tr['state'] = 'CLOSED'
                tr['exit_fill_ts'] = ts
                tr['exit_fill_price'] = px
                
                # Compute PnL
                c_dir = tr['trade_dir']
                gross_pts = c_dir * (tr['exit_fill_price'] - tr['entry_fill_price'])
                net_pts = gross_pts - 0.75 # 0.75 pts friction
                gross_dol = gross_pts * 20.0
                net_dol = net_pts * 20.0
                gross_atr = gross_pts / tr['frozen_atr']
                net_atr = net_pts / tr['frozen_atr']
                
                tr['gross_pnl_pts'] = gross_pts
                tr['net_pnl_pts'] = net_pts
                tr['gross_pnl_dollars'] = gross_dol
                tr['net_pnl_dollars'] = net_dol
                tr['gross_pnl_atr'] = gross_atr
                tr['net_pnl_atr'] = net_atr
                
                self.trades.append(tr)
                self._open_trades.remove(tr)
                return

# Load Jan 2023 bars
print('Loading Jan 2023 catalog bars...')
catalog = ParquetDataCatalog('data/catalog/NQ_v0_2020_2026')
start = pd.Timestamp('2023-01-01 00:00:00', tz='UTC')
end = pd.Timestamp('2023-01-31 23:59:59', tz='UTC')

bars_1s = catalog.bars(bar_types=['NQ.XCME-1-SECOND-LAST-EXTERNAL'], start=start, end=end)
bars_1m = catalog.bars(bar_types=['NQ.XCME-1-MINUTE-LAST-EXTERNAL'], start=start, end=end)
print(f'Loaded {len(bars_1s):,} 1s bars and {len(bars_1m):,} 1m bars.')

engine_cfg = BacktestEngineConfig(
    trader_id='LEAF4-TEST',
    logging=LoggingConfig(log_level='ERROR')
)
engine = BacktestEngine(config=engine_cfg)
engine.add_venue(
    venue=Venue('XCME'),
    oms_type=OmsType.HEDGING,
    account_type=AccountType.MARGIN,
    base_currency=USD,
    starting_balances=[Money(1_000_000, USD)],
    bar_execution=True,
    bar_adaptive_high_low_ordering=True
)
engine.add_instrument(inst_nq)
engine.add_data(bars_1s)
engine.add_data(bars_1m)

class NQLeaf4Config(StrategyConfig):
    pass
strat = NQLeaf4TestStrategy(NQLeaf4Config())
engine.add_strategy(strat)

print('Running engine...')
t_run = time.time()
engine.run()
print(f'Engine finished in {time.time()-t_run:.2f}s. Total trades recorded: {len(strat.trades)}')
engine.dispose()
