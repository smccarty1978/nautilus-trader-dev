import pandas as pd
import numpy as np
from pathlib import Path
import time

OUT = Path("studies/regime_state_transition_atlas/results")

def main():
    t0 = time.time()
    scored_parquet = OUT / "scored_state_rows.parquet"
    state_parquet = OUT / "state_rows.parquet"
    label_parquet = OUT / "forward_labels.parquet"
    
    print("Loading parquets...")
    df_scored = pd.read_parquet(scored_parquet)
    df_states = pd.read_parquet(state_parquet)
    df_labels = pd.read_parquet(label_parquet)
    print(f"Loaded in {time.time() - t0:.2f}s")
    
    # Merge them to get all features, scores, and labels in one place
    print("Merging dataframes...")
    df_all = pd.merge(df_scored, df_states[["regime_id", "bar_ts", "regime_start_ts", "atr_1m_entry"]], on=["regime_id", "bar_ts"])
    df_all = pd.merge(df_all, df_labels, on=["regime_id", "bar_ts"])
    
    # Rename duplicated columns to avoid KeyErrors
    if "next_1s_open_x" in df_all.columns:
        df_all = df_all.rename(columns={"next_1s_open_x": "next_1s_open"})
    elif "next_1s_open_y" in df_all.columns:
        df_all = df_all.rename(columns={"next_1s_open_y": "next_1s_open"})
        
    if "atr_1m_entry_x" in df_all.columns:
        df_all = df_all.rename(columns={"atr_1m_entry_x": "atr_1m_entry"})
    elif "atr_1m_entry_y" in df_all.columns:
        df_all = df_all.rename(columns={"atr_1m_entry_y": "atr_1m_entry"})
        
    df_all = df_all.sort_values("bar_ts").copy()
    print(f"Merged and sorted in {time.time() - t0:.2f}s")
    
    # Calculate thresholds dynamically for 2025 and 2026 upfront
    score_col = "score_opportunity"
    
    print("Calculating thresholds upfront...")
    df_train_2025 = df_all[df_all["year"].isin([2021, 2022, 2023, 2024])]
    enter_thr_2025 = np.percentile(df_train_2025[score_col].values, 99)
    exit_thr_2025 = np.percentile(df_train_2025[score_col].values, 50)
    
    df_train_2026 = df_all[df_all["year"].isin([2021, 2022, 2023, 2024, 2025])]
    enter_thr_2026 = np.percentile(df_train_2026[score_col].values, 99)
    exit_thr_2026 = np.percentile(df_train_2026[score_col].values, 50)
    
    print(f"2025 enter threshold: {enter_thr_2025:.4f}, exit threshold: {exit_thr_2025:.4f}")
    print(f"2026 enter threshold: {enter_thr_2026:.4f}, exit threshold: {exit_thr_2026:.4f}")
    
    # Get regimes list sorted by first occurrence ts
    print("Building causal map...")
    regime_order = df_all["regime_id"].drop_duplicates().tolist()
    
    # Vectorized groupby aggregate to get entry/exit/hold bars for each regime
    agg_df = df_all.groupby("regime_id").agg(
        entry_px=("next_1s_open", "first"),
        entry_ts=("bar_ts", "first"),
        last_px=("next_1s_open", "last"),
        last_ts=("bar_ts", "last"),
        size=("regime_id", "size")
    )
    agg_df = agg_df.reindex(regime_order)
    
    # Compute exit_px, exit_ts, hold_bars causally
    agg_df["exit_px"] = agg_df["entry_px"].shift(-1)
    agg_df["exit_ts"] = agg_df["entry_ts"].shift(-1)
    agg_df["hold_bars"] = agg_df["size"] + 1
    
    # Fill the last row's exit_px, exit_ts, and hold_bars
    last_r_id = regime_order[-1]
    agg_df.loc[last_r_id, "exit_px"] = agg_df.loc[last_r_id, "last_px"]
    agg_df.loc[last_r_id, "exit_ts"] = agg_df.loc[last_r_id, "last_ts"]
    agg_df.loc[last_r_id, "hold_bars"] = agg_df.loc[last_r_id, "size"]
    
    causal_map = agg_df[["entry_px", "entry_ts", "exit_px", "exit_ts", "hold_bars"]].to_dict("index")
    print(f"Causal map built in {time.time() - t0:.2f}s")
    
    # Only iterate over 2025 and 2026 rows for the policy simulation
    print("Running policy simulation...")
    df_oos = df_all[df_all["year"].isin([2025, 2026])].copy()
    
    # To make iteration faster, we can convert to dictionary or record format
    oos_records = df_oos.to_dict("records")
    
    policy_trades = []
    active_trade = None
    
    for row in oos_records:
        r_id = row["regime_id"]
        ts = row["bar_ts"]
        next_open = row["next_1s_open"]
        bar_idx = row["bar_index_in_regime"]
        direction = row["direction"]
        score = row[score_col]
        year = row["year"]
        
        enter_thr = enter_thr_2025 if year == 2025 else enter_thr_2026
        exit_thr = exit_thr_2025 if year == 2025 else exit_thr_2026
        
        if active_trade is not None:
            if active_trade["regime_id"] != r_id:
                # Regime flipped or changed
                px_exit = next_open
                pnl_usd = (px_exit - active_trade["entry_px"]) * active_trade["direction"] * 20.0
                hold_bars = causal_map[active_trade["regime_id"]]["hold_bars"] - (active_trade["entry_bar_idx"] - 1)
                
                policy_trades.append({
                    "regime_id": active_trade["regime_id"],
                    "entry_ts": active_trade["entry_ts"],
                    "entry_bar_idx": active_trade["entry_bar_idx"],
                    "entry_px": active_trade["entry_px"],
                    "exit_ts": ts,
                    "exit_bar_idx": active_trade["entry_bar_idx"] + hold_bars,
                    "exit_px": px_exit,
                    "direction": active_trade["direction"],
                    "gross_pnl": pnl_usd,
                    "hold_bars": hold_bars,
                    "exit_reason": "regime_exit",
                    "year": active_trade["year"],
                    "entry_score": active_trade["entry_score"],
                    "remaining_regime_mfe_atr": active_trade["remaining_regime_mfe_atr"],
                    "remaining_regime_duration_bars": active_trade["remaining_regime_duration_bars"]
                })
                active_trade = None
            else:
                if score <= exit_thr:
                    px_exit = next_open
                    pnl_usd = (px_exit - active_trade["entry_px"]) * direction * 20.0
                    hold_bars = bar_idx - active_trade["entry_bar_idx"]
                    
                    policy_trades.append({
                        "regime_id": r_id,
                        "entry_ts": active_trade["entry_ts"],
                        "entry_bar_idx": active_trade["entry_bar_idx"],
                        "entry_px": active_trade["entry_px"],
                        "exit_ts": ts,
                        "exit_bar_idx": bar_idx,
                        "exit_px": px_exit,
                        "direction": direction,
                        "gross_pnl": pnl_usd,
                        "hold_bars": hold_bars,
                        "exit_reason": "exit_signal",
                        "year": active_trade["year"],
                        "entry_score": active_trade["entry_score"],
                        "remaining_regime_mfe_atr": active_trade["remaining_regime_mfe_atr"],
                        "remaining_regime_duration_bars": active_trade["remaining_regime_duration_bars"]
                    })
                    active_trade = None
                    
        if active_trade is None:
            if score >= enter_thr:
                active_trade = {
                    "regime_id": r_id,
                    "entry_ts": ts,
                    "entry_px": next_open,
                    "entry_bar_idx": bar_idx,
                    "direction": direction,
                    "year": year,
                    "entry_score": score,
                    "remaining_regime_mfe_atr": row["remaining_regime_mfe_atr_x"] if "remaining_regime_mfe_atr_x" in row else row["remaining_regime_mfe_atr"],
                    "remaining_regime_duration_bars": row["remaining_regime_duration_bars_x"] if "remaining_regime_duration_bars_x" in row else row["remaining_regime_duration_bars"]
                }
    print(f"Simulation completed in {time.time() - t0:.2f}s")
    
    df_trades = pd.DataFrame(policy_trades)
    
    # 1. Print Top 20 False Positives details
    losers = df_trades[df_trades["gross_pnl"] < 0]
    group_d = losers.sort_values("entry_score", ascending=False).head(20)
    
    print("\n=== TOP 20 FALSE POSITIVES (GROSS PNL < 0) ===")
    print(group_d[["regime_id", "entry_score", "gross_pnl", "remaining_regime_mfe_atr", "remaining_regime_duration_bars", "exit_reason"]].to_string(index=False))
    
    # 2. Detailed diagnostics for Regime 202502365 if it exists in data
    print("\n=== REGIME 202502365 DETAILED DIAGNOSTICS ===")
    reg_id = 202502365
    df_reg = df_all[df_all["regime_id"] == reg_id].sort_values("bar_ts")
    if df_reg.empty:
        # Let's see if there is a close matches or list of regimes
        print(f"Regime {reg_id} not found. Available regimes in OOS trades:")
        print(df_trades["regime_id"].head(10).tolist())
        # Let's find any regime close to that ID
        similar = df_all[df_all["regime_id"].astype(str).str.contains("202502365")]
        if not similar.empty:
            print("Found similar regime ID:", similar["regime_id"].unique())
            reg_id = int(similar["regime_id"].iloc[0])
            df_reg = df_all[df_all["regime_id"] == reg_id].sort_values("bar_ts")
            
    if not df_reg.empty:
        # Let's print out the details
        first_bar = df_reg.iloc[0]
        direction = int(first_bar["direction"])
        atr = float(first_bar["atr_1m_entry"])
        
        # Check if the policy entered this regime
        trade_rows = df_trades[df_trades["regime_id"] == reg_id]
        if not trade_rows.empty:
            trade = trade_rows.iloc[0]
            print(f"Policy Entry Bar Index: {trade['entry_bar_idx']}")
            print(f"Policy Entry Price: {trade['entry_px']:.2f}")
            print(f"Policy Exit Price: {trade['exit_px']:.2f}")
            print(f"Policy Gross PnL: ${trade['gross_pnl']:.2f}")
            print(f"Policy Exit Reason: {trade['exit_reason']}")
            print(f"Policy Hold Bars: {trade['hold_bars']}")
            
            entry_row = df_reg[df_reg["bar_index_in_regime"] == trade['entry_bar_idx']].iloc[0]
            print(f"Score at entry: {entry_row['score_opportunity']:.4f}")
            
            # 1. Total regime MFE after entry
            rem_mfe_atr = entry_row["remaining_regime_mfe_atr"]
            rem_mfe_pts = rem_mfe_atr * atr
            print(f"Remaining Regime MFE after entry (ATR): {rem_mfe_atr:.4f} ATR ({rem_mfe_pts:.2f} points)")
            
            # 2. Remaining regime duration after entry
            rem_dur = entry_row["remaining_regime_duration_bars"]
            print(f"Remaining Regime Duration after entry (bars): {rem_dur}")
            
            # 4. MFE before exit (or Max Checkpoint PnL during holding)
            hold_rows = df_reg[(df_reg["bar_index_in_regime"] > trade['entry_bar_idx']) & 
                               (df_reg["bar_index_in_regime"] <= trade['exit_bar_idx'])]
            if not hold_rows.empty:
                max_check_pnl = hold_rows["current_pnl_atr"].max()
                print(f"Max Checkpoint PnL during holding (ATR): {max_check_pnl:.4f} ATR")
        else:
            print("Policy did not enter this regime.")
            
        print("\nAll checkpoints inside this regime:")
        print(df_reg[["bar_index_in_regime", "score_opportunity", "current_pnl_atr", "remaining_regime_mfe_atr", "remaining_regime_duration_bars"]].to_string(index=False))

if __name__ == "__main__":
    main()
