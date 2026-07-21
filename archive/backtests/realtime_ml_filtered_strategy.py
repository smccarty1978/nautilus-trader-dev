"""Real-time ML-filtered NT strategy.

Subclasses the v3 collector (DelayedCheckpointCollector) to inherit all
feature plumbing. Adds:
  - LightGBM model loading at on_start
  - At T_000 snap, build feature vector from collector state, run inference
  - If predicted score <= threshold (bottom 50%), schedule market entry
    at signal+30s. Otherwise skip.
  - 1m regime-flip exit, PT/SL bracket exits on 1s bars.
  - Real NT order submission, no precomputed approval list.

This is the PRODUCTION-pattern simulation: features computed in-strategy
in real time, model inference in-strategy, decisions made on the fly.
"""

import sys
import os
import json
import time as _time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import pytz
import lightgbm as lgb

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

# Import v3 collector
sys.path.insert(0, str(project_root / "studies" /
                         "1m_delayed_checkpoint_context"))
from collector import (DelayedCheckpointCollector, DCContextConfig,
                         CT, NQ_MULT, COMMISSION)


MODEL_DIR = Path("models/ml_5m_flip")


class RealtimeMLConfig(StrategyConfig, frozen=True):
    """Config for the real-time ML-filtered strategy."""
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    output_file: str = ""  # required by parent collector but unused
    warmup_1m_bars: int = 150
    pt_atr: float = 1.0
    sl_atr: float = 1.0
    fill_delay_s: int = 30
    model_path: str = str(MODEL_DIR / "model_2026.txt")
    feature_cols_path: str = str(MODEL_DIR / "feature_cols_2026.json")
    threshold_path: str = str(MODEL_DIR / "threshold_2026.json")
    rth_only: bool = True
    # Mode: 'execute' | 'shadow' | 'parity'
    mode: str = "execute"
    # Parity-mode only: list of event_ids to capture (JSON file path)
    parity_event_ids_path: str = ""
    # Parity-mode only: output parquet path
    parity_output_path: str = ""


