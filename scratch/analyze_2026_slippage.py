import pandas as pd
import numpy as np

p = "backtests/hmm_state_filtered/results/nq_kmeans_4_s0_sl1p5_ancflip_minatr15p0_vwapF_qty2_ptr2p0_2026/trades.parquet"
df = pd.read_parquet(p)

print("VWAP_exhaustion trades in 2026:")
vwap_trades = df[df["exit_reason"] == "VWAP_exhaustion"].copy()
print(f"Total VWAP_exhaustion contracts: {len(vwap_trades)}")

# Group by entry_ts to pair c1 and c2
grouped = df.groupby("entry_ts")
rows = []
for ts, group in grouped:
    if len(group) == 2:
        c1 = group.iloc[0]
        c2 = group.iloc[1]
        
        # Determine which is c1 (PT1 or first exit)
        if c1["exit_reason"] in ("PT1", "VWAP_exhaustion") and c2["exit_reason"] == "VWAP_exhaustion":
            # If c1 is PT1 and c2 is VWAP_exhaustion, or both are VWAP_exhaustion
            pt1_px = c1["exit_px"]
            c2_px = c2["exit_px"]
            reason1 = c1["exit_reason"]
            reason2 = c2["exit_reason"]
            direction = c1["signal_direction"]
            
            # Slippage is how much worse c2 filled compared to c1
            slippage_pts = (c2_px - pt1_px) * direction
            # If direction is 1 (Long), we want to sell. c1 sells at limit pt1_px (higher). If c2 sells at c2_px (lower), c2_px - pt1_px is negative, which is slippage.
            # So slippage = (pt1_px - c2_px) * direction
            slippage_pts = (pt1_px - c2_px) * direction
            
            rows.append({
                "entry_ts": ts,
                "direction": direction,
                "entry_px": c1["entry_px"],
                "pt1_px": pt1_px,
                "c2_px": c2_px,
                "reason1": reason1,
                "reason2": reason2,
                "slippage_pts": slippage_pts,
                "slippage_ticks": slippage_pts / 0.25,
                "slippage_usd": slippage_pts * 20.0
            })
            
df_slip = pd.DataFrame(rows)
print("\nSlippage on runner for VWAP_exhaustion trades:")
print(df_slip.to_string())

print("\nSummary statistics of slippage on VWAP_exhaustion runner:")
print(df_slip[["slippage_pts", "slippage_ticks", "slippage_usd"]].describe())
