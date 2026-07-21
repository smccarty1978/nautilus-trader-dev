"""Confirmed-Flip + Trailing Stop — NT Backtest.

Strategy:
  - Subscribe to 1s bars only (synthetic 1m aggregation internally).
  - Detect regime flip on synthetic 1m close.
  - On bar+1 close: if HH (long) / LL (short) confirmed → enter market.
  - Entry fills on next 1s bar (bar+2 first 1s).
  - Exit: trail stop (1.0 ATR activation, 1.0 ATR distance) on 1s bars,
          OR regime flip on synthetic 1m close,
          OR EOD close at 15:55 CT.

Usage:
    python backtests/trailing_confirmed_flip_backtest.py
"""

import sys
import os
import time as _time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import pytz

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import (
    BacktestEngineConfig, LoggingConfig, StrategyConfig)
from nautilus_trader.model.identifiers import Venue, InstrumentId
from nautilus_trader.model.enums import (
    OmsType, AccountType, OrderSide, TimeInForce)
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

# Trail stop config (winners from fixed offline sim Q4 2025)
TRAIL_DIST_ATR = 0.25
TRAIL_ACTIV_ATR = 0.25
# Hard stop loss (in ATR from entry). Set 0 to disable.
HARD_SL_ATR = 0.0
# EOD force-close time (CT)
EOD_HOUR = 15
EOD_MIN = 55


class TrailFlipConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    trail_dist_atr: float = TRAIL_DIST_ATR
    trail_activ_atr: float = TRAIL_ACTIV_ATR
    hard_sl_atr: float = HARD_SL_ATR
    eod_hour: int = EOD_HOUR
    eod_min: int = EOD_MIN


