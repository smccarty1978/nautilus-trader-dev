"""NQ Survivor and Position Add-On Expectancy Study.

Replays NQ 1s bars (2021-2024), aggregates to 5s & 1m, detects flips and confirmed flips.
Replays trades under V0 regime exits, tracks 14 survivor milestones, and simulates
position add-on rules (Add A-D + others) under 3 risk management variants.
Saves the results to Parquet files.
"""
from __future__ import annotations
import argparse, os, sys, time
from pathlib import Path
from collections import deque
import numpy as np
import pandas as pd
import pytz
from nautilus_trader.persistence.catalog import ParquetDataCatalog

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from collectors.collector_v2.registry import CompletedBarRegistry
from collectors.collector_v2.aggregator import TimeframeAggregator
from collectors.collector_v2.regime_engine import RegimeStateEngine

CATALOG = "data/catalog/NQ_v0_2020_2026"
BAR_TYPE = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
OUT = Path("studies/stairstep_exits/results")
CT = pytz.timezone("America/Chicago")
NS_PER_S = 1_000_000_000
TICK = 0.25
TICK_VAL = 5.0  # $5 per tick
MULT = 20.0     # $20 per point
COMMISSION = 5.0 # $5 RT per contract
TFS = ("5s", "1m")
RTH_START_MIN = 510
RTH_END_MIN = 900

def _tick_round(val: float) -> float:
    return round(val * 4) / 4.0

