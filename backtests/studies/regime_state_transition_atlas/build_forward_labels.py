"""NQ Regime State Transition Atlas - Forward Labels Collector.

Replays NQ 1s bars (2021-2026), tracks 1m parent regimes, and evaluates forward
labels (races, excursions, transitions) starting from the next executable point
after each 1m bar close.
"""
from __future__ import annotations
import argparse
import os
import sys
import time
from collections import deque
from pathlib import Path
import numpy as np
import pandas as pd
from nautilus_trader.persistence.catalog import ParquetDataCatalog

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from collectors.collector_v2.registry import CompletedBarRegistry, CompletedBarState
from collectors.collector_v2.aggregator import TimeframeAggregator, _OpenBucket
from collectors.collector_v2.regime_engine import RegimeStateEngine

CATALOG = "data/catalog/NQ_v0_2020_2026"
BAR_TYPE = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
OUT = Path("studies/regime_state_transition_atlas/results")
NS_PER_S = 1_000_000_000
MULT = 20.0
TFS = ("5m", "1m", "5s")


class ForwardLabelsReplay:
    def __init__(self, year: int):
        self._year = year
        self._reg = CompletedBarRegistry(supported_timeframes=TFS)
        self._engines = {tf: RegimeStateEngine(tf, self._reg) for tf in TFS}
        self._agg = TimeframeAggregator(
            on_bucket_closed=self.on_bucket_closed,
            timeframes=TFS
        )
        
        self._prev_regimes = {tf: 0 for tf in TFS}
        
        # 1m parent regime tracking
        self._active_1m_regime = 0
        self._ts_1m_regime_start = 0
        self._px_1m_entry = 0.0
        self._atr_1m_entry_cached = 1.0
        self._1m_regime_id = 0
        self._1m_regime_index = 0
        self._bar_index = 0
        
        self._1m_regime_high = 0.0
        self._1m_regime_low = 0.0
        self._1m_regime_high_prior = 0.0
        self._1m_regime_low_prior = 0.0
        
        self._active_checkpoints = []
        self._pending_exit = []
        self.records = []

        self._regime_flipped_flag = False
        self._prev_regime_dir = 0

    def on_bucket_closed(self, tf: str, completed: _OpenBucket):
        self._engines[tf].on_bar_closed(completed)
        
        state = self._reg.get(tf)
        if state is None:
            return
            
        now = state.regime
        prev = self._prev_regimes[tf]
        flipped = (now != prev and now != 0)
        
        if tf == "1m":
            if flipped:
                self._regime_flipped_flag = True
                self._prev_regime_dir = prev
                
                # Reset new 1m regime
                self._active_1m_regime = now
                self._ts_1m_regime_start = state.close_ts
                self._px_1m_entry = state.close
                self._atr_1m_entry_cached = state.atr if (state.atr > 0 and not np.isnan(state.atr)) else 1.0
                self._1m_regime_index += 1
                self._1m_regime_id = self._year * 100_000 + self._1m_regime_index
                self._bar_index = 0
                
                self._1m_regime_high = state.close
                self._1m_regime_low = state.close
                self._1m_regime_high_prior = state.close
                self._1m_regime_low_prior = state.close
            else:
                if self._active_1m_regime != 0:
                    self._bar_index += 1
                    
                    # Snap checkpoint for evaluation before updating prior variables for next bar
                    if self._bar_index <= 30:
                        self._active_checkpoints.append({
                            "regime_id": self._1m_regime_id,
                            "bar_index_in_regime": self._bar_index,
                            "direction": self._active_1m_regime,
                            "entry_ts": self._ts_1m_regime_start,
                            "entry_px": self._px_1m_entry,
                            "bar_ts": completed.close_ts,
                            "checkpoint_px": completed.close,
                            "atr_1m_entry": self._atr_1m_entry_cached,
                            "path": [],
                            "checkpoint_high_actual": max(self._1m_regime_high_prior, completed.high) if self._active_1m_regime == 1 else completed.high,
                            "checkpoint_low_actual": min(self._1m_regime_low_prior, completed.low) if self._active_1m_regime == -1 else completed.low
                        })
                        
                    # Update prior variables for the next bar
                    d = self._active_1m_regime
                    if d == 1:
                        if completed.high > self._1m_regime_high_prior:
                            self._1m_regime_high_prior = completed.high
                    else:
                        if completed.low < self._1m_regime_low_prior:
                            self._1m_regime_low_prior = completed.low
                            
        self._prev_regimes[tf] = now

    def on_1s(self, o, h, l, c, v, tse, tsi):
        self._regime_flipped_flag = False
        self._prev_regime_dir = 0
        
        self._agg.on_1s_bar(int(tsi), o, h, l, c, v)
        
        ts = int(tsi)

        if self._active_1m_regime != 0:
            self._1m_regime_high = max(self._1m_regime_high, h)
            self._1m_regime_low = min(self._1m_regime_low, l)

        s1m = self._reg.get("1m")
        reg_1m = s1m.regime if s1m is not None else 0

        # (A) Resolve checkpoints queued for exit by the PRIOR bar's flip. The
        # causal regime-exit fill is the OPEN of THIS bar — the first executable
        # price strictly after the flip was confirmed at the prior bar's close.
        # (Audit v5 fix: previously exited at the flip bar's own open, ~1s of
        # look-ahead.)
        if self._pending_exit:
            for cp in self._pending_exit:
                cp["path"].append((ts, o, h, l, c, reg_1m))
                self.evaluate_checkpoint(cp, exit_ts=ts, exit_px=o)
            self._pending_exit = []

        # (B) On a fresh 1m flip, queue OLD-regime checkpoints to exit at the
        # NEXT bar's open (resolved in branch A on the following 1s bar).
        if self._regime_flipped_flag and self._active_checkpoints:
            still_active = []
            for cp in self._active_checkpoints:
                if cp["direction"] == self._prev_regime_dir:
                    cp["path"].append((ts, o, h, l, c, -cp["direction"]))
                    self._pending_exit.append(cp)
                else:
                    still_active.append(cp)
            self._active_checkpoints = still_active

        # (C) Accumulate the forward path for still-active checkpoints.
        for cp in self._active_checkpoints:
            cp["path"].append((ts, o, h, l, c, reg_1m))

    def evaluate_checkpoint(self, cp, exit_ts=None, exit_px=None):
        path = cp["path"]
        if not path:
            return
            
        d = cp["direction"]
        checkpoint_ts = cp["bar_ts"]
        checkpoint_px = cp["checkpoint_px"]
        atr = cp["atr_1m_entry"]
        if np.isnan(atr) or atr <= 0:
            atr = 1.0
            
        checkpoint_high_actual = cp["checkpoint_high_actual"]
        checkpoint_low_actual = cp["checkpoint_low_actual"]
        
        # Define triggering bar threshold to exclude it from path and next bar logic
        trigger_cutoff = checkpoint_ts + 1 * NS_PER_S
        
        # 1. Extract next executable fill price (the open price of the second 1s bar of the new minute)
        # Note: the first 1s bar of the new period starts at checkpoint_ts and closes at checkpoint_ts + 1s.
        # The next executable fill is at the open of the second 1s bar of the period (which is at checkpoint_ts + 1s).
        next_1m_ticks_all = [b for b in path if b[0] > checkpoint_ts and b[0] <= checkpoint_ts + 60 * NS_PER_S]
        if next_1m_ticks_all:
            next_1s_open = next_1m_ticks_all[1][1] if len(next_1m_ticks_all) > 1 else next_1m_ticks_all[0][1]
        else:
            next_1s_open = checkpoint_px
            
        # Use next_1s_open as the baseline price for all return, race, and MFE/MAE calculations
        base_px = next_1s_open
        
        # 2. next_bar_makes_continuation & other next-bar labels (excluding the triggering bar)
        next_1m_ticks = [b for b in path if b[0] > trigger_cutoff and b[0] <= checkpoint_ts + 60 * NS_PER_S]
        if next_1m_ticks:
            next_high = max(b[2] for b in next_1m_ticks)
            next_low = min(b[3] for b in next_1m_ticks)
            next_close = next_1m_ticks[-1][4]
            
            if d == 1:
                next_bar_makes_continuation = int(next_high > checkpoint_high_actual)
                next_bar_close_positive = int(next_close > base_px)
                next_bar_return = (next_close - base_px) / atr
                next_bar_recovers_prior_peak = int(next_high >= checkpoint_high_actual)
            else:
                next_bar_makes_continuation = int(next_low < checkpoint_low_actual)
                next_bar_close_positive = int(next_close < base_px)
                next_bar_return = (base_px - next_close) / atr
                next_bar_recovers_prior_peak = int(next_low <= checkpoint_low_actual)
            next_bar_range = (next_high - next_low) / atr
        else:
            next_bar_makes_continuation = 0
            next_bar_close_positive = 0
            next_bar_return = 0.0
            next_bar_recovers_prior_peak = 0
            next_bar_range = 0.0
            
        # 3. Next-N-Bar Labels (N in 2, 3, 5) (excluding the triggering bar)
        n_labels = {}
        for N in (2, 3, 5):
            ticks_N = [b for b in path if b[0] > trigger_cutoff and b[0] <= checkpoint_ts + N * 60 * NS_PER_S]
            if ticks_N:
                max_h_N = max(b[2] for b in ticks_N)
                min_l_N = min(b[3] for b in ticks_N)
                close_N = ticks_N[-1][4]
                
                if d == 1:
                    n_makes_c = int(max_h_N > checkpoint_high_actual)
                    n_recover = int(max_h_N >= checkpoint_high_actual)
                    n_net_pos = int(close_N > base_px)
                    n_max_fav = (max_h_N - base_px) / atr
                    n_max_adv = (base_px - min_l_N) / atr
                else:
                    n_makes_c = int(min_l_N < checkpoint_low_actual)
                    n_recover = int(min_l_N <= checkpoint_low_actual)
                    n_net_pos = int(close_N < base_px)
                    n_max_fav = (base_px - min_l_N) / atr
                    n_max_adv = (max_h_N - base_px) / atr
            else:
                n_makes_c = 0
                n_recover = 0
                n_net_pos = 0
                n_max_fav = 0.0
                n_max_adv = 0.0
                
            n_labels[f"next_{N}_bars_make_continuation"] = np.int8(n_makes_c)
            n_labels[f"next_{N}_bars_recover_prior_peak"] = np.int8(n_recover)
            n_labels[f"next_{N}_bars_net_positive"] = np.int8(n_net_pos)
            n_labels[f"next_{N}_bars_max_favorable_atr"] = np.float32(n_max_fav)
            n_labels[f"next_{N}_bars_max_adverse_atr"] = np.float32(n_max_adv)

        # 3b. Short & Medium Horizon MFE / MAE Labels (excluding the triggering bar)
        horizon_labels = {}
        for N in (1, 2, 3, 5, 10):
            ticks_N = [b for b in path if b[0] > trigger_cutoff and b[0] <= checkpoint_ts + N * 60 * NS_PER_S]
            if ticks_N:
                max_h_N = max(b[2] for b in ticks_N)
                min_l_N = min(b[3] for b in ticks_N)
                if d == 1:
                    mfe_N = (max_h_N - base_px) / atr
                    mae_N = (base_px - min_l_N) / atr
                else:
                    mfe_N = (base_px - min_l_N) / atr
                    mae_N = (max_h_N - base_px) / atr
            else:
                mfe_N = 0.0
                mae_N = 0.0
                
            horizon_labels[f"future_mfe_{N}_bar_atr"] = np.float32(mfe_N)
            horizon_labels[f"future_mae_{N}_bar_atr"] = np.float32(mae_N)
            
        # 4. First-Passage Races (Standard) (excluding the triggering bar)
        race_labels = {}
        for target_mult, br_name in [(0.25, "025"), (0.50, "050"), (1.00, "100"), (2.00, "200")]:
            pt_mult = target_mult
            sl_mult = 1.00 if target_mult == 2.00 else target_mult
            
            pt_px = base_px + d * pt_mult * atr
            sl_px = base_px - d * sl_mult * atr
            
            race_exit_px = None
            race_exit_ts = None
            race_exit_reason = None
            
            for ts, o, h, l, c, reg1m in path:
                if ts <= trigger_cutoff:
                    continue
                if reg1m == -d or reg1m == 0:
                    race_exit_px = o
                    race_exit_ts = ts
                    race_exit_reason = "opposite_1m_regime"
                    break
                    
                if d == 1:
                    if l <= sl_px and h >= pt_px:
                        race_exit_px = sl_px
                        race_exit_ts = ts
                        race_exit_reason = "sl"
                        break
                    elif l <= sl_px:
                        race_exit_px = sl_px
                        race_exit_ts = ts
                        race_exit_reason = "sl"
                        break
                    elif h >= pt_px:
                        race_exit_px = pt_px
                        race_exit_ts = ts
                        race_exit_reason = "pt"
                        break
                else:
                    if h >= sl_px and l <= pt_px:
                        race_exit_px = sl_px
                        race_exit_ts = ts
                        race_exit_reason = "sl"
                        break
                    elif h >= sl_px:
                        race_exit_px = sl_px
                        race_exit_ts = ts
                        race_exit_reason = "sl"
                        break
                    elif l <= pt_px:
                        race_exit_px = pt_px
                        race_exit_ts = ts
                        race_exit_reason = "pt"
                        break
                        
            if race_exit_px is None:
                # Fallback to last tick after trigger_cutoff if possible
                valid_ticks = [b for b in path if b[0] > trigger_cutoff]
                if valid_ticks:
                    race_exit_px = valid_ticks[-1][4]
                    race_exit_ts = valid_ticks[-1][0]
                else:
                    race_exit_px = path[-1][4]
                    race_exit_ts = path[-1][0]
                race_exit_reason = "end_of_data"
                
            pnl_pts = (race_exit_px - base_px) * d
            pnl_usd = pnl_pts * MULT
            comm = 5.0
            slip = 0.0 if race_exit_reason == "pt" else 2.50
            net_ev = pnl_usd - (comm + slip)
            
            pt_hit = int(race_exit_reason == "pt")
            race_labels[f"pt{br_name}_before_sl{br_name}"] = np.int8(pt_hit)
            race_labels[f"net_ev_{br_name}_primary"] = np.float32(net_ev)
            
            if target_mult == 0.50:
                race_labels["race_resolution_time_s"] = np.float32((race_exit_ts - checkpoint_ts) / NS_PER_S)
                race_labels["race_resolution_reason"] = race_exit_reason

        # 4b. Small-Race Labels (excluding the triggering bar)
        small_race_labels = {}
        for pt_mult, sl_mult, name in [(0.25, 0.15, "pt025_before_sl015"), 
                                       (0.50, 0.25, "pt050_before_sl025"), 
                                       (0.75, 0.35, "pt075_before_sl035"), 
                                       (1.00, 0.50, "pt100_before_sl050")]:
            pt_px = base_px + d * pt_mult * atr
            sl_px = base_px - d * sl_mult * atr
            
            race_exit_px = None
            race_exit_ts = None
            race_exit_reason = None
            
            for ts, o, h, l, c, reg1m in path:
                if ts <= trigger_cutoff:
                    continue
                if reg1m == -d or reg1m == 0:
                    race_exit_px = o
                    race_exit_ts = ts
                    race_exit_reason = "opposite_1m_regime"
                    break
                    
                if d == 1:
                    if l <= sl_px and h >= pt_px:
                        race_exit_px = sl_px
                        race_exit_ts = ts
                        race_exit_reason = "sl"
                        break
                    elif l <= sl_px:
                        race_exit_px = sl_px
                        race_exit_ts = ts
                        race_exit_reason = "sl"
                        break
                    elif h >= pt_px:
                        race_exit_px = pt_px
                        race_exit_ts = ts
                        race_exit_reason = "pt"
                        break
                else:
                    if h >= sl_px and l <= pt_px:
                        race_exit_px = sl_px
                        race_exit_ts = ts
                        race_exit_reason = "sl"
                        break
                    elif h >= sl_px:
                        race_exit_px = sl_px
                        race_exit_ts = ts
                        race_exit_reason = "sl"
                        break
                    elif l <= pt_px:
                        race_exit_px = pt_px
                        race_exit_ts = ts
                        race_exit_reason = "pt"
                        break
                        
            if race_exit_px is None:
                valid_ticks = [b for b in path if b[0] > trigger_cutoff]
                if valid_ticks:
                    race_exit_px = valid_ticks[-1][4]
                    race_exit_ts = valid_ticks[-1][0]
                else:
                    race_exit_px = path[-1][4]
                    race_exit_ts = path[-1][0]
                race_exit_reason = "end_of_data"
                
            pnl_pts = (race_exit_px - base_px) * d
            pnl_usd = pnl_pts * MULT
            comm = 5.0
            slip = 0.0 if race_exit_reason == "pt" else 2.50
            net_ev = pnl_usd - (comm + slip)
            
            pt_hit = int(race_exit_reason == "pt")
            small_race_labels[f"{name}"] = np.int8(pt_hit)
            small_race_labels[f"net_ev_{name.replace('_before_sl', '_sl')}"] = np.float32(net_ev)
                
        # 5. Regime-End Labels (excluding the triggering bar)
        regime_exit_px = exit_px if exit_px is not None else path[-1][4]
        regime_exit_ts = exit_ts if exit_ts is not None else path[-1][0]
        
        forward_pnl_atr = (regime_exit_px - base_px) * d / atr
        forward_pnl_usd = forward_pnl_atr * atr * MULT
        
        path_valid = [b for b in path if b[0] > trigger_cutoff]
        if path_valid:
            max_h_path = max(b[2] for b in path_valid)
            min_l_path = min(b[3] for b in path_valid)
        else:
            max_h_path = base_px
            min_l_path = base_px
            
        if d == 1:
            future_mfe = (max_h_path - base_px) / atr
            future_mae = (base_px - min_l_path) / atr
        else:
            future_mfe = (base_px - min_l_path) / atr
            future_mae = (max_h_path - base_px) / atr
            
        bars_remaining = int((regime_exit_ts - checkpoint_ts) / (60 * NS_PER_S))
        
        rem_eff_denom = future_mfe + future_mae
        rem_efficiency = future_mfe / rem_eff_denom if rem_eff_denom > 1e-9 else 0.0
        rem_ratio = future_mfe / future_mae if future_mae > 1e-9 else 0.0
        
        opportunity_labels = {
            "remaining_regime_mfe_atr": np.float32(future_mfe),
            "remaining_regime_mae_atr": np.float32(future_mae),
            "remaining_regime_duration_bars": np.int16(bars_remaining),
            "remaining_regime_efficiency": np.float32(rem_efficiency),
            "remaining_regime_mfe_mae_ratio": np.float32(rem_ratio)
        }
        
        rec = {
            "regime_id": np.int64(cp["regime_id"]),
            "bar_ts": np.int64(cp["bar_ts"]),
            
            "next_bar_makes_continuation": np.int8(next_bar_makes_continuation),
            "next_bar_close_positive": np.int8(next_bar_close_positive),
            "next_bar_return_atr": np.float32(next_bar_return),
            "next_bar_recovers_prior_peak": np.int8(next_bar_recovers_prior_peak),
            "next_1s_open": np.float32(next_1s_open),
            
            "forward_pnl_to_regime_exit_atr": np.float32(forward_pnl_atr),
            "forward_pnl_to_regime_exit_dollars": np.float32(forward_pnl_usd),
            "future_mfe_from_here_atr": np.float32(future_mfe),
            "future_mae_from_here_atr": np.float32(future_mae),
            "regime_exit_in_next_1_bar": np.int8(int(bars_remaining == 1)),
            "regime_exit_in_next_2_bars": np.int8(int(bars_remaining <= 2)),
            "regime_exit_in_next_3_bars": np.int8(int(bars_remaining <= 3)),
            "remaining_regime_bars": np.int16(bars_remaining)
        }
        rec.update(n_labels)
        rec.update(horizon_labels)
        rec.update(race_labels)
        rec.update(small_race_labels)
        rec.update(opportunity_labels)
        self.records.append(rec)

    def finalize(self):
        for cp in self._pending_exit:
            if cp["path"]:
                self.evaluate_checkpoint(cp, exit_ts=cp["path"][-1][0], exit_px=cp["path"][-1][4])
        self._pending_exit = []
        for cp in self._active_checkpoints:
            if cp["path"]:
                self.evaluate_checkpoint(cp, exit_ts=cp["path"][-1][0], exit_px=cp["path"][-1][4])
        self._active_checkpoints = []


