import pandas as pd
import numpy as np

# 1. Load NT trades
dfs_nt = []
BASE = pd.io.common.Path("backtests/hmm_state_filtered/results/nq_kmeans_4_s0_sl1p5_ancflip_minatr15p0_vwapF_qty2_ptr2p0")
for y in [2023, 2024, 2025, 2026]:
    p = BASE.parent / f"{BASE.name}_{y}" / "trades.parquet"
    if p.exists():
        df = pd.read_parquet(p)
        df["year"] = y
        dfs_nt.append(df)
df_nt = pd.concat(dfs_nt, ignore_index=True)

# 2. Run the exact simulation from simulate_vwap_exit_policy.py and keep the simulated records
df_ex = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
all_years_df = []
bars_cache = {}
for y in sorted(df_ex["year"].unique()):
    year_cohort = df_ex[df_ex["year"] == y].copy()
    if len(year_cohort) == 0:
        continue
    try:
        # Load NQ 1s data
        parts = []
        for year_val in (y - 1, y, y + 1):
            p = f"data/raw/NQ_v0_1s_{year_val}.parquet" if year_val != 2026 else "data/raw/NQ_v0_1s_2026_ytd.parquet"
            import os
            if os.path.exists(p):
                parts.append(pd.read_parquet(p, columns=["high", "low", "close"]))
        bars = pd.concat(parts).sort_index()
        bars = bars[~bars.index.duplicated(keep="first")]
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize("UTC")
        bars_cache[y] = bars
    except Exception as e:
        print(f"Error loading {y}: {e}")
        continue
    all_years_df.append(year_cohort)
    
df_flips = pd.concat(all_years_df, ignore_index=True)

# Load static states and features
df_feat = pd.read_parquet("studies/regime_classification/results/features_nq_1m.parquet")
states_1m = pd.read_parquet("studies/regime_classification/results/states_nq_1m.parquet")
df_feat["kmeans_static"] = states_1m["kmeans_4"]

mask_feat = df_feat.notna().all(axis=1) # Keep all features clean
df_feat_clean = df_feat.copy()
if df_feat_clean.index.tz is None:
    df_feat_clean.index = df_feat_clean.index.tz_localize("UTC")
    
# Re-align Target State 0
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

def lookup_state_causal(target_ts_arr, state_ts_arr, state_arr, bar_duration_ns, is_int=False):
    state_arr = np.asarray(state_arr).flatten()
    state_ts_arr = np.asarray(state_ts_arr).flatten().astype(np.int64)
    target_ts_arr = np.asarray(target_ts_arr).flatten().astype(np.int64)
    query_ts = target_ts_arr - bar_duration_ns
    idx = np.searchsorted(state_ts_arr, query_ts, side="right") - 1
    out = np.full(len(target_ts_arr), -1, dtype=np.int64)
    valid = (idx >= 0) & (idx < len(state_ts_arr))
    out[valid] = state_arr[idx[valid]]
    return out

df_flips["kmeans_static_aligned"] = lookup_state_causal(
    df_flips["entry_ts"].to_numpy(np.int64),
    df_feat_clean.index.values.astype(np.int64),
    df_feat_clean["kmeans_static_aligned"].to_numpy(np.int64),
    60 * 1_000_000_000,
    is_int=True
)

pop = df_flips[(df_flips["year"].isin((2023, 2024, 2025, 2026))) & 
               (df_flips["kmeans_static_aligned"] == 0) & 
               (df_flips["entry_atr"] > 15.0)].copy()

feature_lookup_ts = df_feat_clean.index.values.astype(np.int64)
vwap_z_dict = dict(zip(feature_lookup_ts, df_feat_clean["vwap_z_abs"].values))

