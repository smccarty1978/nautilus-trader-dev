import pandas as pd
p = "backtests/hmm_state_filtered/results/nq_kmeans_4_s0_sl1p5_ancflip_minatr15p0_vwapF_qty2_ptr2p0_2026/trades.parquet"
df = pd.read_parquet(p)
print(f"Loaded {len(df)} contract records.")
print(df.to_string())
