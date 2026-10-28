import pandas as pd
import numpy as np
from pathlib import Path
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, StrategyConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, PositionSide
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.backtest.models import OneTickSlippageFillModel, PerContractFeeModel
from nautilus_trader.trading.strategy import Strategy

# 1. Load RTH cache for 2025-01-03
df_cache = pd.read_parquet('research/noise_vp_study/rth_resampled_cache.parquet')
df_day = df_cache[df_cache['date'] == pd.to_datetime('2025-01-03').date()]
valid_min_epochs = set(int(ts.tz_convert('UTC').timestamp()) for ts in df_day.index)

lookup = {}
for ts, row in df_day.iterrows():
    utc_sec = int(ts.tz_convert('UTC').timestamp())
    hour = ts.hour
    minute = ts.minute
    time_val = hour * 60 + minute
    is_30m = minute in (29, 59)
    blackout = (hour == 11 and minute == 59) or (hour == 13 and minute == 59)
    in_trend_window = (9 * 60 + 59 <= time_val <= 15 * 60 + 29)
    in_fade_window = (9 * 60 + 31 <= time_val <= 15 * 60 + 29)
    is_eod = (hour == 15 and minute >= 59) or (row['minute_idx'] == len(df_day) - 1)
    
    lookup[utc_sec] = {
        'ub': float(row['upper_band']),
        'lb': float(row['lower_band']),
        'vwap': float(row['vwap']),
        'atr': float(row['atr_15m']) if not np.isnan(row['atr_15m']) and row['atr_15m'] > 0 else 15.0,
        'poc': float(row['prev_poc']),
        'vah': float(row['prev_vah']),
        'val': float(row['prev_val']),
        'is_30m': is_30m,
        'in_trend_window': in_trend_window and not blackout,
        'in_fade_window': in_fade_window,
        'is_eod': is_eod,
    }

