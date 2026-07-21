import pandas as pd
import numpy as np

# 1. Load NT trades
p_nt = "backtests/hmm_state_filtered/results/nq_kmeans_4_s0_sl1p5_ancflip_minatr15p0_vwapF_qty2_ptr2p0_2026/trades.parquet"
df_nt = pd.read_parquet(p_nt)
df_nt["trade_id"] = df_nt.index // 2

# 2. Run simulation for 2026
df_ex = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
df_ex_2026 = df_ex[df_ex["year"] == 2026].copy()

# Load NQ 1s data for 2026
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

# Filter for the Strategy F active cohort in 2026: State 0, ATR > 15
pop_2026 = df_ex_2026[(df_ex_2026["kmeans_static_aligned"] == 0) & (df_ex_2026["entry_atr"] > 15.0)].copy()

print(f"Total trades in 2026 cohort (offline): {len(pop_2026)}")
print(f"Total trades in 2026 backtest (Nautilus Trader): {len(df_nt) // 2}")

# Let's perform a match and see the PnL of matched trades
vwap_z_dict = dict(zip(df_feat_clean.index.values.astype(np.int64), df_feat_clean["vwap_z_abs"].values))

results_list = []
ts_1s = bars_2026.index.astype("int64").to_numpy()
h_1s = bars_2026["high"].to_numpy()
l_1s = bars_2026["low"].to_numpy()
c_1s = bars_2026["close"].to_numpy()

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
    
    touch_idx = -1
    for j in range(idx_start, idx_end + 1):
        h, l = h_1s[j], l_1s[j]
        if (d == 1 and h >= pt_0p5) or (d == -1 and l <= pt_0p5):
            touch_idx = j
            break
            
    if touch_idx == -1:
        # No PT1 touch
        for j in range(idx_start, idx_end + 1):
            h, l = h_1s[j], l_1s[j]
            if (d == 1 and l <= sl_px) or (d == -1 and h >= sl_px):
                exit_px_c1 = exit_px_c2 = sl_px
                reason_c1 = reason_c2 = "stop_loss"
                exit_ts_c1 = exit_ts_c2 = ts_1s[j]
                break
        else:
            exit_px_c1 = exit_px_c2 = exit_px_regime
            reason_c1 = reason_c2 = "regime_exit"
            exit_ts_c1 = exit_ts_c2 = exit_ts_regime
    else:
        # PT1 touch
        touch_ts = ts_1s[touch_idx]
        t_closed_open = (touch_ts // 60_000_000_000) * 60_000_000_000 - 60_000_000_000
        vwap_z = vwap_z_dict.get(t_closed_open, 1.0)
        
        exit_px_c1 = pt_0p5
        exit_ts_c1 = touch_ts
        
        if vwap_z <= 1.0:
            reason_c1 = "PT1"
            # Runner traces forward
            for j in range(touch_idx, idx_end + 1):
                h, l = h_1s[j], l_1s[j]
                if (d == 1 and l <= sl_px) or (d == -1 and h >= sl_px):
                    exit_px_c2 = sl_px
                    reason_c2 = "stop_loss"
                    exit_ts_c2 = ts_1s[j]
                    break
                if (d == 1 and h >= pt_2atr) or (d == -1 and l <= pt_2atr):
                    exit_px_c2 = pt_2atr
                    reason_c2 = "PT2"
                    exit_ts_c2 = ts_1s[j]
                    break
            else:
                exit_px_c2 = exit_px_regime
                reason_c2 = "regime_exit"
                exit_ts_c2 = exit_ts_regime
        else:
            reason_c1 = "VWAP_exhaustion"
            exit_px_c2 = pt_0p5
            reason_c2 = "VWAP_exhaustion"
            exit_ts_c2 = touch_ts
            
    results_list.append({
        "entry_ts": entry_ts,
        "entry_px": entry_px,
        "signal_direction": d,
        "study_exit_c1": exit_px_c1,
        "study_reason_c1": reason_c1,
        "study_ts_c1": exit_ts_c1,
        "study_exit_c2": exit_px_c2,
        "study_reason_c2": reason_c2,
        "study_ts_c2": exit_ts_c2,
    })
    
df_sim = pd.DataFrame(results_list)

# Now compare
matched_rows = []
for i in range(len(df_nt) // 2):
    c1_nt = df_nt.iloc[2*i]
    c2_nt = df_nt.iloc[2*i+1]
    
    # find match
    match = df_sim[np.abs(df_sim["entry_ts"] - c1_nt["entry_ts"]) < 60_000_000_000]
    if len(match) > 0:
        m = match.iloc[0]
        pnl_nt = (c1_nt["exit_px"] - c1_nt["entry_px"]) * c1_nt["signal_direction"] + (c2_nt["exit_px"] - c2_nt["entry_px"]) * c2_nt["signal_direction"]
        pnl_study = (m["study_exit_c1"] - m["entry_px"]) * m["signal_direction"] + (m["study_exit_c2"] - m["entry_px"]) * m["signal_direction"]
        
        matched_rows.append({
            "entry_ts": c1_nt["entry_ts"],
            "direction": c1_nt["signal_direction"],
            "nt_r1": c1_nt["exit_reason"],
            "nt_r2": c2_nt["exit_reason"],
            "study_r1": m["study_reason_c1"],
            "study_r2": m["study_reason_c2"],
            "pnl_nt_pts": pnl_nt,
            "pnl_study_pts": pnl_study,
            "diff_pts": pnl_nt - pnl_study
        })
        
df_match = pd.DataFrame(matched_rows)
print(f"\nSuccessfully matched {len(df_match)} out of {len(df_nt)//2} trades.")
print("\nSum of PnL points (Matched only):")
print(f"  Nautilus Trader: {df_match['pnl_nt_pts'].sum():.2f} pts (${df_match['pnl_nt_pts'].sum()*20.0:,.2f})")
print(f"  Offline Study  : {df_match['pnl_study_pts'].sum():.2f} pts (${df_match['pnl_study_pts'].sum()*20.0:,.2f})")
print(f"  Difference     : {df_match['diff_pts'].sum():.2f} pts (${df_match['diff_pts'].sum()*20.0:,.2f})")

print("\nTrade by trade breakdown of difference:")
print(df_match[df_match["diff_pts"] != 0.0].to_string())