results_list = []
for idx, row in pop.iterrows():
    y = int(row["year"])
    bars = bars_cache[y]
    ts_1s = bars.index.astype("int64").to_numpy()
    h_1s = bars["high"].to_numpy()
    l_1s = bars["low"].to_numpy()
    c_1s = bars["close"].to_numpy()
    
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
    
    exit_px_c1 = None
    exit_px_c2 = None
    reason_c1 = ""
    reason_c2 = ""
    
    pt_0p5 = entry_px + d * 0.50 * atr
    pt_2atr = entry_px + d * 2.00 * atr
    
    touch_idx = -1
    for j in range(idx_start, idx_end + 1):
        h, l = h_1s[j], l_1s[j]
        if (d == 1 and h >= pt_0p5) or (d == -1 and l <= pt_0p5):
            touch_idx = j
            break
            
    if touch_idx == -1:
        for j in range(idx_start, idx_end + 1):
            h, l = h_1s[j], l_1s[j]
            if (d == 1 and l <= sl_px) or (d == -1 and h >= sl_px):
                exit_px_c1 = sl_px
                reason_c1 = "stop_loss"
                break
        if exit_px_c1 is None:
            exit_px_c1 = exit_px_regime
            reason_c1 = "regime_exit"
        exit_px_c2 = exit_px_c1
        reason_c2 = reason_c1
    else:
        touch_ts = ts_1s[touch_idx]
        t_closed_open = (touch_ts // 60_000_000_000) * 60_000_000_000 - 60_000_000_000
        vwap_z = vwap_z_dict.get(t_closed_open, 1.0)
        
        if vwap_z <= 1.0:
            exit_px_c1 = pt_0p5
            reason_c1 = "PT1"
            
            for j in range(touch_idx, idx_end + 1):
                h, l = h_1s[j], l_1s[j]
                if (d == 1 and l <= sl_px) or (d == -1 and h >= sl_px):
                    exit_px_c2 = sl_px
                    reason_c2 = "stop_loss"
                    break
                if (d == 1 and h >= pt_2atr) or (d == -1 and l <= pt_2atr):
                    exit_px_c2 = pt_2atr
                    reason_c2 = "PT2"
                    break
            if exit_px_c2 is None:
                exit_px_c2 = exit_px_regime
                reason_c2 = "regime_exit"
        else:
            exit_px_c1 = pt_0p5
            reason_c1 = "VWAP_exhaustion"
            exit_px_c2 = pt_0p5
            reason_c2 = "VWAP_exhaustion"
            
    results_list.append({
        "entry_ts": entry_ts,
        "entry_px": entry_px,
        "signal_direction": d,
        "study_exit_c1": exit_px_c1,
        "study_reason_c1": reason_c1,
        "study_exit_c2": exit_px_c2,
        "study_reason_c2": reason_c2,
    })

df_sim = pd.DataFrame(results_list)

# Now compare study exit prices against NT exit prices!
audits = []
for idx, row in df_nt.iterrows():
    # Find matching row in simulation by entry_ts
    match = df_sim[np.abs(df_sim["entry_ts"] - row["entry_ts"]) < 60_000_000_000]
    if len(match) > 0:
        match = match.iloc[0]
        # Match c1 or c2 by exit reason/px
        if row["exit_reason"] in ("PT1", "VWAP_exhaustion") or ("stop_loss" in row["exit_reason"] and "c1" in str(row)):
            study_px = match["study_exit_c1"]
            study_reason = match["study_reason_c1"]
        else:
            study_px = match["study_exit_c2"]
            study_reason = match["study_reason_c2"]
            
        audits.append({
            "year": row["year"],
            "entry_ts": row["entry_ts"],
            "reason_nt": row["exit_reason"],
            "reason_study": study_reason,
            "px_nt": row["exit_px"],
            "px_study": study_px,
            "diff": (row["exit_px"] - study_px) * row["signal_direction"],
            "dir": row["signal_direction"]
        })
        
df_audit = pd.DataFrame(audits)
print(f"\nAudit complete. Matched {len(df_audit)} contract trades.")

# Calculate average difference
print("\nFirst 15 audit details:")
print(df_audit.head(15).to_string())

# Summarize differences
print("\nSum of difference by year:")
print(df_audit.groupby("year")["diff"].sum())
