import os
import sys
import time
import numpy as np
import pandas as pd
from pathlib import Path
from nautilus_trader.persistence.catalog import ParquetDataCatalog

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

OUT = Path("studies/regime_state_transition_atlas/results")
CATALOG = "data/catalog/NQ_v0_2020_2026"
BAR_TYPE = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
NS_PER_S = 1_000_000_000
MULT = 20.0

def calc_max_dd(pnl_series):
    if len(pnl_series) == 0:
        return 0.0
    cum_pnl = pnl_series.cumsum()
    peak = cum_pnl.cummax()
    dd = peak - cum_pnl
    return dd.max()

def generate_report(df_tr, scenario_name, output_file):
    results = []
    
    sl_grid = sorted(df_tr["sl_atr"].unique())
    pt_grid = sorted(df_tr["pt_atr"].unique())
    gates = ["Top 10%", "Top 5%", "Top 2%", "Top 1%"]
    
    for gate in gates:
        for sl in sl_grid:
            for pt in pt_grid:
                sub = df_tr[(df_tr["gate"] == gate) & (df_tr["sl_atr"] == sl) & (df_tr["pt_atr"] == pt)]
                if len(sub) == 0:
                    continue
                
                total_trades = len(sub)
                gross_pnl_mean = sub["gross_pnl"].mean()
                net_pnl_mean = sub["net_pnl"].mean()
                
                # Profit Factor (PF)
                pos_pnl = sub[sub["net_pnl"] > 0]["net_pnl"].sum()
                neg_pnl = sub[sub["net_pnl"] < 0]["net_pnl"].sum()
                pf = pos_pnl / abs(neg_pnl) if neg_pnl != 0 else np.nan
                
                win_rate = (sub["status"] == "pt").sum() / total_trades
                
                sub_sorted = sub.sort_values("entry_ts")
                max_dd = calc_max_dd(sub_sorted["net_pnl"])
                
                years = sub["year"].unique()
                years_pos = 0
                for yr in years:
                    if sub[sub["year"] == yr]["net_pnl"].sum() > 0:
                        years_pos += 1
                years_pos_str = f"{years_pos}/{len(years)}"
                
                pt_trades = sub[sub["status"] == "pt"]
                mae_before_pt = pt_trades["mae_atr"].mean() if len(pt_trades) > 0 else np.nan
                
                stopped_before_1atr = (sub["max_excursion_atr"] < 1.0).sum() / total_trades
                
                results.append({
                    "Gate": gate,
                    "SL": f"{sl:.2f} ATR",
                    "PT": f"{pt:.2f} ATR",
                    "Trades": total_trades,
                    "Net $/Trade": f"${net_pnl_mean:.2f}",
                    "Gross $/Trade": f"${gross_pnl_mean:.2f}",
                    "PF": f"{pf:.2f}" if not np.isnan(pf) else "NaN",
                    "Win %": f"{win_rate*100:.1f}%",
                    "Max DD": f"${max_dd:.2f}",
                    "Years Pos": years_pos_str,
                    "MAE before PT": f"{mae_before_pt:.2f} ATR" if not np.isnan(mae_before_pt) else "NaN",
                    "Stop before 1ATR": f"{stopped_before_1atr*100:.1f}%"
                })
                
    df_res = pd.DataFrame(results)
    
    # Save as Markdown
    md_content = f"# Bracket Grid Simulation — {scenario_name}\n\n"
    md_content += "| " + " | ".join(df_res.columns) + " |\n"
    md_content += "| " + " | ".join([":---" if c in ["Gate", "SL", "PT", "Net $/Trade", "Gross $/Trade", "Max DD", "MAE before PT"] else ":---:" for c in df_res.columns]) + " |\n"
    for _, row in df_res.iterrows():
        md_content += "| " + " | ".join(str(row[c]) for c in df_res.columns) + " |\n"
    
    with open(output_file, "w") as f:
        f.write(md_content)
    print(f"Saved report to {output_file}")
    
    # Also print top 5 combinations by Net $/Trade
    df_res["net_val"] = df_res["Net $/Trade"].str.replace("$", "").str.replace(",", "").str.replace(" ", "").astype(float)
    top_5 = df_res.sort_values("net_val", ascending=False).head(5)
    print(f"\n--- Top 5 Combinations for {scenario_name} ---")
    print(top_5[["Gate", "SL", "PT", "Trades", "Net $/Trade", "PF", "Win %", "Max DD", "Years Pos"]].to_string(index=False))

