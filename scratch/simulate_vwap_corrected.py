import pandas as pd
import numpy as np

# Load flips and bars
df_ex = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
df_ex_2026 = df_ex[df_ex["year"] == 2026].copy()

bars_2026 = pd.read_parquet("data/raw/NQ_v0_1s_2026_ytd.parquet", columns=["high", "low", "close"])
if bars_2026.index.tz is None:
    bars_2026.index = bars_2026.index.tz_localize("UTC")

# Load features for state alignment
df_feat = pd.read_parquet("studies/regime_classification/results/features_nq_1m.parquet")
states_1m = pd.read_parquet("studies/regime_classification/results/states_nq_1m.parquet")
df_feat["kmeans_static"] = states_1m["kmeans_4"]

mask_feat = df_feat.notna().all(axis=1)
df_feat_clean = df_feat.copy()
if df_feat_clean.index.tz is None:
    df_feat_clean.index = df_feat_clean.index.tz_localize("UTC")
    
# Re-align static clusters
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import MiniBatchKMeans
FEATURE_COLS = [
    "ret_5s", "ret_30s", "ret_60s", "ret_300s", "cum_abs_60s",
    "rv_30s", "rv_300s",
    "range_atr_60s", "range_atr_300s", "range_atr_1800s",
    "vol_expansion",
    "efficiency_300s", "chop_ratio_300s", "n_dir_changes_60s",
    "body_ratio", "upper_wick", "lower_wick", "close_location",
    "vwap_z_signed", "vwap_z_abs", "vwap_slope_5m_atr", "session_pos",
    "range_pct_60s_vs_1h", "compress_drift",
]
df_is = df_feat_clean[df_feat_clean["year"].isin((2020, 2021, 2022))].dropna()
scaler_static = StandardScaler()
X_is_scaled = scaler_static.fit_transform(df_is[FEATURE_COLS].values)
static_km = MiniBatchKMeans(n_clusters=4, random_state=42, n_init=10, batch_size=4096)
static_km.fit(X_is_scaled)
range_idx = FEATURE_COLS.index("range_atr_300s")
target_cluster_idx = np.argmax(static_km.cluster_centers_[:, range_idx])

X_all_static = scaler_static.transform(df_feat_clean[FEATURE_COLS].dropna()[FEATURE_COLS].values)
static_labels = static_km.predict(X_all_static)
df_feat_clean["kmeans_static_aligned"] = -1
df_feat_clean.loc[df_feat_clean.dropna().index, "kmeans_static_aligned"] = np.where(static_labels == target_cluster_idx, 0, -1)

def lookup_state_causal(target_ts_arr, state_ts_arr, state_arr, bar_duration_ns):
    state_arr = np.asarray(state_arr).flatten()
    state_ts_arr = np.asarray(state_ts_arr).flatten().astype(np.int64)
    target_ts_arr = np.asarray(target_ts_arr).flatten().astype(np.int64)
    query_ts = target_ts_arr - bar_duration_ns
    idx = np.searchsorted(state_ts_arr, query_ts, side="right") - 1
    out = np.full(len(target_ts_arr), -1, dtype=np.int64)
    valid = (idx >= 0) & (idx < len(state_ts_arr))
    out[valid] = state_arr[idx[valid]]
    return out

df_ex_2026["kmeans_static_aligned"] = lookup_state_causal(
    df_ex_2026["entry_ts"].to_numpy(np.int64),
    df_feat_clean.index.values.astype(np.int64),
    df_feat_clean["kmeans_static_aligned"].to_numpy(np.int64),
    60 * 1_000_000_000
)

pop_2026 = df_ex_2026[(df_ex_2026["kmeans_static_aligned"] == 0) & (df_ex_2026["entry_atr"] > 15.0)].copy()

ts_1s = bars_2026.index.astype("int64").to_numpy()
h_1s = bars_2026["high"].to_numpy()
l_1s = bars_2026["low"].to_numpy()
c_1s = bars_2026["close"].to_numpy()

vwap_z_dict = dict(zip(df_feat_clean.index.values.astype(np.int64), df_feat_clean["vwap_z_abs"].values))

results_ideal = []
results_corrected = []