def run_year(year, lead_in_days=5, smoke=0):
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
    
    rep = ForwardLabelsReplay(year)
    t0 = time.time()
    for i in range(len(c)):
        rep.on_1s(o[i], h[i], l[i], c[i], v[i], tse[i], tsi[i])
    rep.finalize()
    print(f"  replay done ({time.time()-t0:.0f}s); checkpoints={len(rep.records):,}")
    
    yr0 = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    yr1 = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC").value
    
    df_rec = pd.DataFrame(rep.records)
    if df_rec.empty:
        print(f"No checkpoints recorded for {year}")
        return
        
    df_rec = df_rec[(df_rec.bar_ts >= yr0) & (df_rec.bar_ts <= yr1)].copy()
    
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = f"_smoke{smoke}" if smoke else ""
    df_rec.to_parquet(OUT / f"forward_labels_{year}{suffix}.parquet", index=False)
    print(f"  saved parquet for {year}. Rows={len(df_rec):,}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2021,2022,2023,2024,2025,2026")
    ap.add_argument("--smoke", type=int, default=0)
    args = ap.parse_args()
    
    years = [int(y) for y in args.years.split(",")]
    for y in years:
        run_year(y, smoke=args.smoke)
        
    # Combine parquets
    if not args.smoke:
        list_df = []
        for y in years:
            f = OUT / f"forward_labels_{y}.parquet"
            if f.exists():
                list_df.append(pd.read_parquet(f))
        if list_df:
            combined = pd.concat(list_df, ignore_index=True)
            combined.to_parquet(OUT / "forward_labels.parquet", index=False)
            print(f"Combined parquets saved to results/forward_labels.parquet. Size={len(combined):,}")


if __name__ == "__main__":
    main()
