import numpy as np
import pandas as pd
from pathlib import Path
import json

def compute_rolling_slopes(series: pd.Series, window_s: int) -> pd.Series:
    """Compute rolling OLS slope over window_s using fast cumulative sums."""
    N = window_s
    y = series.values
    n_rows = len(y)
    
    # Pre-compute cumulative sums
    C_y = np.cumsum(y)
    C_jy = np.cumsum(y * np.arange(n_rows))
    
    sum_y = np.empty(n_rows)
    sum_y[:N-1] = np.nan
    sum_y[N-1] = C_y[N-1]
    sum_y[N:] = C_y[N:] - C_y[:-N]
    
    sum_jy = np.empty(n_rows)
    sum_jy[:N-1] = np.nan
    sum_jy[N-1] = C_jy[N-1]
    sum_jy[N:] = C_jy[N:] - C_jy[:-N]
    
    i_arr = np.arange(n_rows)
    sum_ty = sum_jy - (i_arr - N + 1) * sum_y
    
    num = N * sum_ty - (N * (N - 1) / 2.0) * sum_y
    den = N**2 * (N**2 - 1) / 12.0
    slope = num / den
    
    return pd.Series(slope, index=series.index)


def compute_crossing_behavior(price: pd.Series, center: pd.Series, window_s: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Compute crossing count and fraction of time on favorable/adverse side.
    
    A cross occurs when sign of (price - center) changes.
    """
    diff = price - center
    sign = np.sign(diff)
    # Forward fill 0s so they don't count as double crosses
    sign_no_zero = pd.Series(sign).replace(0, method='ffill').values
    cross = np.diff(sign_no_zero) != 0
    cross = np.insert(cross, 0, False)
    
    # Rolling sum of crosses
    cross_series = pd.Series(cross, index=price.index)
    cross_count = cross_series.rolling(window_s).sum()
    
    # Fraction of time favorable (>0) and adverse (<0)
    fav = (sign > 0).astype(float)
    adv = (sign < 0).astype(float)
    
    fav_frac = fav.rolling(window_s).mean()
    adv_frac = adv.rolling(window_s).mean()
    
    return cross_count, fav_frac, adv_frac


def build_median_centers_df(df_1s: pd.DataFrame) -> pd.DataFrame:
    """Compute all Phase 1 median center features on the 1s DataFrame.
    
    Requires columns: 'close', 'high', 'low', 'atr', 'regime' (merged from 1m).
    """
    df = df_1s.copy()
    
    print("  Calculating rolling medians...")
    df['median_center_5m'] = df['close'].rolling(300, min_periods=1).median()
    df['median_center_15m'] = df['close'].rolling(900, min_periods=1).median()
    df['median_center_30m'] = df['close'].rolling(1800, min_periods=1).median()
    df['median_center_60m'] = df['close'].rolling(3600, min_periods=1).median()
    
    # Sensitivity calculation: completed 5s closes
    # Resample 1s close to 5s (taking last close in 5s)
    # We do a rolling median of 5s closes and forward fill back to 1s to compare
    print("  Calculating 5s sampling sensitivity...")
    df_5s = df['close'].resample('5s').last().ffill()
    df['median_center_5m_5s_sampled'] = df_5s.rolling(60, min_periods=1).median().reindex(df.index, method='ffill')
    
    # Distances to centers
    print("  Calculating relative price-to-center distances...")
    # direction-aligned, atr-normalized
    # direction is df['regime'] (+1 or -1)
    d = df['regime'].fillna(0).astype(int)
    atr = df['atr'].fillna(1.0)
    
    df['aligned_price_minus_center_5m'] = d * (df['close'] - df['median_center_5m']) / atr
    df['aligned_price_minus_center_15m'] = d * (df['close'] - df['median_center_15m']) / atr
    df['aligned_price_minus_center_30m'] = d * (df['close'] - df['median_center_30m']) / atr
    
    # Slopes
    print("  Calculating rolling slopes...")
    # 5m slope over 1m (60s), 3m (180s), 5m (300s)
    df['slope_5m_1m'] = compute_rolling_slopes(df['median_center_5m'], 60)
    df['slope_5m_3m'] = compute_rolling_slopes(df['median_center_5m'], 180)
    df['slope_5m_5m'] = compute_rolling_slopes(df['median_center_5m'], 300)
    
    # 15m slope over 3m (180s), 5m (300s), 10m (600s)
    df['slope_15m_3m'] = compute_rolling_slopes(df['median_center_15m'], 180)
    df['slope_15m_5m'] = compute_rolling_slopes(df['median_center_15m'], 300)
    df['slope_15m_10m'] = compute_rolling_slopes(df['median_center_15m'], 600)
    
    # 30m slope over 5m (300s), 10m (600s), 15m (900s)
    df['slope_30m_5m'] = compute_rolling_slopes(df['median_center_30m'], 300)
    df['slope_30m_10m'] = compute_rolling_slopes(df['median_center_30m'], 600)
    df['slope_30m_15m'] = compute_rolling_slopes(df['median_center_30m'], 900)
    
    # Direction-aligned, ATR-normalized slopes
    # (slope is points/second, so we divide by ATR to get ATR/second)
    for col in ['slope_5m_1m', 'slope_5m_3m', 'slope_5m_5m',
                'slope_15m_3m', 'slope_15m_5m', 'slope_15m_10m',
                'slope_30m_5m', 'slope_30m_10m', 'slope_30m_15m']:
        df[f"{col}_aligned_atr"] = d * df[col] / atr
        
    # Slope changes & acceleration
    print("  Calculating slope changes and acceleration...")
    df['center_slope_change_5m'] = df['slope_5m_1m_aligned_atr'] - df['slope_5m_5m_aligned_atr']
    df['center_slope_change_15m'] = df['slope_15m_3m_aligned_atr'] - df['slope_15m_10m_aligned_atr']
    df['center_slope_change_30m'] = df['slope_30m_5m_aligned_atr'] - df['slope_30m_15m_aligned_atr']
    
    df['center_slope_acceleration_5m'] = df['slope_5m_1m_aligned_atr'] - df['slope_5m_1m_aligned_atr'].shift(60)
    df['center_slope_acceleration_15m'] = df['slope_15m_3m_aligned_atr'] - df['slope_15m_3m_aligned_atr'].shift(180)
    df['center_slope_acceleration_30m'] = df['slope_30m_5m_aligned_atr'] - df['slope_30m_5m_aligned_atr'].shift(300)
    
    # Spreads and spread changes
    print("  Calculating spreads and spread changes...")
    df['center_spread_5m_15m'] = d * (df['median_center_5m'] - df['median_center_15m']) / atr
    df['center_spread_15m_30m'] = d * (df['median_center_15m'] - df['median_center_30m']) / atr
    df['center_spread_5m_30m'] = d * (df['median_center_5m'] - df['median_center_30m']) / atr
    
    df['spread_change_5m_15m'] = df['center_spread_5m_15m'] - df['center_spread_5m_15m'].shift(60)
    df['spread_change_15m_30m'] = df['center_spread_15m_30m'] - df['center_spread_15m_30m'].shift(60)
    df['spread_change_5m_30m'] = df['center_spread_5m_30m'] - df['center_spread_5m_30m'].shift(60)
    
    # Ordering state
    print("  Calculating center ordering...")
    s5 = d * df['median_center_5m']
    s15 = d * df['median_center_15m']
    s30 = d * df['median_center_30m']
    
    # Vectorized state mapping
    ordering = np.zeros(len(df), dtype=int)
    
    # States:
    # 0: s5 > s15 > s30 (favorable)
    # 1: s5 > s30 > s15
    # 2: s15 > s5 > s30
    # 3: s15 > s30 > s5
    # 4: s30 > s5 > s15
    # 5: s30 > s15 > s5 (adverse)
    # 6: compressed
    
    cond_0 = (s5 > s15) & (s15 > s30)
    cond_1 = (s5 > s30) & (s30 > s15)
    cond_2 = (s15 > s5) & (s5 > s30)
    cond_3 = (s15 > s30) & (s30 > s5)
    cond_4 = (s30 > s5) & (s5 > s15)
    cond_5 = (s30 > s15) & (s15 > s5)
    
    ordering[cond_0] = 0
    ordering[cond_1] = 1
    ordering[cond_2] = 2
    ordering[cond_3] = 3
    ordering[cond_4] = 4
    ordering[cond_5] = 5
    
    # Compressed flag
    max_val = np.maximum(s5, np.maximum(s15, s30))
    min_val = np.minimum(s5, np.minimum(s15, s30))
    compressed = (max_val - min_val) < 0.1 * atr
    ordering[compressed] = 6
    
    df['ordering_state'] = ordering
    
    # Seconds in current ordering (run-length count)
    print("  Calculating ordering persistence...")
    changes = df['ordering_state'] != df['ordering_state'].shift(1)
    run_ids = changes.cumsum()
    df['seconds_in_current_ordering'] = df.groupby(run_ids).cumcount() + 1
    
    # Ordering changes in last 15m, 30m, 60m
    df['ordering_changes_15m'] = changes.rolling(900).sum()
    df['ordering_changes_30m'] = changes.rolling(1800).sum()
    df['ordering_changes_60m'] = changes.rolling(3600).sum()
    
    # Crossing behavior (30m lookback = 1800s)
    print("  Calculating crossing counts and sides...")
    cross_5m, fav_5m, adv_5m = compute_crossing_behavior(df['close'], df['median_center_5m'], 1800)
    cross_15m, _, _ = compute_crossing_behavior(df['close'], df['median_center_15m'], 1800)
    cross_30m, _, _ = compute_crossing_behavior(df['close'], df['median_center_30m'], 1800)
    
    df['price_cross_count_5m'] = cross_5m
    df['price_cross_count_15m'] = cross_15m
    df['price_cross_count_30m'] = cross_30m
    df['crosses_per_minute'] = (cross_5m + cross_15m + cross_30m) / 30.0
    df['fraction_of_time_on_favorable_side'] = fav_5m
    df['fraction_of_time_on_adverse_side'] = adv_5m
    
    return df
