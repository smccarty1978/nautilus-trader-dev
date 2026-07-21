"""Bar+1 HH + HH Exit 3 — NT Backtest with 1s Fill Fix.

Aggregates 1s bars into synthetic 1m bars inside the strategy.
Regime detection, HH tracking, and exit logic run on synthetic 1m.
Orders fill on 1s bars at realistic prices (bar+1 open = first 1s
of the next minute).

Usage:
    python backtests/regime_flip_hh_backtest.py
"""

import sys
import os
import time as _time
from pathlib import Path
from collections import deque

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import pytz

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, StrategyConfig
from nautilus_trader.model.identifiers import Venue, InstrumentId
from nautilus_trader.model.enums import OmsType, AccountType, OrderSide, TimeInForce
from nautilus_trader.model.objects import Money, Quantity
from nautilus_trader.model.currencies import USD
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.trading.strategy import Strategy

from indicators.regime.indicator_v2 import RegimeIndicatorsV2

NQ_MULT = 20.0
COMMISSION = 5.0
CT = pytz.timezone("America/Chicago")


class FlipHHConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"


class FlipHHStrategy(Strategy):
    """1s bars only. Aggregate into 1m internally. Fill on 1s."""

    def __init__(self, config: FlipHHConfig):
        super().__init__(config)
        self._inst_id = InstrumentId.from_str(config.instrument_id)
        self.regime = RegimeIndicatorsV2()

        # 1s → 1m aggregation
        self._1s_buf_o = None
        self._1s_buf_h = -1e18
        self._1s_buf_l = 1e18
        self._1s_buf_c = 0.0
        self._1s_buf_v = 0.0
        self._1s_buf_ts = 0
        self._1s_buf_count = 0
        self._1s_boundary = 0

        # State
        self._1m_count = 0
        self._warmup = False
        self._reg = 0
        self._reg_start = 0

        self._state = "FLAT"  # FLAT, PENDING_ENTRY, AWAITING_BAR1, TRACKING_HH, PENDING_CLOSE
        self._trade = None
        self._entry_oid = None
        self._close_oid = None

        # Flip info for deferred entry
        self._flip_pending = None

        # HH tracking
        self._prev_extreme = 0.0
        self._consec_no_hh = 0
        self._hh_count = 0
        self._bars_in_trade = 0

        # MFE/MAE
        self._mfe = 0.0
        self._mae = 0.0

        self._trades = []
        self._trade_counter = 0
        self._diag = {
            "flips": 0, "entries": 0, "bar1_no_hh": 0,
            "hh3_stall": 0, "regime_fallback": 0, "rejects": 0,
            "synthetic_1m": 0,
        }

    def on_start(self):
        self._bt_1s = BarType.from_str(self.config.bar_type_1s)
        self.subscribe_bars(self._bt_1s)

    def on_bar(self, bar: Bar):
        if bar.bar_type != self._bt_1s:
            return

        ts = bar.ts_event
        h = float(bar.high)
        l = float(bar.low)
        o = float(bar.open)
        c = float(bar.close)
        v = float(bar.volume) if hasattr(bar, "volume") else 0.0

        # MFE/MAE tracking on 1s bars while in position
        if self._state in ("AWAITING_BAR1", "TRACKING_HH"):
            if self._trade and "entry_price" in self._trade:
                atr = self._trade.get("atr_at_entry", 1e-9)
                ep = self._trade["entry_price"]
                d = self._trade["direction"]
                if atr > 0:
                    if d == 1:
                        self._mfe = max(self._mfe, (h - ep) / atr)
                        self._mae = max(self._mae, (ep - l) / atr)
                    else:
                        self._mfe = max(self._mfe, (ep - l) / atr)
                        self._mae = max(self._mae, (h - ep) / atr)

        # 1s → 1m aggregation on clean 60s boundaries
        ts_sec = ts // 1_000_000_000
        boundary = (ts_sec - (ts_sec % 60)) * 1_000_000_000

        if self._1s_buf_count == 0:
            self._1s_boundary = boundary
            self._1s_buf_o = o
            self._1s_buf_h = h
            self._1s_buf_l = l
            self._1s_buf_c = c
            self._1s_buf_v = v
            self._1s_buf_ts = ts
            self._1s_buf_count = 1
        elif boundary == self._1s_boundary:
            self._1s_buf_h = max(self._1s_buf_h, h)
            self._1s_buf_l = min(self._1s_buf_l, l)
            self._1s_buf_c = c
            self._1s_buf_v += v
            self._1s_buf_count += 1
        else:
            # Emit completed synthetic 1m bar
            self._on_synthetic_1m(
                self._1s_buf_o, self._1s_buf_h, self._1s_buf_l,
                self._1s_buf_c, self._1s_buf_v, self._1s_boundary)

            # Start new 1m bar
            self._1s_boundary = boundary
            self._1s_buf_o = o
            self._1s_buf_h = h
            self._1s_buf_l = l
            self._1s_buf_c = c
            self._1s_buf_v = v
            self._1s_buf_ts = ts
            self._1s_buf_count = 1

    def _on_synthetic_1m(self, o, h, l, c, v, ts_ns):
        """Process a completed synthetic 1m bar."""
        self._1m_count += 1
        self._diag["synthetic_1m"] += 1

        # Feed regime indicator with a pseudo-bar
        # RegimeIndicatorsV2.update() expects a Bar object.
        # We need to create one or call the raw update methods.
        # Call the individual EMAs and ATR directly.
        self.regime.short_ema_high.update_raw(h)
        self.regime.short_ema_low.update_raw(l)
        self.regime.short_ema_close.update_raw(c)
        self.regime.long_ema_high.update_raw(h)
        self.regime.long_ema_low.update_raw(l)
        self.regime.long_ema_close.update_raw(c)
        self.regime.atr.update_raw(h, l, c)
        if hasattr(self.regime, 'atr_long'):
            self.regime.atr_long.update_raw(h, l, c)

        atr = (self.regime.atr.value
               if self.regime.atr.initialized else 1e-9)

        # Regime detection
        eh3 = self.regime.short_ema_high.value
        eh9 = self.regime.long_ema_high.value
        el3 = self.regime.short_ema_low.value
        el9 = self.regime.long_ema_low.value
        new_r = self._reg
        if c > eh3 and c > eh9:
            new_r = 1
        elif c < el3 and c < el9:
            new_r = -1

        if not self._warmup:
            self._warmup = (
                self.regime.short_ema_high.initialized
                and self.regime.long_ema_high.initialized
                and self.regime.atr.initialized
                and self._1m_count >= 60)
            self._reg = new_r
            if self._reg != 0:
                self._reg_start = self._1m_count
            return

        # Handle deferred entry (bar+1 open = first 1s of new minute)
        if self._flip_pending is not None and self._state == "FLAT":
            self._submit_entry(o, ts_ns, atr)

        # Bar+1 HH check
        if self._state == "AWAITING_BAR1":
            self._check_bar1(h, l, c, ts_ns)

        # HH tracking
        elif self._state == "TRACKING_HH":
            self._update_hh(h, l, c, ts_ns)

        # Regime flip
        flip = (new_r != self._reg and self._reg != 0 and new_r != 0)
        if flip:
            self._diag["flips"] += 1
            prior_dur = self._1m_count - self._reg_start

            if self._state in ("AWAITING_BAR1", "TRACKING_HH"):
                self._record_exit(c, ts_ns, "regime_flip_fallback")
                self._diag["regime_fallback"] += 1

            # Defer entry to next synthetic 1m bar open
            dt_ct = pd.Timestamp(ts_ns, unit="ns", tz="UTC").astimezone(CT)
            ct_min = dt_ct.hour * 60 + dt_ct.minute
            self._flip_pending = {
                "direction": new_r,
                "flip_bar_high": h,
                "flip_bar_low": l,
                "flip_bar_range": h - l,
                "flip_bar_range_atr": (h - l) / atr if atr > 0 else 0,
                "flip_bar_body_pct": (
                    abs(c - o) / (h - l) if (h - l) > 0 else 0),
                "flip_bar_volume": v,
                "atr": atr,
                "prior_regime_duration": prior_dur,
                "flip_time": pd.Timestamp(ts_ns, unit="ns", tz="UTC"),
            }
            self._reg_start = self._1m_count

        self._reg = new_r

    def _submit_entry(self, bar1_open, ts_ns, atr):
        """Submit market order. Fill will be on next 1s bar."""
        fp = self._flip_pending
        self._flip_pending = None
        d = fp["direction"]

        side = OrderSide.BUY if d == 1 else OrderSide.SELL
        order = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=side,
            quantity=Quantity.from_int(1),
            time_in_force=TimeInForce.GTC,
        )
        self._entry_oid = order.client_order_id

        dt_ct = pd.Timestamp(ts_ns, unit="ns", tz="UTC").astimezone(CT)
        ct_min = dt_ct.hour * 60 + dt_ct.minute

        self._trade = {
            "direction": d,
            "flip_bar_high": fp["flip_bar_high"],
            "flip_bar_low": fp["flip_bar_low"],
            "flip_bar_range_atr": fp["flip_bar_range_atr"],
            "flip_bar_body_pct": fp["flip_bar_body_pct"],
            "flip_bar_volume": fp["flip_bar_volume"],
            "flip_time": fp["flip_time"],
            "atr_at_entry": fp["atr"],
            "prior_regime_duration_bars": fp["prior_regime_duration"],
            "bar1_open": bar1_open,
            "date": str(dt_ct.date()),
            "year": dt_ct.year,
            "hour_ct": dt_ct.hour,
            "is_rth": 1 if 510 <= ct_min < 900 else 0,
            "session": "RTH" if 510 <= ct_min < 900 else "ETH",
        }

        self._state = "PENDING_ENTRY"
        self._diag["entries"] += 1
        self.submit_order(order)

    def _check_bar1(self, h, l, c, ts_ns):
        if not self._trade or "entry_price" not in self._trade:
            return

        t = self._trade
        d = t["direction"]

        if d == 1:
            made_hh = h > t["flip_bar_high"]
        else:
            made_hh = l < t["flip_bar_low"]

        t["bar1_made_hh"] = 1 if made_hh else 0
        t["bar1_high"] = h
        t["bar1_low"] = l
        self._bars_in_trade = 1

        if not made_hh:
            self._diag["bar1_no_hh"] += 1
            # Exit at bar+1 close — submit close order
            self._submit_close(c, ts_ns, "bar1_no_hh")
        else:
            if d == 1:
                self._prev_extreme = h
            else:
                self._prev_extreme = l
            self._consec_no_hh = 0
            self._hh_count = 1
            self._state = "TRACKING_HH"

    def _update_hh(self, h, l, c, ts_ns):
        if not self._trade or "entry_price" not in self._trade:
            return

        d = self._trade["direction"]
        self._bars_in_trade += 1

        if d == 1:
            made_new = h > self._prev_extreme
            if made_new:
                self._prev_extreme = h
        else:
            made_new = l < self._prev_extreme
            if made_new:
                self._prev_extreme = l

        if made_new:
            self._consec_no_hh = 0
            self._hh_count += 1
        else:
            self._consec_no_hh += 1

        if self._consec_no_hh >= 3:
            self._diag["hh3_stall"] += 1
            self._submit_close(c, ts_ns, "hh3_stall")

    def _submit_close(self, signal_price, ts_ns, reason):
        """Submit close order. Fill on next 1s bar."""
        if self._state == "PENDING_CLOSE":
            return
        t = self._trade
        if not t or "entry_price" not in t:
            self._state = "FLAT"
            self._trade = None
            return

        d = t["direction"]
        close_side = OrderSide.SELL if d == 1 else OrderSide.BUY
        order = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=close_side,
            quantity=Quantity.from_int(1),
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
        )
        self._close_oid = order.client_order_id
        t["_exit_reason"] = reason
        t["_signal_exit_price"] = signal_price
        self._state = "PENDING_CLOSE"
        self.submit_order(order)

    def _record_exit(self, exit_price, ts_ns, reason):
        """Record trade without order (for regime flip during tracking)."""
        t = self._trade
        if not t or "entry_price" not in t:
            self._state = "FLAT"
            self._trade = None
            return

        ep = t["entry_price"]
        d = t["direction"]
        pnl_pts = (exit_price - ep) * d
        pnl_dollars = pnl_pts * NQ_MULT - COMMISSION

        t.update({
            "exit_price": exit_price,
            "exit_time": pd.Timestamp(ts_ns, unit="ns", tz="UTC"),
            "exit_reason": reason,
            "pnl_pts": pnl_pts,
            "pnl_dollars": pnl_dollars,
            "commission": COMMISSION,
            "total_hh_count": self._hh_count,
            "bars_in_trade": self._bars_in_trade,
            "mfe_atr": max(self._mfe, 0),
            "mae_atr": max(self._mae, 0),
        })
        self._trades.append(t)
        self._state = "FLAT"
        self._trade = None

    # ---- Fills ----

    def on_order_filled(self, event):
        oid = event.client_order_id
        px = float(event.last_px)

        if self._entry_oid and oid == self._entry_oid:
            self._entry_oid = None
            if self._trade:
                self._trade["entry_price"] = px
                self._trade["entry_ts"] = event.ts_event
                self._trade["entry_time"] = pd.Timestamp(
                    event.ts_event, unit="ns", tz="UTC")
                self._trade_counter += 1
                self._trade["trade_id"] = self._trade_counter
                slippage = px - self._trade.get("bar1_open", px)
                if self._trade["direction"] == -1:
                    slippage = -slippage
                self._trade["slippage_entry_pts"] = slippage
                self._mfe = 0.0
                self._mae = 0.0
                self._bars_in_trade = 0
                self._consec_no_hh = 0
                self._hh_count = 0
                self._state = "AWAITING_BAR1"
            return

        if self._close_oid and oid == self._close_oid:
            self._close_oid = None
            t = self._trade
            if not t or "entry_price" not in t:
                self._state = "FLAT"
                self._trade = None
                return

            reason = t.get("_exit_reason", "unknown")
            ep = t["entry_price"]
            d = t["direction"]
            pnl_pts = (px - ep) * d
            pnl_dollars = pnl_pts * NQ_MULT - COMMISSION

            slippage_exit = px - t.get("_signal_exit_price", px)
            if d == -1:
                slippage_exit = -slippage_exit

            t.update({
                "exit_price": px,
                "exit_time": pd.Timestamp(
                    event.ts_event, unit="ns", tz="UTC"),
                "exit_reason": reason,
                "pnl_pts": pnl_pts,
                "pnl_dollars": pnl_dollars,
                "commission": COMMISSION,
                "slippage_exit_pts": slippage_exit,
                "total_hh_count": self._hh_count,
                "bars_in_trade": self._bars_in_trade,
                "mfe_atr": max(self._mfe, 0),
                "mae_atr": max(self._mae, 0),
            })
            for k in ["_exit_reason", "_signal_exit_price"]:
                t.pop(k, None)
            self._trades.append(t)
            self._state = "FLAT"
            self._trade = None

    def on_order_rejected(self, event):
        self._diag["rejects"] += 1
        if self._entry_oid and event.client_order_id == self._entry_oid:
            self._entry_oid = None
            self._state = "FLAT"
            self._trade = None
        if self._close_oid and event.client_order_id == self._close_oid:
            self._close_oid = None
            self._state = "FLAT"
            self._trade = None

    def on_stop(self):
        for oid in [self._entry_oid, self._close_oid]:
            if oid:
                o = self.cache.order(oid)
                if o and not o.is_closed:
                    self.cancel_order(o)


