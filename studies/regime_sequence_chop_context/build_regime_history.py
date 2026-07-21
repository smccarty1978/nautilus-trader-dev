import numpy as np
import pandas as pd
from pathlib import Path

def get_session_start(ts: pd.Timestamp) -> pd.Timestamp:
    """Return the CME session start (17:00 CT of trading day) for a given UTC timestamp."""
    ct = ts.tz_convert("America/Chicago")
    if ct.time() >= pd.Timestamp("17:00:00").time():
        start_ct = ct.normalize() + pd.Timedelta(hours=17)
    else:
        start_ct = ct.normalize() - pd.Timedelta(days=1) + pd.Timedelta(hours=17)
    return start_ct.tz_convert("UTC")


def build_completed_regimes(df_1m: pd.DataFrame, df_1s: pd.DataFrame) -> pd.DataFrame:
    """Extract completed 1m regimes from reconstructed 1m regime engine results."""
    # Flips occur when regime changes and is not 0
    df_1m = df_1m.copy()
    df_1m['prev_regime'] = df_1m['regime'].shift(1).fillna(0).astype(int)
    
    # A flip occurs at the close_ts of the bar where the regime changed
    flips = df_1m[(df_1m['regime'] != 0) & (df_1m['prev_regime'] != 0) & (df_1m['regime'] != df_1m['prev_regime'])].copy()
    
    # Convert df_1s index to Int64 once for fast slicing
    df_1s_ns = df_1s.copy()
    if isinstance(df_1s_ns.index, pd.DatetimeIndex):
        df_1s_ns.index = df_1s_ns.index.view(np.int64)
        
    regimes = []
    flip_rows = list(flips.itertuples())
    
    for i in range(len(flip_rows) - 1):
        r1 = flip_rows[i]
        r2 = flip_rows[i+1]
        
        direction = int(r1.regime)
        start_ts = int(r1.close_ts)
        end_ts = int(r2.close_ts)
        
        # Get 1s bars during this regime: (start_ts, end_ts]
        # Causal: since the regime ends at end_ts, all bars up to end_ts are completed
        bars_1s = df_1s_ns.loc[start_ts + 1000000 : end_ts]
        if len(bars_1s) == 0:
            continue
            
        start_price = float(bars_1s.iloc[0]['open'])
        end_price = float(bars_1s.iloc[-1]['close'])
        net_aligned_move = direction * (end_price - start_price)
        
        closes = bars_1s['close'].values
        highs = bars_1s['high'].values
        lows = bars_1s['low'].values
        vols = bars_1s['volume'].values
        
        mfe = float(np.max(highs - start_price) if direction == 1 else np.max(start_price - lows))
        mae = float(np.max(start_price - lows) if direction == 1 else np.max(highs - start_price))
        
        # Ranges
        rng = float(np.max(highs) - np.min(lows))
        
        # Efficiency
        diffs = np.abs(np.diff(closes))
        total_abs_move = float(np.sum(diffs)) if len(diffs) > 0 else 1e-8
        dir_efficiency = net_aligned_move / total_abs_move if total_abs_move > 0 else 0.0
        
        # Extremes
        fav_extremes = 0
        adv_extremes = 0
        if direction == 1:
            running_max = -np.inf
            running_min = np.inf
            for h in highs:
                if h > running_max:
                    running_max = h
                    fav_extremes += 1
            for l in lows:
                if l < running_min:
                    running_min = l
                    adv_extremes += 1
        else:
            running_max = -np.inf
            running_min = np.inf
            for l in lows:
                if l < running_min:
                    running_min = l
                    fav_extremes += 1
            for h in highs:
                if h > running_max:
                    running_max = h
                    adv_extremes += 1
                    
        regime_center = float(np.median(closes))
        volume = float(np.sum(vols))
        
        regimes.append({
            "regime_index": i,
            "direction": direction,
            "start_time": start_ts,
            "end_time": end_ts,
            "duration": (end_ts - start_ts) / 1e9, # seconds
            "start_price": start_price,
            "end_price": end_price,
            "net_aligned_move": net_aligned_move,
            "MFE": mfe,
            "MAE": mae,
            "range": rng,
            "directional_efficiency": dir_efficiency,
            "volume": volume,
            "regime_center": regime_center,
            "fav_extremes": fav_extremes,
            "adv_extremes": adv_extremes,
        })
        
    return pd.DataFrame(regimes)