def main():
    t0 = time.time()
    scored_parquet = OUT / "scored_state_rows.parquet"
    state_parquet = OUT / "state_rows.parquet"
    label_parquet = OUT / "forward_labels.parquet"
    
    print("Loading parquets...")
    df_scored = pd.read_parquet(scored_parquet)
    df_states = pd.read_parquet(state_parquet)
    df_labels = pd.read_parquet(label_parquet)
    
    print("Merging dataframes...")
    df_all = pd.merge(df_scored, df_states[["regime_id", "bar_ts", "regime_start_ts"]], on=["regime_id", "bar_ts"])
    df_all = pd.merge(df_all, df_labels, on=["regime_id", "bar_ts"])
    
    if "next_1s_open_x" in df_all.columns:
        df_all = df_all.rename(columns={"next_1s_open_x": "next_1s_open"})
    elif "next_1s_open_y" in df_all.columns:
        df_all = df_all.rename(columns={"next_1s_open_y": "next_1s_open"})
        
    if "atr_1m_entry_x" in df_all.columns:
        df_all = df_all.rename(columns={"atr_1m_entry_x": "atr_1m_entry"})
    elif "atr_1m_entry_y" in df_all.columns:
        df_all = df_all.rename(columns={"atr_1m_entry_y": "atr_1m_entry"})
        
    df_all = df_all.sort_values("bar_ts").copy()
    
    # Pre-calculate thresholds for score gates
    df_tr_2025 = df_all[df_all["year"].isin([2021, 2022, 2023, 2024])]
    df_tr_2026 = df_all[df_all["year"].isin([2021, 2022, 2023, 2024, 2025])]
    
    gates_percentiles = {
        "Top 10%": 90,
        "Top 5%": 95,
        "Top 2%": 98,
        "Top 1%": 99
    }
    
    thr_2025 = {g: np.percentile(df_tr_2025["score_opportunity"].values, p) for g, p in gates_percentiles.items()}
    thr_2026 = {g: np.percentile(df_tr_2026["score_opportunity"].values, p) for g, p in gates_percentiles.items()}
    
    # Filter OOS
    df_oos = df_all[df_all["year"].isin([2025, 2026])].copy()
    
    # Grid parameters
    sl_grid = [0.50, 0.75, 1.00, 1.25]
    pt_grid = [1.00, 1.25, 1.50, 2.00, 2.50]
    gates = ["Top 10%", "Top 5%", "Top 2%", "Top 1%"]
    
    trades = []
    catalog = ParquetDataCatalog(CATALOG)
    
    years = [2025, 2026]
    for year in years:
        t_yr = time.time()
        print(f"\nProcessing year {year}...")
        load_start = pd.Timestamp(f"{year}-01-01", tz="UTC") - pd.Timedelta(days=1)
        load_end = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
        bars = catalog.bars(bar_types=[BAR_TYPE], start=load_start, end=load_end)
        print(f"  Loaded {len(bars):,} 1s bars ({time.time()-t_yr:.0f}s)")
        
        # Extract numpy arrays for fast vector slicing
        t_arr = time.time()
        o_arr = np.fromiter((float(b.open) for b in bars), dtype=np.float64, count=len(bars))
        h_arr = np.fromiter((float(b.high) for b in bars), dtype=np.float64, count=len(bars))
        l_arr = np.fromiter((float(b.low) for b in bars), dtype=np.float64, count=len(bars))
        c_arr = np.fromiter((float(b.close) for b in bars), dtype=np.float64, count=len(bars))
        tsi_arr = np.fromiter((int(b.ts_init) for b in bars), dtype=np.int64, count=len(bars))
        del bars
        print(f"  Extracted numpy arrays ({time.time()-t_arr:.0f}s)")
        
        # Get OOS checkpoints for this year
        df_yr = df_oos[df_oos["year"] == year].copy()
        
        # Pre-filter first entries per regime for each gate
        # regime_id -> first bar_ts where score triggers the gate
        first_regime_entries = {g: {} for g in gates}
        thrs = thr_2025 if year == 2025 else thr_2026
        
        for idx, row in df_yr.sort_values("bar_ts").iterrows():
            r_id = int(row["regime_id"])
            score = float(row["score_opportunity"])
            ts = int(row["bar_ts"])
            for g in gates:
                if score >= thrs[g]:
                    if r_id not in first_regime_entries[g]:
                        first_regime_entries[g][r_id] = ts
                        
        records = df_yr.to_dict("records")
        print(f"  Simulating {len(records)} checkpoints...")
        
        t_sim = time.time()
        for r_idx, row in enumerate(records):
            checkpoint_ts = int(row["bar_ts"])
            direction = int(row["direction"])
            atr = float(row["atr_1m_entry"])
            reg_id = int(row["regime_id"])
            bar_idx = int(row["bar_index_in_regime"])
            score = float(row["score_opportunity"])
            
            # Slice 1s arrays from checkpoint_ts to 6 hours later
            start_idx = np.searchsorted(tsi_arr, checkpoint_ts)
            end_idx = np.searchsorted(tsi_arr, checkpoint_ts + 6 * 3600 * NS_PER_S)
            
            o_slice = o_arr[start_idx:end_idx]
            h_slice = h_arr[start_idx:end_idx]
            l_slice = l_arr[start_idx:end_idx]
            c_slice = c_arr[start_idx:end_idx]
            ts_slice = tsi_arr[start_idx:end_idx]
            
            if len(ts_slice) < 5:
                continue
                
            # Entry open price (2nd 1s bar open)
            base_px = o_slice[1] if len(o_slice) > 1 else o_slice[0]
            
            # Determine which gates are triggered
            active_gates = []
            for g in gates:
                if score >= thrs[g]:
                    active_gates.append(g)
            
            if not active_gates:
                continue
                
            for g in active_gates:
                is_first = (checkpoint_ts == first_regime_entries[g].get(reg_id, -1))
                
                for sl in sl_grid:
                    for pt in pt_grid:
                        # Define target and stop prices
                        sl_px = base_px - direction * sl * atr
                        pt_px = base_px + direction * pt * atr
                        
                        # Find cross indices using fast numpy vector operations
                        if direction == 1:
                            sl_hits = np.where(l_slice[1:] <= sl_px)[0]
                            pt_hits = np.where(h_slice[1:] >= pt_px)[0]
                        else:
                            sl_hits = np.where(h_slice[1:] >= sl_px)[0]
                            pt_hits = np.where(l_slice[1:] <= pt_px)[0]
                            
                        # Resolve bracket outcome
                        exit_idx = None
                        status = "end_of_data"
                        exit_px = c_slice[-1]
                        exit_ts = ts_slice[-1]
                        
                        has_sl = len(sl_hits) > 0
                        has_pt = len(pt_hits) > 0
                        
                        if has_sl and has_pt:
                            first_sl = sl_hits[0]
                            first_pt = pt_hits[0]
                            if first_sl <= first_pt: # Stop-first on double hit
                                status = "sl"
                                exit_idx = first_sl + 1
                                exit_px = sl_px
                            else:
                                status = "pt"
                                exit_idx = first_pt + 1
                                exit_px = pt_px
                        elif has_sl:
                            status = "sl"
                            exit_idx = sl_hits[0] + 1
                            exit_px = sl_px
                        elif has_pt:
                            status = "pt"
                            exit_idx = pt_hits[0] + 1
                            exit_px = pt_px
                            
                        if exit_idx is not None:
                            exit_ts = ts_slice[exit_idx]
                            h_hold = h_slice[1:exit_idx+1]
                            l_hold = l_slice[1:exit_idx+1]
                        else:
                            h_hold = h_slice[1:]
                            l_hold = l_slice[1:]
                            
                        # Calculate excursions
                        if direction == 1:
                            mae = np.max(base_px - l_hold) if len(l_hold) > 0 else 0.0
                            max_ex = np.max(h_hold - base_px) if len(h_hold) > 0 else 0.0
                        else:
                            mae = np.max(h_hold - base_px) if len(h_hold) > 0 else 0.0
                            max_ex = np.max(base_px - l_hold) if len(l_hold) > 0 else 0.0
                            
                        # Gross PnL
                        gross_pnl = (exit_px - base_px) * direction * MULT
                        friction = 5.0 if status == "pt" else 7.50
                        net_pnl = gross_pnl - friction
                        
                        trades.append({
                            "gate": g,
                            "sl_atr": sl,
                            "pt_atr": pt,
                            "entry_ts": checkpoint_ts,
                            "base_px": base_px,
                            "exit_px": exit_px,
                            "status": status,
                            "gross_pnl": gross_pnl,
                            "net_pnl": net_pnl,
                            "mae_atr": mae / atr,
                            "max_excursion_atr": max_ex / atr,
                            "year": year,
                            "regime_id": reg_id,
                            "bar_index": bar_idx,
                            "is_first": is_first
                        })
                        
            if (r_idx + 1) % 10000 == 0:
                print(f"    processed {r_idx+1}/{len(records)} checkpoints in {time.time()-t_sim:.2f}s")
                
        print(f"  Year completed in {time.time()-t_yr:.2f}s. Total trades accumulated={len(trades)}")
        
    df_tr = pd.DataFrame(trades)
    
    # Generate reports
    print("\nGenerating Scenario 1: All Entries (Baseline)...")
    generate_report(df_tr, "All Entries", OUT / "bracket_grid_all.md")
    
    print("\nGenerating Scenario 2: Entry gated to bar_index <= 10...")
    df_bar10 = df_tr[df_tr["bar_index"] <= 10]
    generate_report(df_bar10, "Entry gated to bar_index <= 10", OUT / "bracket_grid_bar10.md")
    
    print("\nGenerating Scenario 3: Entry gated to first entry per regime...")
    df_first = df_tr[df_tr["is_first"]]
    generate_report(df_first, "First Entry Per Regime Only", OUT / "bracket_grid_first.md")
    
    print("\nGenerating Scenario 4: bar_index <= 10 AND first entry per regime...")
    df_both = df_tr[(df_tr["bar_index"] <= 10) & df_tr["is_first"]]
    generate_report(df_both, "bar_index <= 10 AND First Entry Per Regime", OUT / "bracket_grid_bar10_first.md")
    
    print(f"\nGrid simulation completed successfully in {time.time()-t0:.1f}s.")

if __name__ == "__main__":
    main()