for idx, row in pop_2026.iterrows():
    entry_ts = int(row["entry_ts"])
    entry_px = float(row["entry_px"])
    atr = float(row["entry_atr"])
    d = int(row["signal_direction"])
    exit_ts_regime = int(row["exit_ts"])
    exit_px_regime = float(row["exit_px"])
    
    idx_start = np.searchsorted(ts_1s, entry_ts, side="left")
    idx_end = np.searchsorted(ts_1s, exit_ts_regime, side="right") - 1
    idx_end = max(idx_start, min(idx_end, len(ts_1s) - 1))
    
    sl_px = entry_px - d * 1.50 * atr
    pt_0p5 = entry_px + d * 0.50 * atr
    pt_2atr = entry_px + d * 2.00 * atr
    
    # ── 1. Idealized (with look-ahead bug) ──
    touch_idx_ideal = -1
    for j in range(idx_start, idx_end + 1):
        h, l = h_1s[j], l_1s[j]
        if (d == 1 and h >= pt_0p5) or (d == -1 and l <= pt_0p5):
            touch_idx_ideal = j
            break
            
    if touch_idx_ideal == -1:
        # Never touched target
        exit_px_c1 = exit_px_c2 = exit_px_regime
        for j in range(idx_start, idx_end + 1):
            h, l = h_1s[j], l_1s[j]
            if (d == 1 and l <= sl_px) or (d == -1 and h >= sl_px):
                exit_px_c1 = exit_px_c2 = sl_px
                break
    else:
        # Touched target (regardless of stop loss before it!)
        touch_ts = ts_1s[touch_idx_ideal]
        t_closed_open = (touch_ts // 60_000_000_000) * 60_000_000_000 - 60_000_000_000
        vwap_z = vwap_z_dict.get(t_closed_open, 1.0)
        
        exit_px_c1 = pt_0p5
        if vwap_z <= 1.0:
            # Runner
            exit_px_c2 = exit_px_regime
            for j in range(touch_idx_ideal, idx_end + 1):
                h, l = h_1s[j], l_1s[j]
                if (d == 1 and l <= sl_px) or (d == -1 and h >= sl_px):
                    exit_px_c2 = sl_px
                    break
                if (d == 1 and h >= pt_2atr) or (d == -1 and l <= pt_2atr):
                    exit_px_c2 = pt_2atr
                    break
        else:
            exit_px_c2 = pt_0p5
            
    pnl_ideal = (exit_px_c1 - entry_px) * d + (exit_px_c2 - entry_px) * d
    results_ideal.append(pnl_ideal)
    
    # ── 2. Corrected Chronological Simulation (No look-ahead) ──
    touch_idx_corr = -1
    exit_px_c1_corr = None
    exit_px_c2_corr = None
    
    for j in range(idx_start, idx_end + 1):
        h, l = h_1s[j], l_1s[j]
        # Check SL first (chronological order inside the second or bar)
        if (d == 1 and l <= sl_px) or (d == -1 and h >= sl_px):
            exit_px_c1_corr = exit_px_c2_corr = sl_px
            break
        # Check PT1
        if (d == 1 and h >= pt_0p5) or (d == -1 and l <= pt_0p5):
            touch_idx_corr = j
            break
            
    if touch_idx_corr == -1 and exit_px_c1_corr is None:
        # Never touched SL or PT1, exited at regime flip
        exit_px_c1_corr = exit_px_c2_corr = exit_px_regime
        
    elif touch_idx_corr != -1:
        # Touched PT1 first! Check VWAP
        touch_ts = ts_1s[touch_idx_corr]
        t_closed_open = (touch_ts // 60_000_000_000) * 60_000_000_000 - 60_000_000_000
        vwap_z = vwap_z_dict.get(t_closed_open, 1.0)
        
        exit_px_c1_corr = pt_0p5
        if vwap_z <= 1.0:
            # Runner contract
            exit_px_c2_corr = exit_px_regime
            for j in range(touch_idx_corr, idx_end + 1):
                h, l = h_1s[j], l_1s[j]
                if (d == 1 and l <= sl_px) or (d == -1 and h >= sl_px):
                    exit_px_c2_corr = sl_px
                    break
                if (d == 1 and h >= pt_2atr) or (d == -1 and l <= pt_2atr):
                    exit_px_c2_corr = pt_2atr
                    break
        else:
            # VWAP exhaustion, exit both at PT1
            exit_px_c2_corr = pt_0p5
            
    pnl_corr = (exit_px_c1_corr - entry_px) * d + (exit_px_c2_corr - entry_px) * d
    results_corrected.append(pnl_corr)

df_pop = pop_2026.copy()
df_pop["pnl_ideal_pts"] = results_ideal
df_pop["pnl_corr_pts"] = results_corrected
df_pop["diff_pts"] = df_pop["pnl_corr_pts"] - df_pop["pnl_ideal_pts"]

print(f"Corrected vs Idealized Simulation of 2026 population ({len(df_pop)} trades):")
print(f"  Idealized PnL (points) : {df_pop['pnl_ideal_pts'].sum():.2f} pts (${df_pop['pnl_ideal_pts'].sum()*20.0:,.2f})")
print(f"  Corrected PnL (points) : {df_pop['pnl_corr_pts'].sum():.2f} pts (${df_pop['pnl_corr_pts'].sum()*20.0:,.2f})")
print(f"  PnL Gap (points)       : {df_pop['diff_pts'].sum():.2f} pts (${df_pop['diff_pts'].sum()*20.0:,.2f})")

print("\nTrades with discrepancy in simulation:")
print(df_pop[df_pop["diff_pts"] != 0.0][["entry_ts", "signal_direction", "entry_px", "entry_atr", "pnl_ideal_pts", "pnl_corr_pts", "diff_pts"]].to_string())