class SurvivorTracker:
    def __init__(self, entry_id, pop, direction, entry_px, atr, entry_ts, cat_px=None):
        self.entry_id = entry_id
        self.pop = pop
        self.d = int(direction)
        self.ep = float(entry_px)
        self.atr = float(atr)
        self.entry_ts = int(entry_ts)
        self.cat_px = float(cat_px) if cat_px is not None else None
        
        # Original catastrophic stop (only for Population A under V0)
        self.stop_px = None
        if self.cat_px is not None:
            self.stop_px = _tick_round(self.cat_px)
            if self.d == 1:
                self.stop_px = min(self.stop_px, self.ep - 0.25)
            else:
                self.stop_px = max(self.stop_px, self.ep + 0.25)
                
        self.running_mfe = 0.0
        self.running_mae = 0.0
        self._cum_abs_move = 0.0
        self._prev_close = self.ep
        
        self.exited = False
        self.exit_ts = None
        self.exit_px = None
        self.exit_reason = None
        
        # We will collect the path here!
        self.path = []
        self.milestones = {}
        self.completed_adds = []

    def on_1s(self, ts, o, h, l, c, reg5, tsi):
        if self.exited:
            return
            
        ts = int(tsi)
        
        # Append bar to path
        self.path.append((ts, float(o), float(h), float(l), float(c), int(reg5)))
        
        # Update path move
        self._cum_abs_move += abs(c - self._prev_close)
        self._prev_close = c
        
        # Excursion tracking
        if self.d == 1:
            mfe_bar = h - self.ep
            mae_bar = self.ep - l
        else:
            mfe_bar = self.ep - l
            mae_bar = h - self.ep
            
        self.running_mfe = max(self.running_mfe, mfe_bar)
        self.running_mae = max(self.running_mae, mae_bar)
        
        # Check catastrophic stop for main trade (if stop_px is set)
        if self.stop_px is not None:
            if self.d == 1:
                if l <= self.stop_px:
                    self._exit(ts, min(self.stop_px, c), "stop")
                    return
            else:
                if h >= self.stop_px:
                    self._exit(ts, max(self.stop_px, c), "stop")
                    return

    def _exit(self, ts, px, reason):
        self.exited = True
        self.exit_ts = int(ts)
        self.exit_px = float(px)
        self.exit_reason = reason

    def regime_exit(self, ts, px):
        if not self.exited:
            self._exit(ts, px, "regime")

    def force_exit(self, ts, px):
        if not self.exited:
            self._exit(ts, px, "end_of_data")

    def evaluate_milestones_and_adds(self):
        # Time-based & progress-based & path-based milestones evaluation on path
        self.milestones = {}
        self.completed_adds = []
        
        if not self.path:
            return
            
        running_mfe = 0.0
        running_mae = 0.0
        cum_abs_move = 0.0
        prev_close = self.ep
        gate30_failed = False
        gate60_failed = False
        has_opposing_5s_first_90s = False
        
        # Loop through path to identify first occurrence of each milestone
        for i, (ts, o, h, l, c, reg5) in enumerate(self.path):
            dt = (ts - self.entry_ts) / NS_PER_S
            
            cum_abs_move += abs(c - prev_close)
            prev_close = c
            
            if self.d == 1:
                mfe_bar = h - self.ep
                mae_bar = self.ep - l
            else:
                mfe_bar = self.ep - l
                mae_bar = h - self.ep
                
            running_mfe = max(running_mfe, mfe_bar)
            running_mae = max(running_mae, mae_bar)
            
            align5s = self.d * reg5
            if dt <= 90 and align5s == -1:
                has_opposing_5s_first_90s = True
                
            net = self.d * (c - self.ep)
            if dt >= 30 and dt < 31 and not gate30_failed:
                if net < 0 and align5s == -1:
                    gate30_failed = True
            if dt >= 60 and dt < 61 and not gate60_failed:
                if net < 0:
                    gate60_failed = True
                    
            # 1. Time-based
            for sec in (30, 60, 90, 120, 180):
                name = f"Alive at +{sec}s"
                if name not in self.milestones and dt >= sec:
                    self.milestones[name] = (ts, c, i)
                    
            # 2. Progress-based
            mfe_atr = running_mfe / self.atr if self.atr > 0 else 0.0
            for atr_thr in (0.25, 0.50, 0.75, 1.00, 1.50):
                name = f"Reached +{atr_thr:.2f} ATR"
                if name not in self.milestones and mfe_atr >= atr_thr:
                    self.milestones[name] = (ts, c, i)
                    
            # 3. Path-based
            # Passed V2 prove-it gate
            if "Passed V2 prove-it gate" not in self.milestones and dt >= 60:
                if not (gate30_failed or gate60_failed):
                    self.milestones["Passed V2 prove-it gate"] = (ts, c, i)
                    
            # No opposing 5s flip first 90s
            if "No opposing 5s flip first 90s" not in self.milestones and dt >= 90:
                if not has_opposing_5s_first_90s:
                    self.milestones["No opposing 5s flip first 90s"] = (ts, c, i)
                    
            # Positive path efficiency at 60s
            if "Positive path efficiency at 60s" not in self.milestones and dt >= 60:
                eff = net / cum_abs_move if cum_abs_move > 0 else 0.0
                if eff > 0.0:
                    self.milestones["Positive path efficiency at 60s"] = (ts, c, i)
                    
            # MFE > MAE at 60s
            if "MFE > MAE at 60s" not in self.milestones and dt >= 60:
                if running_mfe > running_mae:
                    self.milestones["MFE > MAE at 60s"] = (ts, c, i)
                    
        # Now evaluate adds from milestones
        for name, (ts_m, px_m, idx_m) in list(self.milestones.items()):
            # Remaining path after milestone bar
            rem_path = self.path[idx_m + 1:]
            
            # Variant 1: independent stop (1.0 ATR from milestone price)
            stop_v1 = px_m - self.d * 1.0 * self.atr
            stop_v1 = _tick_round(stop_v1)
            if self.d == 1:
                stop_v1 = min(stop_v1, px_m - 0.25)
            else:
                stop_v1 = max(stop_v1, px_m + 0.25)
                
            # Variant 3: stop both contracts at average price
            avg_px = (self.ep + px_m) / 2
            avg_stop = _tick_round(avg_px)
            if self.d == 1:
                avg_stop = min(avg_stop, px_m - 0.25)
            else:
                avg_stop = max(avg_stop, px_m + 0.25)
                
            # Evaluate Variant 1
            exit_ts_v1, exit_px_v1, exit_reason_v1 = self.exit_ts, self.exit_px, self.exit_reason
            for bar_ts, bar_o, bar_h, bar_l, bar_c, bar_reg5 in rem_path:
                if self.d == 1:
                    if bar_l <= stop_v1:
                        exit_ts_v1 = bar_ts
                        exit_px_v1 = min(stop_v1, bar_c)
                        exit_reason_v1 = "stop"
                        break
                else:
                    if bar_h >= stop_v1:
                        exit_ts_v1 = bar_ts
                        exit_px_v1 = max(stop_v1, bar_c)
                        exit_reason_v1 = "stop"
                        break
                        
            # Evaluate Variant 2 (Original Stop)
            exit_ts_v2, exit_px_v2, exit_reason_v2 = self.exit_ts, self.exit_px, self.exit_reason
            
            # Evaluate Variant 3
            exit_ts_v3, exit_px_v3, exit_reason_v3 = self.exit_ts, self.exit_px, self.exit_reason
            for bar_ts, bar_o, bar_h, bar_l, bar_c, bar_reg5 in rem_path:
                if self.d == 1:
                    if bar_l <= avg_stop:
                        exit_ts_v3 = bar_ts
                        exit_px_v3 = min(avg_stop, bar_c)
                        exit_reason_v3 = "stop"
                        break
                else:
                    if bar_h >= avg_stop:
                        exit_ts_v3 = bar_ts
                        exit_px_v3 = max(avg_stop, bar_c)
                        exit_reason_v3 = "stop"
                        break
                        
            self.completed_adds.append({
                "milestone": name, "variant": 1,
                "ts_milestone": ts_m, "px_milestone": px_m,
                "exit_ts": exit_ts_v1, "exit_px": exit_px_v1, "exit_reason": exit_reason_v1
            })
            self.completed_adds.append({
                "milestone": name, "variant": 2,
                "ts_milestone": ts_m, "px_milestone": px_m,
                "exit_ts": exit_ts_v2, "exit_px": exit_px_v2, "exit_reason": exit_reason_v2
            })
            self.completed_adds.append({
                "milestone": name, "variant": 3,
                "ts_milestone": ts_m, "px_milestone": px_m,
                "exit_ts": exit_ts_v3, "exit_px": exit_px_v3, "exit_reason": exit_reason_v3
            })
            
        # Clean up path to save memory
        self.path = None