# 2. Load 1s bars for 2025-01-03
catalog = ParquetDataCatalog('data/catalog/NQ_1S_V2')
start = pd.Timestamp('2025-01-03 14:00:00', tz='UTC')
end = pd.Timestamp('2025-01-03 21:00:00', tz='UTC')
all_bars = catalog.bars(bar_types=['NQ.XCME-1-SECOND-LAST-EXTERNAL'], start=start, end=end)
bars = [b for b in all_bars if (b.ts_event // 60_000_000_000 * 60) in valid_min_epochs]
print(f'Loaded {len(bars):,} RTH 1s bars for 2025-01-03')

class Pillar1TrendV2(Strategy):
    def __init__(self, config):
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str('NQ.XCME')
        self.pos_side = PositionSide.FLAT
        self.entry_price = 0.0
        self.sl_pts = 0.0
        self.is_closing = False

    def on_start(self):
        self.subscribe_bars(BarType.from_str('NQ.XCME-1-SECOND-LAST-EXTERNAL'))

    def on_bar(self, bar: Bar):
        sec_epoch = bar.ts_event // 1_000_000_000
        sec_of_min = sec_epoch % 60
        min_epoch = (sec_epoch // 60) * 60
        info = lookup.get(min_epoch)
        if info is None:
            return
        
        c = float(bar.close)
        
        # Only evaluate on minute close (second 59)
        if sec_of_min == 59:
            # Exits
            if self.pos_side != PositionSide.FLAT and not self.is_closing:
                exit_triggered = False
                if self.pos_side == PositionSide.LONG:
                    if c < self.entry_price - self.sl_pts:
                        exit_triggered = True
                    elif info['is_30m'] and c < max(info['ub'], info['vwap']):
                        exit_triggered = True
                elif self.pos_side == PositionSide.SHORT:
                    if c > self.entry_price + self.sl_pts:
                        exit_triggered = True
                    elif info['is_30m'] and c > min(info['lb'], info['vwap']):
                        exit_triggered = True
                
                if info['is_eod']:
                    exit_triggered = True

                if exit_triggered:
                    self.close_all_positions(self.instrument_id)
                    self.is_closing = True
                    return

            # Entries (30m Checkpoint)
            if self.pos_side == PositionSide.FLAT and not self.is_closing and info['is_30m'] and info['in_trend_window']:
                is_long = (c > info['ub']) and (c > info['vwap'])
                is_short = (c < info['lb']) and (c < info['vwap'])
                if is_long or is_short:
                    pass_vp = False
                    if is_long:
                        pass_vp = (c > info['vah']) or (c < info['val'] and (info['poc'] - c >= 1.5 * info['atr']))
                    else:
                        pass_vp = (c < info['val']) or (c > info['vah'] and (c - info['poc'] >= 1.5 * info['atr']))
                    
                    if pass_vp:
                        b_stop = max(info['ub'], info['vwap']) if is_long else min(info['lb'], info['vwap'])
                        e0 = abs(c - b_stop)
                        if e0 <= 65.0:
                            side = OrderSide.BUY if is_long else OrderSide.SELL
                            order = self.order_factory.market(self.instrument_id, side, Quantity.from_int(1))
                            self.submit_order(order)
                            self.pos_side = PositionSide.LONG if is_long else PositionSide.SHORT
                            self.entry_price = c
                            self.sl_pts = 1.0 * info['atr']

    def on_position_closed(self, event):
        self.pos_side = PositionSide.FLAT
        self.is_closing = False

class Pillar2VPFade(Strategy):
    def __init__(self, config):
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str('NQ.XCME')
        self.pos_side = PositionSide.FLAT
        self.entry_price = 0.0
        self.sl_pts = 0.0
        self.tp_pts = 0.0
        self.bars_held = 0
        self.needs_reset_long = False
        self.needs_reset_short = False
        self.is_closing = False

    def on_start(self):
        self.subscribe_bars(BarType.from_str('NQ.XCME-1-SECOND-LAST-EXTERNAL'))

    def on_bar(self, bar: Bar):
        sec_epoch = bar.ts_event // 1_000_000_000
        sec_of_min = sec_epoch % 60
        min_epoch = (sec_epoch // 60) * 60
        info = lookup.get(min_epoch)
        if info is None:
            return
        
        c = float(bar.close)

        # Reset cone debounce
        if info['lb'] <= c <= info['ub']:
            self.needs_reset_long = False
            self.needs_reset_short = False

        # Exits evaluated on every second
        if self.pos_side != PositionSide.FLAT and not self.is_closing:
            exit_triggered = False
            if self.pos_side == PositionSide.LONG:
                if c <= self.entry_price - self.sl_pts or c >= self.entry_price + self.tp_pts:
                    exit_triggered = True
                    if c <= self.entry_price - self.sl_pts:
                        self.needs_reset_short = True
            elif self.pos_side == PositionSide.SHORT:
                if c >= self.entry_price + self.sl_pts or c <= self.entry_price - self.tp_pts:
                    exit_triggered = True
                    if c >= self.entry_price + self.sl_pts:
                        self.needs_reset_long = True
            
            if exit_triggered:
                self.close_all_positions(self.instrument_id)
                self.is_closing = True
                return

        # Minute boundary checks
        if sec_of_min == 59:
            if self.pos_side != PositionSide.FLAT and not self.is_closing:
                self.bars_held += 1
                if self.bars_held >= 15 or info['is_eod']:
                    self.close_all_positions(self.instrument_id)
                    self.is_closing = True
                    if self.pos_side == PositionSide.SHORT and c > info['ub']:
                        self.needs_reset_long = True
                    elif self.pos_side == PositionSide.LONG and c < info['lb']:
                        self.needs_reset_short = True
                    return

            # Entries evaluated on minute close
            if self.pos_side == PositionSide.FLAT and not self.is_closing and info['in_fade_window']:
                is_up = (c > info['ub']) and (c > info['vwap'])
                is_dn = (c < info['lb']) and (c < info['vwap'])
                if is_up or is_dn:
                    skip = (is_up and self.needs_reset_long) or (is_dn and self.needs_reset_short)
                    if not skip:
                        pass_vp = False
                        if is_up:
                            pass_vp = (c > info['vah']) or (c < info['val'] and (info['poc'] - c >= 1.5 * info['atr']))
                        else:
                            pass_vp = (c < info['val']) or (c > info['vah'] and (c - info['poc'] >= 1.5 * info['atr']))
                        
                        if not pass_vp: # Rejected by VP -> Trigger Fade
                            fade_side = OrderSide.SELL if is_up else OrderSide.BUY
                            order = self.order_factory.market(self.instrument_id, fade_side, Quantity.from_int(1))
                            self.submit_order(order)
                            self.pos_side = PositionSide.SHORT if is_up else PositionSide.LONG
                            self.entry_price = c
                            self.sl_pts = 0.50 * info['atr']
                            self.tp_pts = 0.25 * info['atr']
                            self.bars_held = 0

    def on_position_closed(self, event):
        self.pos_side = PositionSide.FLAT
        self.is_closing = False
        self.bars_held = 0

engine = BacktestEngine(config=BacktestEngineConfig(trader_id='TEST-DAY', logging=LoggingConfig(log_level='ERROR')))
engine.add_venue(
    venue=Venue('XCME'),
    oms_type=OmsType.HEDGING,
    account_type=AccountType.MARGIN,
    base_currency=USD,
    starting_balances=[Money(1_000_000, USD)],
    fill_model=OneTickSlippageFillModel(),
    fee_model=PerContractFeeModel(commission=Money(0.65, USD)),
)
t = TestInstrumentProvider.future(symbol='NQ', underlying='NQ', venue='XCME', exchange='XCME')
d = t.to_dict(t)
d['price_increment'] = '0.25'
d['multiplier'] = '20'
d['activation_ns'] = pd.Timestamp('2019-01-01', tz='UTC').value
d['expiration_ns'] = pd.Timestamp('2027-12-31 23:59:59', tz='UTC').value
d['ts_event'] = d['ts_init'] = pd.Timestamp('2019-01-01', tz='UTC').value
inst = FuturesContract.from_dict(d)
engine.add_instrument(inst)
engine.add_data(bars)

s1 = Pillar1TrendV2(StrategyConfig())
s2 = Pillar2VPFade(StrategyConfig())
engine.add_strategy(s1)
engine.add_strategy(s2)

engine.run()

pos = engine.trader.generate_positions_report()
print('Total positions closed:', len(pos))
for r in pos.itertuples():
    ts_open = pd.to_datetime(r.ts_opened).tz_convert('America/New_York')
    ts_close = pd.to_datetime(r.ts_closed).tz_convert('America/New_York')
    print(f"[{r.strategy_id}] {r.side} open={ts_open.strftime('%H:%M:%S')} @ {r.avg_px_open:.2f}, close={ts_close.strftime('%H:%M:%S')} @ {r.avg_px_close:.2f}, PnL={r.realized_pnl}")
