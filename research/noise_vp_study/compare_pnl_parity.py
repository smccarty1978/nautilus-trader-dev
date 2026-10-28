"""
PnL & Trade Parity Reconciliation: Python Reference Sim vs Nautilus BacktestEngine
Location: research/noise_vp_study/compare_pnl_parity.py
"""

import sys
import time
from pathlib import Path
import pandas as pd
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from strategies.noise_band_v2_strategy import NoiseBandV2Strategy, NoiseBandV2Config, DailyContext

def run_parity_reconciliation(interval_mins: int = 30):
    print("=" * 80)
    print(f"RUNNING PARITY RECONCILIATION: STOP INTERVAL = {interval_mins} MINUTES")
    print("=" * 80)

    # 1. Load Caches
    df_bars_cache = pd.read_parquet(SCRIPT_DIR / "rth_resampled_cache.parquet")
    df_daily = pd.read_parquet(SCRIPT_DIR / "daily_context_cache.parquet")

    bars_by_date = {d: grp for d, grp in df_bars_cache.groupby("date")}

    daily_contexts = {}
    for date_val, row in df_daily.iterrows():
        date_str = str(date_val)
        bars_day = bars_by_date.get(date_val)
        if bars_day is None or len(bars_day) == 0:
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

    # 2. Load 1s & 1m bars from Catalog for January 2025
    print("[DataLoader] Loading Jan 2025 1s & 1m bars from data/catalog/NQ_1S_V2...")
    cat = ParquetDataCatalog("data/catalog/NQ_1S_V2")
    nq = cat.instruments()[0]
    bars_1s_all = cat.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp("2025-01-02 00:00:00", tz="UTC"),
        end=pd.Timestamp("2025-01-31 23:59:59", tz="UTC"),
    )
    bars_1s = [b for b in bars_1s_all if 14 <= ((b.ts_event // 3_600_000_000_000) % 24) <= 21]

    bars_1m_all = cat.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=pd.Timestamp("2025-01-02 00:00:00", tz="UTC"),
        end=pd.Timestamp("2025-01-31 23:59:59", tz="UTC"),
    )
    bars_1m = [b for b in bars_1m_all if 14 <= ((b.ts_event // 3_600_000_000_000) % 24) <= 21]
    print(f"[DataLoader] Loaded {len(bars_1s):,} 1s RTH bars and {len(bars_1m):,} 1m RTH bars.")

    # 3. Execute NautilusTrader BacktestEngine
    engine = BacktestEngine(config=BacktestEngineConfig(trader_id="PARITY-TEST", logging=LoggingConfig(log_level="ERROR")))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING, account_type=AccountType.MARGIN,
        base_currency=USD, starting_balances=[Money(1_000_000, USD)], bar_execution=True
    )
    engine.add_instrument(nq)
    engine.add_data(bars_1m)
    engine.add_data(bars_1s)

    strat_cfg = NoiseBandV2Config(
        instrument_id="NQ.XCME",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        stop_check_interval_minutes=interval_mins,
        stop_check_second=59,
        hard_stop_atr_mult=0.0,  # Pure cadence test
        blackout_entries=("11:59", "13:59"),
        sizing_mode="fixed",
        fixed_qty=1,
    )
    strat = NoiseBandV2Strategy(strat_cfg, daily_contexts=daily_contexts)
    engine.add_strategy(strat)
    print("[NautilusEngine] Running engine...")
    t0 = time.time()
    engine.run()
    print(f"[NautilusEngine] Completed in {time.time()-t0:.2f}s. Trades: {len(strat.trade_log)}")
    df_nt = pd.DataFrame(strat.trade_log)
    engine.dispose()

    # 4. Execute Python Reference Sim on the exact same catalog data
    print("[PythonSim] Running reference simulation on catalog bars...")
    p59_map = {b.ts_event: float(b.close) for b in bars_1s if (b.ts_event // 1_000_000_000) % 60 == 59}

    records_1m = []
    for b in bars_1m:
        p59_val = p59_map.get(b.ts_event + 59_000_000_000, float(b.close))
        records_1m.append({
            "ts_event": pd.Timestamp(b.ts_event, unit="ns", tz="UTC").tz_convert("America/New_York"),
            "open": float(b.open),
            "high": float(b.high),
            "low": float(b.low),
            "close": float(b.close),
            "volume": float(b.volume),
            "p_59s": p59_val,
        })
    df_cat_1m = pd.DataFrame(records_1m).set_index("ts_event")
    df_cat_1m = df_cat_1m.between_time("09:30:00", "16:00:00")

    all_cat_1m = []
    for d, grp in df_cat_1m.groupby(df_cat_1m.index.date):
        grp = grp.copy()
        cum_vol = grp["volume"].cumsum()
        cum_vp = (((grp["high"] + grp["low"] + grp["close"]) / 3.0) * grp["volume"]).cumsum()
        grp["vwap"] = cum_vp / np.maximum(cum_vol, 1.0)
        grp["date"] = str(d)
        grp["minute_idx"] = (grp.index.hour * 60 + grp.index.minute) - (9 * 60 + 30)
        all_cat_1m.append(grp)
    df_ref_1m = pd.concat(all_cat_1m)

    TICK_SIZE = 0.25
    COMMISSION_NQ_RT = 4.50
    POINT_VALUE = 20.0
    slip_side = 1 * TICK_SIZE
    comm_side = (COMMISSION_NQ_RT / POINT_VALUE) / 2.0
    t_start = pd.to_datetime("09:59:00").time()
    t_end = pd.to_datetime("15:29:00").time()

    sim_trades = []
    for d, day in df_ref_1m.groupby("date"):
        ctx = daily_contexts.get(str(d))
        if ctx is None:
            continue
        day_bars = list(day.itertuples(name="Bar"))
        pos = 0
        entry_p = 0.0
        entry_t = None
        for bar in day_bars:
            ts = bar.Index
            t_val = ts.time()
            min_val = ts.minute
            is_entry_chk = (min_val in (29, 59)) and (t_start <= t_val <= t_end)

            if interval_mins == 30:
                is_stop_mark = min_val in (29, 59)
            elif interval_mins == 15:
                is_stop_mark = min_val in (14, 29, 44, 59)
            elif interval_mins == 5:
                is_stop_mark = (min_val % 5 == 4)
            else:
                is_stop_mark = True

            eval_p = bar.p_59s
            upper, lower = ctx.get_bands(bar.minute_idx, 1.0)
            vwap = bar.vwap
            poc = ctx.prev_poc
            vah = ctx.prev_vah
            val = ctx.prev_val
            atr = 15.0

            if pos == 1:
                if is_stop_mark and eval_p < max(upper, vwap):
                    exit_p = eval_p - slip_side
                    gross = exit_p - entry_p
                    net = gross - (slip_side + 2 * comm_side)
                    sim_trades.append({"entry_time": entry_t, "exit_time": ts, "direction": 1, "entry_p": entry_p, "exit_p": exit_p, "net_pts": net, "reason": "TrailingStop"})
                    pos = 0
            elif pos == -1:
                if is_stop_mark and eval_p > min(lower, vwap):
                    exit_p = eval_p + slip_side
                    gross = entry_p - exit_p
                    net = gross - (slip_side + 2 * comm_side)
                    sim_trades.append({"entry_time": entry_t, "exit_time": ts, "direction": -1, "entry_p": entry_p, "exit_p": exit_p, "net_pts": net, "reason": "TrailingStop"})
                    pos = 0

            if pos == 0 and is_entry_chk:
                if (ts.hour == 11 and min_val == 59) or (ts.hour == 13 and min_val == 59):
                    continue
                if eval_p > upper and eval_p > vwap:
                    if (eval_p > vah) or (eval_p < val and (poc - eval_p >= 1.5 * atr)):
                        pos = 1
                        entry_p = eval_p + slip_side
                        entry_t = ts
                elif eval_p < lower and eval_p < vwap:
                    if (eval_p < val) or (eval_p > vah and (eval_p - poc >= 1.5 * atr)):
                        pos = -1
                        entry_p = eval_p - slip_side
                        entry_t = ts

        if pos != 0:
            eod_p = day_bars[-1].close
            exit_p = eod_p - slip_side if pos == 1 else eod_p + slip_side
            gross = (exit_p - entry_p) * pos
            net = gross - (slip_side + 2 * comm_side)
            sim_trades.append({"entry_time": entry_t, "exit_time": day_bars[-1].Index, "direction": pos, "entry_p": entry_p, "exit_p": exit_p, "net_pts": net, "reason": "EOD_Flat"})

    df_sim = pd.DataFrame(sim_trades)
    print(f"[PythonSim] Completed. Trades: {len(df_sim)}")

    # 5. Output Reconciliation Table
    sim_pts = df_sim["net_pts"].sum()
    nt_pts = df_nt["net_pts"].sum()
    print("\n" + "=" * 80)
    print("PARITY RECONCILIATION SUMMARY (JANUARY 2025)")
    print("=" * 80)
    print(f"Python Reference Trades: {len(df_sim)} | Total Net: {sim_pts:+8.2f} pt (${sim_pts*20:+9,.2f})")
    print(f"Nautilus Engine Trades:  {len(df_nt)} | Total Net: {nt_pts:+8.2f} pt (${nt_pts*20:+9,.2f})")
    print(f"Delta:                   {len(df_nt)-len(df_sim):+2d} trades | Net Pts Diff: {nt_pts-sim_pts:+6.2f} pt")
    print("=" * 80)

    print("\nTrade-by-Trade Alignment:")
    df_sim["entry_str"] = df_sim["entry_time"].dt.strftime("%Y-%m-%d %H:%M")
    df_nt["entry_str"] = df_nt["entry_time"].dt.strftime("%Y-%m-%d %H:%M")
    nt_dict = {r["entry_str"]: r for _, r in df_nt.iterrows()}

    for i, s in df_sim.iterrows():
        t_key = s["entry_str"]
        nt = nt_dict.get(t_key)
        if nt is not None:
            diff = nt["net_pts"] - s["net_pts"]
            print(f"  #{i+1:2d} | Matched {t_key} | Sim: {s['net_pts']:+7.2f} pt ({s['reason']:12s}) | NT: {nt['net_pts']:+7.2f} pt ({nt['exit_reason']:12s}) | Diff: {diff:+5.2f} pt")
        else:
            print(f"  #{i+1:2d} | Sim Only {t_key} | Sim: {s['net_pts']:+7.2f} pt ({s['reason']:12s}) | NT: No Trade")

    sim_keys = set(df_sim["entry_str"])
    for _, nt in df_nt.iterrows():
        if nt["entry_str"] not in sim_keys:
            print(f"       | NT Only  {nt['entry_str']} | NT: {nt['net_pts']:+7.2f} pt ({nt['exit_reason']:12s}) | Sim: No Trade")

if __name__ == "__main__":
    run_parity_reconciliation(interval_mins=30)