class SurvivorReplay:
    def __init__(self):
        self._reg = CompletedBarRegistry(supported_timeframes=TFS)
        self._eng = {tf: RegimeStateEngine(tf, self._reg) for tf in TFS}
        self._agg = TimeframeAggregator(
            on_bucket_closed=lambda tf, b: self._eng[tf].on_bar_closed(b),
            timeframes=TFS)

        self._last_1m = 0
        self._prev_1m = 0
        self._pending_bar1 = None
        self._n_1m = 0
        self._entry_seq = 0
        self._open: list[SurvivorTracker] = []
        self._open_meta: dict[int, dict] = {}
        
        self.records_trades: list[dict] = []
        self.records_milestones: list[dict] = []
        self.records_adds: list[dict] = []

    def on_bar(self, o, h, l, c, v, tse, tsi):
        self._agg.on_1s_bar(int(tse), o, h, l, c, v)
        s1m = self._reg.get("1m"); s5 = self._reg.get("5s")
        reg5 = s5.regime if s5 is not None else 0
        closed_1m = s1m is not None and s1m.close_ts != self._last_1m

        if closed_1m:
            self._last_1m = s1m.close_ts
            self._n_1m += 1

        # Flip / entry detection
        new_entries = []
        if closed_1m:
            regime = s1m.regime; prev = self._prev_1m
            flipped = (regime != prev and regime != 0)
            if flipped:
                self._close_all(int(s1m.close_ts), s1m.close)
                new_entries.append(("A", regime, s1m.open))
                self._pending_bar1 = {
                    "dir": regime, "flip_h": s1m.high, "flip_l": s1m.low,
                    "flip_close_ts": s1m.close_ts}
            else:
                pb = self._pending_bar1
                if pb and s1m.open_ts == pb["flip_close_ts"] and regime == pb["dir"]:
                    conf = (regime == 1 and s1m.high > pb["flip_h"] and s1m.close > s1m.open) or \
                           (regime == -1 and s1m.low < pb["flip_l"] and s1m.close < s1m.open)
                    if conf:
                        new_entries.append(("B", regime, None))
                    self._pending_bar1 = None
                elif pb and s1m.open_ts > pb["flip_close_ts"]:
                    self._pending_bar1 = None
            self._prev_1m = regime

        for pop, d, cat in new_entries:
            self._open_entry(pop, d, o, int(tsi), s1m, cat)

        if self._open:
            still = []
            for tr in self._open:
                tr.on_1s(int(tse), o, h, l, c, reg5, tsi)
                if tr.exited:
                    self._record(tr)
                else:
                    still.append(tr)
            self._open = still

    def _open_entry(self, pop, d, entry_px, entry_ts, s1m, cat_px):
        atr = s1m.atr
        if atr is None or atr != atr or atr <= 0:
            return
        warmed = (self._n_1m >= 50)
        ct = pd.Timestamp(int(entry_ts), tz="UTC").tz_convert(CT)
        minct = ct.hour * 60 + ct.minute
        self._entry_seq += 1
        eid = self._entry_seq
        self._open_meta[eid] = {
            "entry_id": eid, "population": pop, "direction": d,
            "entry_ts": entry_ts, "entry_px": entry_px, "atr_at_entry": atr,
            "rth_flag": bool(RTH_START_MIN <= minct < RTH_END_MIN),
            "warmed_up": bool(warmed), "year": ct.year,
        }
        tr = SurvivorTracker(eid, pop, d, entry_px, atr, entry_ts, cat_px)
        self._open.append(tr)

    def _record(self, tr):
        tr.evaluate_milestones_and_adds()
        meta = self._open_meta[tr.entry_id]
        
        # 1. Record original trade outcome
        tr_rec = dict(meta)
        tr_rec.update({
            "exit_ts": tr.exit_ts,
            "exit_px": tr.exit_px,
            "exit_reason": tr.exit_reason,
            "max_mfe_pts": tr.running_mfe,
            "max_mae_pts": tr.running_mae,
            "hold_s": (tr.exit_ts - tr.entry_ts) / NS_PER_S,
        })
        self.records_trades.append(tr_rec)
        
        # 2. Record milestones (survivor states)
        for name, m_info in tr.milestones.items():
            ts_m, px_m = m_info[0], m_info[1]
            # Future MFE/MAE and remaining PnL from milestone to trade exit
            rem_pnl_pts = (tr.exit_px - px_m) * tr.d
            rem_pnl_atr = rem_pnl_pts / tr.atr
            
            self.records_milestones.append({
                "entry_id": tr.entry_id,
                "population": tr.pop,
                "direction": tr.d,
                "year": meta["year"],
                "warmed_up": meta["warmed_up"],
                "milestone": name,
                "ts_milestone": ts_m,
                "px_milestone": px_m,
                "exit_ts": tr.exit_ts,
                "exit_px": tr.exit_px,
                "exit_reason": tr.exit_reason,
                "remaining_pnl_pts": rem_pnl_pts,
                "remaining_pnl_atr": rem_pnl_atr,
            })
            
        # 3. Record simulated add-ons
        for add in tr.completed_adds:
            add_pnl_pts = (add["exit_px"] - add["px_milestone"]) * tr.d
            add_pnl_atr = add_pnl_pts / tr.atr
            
            self.records_adds.append({
                "entry_id": tr.entry_id,
                "population": tr.pop,
                "direction": tr.d,
                "year": meta["year"],
                "warmed_up": meta["warmed_up"],
                "milestone": add["milestone"],
                "variant": add["variant"],
                "ts_milestone": add["ts_milestone"],
                "px_milestone": add["px_milestone"],
                "exit_ts": add["exit_ts"],
                "exit_px": add["exit_px"],
                "exit_reason": add["exit_reason"],
                "add_pnl_pts": add_pnl_pts,
                "add_pnl_atr": add_pnl_atr,
            })

    def _close_all(self, ts, px):
        for tr in self._open:
            tr.regime_exit(ts, px)
            self._record(tr)
        self._open = []

    def finalize(self):
        s1m = self._reg.get("1m")
        if s1m is not None and self._open:
            for tr in self._open:
                tr.force_exit(s1m.close_ts, s1m.close)
                self._record(tr)
        self._open = []


