"""NT backtest with ML inverse filter.

Identical to flip_5m_nonaligned_bracket_backtest.py except: only enters
trades whose signal_ts is in the precomputed 'approved' list (bottom 50%
of model predicted score).

Confirms whether the walk-forward inverse filter holds in actual NT
execution on 2025.

Usage:
    python backtests/flip_5m_nonaligned_bracket_filtered_backtest.py
"""

import sys
import os
import time as _time
from pathlib import Path

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

# Reuse base class components
sys.path.insert(0, str(project_root / "backtests"))
from flip_5m_nonaligned_bracket_backtest import (
    LocalEMA, RegimeState, FlipBracketStrategy, FlipBracketConfig,
    create_nq, CT, NQ_MULT, COMMISSION,
)

APPROVED_PATH_DEFAULT = (
    "studies/ml_5m_flip_prediction/results/"
    "approved_signals_2025_bottom_50.parquet")


class FilteredFlipBracketConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    pt_atr: float = 1.0
    sl_atr: float = 1.0
    warmup_1m_bars: int = 150
    fill_delay_s: int = 30
    approved_signals_path: str = APPROVED_PATH_DEFAULT


class FilteredFlipBracketStrategy(FlipBracketStrategy):
    """Same as FlipBracketStrategy but only enters approved signal_ts."""

    def __init__(self, config: FilteredFlipBracketConfig):
        # Construct underlying base config
        base_cfg = FlipBracketConfig(
            strategy_id=str(config.strategy_id),
            instrument_id=config.instrument_id,
            bar_type_1s=config.bar_type_1s,
            bar_type_1m=config.bar_type_1m,
            pt_atr=config.pt_atr,
            sl_atr=config.sl_atr,
            warmup_1m_bars=config.warmup_1m_bars,
            fill_delay_s=config.fill_delay_s,
        )
        super().__init__(base_cfg)
        # Load approved signal_ts set
        approved = pd.read_parquet(config.approved_signals_path)
        self._approved = set(approved["event_id"].astype(int).values)
        print(f"  Loaded {len(self._approved):,} approved signals from "
              f"{config.approved_signals_path}")
        self._diag["skipped_ml_filter"] = 0

    def _on_1m(self, bar):
        # Same as parent except in the confirmation block we additionally
        # check the ML filter. Easiest: monkey-patch the eligibility by
        # overriding the queue_pending step. Cleanest: copy parent body
        # with one added check.
        # Use the same logic as parent but intercept just before
        # state="PENDING_FILL" is set.
        # Simplest approach: override the parent's behavior by calling it
        # then intervening — but parent submits in the same call. Instead
        # we re-implement just the bar+1 confirmation block with the
        # ML filter check added.
        ts = bar.ts_event
        o = float(bar.open)
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)

        self._1m_count += 1
        from nautilus_trader.indicators import AverageTrueRange  # noqa
        self.atr_14.update_raw(h, l, c)
        prev_regime_1m = self.regime_1m.regime
        prev_regime_5m = self.regime_5m.regime
        new_r_1m = self.regime_1m.update(h, l, c)

        self._1m_for_5m.append((ts, o, h, l, c))
        minute_of_hour = (ts // 60_000_000_000) % 60
        if minute_of_hour % 5 == 4 and len(self._1m_for_5m) >= 5:
            sub = self._1m_for_5m[-5:]
            agg_h = max(b[2] for b in sub)
            agg_l = min(b[3] for b in sub)
            agg_c = sub[-1][4]
            self.regime_5m.update(agg_h, agg_l, agg_c)
            self._1m_for_5m = []

        if not self._warmup:
            self._warmup = (
                self._1m_count >= self.config.warmup_1m_bars
                and self.atr_14.initialized
                and self.regime_5m.ema9.initialized
            )
            return

        flip_occurred = (prev_regime_1m != 0 and new_r_1m != 0
                          and prev_regime_1m != new_r_1m)

        if flip_occurred:
            self._diag["flips"] += 1
            if self._state == "IN_TRADE" and self._trade is not None:
                d = self._trade["direction"]
                if new_r_1m == -d:
                    self._submit_close(
                        c, ts + 60_000_000_000, "regime_flip")
                    return
                return
            if self._state == "PENDING_CLOSE":
                return
            if self._state == "PENDING_FILL" and self._trade is not None:
                d = self._trade["direction"]
                if new_r_1m == -d:
                    self._diag["regime_died_before_fill"] += 1
                    self._abort_pending()
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

            self._diag["confirmed"] += 1
            signal_time = ts + 60_000_000_000

            dt_ct = pd.Timestamp(
                signal_time, unit="ns", tz="UTC").astimezone(CT)
            ct_min = dt_ct.hour * 60 + dt_ct.minute
            if not (510 <= ct_min < 900):
                self._diag["skipped_eth"] += 1
                self._flip_pending = None
                self._state = "FLAT"
                return

            if prev_regime_5m == d:
                self._diag["skipped_5m_aligned"] += 1
                self._flip_pending = None
                self._state = "FLAT"
                return

            # ML FILTER CHECK
            if signal_time not in self._approved:
                self._diag["skipped_ml_filter"] += 1
                self._flip_pending = None
                self._state = "FLAT"
                return

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
            self._pending_submit_ts = fill_target_ts - 1_000_000_000
            self._state = "PENDING_FILL"
            self._flip_pending = None


def main():
    # Year via env var or sys.argv (default 2025)
    year_arg = os.environ.get("BACKTEST_YEAR", "2025")
    if len(sys.argv) > 1:
        year_arg = sys.argv[1]
    year = int(year_arg)
    approved_path = (
        f"studies/ml_5m_flip_prediction/results/"
        f"approved_signals_{year}_bottom_50.parquet")

    print("=" * 80)
    print(f"FLIP + 5m-NON-ALIGN + ML FILTER (bottom 50%) — NT BACKTEST {year}")
    print("=" * 80)

    cat_path = os.environ.get("CATALOG_PATH",
        "data/catalog/NQ_multi_year" if year == 2026
        else "data/catalog/NQ_2020_2025")
    catalog = ParquetDataCatalog(cat_path)
    print(f"  catalog: {cat_path}")
    start = pd.Timestamp(f"{year}-01-01", tz="UTC")
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

    nq = create_nq()
    safe_year = str(year)
    config = FilteredFlipBracketConfig(
        strategy_id=f"FLIP-FILT-B50-{safe_year}",
        approved_signals_path=approved_path,
    )

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"FILT-{safe_year[-3:]}",
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

    strat = FilteredFlipBracketStrategy(config)
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
    out_dir = Path(
        "backtests/results/flip_5m_nonaligned_bracket")
    out_file = out_dir / f"trades_{year}_filter_b50.parquet"
    df.to_parquet(out_file, index=False)
    print(f"\nSaved {len(df):,} trades → {out_file}")

    # Summary
    n = len(df)
    wr = (df["pnl_dollars"] > 0).mean() * 100
    avg = df["pnl_dollars"].mean()
    tot = df["pnl_dollars"].sum()
    gp = df[df["pnl_dollars"] > 0]["pnl_dollars"].sum()
    gl = abs(df[df["pnl_dollars"] <= 0]["pnl_dollars"].sum())
    pf = gp / gl if gl > 0 else float("inf")

    print(f"\n{'='*80}")
    print(f"  RESULTS — {year} (ML filter: keep bottom 50% pred)")
    print(f"{'='*80}")
    print(f"  Trades:         {n:,}")
    print(f"  WR:             {wr:.1f}%")
    print(f"  Avg$:           ${avg:+.2f}")
    print(f"  Total$:         ${tot:+,.0f}")
    print(f"  PF:             {pf:.2f}")

    print(f"\n  By exit reason:")
    for r in sorted(df["exit_reason"].unique()):
        s = df[df["exit_reason"] == r]
        wr_r = (s["pnl_dollars"] > 0).mean() * 100
        print(f"    {r:>20}: N={len(s):>5,}  "
              f"Avg=${s['pnl_dollars'].mean():+7.1f}  "
              f"WR={wr_r:5.1f}%  "
              f"Total=${s['pnl_dollars'].sum():+8,.0f}")

    df["_ym"] = pd.to_datetime(df["date"]).dt.to_period("M")
    print(f"\n  Monthly:")
    print(f"    {'Month':>8} {'N':>4} {'Avg$':>8} {'Total$':>10} {'WR':>6}")
    for ym, g in df.groupby("_ym"):
        a = g["pnl_dollars"].mean()
        t = g["pnl_dollars"].sum()
        wr_m = (g["pnl_dollars"] > 0).mean() * 100
        print(f"    {str(ym):>8} {len(g):>4,} {a:>+7.1f} "
              f"{t:>+9,.0f} {wr_m:>5.1f}%")

    sim_ref = {
        2022: (1541, 29.1, 1.22, 44867),
        2023: (1566, 43.6, 1.56, 68329),
        2024: (1485, 66.7, 1.76, 99087),
        2025: (1542, 110.2, 1.94, 169950),
    }
    if year in sim_ref:
        sn, savg, spf, stot = sim_ref[year]
        print(f"\n  Comparison to walk-forward sim 'keep bottom 50%' {year}:")
        print(f"    sim:  N={sn:,}  Avg=$+{savg}  PF={spf}  "
              f"Total=$+{stot:,}")
        print(f"    NT :  N={n:,}  Avg=${avg:+.1f}  PF={pf:.2f}  "
              f"Total=${tot:+,.0f}")


if __name__ == "__main__":
    main()
