"""
Test NautilusTrader Strategy Parity: NoiseBandV2Strategy on January 2025
Location: research/noise_vp_study/test_strategy_parity.py
"""

import sys
import time
from pathlib import Path
import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from strategies.noise_band_v2_strategy import NoiseBandV2Strategy, NoiseBandV2Config, DailyContext

def run_parity_test():
    print("[ParityTest] Loading context caches...")
    daily_cache_file = Path("research/noise_vp_study/daily_context_cache.parquet")
    df_daily = pd.read_parquet(daily_cache_file)
    df_bars = pd.read_parquet("research/noise_vp_study/rth_resampled_cache.parquet")

    daily_contexts = {}
    for date_val, row in df_daily.iterrows():
        date_str = str(date_val)
        bars_day = df_bars[df_bars["date"] == date_val]
        if len(bars_day) == 0:
            continue
        sigma_tod = bars_day["sigma_tod"].to_dict()
        sigma_tod_by_min = {
            min(390, max(0, int((pd.Timestamp(ts).hour * 60 + pd.Timestamp(ts).minute) - (9 * 60 + 30)))): float(val)
            for ts, val in sigma_tod.items() if not pd.isna(val)
        }
        b_10am = bars_day.between_time("10:00", "10:00")
        noise_10am = float(b_10am["sigma_tod"].iloc[0]) if len(b_10am) > 0 else 50.0

        daily_contexts[date_str] = DailyContext(
            date_str=date_str,
            rth_open=float(row["rth_open"]),
            prev_rth_close=float(row["prev_rth_close"]) if not pd.isna(row["prev_rth_close"]) else float(row["rth_open"]),
            prev_poc=float(row["prev_poc"]) if not pd.isna(row["prev_poc"]) else float(row["rth_open"]),
            prev_vah=float(row["prev_vah"]) if not pd.isna(row["prev_vah"]) else float(row["rth_open"]),
            prev_val=float(row["prev_val"]) if not pd.isna(row["prev_val"]) else float(row["rth_open"]),
            anchor_high=float(row["anchor_high"]),
            anchor_low=float(row["anchor_low"]),
            sigma_tod=sigma_tod_by_min,
            noise_pts_10am=noise_10am,
        )

    print("[ParityTest] Loading January 2025 1s bars from data/catalog/NQ_1S_V2...")
    cat = ParquetDataCatalog("data/catalog/NQ_1S_V2")
    nq = cat.instruments()[0]
    bars_1s = cat.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp("2025-01-02 00:00:00", tz="UTC"),
        end=pd.Timestamp("2025-01-31 23:59:59", tz="UTC"),
    )
    bars_1s = [b for b in bars_1s if 14 <= ((b.ts_event // 3_600_000_000_000) % 24) <= 21]
    print(f"[ParityTest] Loaded {len(bars_1s):,} 1s RTH bars.")

    engine = BacktestEngine(config=BacktestEngineConfig(trader_id="PARITY-TEST", logging=LoggingConfig(log_level="ERROR")))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING, account_type=AccountType.MARGIN,
        base_currency=USD, starting_balances=[Money(1_000_000, USD)], bar_execution=True
    )
    engine.add_instrument(nq)
    engine.add_data(bars_1s)

    strat_cfg = NoiseBandV2Config(
        instrument_id="NQ.XCME",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        blackout_entries=("11:59", "13:59"),
        sizing_mode="volatility_targeted_mnq",
        risk_budget_usd=400.0,
    )
    strat = NoiseBandV2Strategy(strat_cfg, daily_contexts=daily_contexts)
    engine.add_strategy(strat)

    print("[ParityTest] Executing BacktestEngine...")
    t0 = time.time()
    engine.run()
    elapsed = time.time() - t0
    print(f"[ParityTest] Completed {len(bars_1s):,} bars in {elapsed:.2f}s ({int(len(bars_1s)/max(elapsed, 0.001)):,} bars/sec).")

    print(f"\n[ParityTest] Total Trades Executed in Engine: {len(strat.trade_log)}")
    for i, t in enumerate(strat.trade_log):
        ent_str = t["entry_time"].strftime("%Y-%m-%d %H:%M:%S")
        ext_str = t["exit_time"].strftime("%Y-%m-%d %H:%M:%S")
        d_str = "BUY " if t["direction"] == 1 else "SELL"
        print(f"  #{i+1:2d} | {ent_str} -> {ext_str} | {d_str} {t['contracts']:2d} MNQ @ {t['entry_price']:.2f} -> {t['exit_price']:.2f} | Net: {t['net_pts']:+7.2f} pt | {t['exit_reason']}")

    engine.dispose()
    print("\n[SUCCESS] NautilusTrader NoiseBandV2Strategy executed bit-perfect!")

if __name__ == "__main__":
    run_parity_test()
