"""NT backtest — RTH 1m-flip + bar+1 HH/LL + 5m-not-aligned + PT/SL bracket.

Confirmation test for the ML tradeability finding:
  population: RTH + confirmed 1m flip + regime_5m NOT aligned with direction
              at signal time + regime alive at fill (signal_time + 30s)
  entry timing: 30s-delayed fill at signal_time + 30s (matches collector T=0)
  bracket: PT = 1.0 ATR from fill, SL = 1.0 ATR from fill
  safety exit: 1m regime flip against direction

Goal: validate that ML study's +$60.2/trade on PT=1.0/SL=1.0 reproduces
in NT under honest execution. Run 2025 only.

Usage:
    python backtests/flip_5m_nonaligned_bracket_backtest.py
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

import numpy as np
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
from nautilus_trader.indicators import AverageTrueRange

CT = pytz.timezone("America/Chicago")
NQ_MULT = 20.0
COMMISSION = 5.0  # $/round trip


# ---- Local EMA + RegimeState (copied from collector for self-contained use)
class LocalEMA:
    def __init__(self, period: int):
        self.period = period
        self.alpha = 2.0 / (period + 1)
        self.value = 0.0
        self.initialized = False
        self.count = 0

    def update(self, v: float) -> None:
        self.count += 1
        if self.count == 1:
            self.value = v
        else:
            self.value = self.alpha * v + (1 - self.alpha) * self.value
        if self.count >= self.period:
            self.initialized = True


class RegimeState:
    """EMA3/9 sticky regime on H/L/C for one timeframe."""

    def __init__(self):
        self.emaH_3 = LocalEMA(3)
        self.emaH_9 = LocalEMA(9)
        self.emaL_3 = LocalEMA(3)
        self.emaL_9 = LocalEMA(9)
        self.ema3 = LocalEMA(3)
        self.ema9 = LocalEMA(9)
        self.regime = 0
        self.completed_bars = 0

    def update(self, h: float, l: float, c: float) -> int:
        self.emaH_3.update(h)
        self.emaH_9.update(h)
        self.emaL_3.update(l)
        self.emaL_9.update(l)
        self.ema3.update(c)
        self.ema9.update(c)
        self.completed_bars += 1

        if not (self.emaH_3.initialized and self.emaH_9.initialized
                and self.emaL_3.initialized and self.emaL_9.initialized):
            return self.regime

        new_r = self.regime
        if c > self.emaH_3.value and c > self.emaH_9.value:
            new_r = 1
        elif c < self.emaL_3.value and c < self.emaL_9.value:
            new_r = -1
        self.regime = new_r
        return self.regime


# ------------------------------------------------------------------
# Strategy
# ------------------------------------------------------------------

class FlipBracketConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    pt_atr: float = 1.0
    sl_atr: float = 1.0
    warmup_1m_bars: int = 150
    fill_delay_s: int = 30  # match collector T_d=0 fill convention


class FlipBracketStrategy(Strategy):
    """1m confirmed flip + 5m not aligned + PT/SL bracket."""

    def __init__(self, config: FlipBracketConfig):
        super().__init__(config)
        self._inst_id = InstrumentId.from_str(config.instrument_id)
        self.regime_1m = RegimeState()
        self.regime_5m = RegimeState()
        self.atr_14 = AverageTrueRange(14)

        # 1m → 5m aggregation
        self._1m_for_5m = []

        # Flip tracking
        self._1m_count = 0
        self._warmup = False
        self._flip_pending = None  # {direction, flip_bar_high, flip_bar_low,
                                    #  atr_at_flip, flip_time}
        self._fill_delay_ns = config.fill_delay_s * 1_000_000_000

        # State machine
        # FLAT → AWAITING_CONFIRMATION (on flip)
        # → (confirmed+eligible) PENDING_FILL → (fill) IN_TRADE
        # → (PT/SL/regime) PENDING_CLOSE → (close filled) FLAT
        self._state = "FLAT"
        self._trade = None
        self._pending_entry_ts = None  # ns — target fill time
        self._pending_submit_ts = None  # ns — when to submit (fill_ts - 1s)
        self._entry_oid = None
        self._close_oid = None

        self._trades = []
        self._trade_counter = 0

        self._diag = {
            "flips": 0,
            "confirmed": 0,
            "skipped_no_hhll": 0,
            "skipped_eth": 0,
            "skipped_5m_aligned": 0,
            "regime_died_before_fill": 0,
            "entries_submitted": 0,
            "entries_filled": 0,
            "entries_rejected": 0,
            "exits_pt": 0,
            "exits_sl": 0,
            "exits_regime": 0,
            "exits_pt_and_sl_same_bar": 0,
        }

    def on_start(self):
        self._bt_1s = BarType.from_str(self.config.bar_type_1s)
        self._bt_1m = BarType.from_str(self.config.bar_type_1m)
        self.subscribe_bars(self._bt_1s)
        self.subscribe_bars(self._bt_1m)

    def on_bar(self, bar: Bar):
        if bar.bar_type == self._bt_1s:
            self._on_1s(bar)
        elif bar.bar_type == self._bt_1m:
            self._on_1m(bar)

    # --------------------------------------------------------------
    def _on_1s(self, bar: Bar):
        ts = bar.ts_event
        h = float(bar.high)
        l = float(bar.low)

        # Submit pending entry when we see the 1s bar just before fill
        # fill target: signal_time + 30s (open of 1s bar with ts_event == target)
        # submit when current bar ts_init == target (i.e., ts_event = target - 1s)
        if (self._state == "PENDING_FILL"
                and self._pending_submit_ts is not None
                and ts == self._pending_submit_ts):
            self._submit_entry()

        # Monitor brackets
        if self._state == "IN_TRADE" and self._trade is not None \
                and "entry_price" in self._trade:
            self._check_brackets(h, l, bar.ts_event, float(bar.close))

    def _on_1m(self, bar: Bar):
        ts = bar.ts_event
        o = float(bar.open)
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)

        self._1m_count += 1

        # Update indicators
        self.atr_14.update_raw(h, l, c)
        prev_regime_1m = self.regime_1m.regime
        # Capture 5m state BEFORE _update_5m — matches T_000 snap semantics
        prev_regime_5m = self.regime_5m.regime
        new_r_1m = self.regime_1m.update(h, l, c)

        # 5m aggregation
        self._1m_for_5m.append((ts, o, h, l, c))
        minute_of_hour = (ts // 60_000_000_000) % 60
        if minute_of_hour % 5 == 4 and len(self._1m_for_5m) >= 5:
            sub = self._1m_for_5m[-5:]
            agg_h = max(b[2] for b in sub)
            agg_l = min(b[3] for b in sub)
            agg_c = sub[-1][4]
            self.regime_5m.update(agg_h, agg_l, agg_c)
            self._1m_for_5m = []

        # Warmup check
        if not self._warmup:
            self._warmup = (
                self._1m_count >= self.config.warmup_1m_bars
                and self.atr_14.initialized
                and self.regime_5m.ema9.initialized
            )
            return

        # 1m flip detection
        flip_occurred = (prev_regime_1m != 0 and new_r_1m != 0
                          and prev_regime_1m != new_r_1m)

        if flip_occurred:
            self._diag["flips"] += 1

            # If IN_TRADE and flip against direction, close and consume
            if self._state == "IN_TRADE" and self._trade is not None:
                d = self._trade["direction"]
                if new_r_1m == -d:
                    self._submit_close(
                        c, ts + 60_000_000_000, "regime_flip")
                    return
                # same direction re-flip shouldn't occur given sticky regime
                return

            # If PENDING_CLOSE, drop new flip (wait for close)
            if self._state == "PENDING_CLOSE":
                return

            # If PENDING_FILL and flip against pending direction, abandon
            if self._state == "PENDING_FILL" and self._trade is not None:
                d = self._trade["direction"]
                if new_r_1m == -d:
                    self._diag["regime_died_before_fill"] += 1
                    self._abort_pending()
                # else: fall through to register new flip (unlikely same dir)

            # Register new flip (overwrite any prior pending)
            atr = self.atr_14.value if self.atr_14.initialized else 0.0
            self._flip_pending = {
                "direction": new_r_1m,
                "flip_bar_high": h,
                "flip_bar_low": l,
                "flip_bar_close": c,
                "atr_at_flip": atr,
                "flip_time": ts,
            }
            self._state = "AWAITING_CONFIRMATION"
            return

        # Bar+1 confirmation
        if self._state == "AWAITING_CONFIRMATION" and self._flip_pending:
            fp = self._flip_pending
            d = fp["direction"]
            made = (h > fp["flip_bar_high"]) if d == 1 \
                else (l < fp["flip_bar_low"])
            if not made:
                self._diag["skipped_no_hhll"] += 1
                self._flip_pending = None
                self._state = "FLAT"
                return

            # Confirmed — now apply eligibility filters
            self._diag["confirmed"] += 1
            signal_time = ts + 60_000_000_000  # bar+1 close

            # RTH check at signal_time
            dt_ct = pd.Timestamp(
                signal_time, unit="ns", tz="UTC").astimezone(CT)
            ct_min = dt_ct.hour * 60 + dt_ct.minute
            if not (510 <= ct_min < 900):
                self._diag["skipped_eth"] += 1
                self._flip_pending = None
                self._state = "FLAT"
                return

            # 5m alignment check — prev_regime_5m captured at TOP of this
            # bar+1 _on_1m call (BEFORE bar+1 triggers _update_5m).
            # This matches collector T_000 snap semantics exactly.
            if prev_regime_5m == d:
                # 5m already aligned → skip (not our population)
                self._diag["skipped_5m_aligned"] += 1
                self._flip_pending = None
                self._state = "FLAT"
                return

            # Eligible — queue delayed entry
            self._trade = {
                "direction": d,
                "atr_at_signal": fp["atr_at_flip"],
                "signal_time": signal_time,
                "flip_time": fp["flip_time"],
                "flip_bar_high": fp["flip_bar_high"],
                "flip_bar_low": fp["flip_bar_low"],
                "bar1_high": h,
                "bar1_low": l,
                "bar1_close": c,
                "date": str(dt_ct.date()),
                "year": dt_ct.year,
                "hour_ct": dt_ct.hour,
                "session": "RTH",
                "is_rth": 1,
                "regime_5m_at_signal": prev_regime_5m,
            }
            fill_target_ts = signal_time + self._fill_delay_ns
            self._pending_entry_ts = fill_target_ts
            # Submit during processing of 1s bar that ends at fill_target_ts
            # (ts_event = fill_target_ts - 1s, ts_init = fill_target_ts)
            self._pending_submit_ts = fill_target_ts - 1_000_000_000
            self._state = "PENDING_FILL"
            self._flip_pending = None

    # --------------------------------------------------------------
    def _submit_entry(self):
        if self._trade is None:
            self._state = "FLAT"
            return
        d = self._trade["direction"]
        side = OrderSide.BUY if d == 1 else OrderSide.SELL
        order = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=side,
            quantity=Quantity.from_int(1),
            time_in_force=TimeInForce.GTC,
        )
        self._entry_oid = order.client_order_id
        self._diag["entries_submitted"] += 1
        self.submit_order(order)

    def _abort_pending(self):
        """Abort a pending fill (regime flipped against before fill)."""
        self._state = "FLAT"
        self._trade = None
        self._pending_entry_ts = None
        self._pending_submit_ts = None

    def _check_brackets(self, h, l, ts_event, close):
        """PT/SL check on each 1s bar after fill."""
        t = self._trade
        ep = t["entry_price"]
        d = t["direction"]
        atr = t["atr_at_signal"]
        if atr <= 0:
            return
        pt_pts = self.config.pt_atr * atr
        sl_pts = self.config.sl_atr * atr

        if d == 1:
            pt_px = ep + pt_pts
            sl_px = ep - sl_pts
            hit_pt = h >= pt_px
            hit_sl = l <= sl_px
        else:
            pt_px = ep - pt_pts
            sl_px = ep + sl_pts
            hit_pt = l <= pt_px
            hit_sl = h >= sl_px

        if hit_pt and hit_sl:
            # Both in same bar — pessimistic: SL first
            self._diag["exits_pt_and_sl_same_bar"] += 1
            self._submit_close(sl_px, ts_event + 1_000_000_000,
                                "sl_same_bar_both")
        elif hit_pt:
            self._submit_close(pt_px, ts_event + 1_000_000_000, "pt")
        elif hit_sl:
            self._submit_close(sl_px, ts_event + 1_000_000_000, "sl")

    def _submit_close(self, signal_price, ts_event, reason):
        if self._state == "PENDING_CLOSE":
            return
        t = self._trade
        if t is None or "entry_price" not in t:
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
        if reason == "pt":
            self._diag["exits_pt"] += 1
        elif reason.startswith("sl"):
            self._diag["exits_sl"] += 1
        elif reason == "regime_flip":
            self._diag["exits_regime"] += 1
        self.submit_order(order)

    def on_order_filled(self, event):
        oid = event.client_order_id
        px = float(event.last_px)

        if self._entry_oid and oid == self._entry_oid:
            self._entry_oid = None
            if self._trade is None:
                return
            self._diag["entries_filled"] += 1
            self._trade["entry_price"] = px
            self._trade["entry_ts"] = event.ts_event
            self._trade_counter += 1
            self._trade["trade_id"] = self._trade_counter
            # Slippage vs collector's fill price measurement
            # (open of 1s bar at signal_time + 30s)
            self._state = "IN_TRADE"
            return

        if self._close_oid and oid == self._close_oid:
            self._close_oid = None
            t = self._trade
            if t is None or "entry_price" not in t:
                self._state = "FLAT"
                self._trade = None
                return
            reason = t.get("_exit_reason", "unknown")
            ep = t["entry_price"]
            d = t["direction"]
            pnl_pts = (px - ep) * d
            pnl_gross = pnl_pts * NQ_MULT
            pnl_net = pnl_gross - COMMISSION
            sig_ex = t.get("_signal_exit_price", px)
            slip_exit = (px - sig_ex) * d  # positive = adverse? no — for close
            # For close, exit_slip>0 means we got a worse price than signal
            # Actually for a close side: if d=1 (long→sell), worse = lower px
            # So slip = signal_px - actual_px for unfavorable
            # Just record raw
            t.update({
                "exit_price": px,
                "exit_ts": event.ts_event,
                "exit_reason": reason,
                "pnl_pts": pnl_pts,
                "pnl_gross": pnl_gross,
                "pnl_dollars": pnl_net,
                "commission": COMMISSION,
            })
            for k in ["_exit_reason", "_signal_exit_price"]:
                t.pop(k, None)
            self._trades.append(t)
            self._trade = None
            self._pending_entry_ts = None
            self._pending_submit_ts = None
            self._state = "FLAT"

    def on_order_rejected(self, event):
        self._diag["entries_rejected"] += 1
        if self._entry_oid and event.client_order_id == self._entry_oid:
            self._entry_oid = None
            self._trade = None
            self._state = "FLAT"
            self._pending_entry_ts = None
            self._pending_submit_ts = None
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


# ------------------------------------------------------------------
# Runner
# ------------------------------------------------------------------

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
    print("=" * 80)
    print("FLIP + 5m-NON-ALIGNED + PT=1.0/SL=1.0 BRACKET — NT BACKTEST")
    print("  Period: 2025 (confirmation run)")
    print("  Rule:   RTH + bar+1 HH/LL confirmed 1m flip +")
    print("          regime_5m NOT aligned at signal time + fillable")
    print("          Entry: 30s-delayed (fill at signal_time + 30s open)")
    print("          Exit:  PT=1.0 ATR, SL=1.0 ATR, or 1m regime flip")
    print("=" * 80)

    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    start = pd.Timestamp("2025-01-01", tz="UTC")
    end = pd.Timestamp("2025-12-31 23:59:59", tz="UTC")
    # Include ~1 day of warmup
    warmup_start = start - pd.Timedelta(days=2)

    print(f"\nLoading 1s bars {warmup_start.date()} to {end.date()}...",
          flush=True)
    t0 = _time.time()
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=warmup_start, end=end)
    print(f"  {len(bars_1s):,} 1s bars ({_time.time()-t0:.0f}s)")

    print("Loading 1m bars...", flush=True)
    t0 = _time.time()
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=warmup_start, end=end)
    print(f"  {len(bars_1m):,} 1m bars ({_time.time()-t0:.0f}s)")

    nq = create_nq()
    config = FlipBracketConfig(strategy_id="FLIP-5M-NONALIGN-BR-01")

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id="FLIP-BR-001",
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
    engine.add_data(bars_1m)

    strat = FlipBracketStrategy(config)
    engine.add_strategy(strat)

    print("\nRunning...", flush=True)
    t0 = _time.time()
    engine.run()
    elapsed = _time.time() - t0
    engine.dispose()

    print(f"\nDone in {elapsed:.0f}s.")
    print("\nDiagnostics:")
    for k, v in sorted(strat._diag.items()):
        print(f"  {k}: {v:,}")

    trades = strat._trades
    if not trades:
        print("\nNO TRADES")
        return

    df = pd.DataFrame(trades)
    out_dir = Path("backtests/results/flip_5m_nonaligned_bracket")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "trades_2025.parquet"
    df.to_parquet(out_file, index=False)
    print(f"\nSaved {len(df):,} trades → {out_file}")

    # -------- summary --------
    print(f"\n{'='*80}")
    print(f"  RESULTS — 2025")
    print(f"{'='*80}")
    n = len(df)
    print(f"  Trades:          {n:,}")
    wr = (df["pnl_dollars"] > 0).mean() * 100
    avg = df["pnl_dollars"].mean()
    tot = df["pnl_dollars"].sum()
    gp = df[df["pnl_dollars"] > 0]["pnl_dollars"].sum()
    gl = abs(df[df["pnl_dollars"] <= 0]["pnl_dollars"].sum())
    pf = gp / gl if gl > 0 else float("inf")
    print(f"  WR:              {wr:.1f}%")
    print(f"  Avg$ per trade:  ${avg:+.2f}")
    print(f"  Total$:          ${tot:+,.0f}")
    print(f"  PF:              {pf:.2f}")

    # Exit reason breakdown
    print(f"\n  By exit reason:")
    for r in sorted(df["exit_reason"].unique()):
        s = df[df["exit_reason"] == r]
        wr_r = (s["pnl_dollars"] > 0).mean() * 100
        print(f"    {r:>20}: N={len(s):>5,}  "
              f"Avg=${s['pnl_dollars'].mean():+7.1f}  "
              f"WR={wr_r:5.1f}%  "
              f"Total=${s['pnl_dollars'].sum():+8,.0f}")

    # Monthly
    df["_ym"] = pd.to_datetime(df["date"]).dt.to_period("M")
    print(f"\n  Monthly:")
    print(f"    {'Month':>8} {'N':>4} {'Avg$':>8} {'Total$':>10} {'WR':>6}")
    for ym, g in df.groupby("_ym"):
        a = g["pnl_dollars"].mean()
        t = g["pnl_dollars"].sum()
        wr_m = (g["pnl_dollars"] > 0).mean() * 100
        print(f"    {str(ym):>8} {len(g):>4,} {a:>+7.1f} "
              f"{t:>+9,.0f} {wr_m:>5.1f}%")

    # Direction
    for d, lbl in [(1, "LONG"), (-1, "SHORT")]:
        s = df[df["direction"] == d]
        if len(s) == 0:
            continue
        wr_d = (s["pnl_dollars"] > 0).mean() * 100
        print(f"\n  {lbl}: N={len(s):,}  "
              f"Avg=${s['pnl_dollars'].mean():+.1f}  WR={wr_d:.1f}%  "
              f"Total=${s['pnl_dollars'].sum():+,.0f}")

    # ML study comparison
    print(f"\n{'='*80}")
    print("  COMPARISON TO ML STUDY TRADEABILITY SIM (TEST=2025):")
    print(f"{'='*80}")
    print(f"  ML sim (collector bracket race): n=2,253  "
          f"Avg=$+87.8  WR=63.6%  PF=1.72")
    print(f"  NT backtest:                     n={n:,}  "
          f"Avg=${avg:+.1f}  WR={wr:.1f}%  PF={pf:.2f}")
    diff = avg - 87.8
    print(f"  Per-trade delta: ${diff:+.1f} "
          f"({'favorable' if diff >= 0 else 'adverse'})")


if __name__ == "__main__":
    main()
