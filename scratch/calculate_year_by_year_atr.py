import pandas as pd
import numpy as np

df = pd.read_parquet("scratch/bar1_conditioning_dataset.parquet")
# Calculate VWAP features
df["vwap_z_signed"] = ((df["entry_px_bar1"] - df["vwap"]) / df["entry_atr"].replace(0, 1.0)) * df["signal_direction"]
df["vwap_z_abs"] = df["vwap_z_signed"].abs()

def compute_pf(pnl):
    wins = pnl[pnl > 0].sum()
    losses = abs(pnl[pnl < 0].sum())
    return wins / losses if losses > 0 else float("inf")

top_features = [
    ("dist_ema13_atr", 10),
    ("dist_ema3_atr", 10),
    ("keltner_width_percentile", 4)
]

for feat, best_decile in top_features:
    print(f"\nFeature: {feat} | Best Decile: {best_decile}")
    print("| Year | Total Trades | Decile Trades | Gross WR% | Gross PF | Gross EV (ATR) | Net PnL ($) |")
    print("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
    
    sub = df[[feat, "regime_pnl_atr_bar1", "regime_pnl_pts_bar1", "year"]].copy()
    sub[feat] = pd.to_numeric(sub[feat], errors="coerce")
    sub = sub.dropna()
    noise = np.random.normal(0, 1e-10, len(sub))
    sub["decile"] = pd.qcut(sub[feat] + noise, 10, labels=False, duplicates="drop") + 1
    
    for yr in [2020, 2021, 2022, 2023, 2024, 2025, 2026]:
        yr_total = sub[sub["year"] == yr]
        yr_decile = yr_total[yr_total["decile"] == best_decile]
        n_tot = len(yr_total)
        n_dec = len(yr_decile)
        if n_dec == 0:
            print(f"| {yr} | {n_tot:<12,} | 0 | - | - | 0.00 | $0.00 |")
            continue
        wr = (yr_decile["regime_pnl_atr_bar1"] > 0).mean() * 100
        pf = compute_pf(yr_decile["regime_pnl_atr_bar1"])
        ev_atr = yr_decile["regime_pnl_atr_bar1"].mean()
        net_usd = (yr_decile["regime_pnl_pts_bar1"].sum() * 20.0) - (n_dec * 10.0) # applying $10 friction
        print(f"| {yr} | {n_tot:<12,} | {n_dec:<13,} | {wr:>8.1f}% | {pf:>8.2f} | {ev_atr:>13.2f} | ${net_usd:>+10,.2f} |")