def create_nq():
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2025-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)


def main():
    print("=" * 70)
    print("BAR+1 HH + HH EXIT 3 — 1s FILL FIX (2020-2025)")
    print("  1s bars only. Synthetic 1m aggregation.")
    print("  Fills on 1s bars = bar+1 open equivalent.")
    print("=" * 70)

    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    start = pd.Timestamp("2020-01-01", tz="UTC")
    end = pd.Timestamp("2025-12-31 23:59:59", tz="UTC")

    print("\nLoading 1s bars...", flush=True)
    t0 = _time.time()
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=start, end=end)
    print(f"  {len(bars_1s):,} bars ({_time.time()-t0:.0f}s)")

    nq = create_nq()
    config = FlipHHConfig(strategy_id="FLIPHH-1SFIX-01")

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id="FLIPHH-1SFIX-001",
        logging=LoggingConfig(log_level="ERROR"),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(10_000_000, USD)],
        bar_execution=True,
    )
    engine.add_instrument(nq)
    engine.add_data(bars_1s)

    strat = FlipHHStrategy(config)
    engine.add_strategy(strat)

    print("\nRunning...", flush=True)
    t0 = _time.time()
    engine.run()
    elapsed = _time.time() - t0
    engine.dispose()

    print(f"\nDone in {elapsed:.0f}s.")
    for k, v in sorted(strat._diag.items()):
        print(f"  {k}: {v:,}")

    trades = strat._trades
    if not trades:
        print("\nNO TRADES")
        return

    df = pd.DataFrame(trades)
    out = Path("studies/1m_regime_flip_study/results/nt_validation_1sfix_all.parquet")
    df.to_parquet(out, index=False)
    print(f"\nSaved {len(df):,} trades")

    n = len(df)
    hh = df[df["bar1_made_hh"] == 1]

    print(f"\n{'='*70}")
    print(f"  RESULTS")
    print(f"{'='*70}")
    print(f"  Total: {n:,}  HH passed: {len(hh):,} ({len(hh)/n*100:.1f}%)")
    print(f"  All trades avg: ${df['pnl_dollars'].mean():+.1f}  total: ${df['pnl_dollars'].sum():+,.0f}")
    print(f"  HH trades avg: ${hh['pnl_dollars'].mean():+.1f}  total: ${hh['pnl_dollars'].sum():+,.0f}")

    # Entry slippage (fill vs bar1_open)
    if "slippage_entry_pts" in df.columns:
        slip = df["slippage_entry_pts"]
        print(f"\n  Entry slippage: mean={slip.mean():+.3f} std={slip.std():.3f}")

    # Exit reasons
    for r in sorted(df["exit_reason"].unique()):
        s = df[df["exit_reason"] == r]
        print(f"  {r}: {len(s):,} avg ${s['pnl_dollars'].mean():+.1f}")

    # By year
    print(f"\n  {'Year':>6} {'N':>7} {'Avg$':>8} {'Total$':>10} {'WR':>6} {'PF':>6}")
    print(f"  {'-'*48}")
    for year in sorted(df["year"].unique()):
        ydf = df[df["year"] == year]
        ya = ydf["pnl_dollars"].mean()
        yt = ydf["pnl_dollars"].sum()
        ywr = (ydf["pnl_dollars"] > 0).mean() * 100
        ygw = ydf[ydf["pnl_dollars"] > 0]["pnl_dollars"].sum()
        ygl = abs(ydf[ydf["pnl_dollars"] <= 0]["pnl_dollars"].sum())
        ypf = ygw / ygl if ygl > 0 else 999
        print(f"  {year:>6} {len(ydf):>7,} {ya:>+7.1f} {yt:>+9,.0f} "
              f"{ywr:>5.1f}% {ypf:>5.2f}")

    # Monthly
    df["_ym"] = pd.to_datetime(df["date"]).dt.to_period("M")
    monthly = df.groupby("_ym")["pnl_dollars"].mean()
    neg = (monthly < 0).sum()
    print(f"\n  Monthly: {len(monthly)} months, {neg} negative ({neg/len(monthly)*100:.0f}%)")

    # RTH/ETH
    for val, label in [(1, "RTH"), (0, "ETH")]:
        s = df[df["is_rth"] == val]
        if len(s):
            print(f"  {label}: {len(s):,} avg ${s['pnl_dollars'].mean():+.1f}")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