class RealtimeMLStrategy(DelayedCheckpointCollector):
    """v3 collector + ML inference + NT order management."""

    def __init__(self, config: RealtimeMLConfig):
        # Build a parent DCContextConfig
        parent_cfg = DCContextConfig(
            strategy_id=str(config.strategy_id),
            instrument_id=config.instrument_id,
            bar_type_1s=config.bar_type_1s,
            bar_type_1m=config.bar_type_1m,
            output_file=config.output_file or
                "studies/ml_5m_flip_prediction/results/_ml_rt_unused.parquet",
            warmup_1m_bars=config.warmup_1m_bars,
        )
        super().__init__(parent_cfg)
        self._cfg = config

        # Load model + feature cols + threshold
        self.model = lgb.Booster(model_file=config.model_path)
        with open(config.feature_cols_path) as f:
            self.feature_cols = json.load(f)
        with open(config.threshold_path) as f:
            thr_data = json.load(f)
            self.threshold = thr_data["bottom_50"]

        # Mode + parity setup
        self.mode = config.mode
        self.parity_event_ids = set()
        self.parity_captures = []
        if self.mode == "parity":
            if not config.parity_event_ids_path:
                raise ValueError("parity mode requires parity_event_ids_path")
            with open(config.parity_event_ids_path) as f:
                pdata = json.load(f)
            self.parity_event_ids = set(int(e) for e in pdata["event_ids"])
            print(f"[RealtimeML] mode={self.mode}, "
                  f"parity event_ids: {len(self.parity_event_ids):,}")
        else:
            print(f"[RealtimeML] mode={self.mode}")

        # NT execution state — FLAT, PENDING_FILL, IN_TRADE, PENDING_CLOSE
        self._exec_state = "FLAT"
        self._exec_trade = None  # holds the trade dict for the live trade
        self._exec_pending_submit_ts = None
        self._exec_pending_fill_ts = None
        self._exec_entry_oid = None
        self._exec_close_oid = None
        self._exec_trades = []  # output trade records
        self._exec_trade_counter = 0

        self._exec_diag = {
            "ml_evaluated": 0,
            "ml_approved": 0,
            "ml_rejected": 0,
            "skipped_eth_at_eval": 0,
            "skipped_already_in_trade": 0,
            "entries_submitted": 0,
            "entries_filled": 0,
            "exits_pt": 0,
            "exits_sl": 0,
            "exits_regime": 0,
            "exits_pt_and_sl_same_bar": 0,
        }

        print(f"[RealtimeML] loaded model with "
              f"{len(self.feature_cols)} features, threshold={self.threshold:.4f}")

    # ----------------------------------------------------------------
    # Override _snap_checkpoint to hook in ML inference at T=0
    # ----------------------------------------------------------------
    def _snap_checkpoint(self, ts_data, T: int, current_ts: int):
        super()._snap_checkpoint(ts_data, T, current_ts)
        if T != 0:
            return
        # T=0 snap just completed. If alive_at_T_000=1, build features +
        # predict. If approved AND we're FLAT (no concurrent trade),
        # schedule entry.
        cp = ts_data.cps[0]
        if cp.alive_at_T == 0:
            return  # already dead, no decision

        # RTH check (collector caches is_rth at root level via _snap_root_features)
        if self._cfg.rth_only:
            if ts_data.collector_root_features.get("is_rth", 0) != 1:
                self._exec_diag["skipped_eth_at_eval"] += 1
                return

        # 5m alignment check (model is trained on the 5m-not-aligned-T0
        # population). If 5m IS aligned at T_000, this row wouldn't be
        # in the training distribution.
        # regime_5m_aligned_T from cp:
        if cp.regime_5m_aligned_T == 1:
            return  # not our population

        # Build feature vector
        try:
            feats = self._build_feature_vector(ts_data, cp)
        except Exception as e:
            print(f"[RealtimeML] feature build error: {e}")
            return

        # Predict
        X = np.array([feats], dtype=float)
        pred = float(self.model.predict(X)[0])
        self._exec_diag["ml_evaluated"] += 1
        decision = 1 if pred <= self.threshold else 0

        # PARITY MODE: capture features + score for sampled event_ids,
        # then exit (no trading)
        if self.mode == "parity":
            event_id = ts_data.signal_time
            if event_id in self.parity_event_ids:
                rec = {
                    "event_id": int(event_id),
                    "runtime_pred": pred,
                    "runtime_decision": decision,
                }
                # Build column-for-column feature mapping
                for col, val in zip(self.feature_cols, feats):
                    rec[col] = val
                self.parity_captures.append(rec)
            return  # parity mode never trades

        # SHADOW MODE: log decision, no trade
        if self.mode == "shadow":
            return

        # EXECUTE MODE
        if pred > self.threshold:
            self._exec_diag["ml_rejected"] += 1
            return

        self._exec_diag["ml_approved"] += 1

        # Check execution state — only enter if FLAT
        if self._exec_state != "FLAT":
            self._exec_diag["skipped_already_in_trade"] += 1
            return

        # Schedule entry: target fill at signal_time + 30s
        fill_target_ts = ts_data.signal_time + 30 * 1_000_000_000
        # Submit during processing of 1s bar with ts_event = fill - 1s
        # (i.e., ts_init = fill_target). For T=0, current_ts == signal_time
        # and snap fired in _on_1s for 1s bar with ts_event = signal_time.
        # Next 1s bar (ts_event = signal+1s) hasn't happened yet. We need
        # to submit during the bar with ts_event = fill_target - 1s
        # = signal + 29s.
        self._exec_pending_submit_ts = fill_target_ts - 1_000_000_000
        self._exec_pending_fill_ts = fill_target_ts
        self._exec_state = "PENDING_FILL"
        self._exec_trade = {
            "direction": ts_data.signal_direction,
            "atr_at_signal": ts_data.atr_at_signal,
            "signal_time": ts_data.signal_time,
            "ml_pred": pred,
            "regime_5m_at_signal": ts_data.regime_5m_at_signal,
        }
        # Add timing context
        dt_ct = pd.Timestamp(
            ts_data.signal_time, unit="ns", tz="UTC").astimezone(CT)
        self._exec_trade.update({
            "date": str(dt_ct.date()),
            "year": dt_ct.year,
            "hour_ct": dt_ct.hour,
            "is_rth": 1,
            "session": "RTH",
        })

    def _build_feature_vector(self, ts_data, cp):
        """Construct ordered feature vector matching self.feature_cols."""
        # Combine root features (from ts_data.collector_root_features) with
        # T_000 checkpoint state. Some features need explicit name mapping.
        root = ts_data.collector_root_features

        # Top-level ts_data fields — these are NOT in collector_root_features
        # (the collector stores them as direct attributes on TradeState).
        ts_level_map = {
            "atr_at_signal": ts_data.atr_at_signal,
            "regime_30s_aligned_t0":
                ts_data.regime_30s_aligned_at_signal,
            "regime_5m_aligned_t0":
                ts_data.regime_5m_aligned_at_signal,
            "signal_direction": ts_data.signal_direction,
        }

        # Feature mapping — read from cp + root
        # Most _T suffixed features come from cp. Root features (no _T)
        # come from `root` dict.
        cp_map = {
            "atr_14_at_T": cp.atr_14_at_T,
            "regime_30s_T": cp.regime_30s_T,
            "regime_30s_aligned_T": cp.regime_30s_aligned_T,
            "regime_30s_duration_bars_T": cp.regime_30s_duration_bars_T,
            "ema3_slope_30s_atr_T": cp.ema3_slope_30s_atr_T,
            "ema_spread_30s_atr_T": cp.ema_spread_30s_atr_T,
            "price_vs_sma20_30s_atr_T": cp.price_vs_sma20_30s_atr_T,
            "bar_range_30s_current_atr_T":
                cp.bar_range_30s_current_atr_T,
            "regime_5m_T": cp.regime_5m_T,
            "regime_5m_duration_bars_T": cp.regime_5m_duration_bars_T,
            "ema3_slope_5m_atr_T": cp.ema3_slope_5m_atr_T,
            "ema_spread_5m_atr_T": cp.ema_spread_5m_atr_T,
            "price_vs_sma20_5m_atr_T": cp.price_vs_sma20_5m_atr_T,
            "regime_5m_changed_during_delay_by_T":
                cp.regime_5m_changed_during_delay_by_T,
            "regime_1m_T": cp.regime_1m_T,
            "micro_same_dir_count_12s_T": cp.micro_same_dir_count_12s_T,
            "micro_opp_dir_count_12s_T": cp.micro_opp_dir_count_12s_T,
            "micro_aligned_T": cp.micro_aligned_T,
            "micro_opposing_T": cp.micro_opposing_T,
            "micro_net_return_atr_T": cp.micro_net_return_atr_T,
            "micro_range_compression_T": cp.micro_range_compression_T,
            "micro_body_pct_avg_T": cp.micro_body_pct_avg_T,
            "continuation_count_since_signal_T":
                cp.continuation_count_since_signal_T,
            "consecutive_continuation_bars_T":
                cp.consecutive_continuation_bars_T,
            "bars_since_last_continuation_T":
                cp.bars_since_last_continuation_T,
            "checkpoint_bars_since_signal_1m_T": 0,  # 0 at T=0
            "is_rth_T": cp.is_rth_T,
            "hour_of_day_T": cp.hour_of_day_T,
            "minute_of_hour_T": cp.minute_of_hour_T,
            "minutes_since_rth_open_T": cp.minutes_since_rth_open_T,
            "distance_from_session_high_atr_T":
                cp.distance_from_session_high_atr_T,
            "distance_from_session_low_atr_T":
                cp.distance_from_session_low_atr_T,
            "vol_total_30s_recent_T": cp.vol_total_30s_recent_T,
            "vol_vs_20avg_30s_T": cp.vol_vs_20avg_30s_T,
            "decision_checkpoint_s": 0,
        }

        feats = []
        for col in self.feature_cols:
            if col in cp_map:
                feats.append(float(cp_map[col]))
            elif col in ts_level_map:
                feats.append(float(ts_level_map[col]))
            elif col in root:
                feats.append(float(root[col]))
            else:
                # Missing feature — use NaN (LightGBM handles)
                feats.append(np.nan)
        return feats

    # ----------------------------------------------------------------
    # Override on_bar to add ML execution layer
    # ----------------------------------------------------------------
    def on_bar(self, bar):
        # Let parent handle feature plumbing + checkpoint snapping
        super().on_bar(bar)

        if bar.bar_type == self._bt_1s:
            self._exec_on_1s(bar)
        elif bar.bar_type == self._bt_1m:
            self._exec_on_1m(bar)

    def _exec_on_1s(self, bar):
        ts = bar.ts_event
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)

        # Submit pending entry
        if (self._exec_state == "PENDING_FILL"
                and self._exec_pending_submit_ts is not None
                and ts == self._exec_pending_submit_ts):
            self._exec_submit_entry()

        # Check brackets
        if (self._exec_state == "IN_TRADE" and self._exec_trade
                and "entry_price" in self._exec_trade):
            self._exec_check_brackets(h, l, ts, c)

    def _exec_on_1m(self, bar):
        # Check 1m regime flip exit for active trade
        if self._exec_state != "IN_TRADE" or self._exec_trade is None:
            return
        # Use the parent's regime_1m state (now updated for this 1m bar)
        d = self._exec_trade["direction"]
        # current regime = self.regime_1m.regime
        if self.regime_1m.regime == -d:
            c = float(bar.close)
            ts = bar.ts_event + 60_000_000_000
            self._exec_submit_close(c, ts, "regime_flip")

    def _exec_submit_entry(self):
        if self._exec_trade is None:
            self._exec_state = "FLAT"
            return
        d = self._exec_trade["direction"]
        side = OrderSide.BUY if d == 1 else OrderSide.SELL
        order = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=side,
            quantity=Quantity.from_int(1),
            time_in_force=TimeInForce.GTC,
        )
        self._exec_entry_oid = order.client_order_id
        self._exec_diag["entries_submitted"] += 1
        self.submit_order(order)

    def _exec_check_brackets(self, h, l, ts_event, close_px):
        t = self._exec_trade
        ep = t["entry_price"]
        d = t["direction"]
        atr = t["atr_at_signal"]
        if atr <= 0:
            return
        pt_pts = self._cfg.pt_atr * atr
        sl_pts = self._cfg.sl_atr * atr
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
            self._exec_diag["exits_pt_and_sl_same_bar"] += 1
            self._exec_submit_close(
                sl_px, ts_event + 1_000_000_000, "sl_same_bar_both")
        elif hit_pt:
            self._exec_submit_close(
                pt_px, ts_event + 1_000_000_000, "pt")
        elif hit_sl:
            self._exec_submit_close(
                sl_px, ts_event + 1_000_000_000, "sl")

    def _exec_submit_close(self, signal_px, ts_event, reason):
        if self._exec_state == "PENDING_CLOSE":
            return
        t = self._exec_trade
        if t is None or "entry_price" not in t:
            self._exec_state = "FLAT"
            self._exec_trade = None
            return
        d = t["direction"]
        side = OrderSide.SELL if d == 1 else OrderSide.BUY
        order = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=side,
            quantity=Quantity.from_int(1),
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
        )
        self._exec_close_oid = order.client_order_id
        t["_exit_reason"] = reason
        t["_signal_exit_price"] = signal_px
        self._exec_state = "PENDING_CLOSE"
        if reason == "pt":
            self._exec_diag["exits_pt"] += 1
        elif reason.startswith("sl"):
            self._exec_diag["exits_sl"] += 1
        elif reason == "regime_flip":
            self._exec_diag["exits_regime"] += 1
        self.submit_order(order)

    def on_order_filled(self, event):
        oid = event.client_order_id
        px = float(event.last_px)

        if self._exec_entry_oid and oid == self._exec_entry_oid:
            self._exec_entry_oid = None
            if self._exec_trade is None:
                return
            self._exec_diag["entries_filled"] += 1
            self._exec_trade["entry_price"] = px
            self._exec_trade["entry_ts"] = event.ts_event
            self._exec_trade_counter += 1
            self._exec_trade["trade_id"] = self._exec_trade_counter
            self._exec_state = "IN_TRADE"
            return

        if self._exec_close_oid and oid == self._exec_close_oid:
            self._exec_close_oid = None
            t = self._exec_trade
            if t is None or "entry_price" not in t:
                self._exec_state = "FLAT"
                self._exec_trade = None
                return
            reason = t.get("_exit_reason", "unknown")
            ep = t["entry_price"]
            d = t["direction"]
            pnl_pts = (px - ep) * d
            pnl_gross = pnl_pts * NQ_MULT
            pnl_net = pnl_gross - COMMISSION
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
            self._exec_trades.append(t)
            self._exec_trade = None
            self._exec_pending_submit_ts = None
            self._exec_pending_fill_ts = None
            self._exec_state = "FLAT"

    def on_order_rejected(self, event):
        if self._exec_entry_oid and event.client_order_id == self._exec_entry_oid:
            self._exec_entry_oid = None
            self._exec_trade = None
            self._exec_state = "FLAT"
            self._exec_pending_submit_ts = None
            self._exec_pending_fill_ts = None
        if self._exec_close_oid and event.client_order_id == self._exec_close_oid:
            self._exec_close_oid = None
            self._exec_state = "FLAT"
            self._exec_trade = None

    def on_stop(self):
        for oid in [self._exec_entry_oid, self._exec_close_oid]:
            if oid:
                o = self.cache.order(oid)
                if o and not o.is_closed:
                    self.cancel_order(o)

        # If parity mode, dump captures to parquet
        if self.mode == "parity" and self._cfg.parity_output_path:
            if self.parity_captures:
                df = pd.DataFrame(self.parity_captures)
                df.to_parquet(self._cfg.parity_output_path, index=False)
                print(f"[RealtimeML] saved {len(df):,} parity captures → "
                      f"{self._cfg.parity_output_path}")
            else:
                print("[RealtimeML] parity mode: NO captures (none of the "
                      "sampled event_ids were evaluated)")
        # Skip parent on_stop (which would write a parquet)


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
    # Year, catalog, mode from sys.argv
    year_arg = sys.argv[1] if len(sys.argv) > 1 else "2026"
    catalog_path = sys.argv[2] if len(sys.argv) > 2 else \
        "data/catalog/NQ_multi_year"
    mode_arg = sys.argv[3] if len(sys.argv) > 3 else "execute"
    year = int(year_arg)

    print("=" * 80)
    print(f"REALTIME ML-FILTERED NT BACKTEST — {year} ({mode_arg})")
    print(f"  Catalog: {catalog_path}")
    print(f"  Model:   trained on 2020-2024, val 2025")
    print("=" * 80)

    catalog = ParquetDataCatalog(catalog_path)
    start = pd.Timestamp(f"{year}-01-01", tz="UTC")
    # Use end of available data; for 2026 that's mid-April
    end = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
    warmup_start = start - pd.Timedelta(days=2)

    print(f"\nLoading 1s bars...", flush=True)
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

    if len(bars_1m) == 0:
        print("NO DATA")
        return

    nq = create_nq()
    parity_ids_path = ""
    parity_out_path = ""
    if mode_arg == "parity":
        parity_ids_path = (
            f"studies/ml_5m_flip_prediction/parity/"
            f"parity_event_ids_{year}.json")
        parity_out_path = (
            f"studies/ml_5m_flip_prediction/parity/"
            f"parity_runtime_features_{year}.parquet")
    config = RealtimeMLConfig(
        strategy_id=f"RT-ML-{year}-{mode_arg[:3].upper()}",
        mode=mode_arg,
        parity_event_ids_path=parity_ids_path,
        parity_output_path=parity_out_path,
    )

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"RT-ML-{str(year)[-3:]}",
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

    strat = RealtimeMLStrategy(config)
    engine.add_strategy(strat)

    print("\nRunning...", flush=True)
    t0 = _time.time()
    engine.run()
    elapsed = _time.time() - t0
    engine.dispose()

    print(f"\nDone in {elapsed:.0f}s.")
    print("\nDiagnostics:")
    for k, v in sorted(strat._exec_diag.items()):
        print(f"  {k}: {v:,}")
    print(f"  collector flips: {strat._diag.get('flips', 0):,}")
    print(f"  collector confirmed: {strat._diag.get('confirmed', 0):,}")

    trades = strat._exec_trades
    if not trades:
        print("\nNO TRADES")
        return

    df = pd.DataFrame(trades)
    out_dir = Path("backtests/results/realtime_ml_filtered")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"trades_{year}_realtime_ml.parquet"
    df.to_parquet(out_file, index=False)
    print(f"\nSaved {len(df):,} trades → {out_file}")

    n = len(df)
    wr = (df["pnl_dollars"] > 0).mean() * 100
    avg = df["pnl_dollars"].mean()
    tot = df["pnl_dollars"].sum()
    gp = df[df["pnl_dollars"] > 0]["pnl_dollars"].sum()
    gl = abs(df[df["pnl_dollars"] <= 0]["pnl_dollars"].sum())
    pf = gp / gl if gl > 0 else float("inf")

    print(f"\n{'='*80}")
    print(f"  RESULTS — {year} (realtime ML-filtered, bottom-50% threshold)")
    print(f"{'='*80}")
    print(f"  Trades:   {n:,}")
    print(f"  WR:       {wr:.1f}%")
    print(f"  Avg$:     ${avg:+.2f}")
    print(f"  Total$:   ${tot:+,.0f}")
    print(f"  PF:       {pf:.2f}")
    print(f"  ML pred dist: min={df['ml_pred'].min():.3f}  "
          f"max={df['ml_pred'].max():.3f}  "
          f"median={df['ml_pred'].median():.3f}")

    print(f"\n  By exit reason:")
    for r in sorted(df["exit_reason"].unique()):
        s = df[df["exit_reason"] == r]
        wr_r = (s["pnl_dollars"] > 0).mean() * 100
        print(f"    {r:>20}: N={len(s):>5,}  "
              f"Avg=${s['pnl_dollars'].mean():+7.1f}  "
              f"WR={wr_r:5.1f}%  Total=${s['pnl_dollars'].sum():+8,.0f}")

    df["_ym"] = pd.to_datetime(df["date"]).dt.to_period("M")
    print(f"\n  Monthly:")
    print(f"    {'Month':>8} {'N':>4} {'Avg$':>8} {'Total$':>10} {'WR':>6}")
    for ym, g in df.groupby("_ym"):
        a = g["pnl_dollars"].mean()
        t = g["pnl_dollars"].sum()
        wr_m = (g["pnl_dollars"] > 0).mean() * 100
        print(f"    {str(ym):>8} {len(g):>4,} {a:>+7.1f} "
              f"{t:>+9,.0f} {wr_m:>5.1f}%")


if __name__ == "__main__":
    main()
