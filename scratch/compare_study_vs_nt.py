import pandas as pd
import numpy as np

# Load event-driven trades
dfs_nt = []
BASE = pd.io.common.Path("backtests/hmm_state_filtered/results/nq_kmeans_4_s0_sl1p5_ancflip_minatr15p0_vwapF_qty2_ptr2p0")
for y in [2023, 2024, 2025, 2026]:
    p = BASE.parent / f"{BASE.name}_{y}" / "trades.parquet"
    if p.exists():
        df = pd.read_parquet(p)
        df["year"] = y
        dfs_nt.append(df)
df_nt = pd.concat(dfs_nt, ignore_index=True)

# Load flips_excursion_paths.parquet (raw triggers)
df_ex = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")

print(f"Total NT trades recorded (contracts): {len(df_nt)}")
print(f"Total study flips loaded: {len(df_ex)}")

# Align NT entry_ts with study entry_ts
# In NT, entry_ts is in nanoseconds UTC.
# Let's see if we can match them.
matched = []
for idx, row in df_nt.iterrows():
    # Find study flip closest in time (within 1 minute)
    diffs = np.abs(df_ex["entry_ts"].to_numpy() - row["entry_ts"])
    best_idx = np.argmin(diffs)
    if diffs[best_idx] < 60_000_000_000: # 1 minute
        match = df_ex.iloc[best_idx]
        matched.append({
            "year": row["year"],
            "entry_ts": row["entry_ts"],
            "nt_entry_px": row["entry_px"],
            "study_entry_px": match["entry_px"],
            "nt_exit_px": row["exit_px"],
            "study_exit_px": match["exit_px"],
            "nt_exit_reason": row["exit_reason"],
            "direction": row["signal_direction"],
            "diff_ns": diffs[best_idx]
        })
df_match = pd.DataFrame(matched)
print(f"Matched {len(df_match)} contract records.")

# Print some matches
print("\nFirst 10 matched trades comparison:")
print(df_match.head(10).to_string())