def run_year(year, lead_in_days=3, smoke=0):
    t0 = time.time()
    load_start = pd.Timestamp(f"{year}-01-01", tz="UTC") - pd.Timedelta(days=lead_in_days)
    load_end = (pd.Timestamp(f"{year}-01-01", tz="UTC") + pd.Timedelta(days=smoke)
                if smoke else pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC"))
    
    print(f"Loading data for year {year}...")
    catalog = ParquetDataCatalog(CATALOG)
    bars = catalog.bars(bar_types=[BAR_TYPE], start=load_start, end=load_end)
    print(f"  loaded {len(bars):,} 1s bars ({time.time()-t0:.0f}s)")
    if not bars:
        return
        
    t0 = time.time()
    o = np.fromiter((float(b.open) for b in bars), dtype=np.float64, count=len(bars))
    h = np.fromiter((float(b.high) for b in bars), dtype=np.float64, count=len(bars))
    l = np.fromiter((float(b.low) for b in bars), dtype=np.float64, count=len(bars))
    c = np.fromiter((float(b.close) for b in bars), dtype=np.float64, count=len(bars))
    v = np.fromiter((float(b.volume) for b in bars), dtype=np.float64, count=len(bars))
    tse = np.fromiter((int(b.ts_event) for b in bars), dtype=np.int64, count=len(bars))
    tsi = np.fromiter((int(b.ts_init) for b in bars), dtype=np.int64, count=len(bars))
    del bars
    print(f"  extracted arrays ({time.time()-t0:.0f}s)")
    
    rep = SurvivorReplay()
    t0 = time.time()
    for i in range(len(c)):
        rep.on_bar(o[i], h[i], l[i], c[i], v[i], tse[i], tsi[i])
    rep.finalize()
    print(f"  replay done ({time.time()-t0:.0f}s); records={len(rep.records_trades):,}")
    
    # Filter to in-year rows
    yr0 = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    yr1 = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC").value
    
    df_t = pd.DataFrame(rep.records_trades)
    df_t = df_t[(df_t.entry_ts >= yr0) & (df_t.entry_ts <= yr1) & df_t.warmed_up].copy()
    
    # Milestones and Adds filter based on matched entry_ids
    valid_eids = set(df_t["entry_id"])
    
    df_m = pd.DataFrame(rep.records_milestones)
    if not df_m.empty:
        df_m = df_m[df_m["entry_id"].isin(valid_eids)].copy()
        
    df_a = pd.DataFrame(rep.records_adds)
    if not df_a.empty:
        df_a = df_a[df_a["entry_id"].isin(valid_eids)].copy()
        
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = f"_smoke{smoke}" if smoke else ""
    
    df_t.to_parquet(OUT / f"survivor_trades_{year}{suffix}.parquet", index=False)
    df_m.to_parquet(OUT / f"survivor_milestones_{year}{suffix}.parquet", index=False)
    df_a.to_parquet(OUT / f"survivor_adds_{year}{suffix}.parquet", index=False)
    
    print(f"  saved parquets for {year}. Trades={len(df_t):,}, Milestones={len(df_m):,}, Adds={len(df_a):,}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2021,2022,2023,2024")
    ap.add_argument("--smoke", type=int, default=0)
    args = ap.parse_args()
    
    years = [int(y) for y in args.years.split(",")]
    for y in years:
        run_year(y, smoke=args.smoke)
        
if __name__ == "__main__":
    main()