class TrailFlipStrategy(Strategy):
    """Confirmed flip entry + 1.0/1.0 trail stop + regime/EOD exit."""

    def __init__(self, config: TrailFlipConfig):
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

        # Regime state
        self._1m_count = 0
        self._warmup = False
        self._reg = 0
        self._reg_start = 0

        # Trade state
        # FLAT → flip → AWAITING_CONFIRMATION
        # AWAITING_CONFIRMATION → bar+1 HH/LL yes → PENDING_ENTRY
        # AWAITING_CONFIRMATION → bar+1 no HH/LL → FLAT (no trade)
        # PENDING_ENTRY → fill → IN_TRADE
        # IN_TRADE → trail/regime/eod → PENDING_CLOSE
        # PENDING_CLOSE → fill → FLAT
        self._state = "FLAT"
        self._trade = None
        self._entry_oid = None
        self._close_oid = None

        # Flip info awaiting bar+1 confirmation
        self._flip_pending = None

        # Trail stop tracking (on 1s bars)
        self._peak_price = None  # highest high (long) / lowest low (short)
        self._trail_active = False
        self._trail_stop_px = None  # current trail stop price level

        # MFE/MAE
        self._mfe = 0.0
        self._mae = 0.0
        self._bars_in_trade = 0

        self._trades = []
        self._trade_counter = 0
        self._diag = {
            "flips": 0, "entries": 0, "no_confirm_skip": 0,
            "trail_hit": 0, "hard_sl_hit": 0, "regime_flip_exit": 0,
            "eod_exit": 0, "rejects": 0, "synthetic_1m": 0,
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

        # ---- 1s-level processing (for open positions) ----
        if self._state == "IN_TRADE" and self._trade \
                and "entry_price" in self._trade:
            self._update_tracking_1s(h, l, c, ts)

        # ---- 1s → 1m aggregation on 60s boundaries ----
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

    def _update_tracking_1s(self, h, l, c, ts_ns):
        """Per-1s-bar: MFE/MAE, trail stop, EOD check."""
        t = self._trade
        atr = t.get("atr_at_entry", 1e-9)
        ep = t["entry_price"]
        d = t["direction"]

        if atr <= 0:
            return

        # MFE/MAE
        if d == 1:
            self._mfe = max(self._mfe, (h - ep) / atr)
            self._mae = max(self._mae, (ep - l) / atr)
        else:
            self._mfe = max(self._mfe, (ep - l) / atr)
            self._mae = max(self._mae, (h - ep) / atr)

        # Hard SL check (before trail) — exit if loss reaches hard_sl_atr
        if self.config.hard_sl_atr > 0:
            sl_pts = self.config.hard_sl_atr * atr
            if d == 1:
                sl_px = ep - sl_pts
                if l <= sl_px:
                    self._submit_close(sl_px, ts_ns, "hard_sl")
                    return
            else:
                sl_px = ep + sl_pts
                if h >= sl_px:
                    self._submit_close(sl_px, ts_ns, "hard_sl")
                    return

        # Update peak price
        if d == 1:
            if self._peak_price is None or h > self._peak_price:
                self._peak_price = h
        else:
            if self._peak_price is None or l < self._peak_price:
                self._peak_price = l

        # Activation check
        if not self._trail_active:
            peak_atr = abs(self._peak_price - ep) / atr
            if peak_atr >= self.config.trail_activ_atr:
                self._trail_active = True

        # Trail stop update + check
        if self._trail_active:
            trail_pts = self.config.trail_dist_atr * atr
            if d == 1:
                self._trail_stop_px = self._peak_price - trail_pts
                # Exit if 1s bar low breaks stop
                if l <= self._trail_stop_px:
                    self._submit_close(
                        self._trail_stop_px, ts_ns, "trail_hit")
                    return
            else:
                self._trail_stop_px = self._peak_price + trail_pts
                if h >= self._trail_stop_px:
                    self._submit_close(
                        self._trail_stop_px, ts_ns, "trail_hit")
                    return

        # EOD check — fire only in 15:55-15:59 CT window (5-min before
        # futures session close at 16:00 CT). NQ futures break 16:00-17:00
        # then re-open. Trades opened in evening (17:00+) survive overnight
        # and close at 15:55 CT next day.
        dt_ct = pd.Timestamp(ts_ns, unit="ns", tz="UTC").astimezone(CT)
        if (dt_ct.hour == self.config.eod_hour
                and dt_ct.minute >= self.config.eod_min):
            self._submit_close(c, ts_ns, "eod")

    def _on_synthetic_1m(self, o, h, l, c, v, ts_ns):
        """Process a completed synthetic 1m bar."""
        self._1m_count += 1
        self._diag["synthetic_1m"] += 1

        # Feed indicators
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

        # Bar+1 confirmation check (current bar is bar+1 after flip)
        if self._state == "AWAITING_CONFIRMATION":
            self._check_confirmation(o, h, l, c, ts_ns, atr)

        # Regime flip detection
        flip = (new_r != self._reg and self._reg != 0 and new_r != 0)
        if flip:
            self._diag["flips"] += 1
            prior_dur = self._1m_count - self._reg_start

            if self._state == "IN_TRADE":
                self._submit_close(c, ts_ns, "regime_flip")
                self._diag["regime_flip_exit"] += 1
            elif self._state == "AWAITING_CONFIRMATION":
                # New flip before confirming previous — abandon previous
                self._diag["no_confirm_skip"] += 1
                self._flip_pending = None
                self._state = "FLAT"

            # Queue new flip — wait for next synthetic 1m bar to confirm
            self._flip_pending = {
                "direction": new_r,
                "flip_bar_high": h,
                "flip_bar_low": l,
                "atr": atr,
                "prior_regime_duration": prior_dur,
                "flip_time": pd.Timestamp(ts_ns, unit="ns", tz="UTC"),
            }
            if self._state == "FLAT":
                self._state = "AWAITING_CONFIRMATION"
            self._reg_start = self._1m_count

        self._reg = new_r

    def _check_confirmation(self, o, h, l, c, ts_ns, atr):
        """At bar+1 close: confirm HH (long) / LL (short).

        If confirmed, submit market order. Order fills on next 1s bar
        (≈1s after bar+1 close).
        If not confirmed, abandon — no trade.
        """
        fp = self._flip_pending
        if fp is None:
            self._state = "FLAT"
            return
        d = fp["direction"]
        made_hh = (h > fp["flip_bar_high"]) if d == 1 \
            else (l < fp["flip_bar_low"])

        if not made_hh:
            self._diag["no_confirm_skip"] += 1
            self._flip_pending = None
            self._state = "FLAT"
            return

        # Confirmed — submit entry
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
            "flip_time": fp["flip_time"],
            "atr_at_entry": fp["atr"],
            "prior_regime_duration_bars": fp["prior_regime_duration"],
            "bar1_high": h,
            "bar1_low": l,
            "bar1_close": c,
            "date": str(dt_ct.date()),
            "year": dt_ct.year,
            "hour_ct": dt_ct.hour,
            "is_rth": 1 if 510 <= ct_min < 900 else 0,
            "session": "RTH" if 510 <= ct_min < 900 else "ETH",
        }

        self._flip_pending = None
        self._state = "PENDING_ENTRY"
        self._diag["entries"] += 1
        self.submit_order(order)

    def _submit_close(self, signal_price, ts_ns, reason):
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

        if reason == "eod":
            self._diag["eod_exit"] += 1
        elif reason == "trail_hit":
            self._diag["trail_hit"] += 1
        elif reason == "hard_sl":
            self._diag["hard_sl_hit"] += 1
        self.submit_order(order)

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
                # Slippage vs bar+1 close (collector's idealized entry)
                slip = px - self._trade.get("bar1_close", px)
                if self._trade["direction"] == -1:
                    slip = -slip
                self._trade["slippage_entry_pts"] = slip
                self._mfe = 0.0
                self._mae = 0.0
                self._bars_in_trade = 0
                # Seed peak from entry price (trail from entry, not bar1)
                self._peak_price = px
                self._trail_active = False
                self._trail_stop_px = None
                self._state = "IN_TRADE"
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
            slip_exit = px - t.get("_signal_exit_price", px)
            if d == -1:
                slip_exit = -slip_exit

            t.update({
                "exit_price": px,
                "exit_time": pd.Timestamp(
                    event.ts_event, unit="ns", tz="UTC"),
                "exit_reason": reason,
                "pnl_pts": pnl_pts,
                "pnl_dollars": pnl_dollars,
                "commission": COMMISSION,
                "slippage_exit_pts": slip_exit,
                "bars_in_trade": self._bars_in_trade,
                "mfe_atr": max(self._mfe, 0),
                "mae_atr": max(self._mae, 0),
            })
            for k in ["_exit_reason", "_signal_exit_price"]:
                t.pop(k, None)
            self._trades.append(t)
            self._trade = None
            # If a new flip queued during PENDING_CLOSE, resume confirm cycle
            if self._flip_pending is not None:
                self._state = "AWAITING_CONFIRMATION"
            else:
                self._state = "FLAT"

    def on_order_rejected(self, event):
        self._diag["rejects"] += 1
        if self._entry_oid and event.client_order_id == self._entry_oid:
            self._entry_oid = None
            self._trade = None
            self._state = ("AWAITING_CONFIRMATION"
                           if self._flip_pending else "FLAT")
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
    d["expiration_ns"] = pd.Timestamp(
        "2026-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp(
        "2020-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)


def main():
    print("=" * 70)
    print("CONFIRMED-FLIP + TRAIL STOP — NT BACKTEST (Oct-Dec 2025)")
    print(f"  Trail dist={TRAIL_DIST_ATR} ATR, activation={TRAIL_ACTIV_ATR} ATR")
    print(f"  Hard SL: {HARD_SL_ATR} ATR from entry")
    print(f"  EOD close: {EOD_HOUR:02d}:{EOD_MIN:02d} CT")
    print("=" * 70)

    catalog = ParquetDataCatalog("data/catalog/NQ_multi_year")
    start = pd.Timestamp("2025-10-01", tz="UTC")
    end = pd.Timestamp("2025-12-31 23:59:59", tz="UTC")

    print("\nLoading 1s bars...", flush=True)
    t0 = _time.time()
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=start, end=end)
    print(f"  {len(bars_1s):,} bars ({_time.time()-t0:.0f}s)")

    nq = create_nq()
    config = TrailFlipConfig(strategy_id="TRAIL-FLIP-01")

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id="TRAIL-FLIP-001",
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

    strat = TrailFlipStrategy(config)
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
    out = Path(
        "studies/1m_confirmed_flip/results/nt_trail_q4_2025_tight.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"\nSaved {len(df):,} trades → {out}")

    n = len(df)

    print(f"\n{'='*70}")
    print(f"  RESULTS — Oct-Dec 2025")
    print(f"{'='*70}")
    print(f"  Confirmed entries: {n:,}")
    print(f"  Skipped (no bar+1 HH/LL): "
          f"{strat._diag['no_confirm_skip']:,}")
    print(f"  Avg ${df['pnl_dollars'].mean():+.1f}  "
          f"total ${df['pnl_dollars'].sum():+,.0f}")

    wr_all = (df["pnl_dollars"] > 0).mean() * 100
    gw = df[df["pnl_dollars"] > 0]["pnl_dollars"].sum()
    gl = abs(df[df["pnl_dollars"] <= 0]["pnl_dollars"].sum())
    pf = gw / gl if gl > 0 else 999
    print(f"  WR: {wr_all:.1f}%  PF: {pf:.2f}")

    if "slippage_entry_pts" in df.columns:
        slip = df["slippage_entry_pts"]
        print(f"\n  Entry slippage: mean={slip.mean():+.3f} "
              f"std={slip.std():.3f}")

    for r in sorted(df["exit_reason"].unique()):
        s = df[df["exit_reason"] == r]
        wr = (s["pnl_dollars"] > 0).mean() * 100
        print(f"  {r:>18}: {len(s):>6,} "
              f"avg ${s['pnl_dollars'].mean():+.1f}  "
              f"WR {wr:.1f}%  "
              f"total ${s['pnl_dollars'].sum():+,.0f}")

    # Monthly
    df["_ym"] = pd.to_datetime(df["date"]).dt.to_period("M")
    print(f"\n  Monthly:")
    print(f"    {'Month':>8} {'N':>6} {'Avg$':>8} {'Total$':>10} {'WR':>6}")
    for ym, g in df.groupby("_ym"):
        avg = g["pnl_dollars"].mean()
        tot = g["pnl_dollars"].sum()
        wr = (g["pnl_dollars"] > 0).mean() * 100
        print(f"    {str(ym):>8} {len(g):>6,} {avg:>+7.1f} "
              f"{tot:>+9,.0f} {wr:>5.1f}%")
    monthly = df.groupby("_ym")["pnl_dollars"].mean()
    neg = (monthly < 0).sum()
    print(f"    {neg}/{len(monthly)} negative months")

    # RTH / ETH
    for val, label in [(1, "RTH"), (0, "ETH")]:
        s = df[df["is_rth"] == val]
        if len(s):
            wr = (s["pnl_dollars"] > 0).mean() * 100
            print(f"  {label}: {len(s):,} avg "
                  f"${s['pnl_dollars'].mean():+.1f}  "
                  f"WR {wr:.1f}%  "
                  f"total ${s['pnl_dollars'].sum():+,.0f}")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
