"""NQ Regime State Transition Atlas - State Memory Analyzer.

Performs walk-forward similarity scoring, evaluates probability calibration,
identifies top stable cells, and generates markdown summaries.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors

PROJECT_ROOT = Path(__file__).parent.parent.parent
OUT = Path("studies/regime_state_transition_atlas/results")

NUMERIC_COLS = [
    "current_pnl_atr", "mfe_so_far_atr", "mae_so_far_atr", "pullback_from_peak_atr",
    "consecutive_no_continuation_bars", "continuation_count_so_far",
    "5s_flip_count_since_1m_start", "ema9_slope_atr", "ema9_slope_change",
    "distance_to_ema9_atr", "volume_percentile_20"
]

CATEGORICAL_COLS = [
    "bar_index_in_regime", "last_3_bar_pattern", "regime_5s_aligned"
]

LABEL_COLS = [
    "next_bar_makes_continuation", "pt050_before_sl050", "pt100_before_sl100",
    "forward_pnl_to_regime_exit_dollars", "future_mfe_from_here_atr", "future_mae_from_here_atr"
]


def check_lift_stability(df: pd.DataFrame, mask: pd.Series, label_col: str, 
                           base_rates_by_year: dict, target_lift_dir: int) -> bool:
    sub = df.loc[mask]
    if len(sub) == 0:
        return False
        
    years_present = sub["year"].unique()
    is_years = [y for y in years_present if y in (2021, 2022, 2023, 2024)]
    
    # Check IS years (at least 3 of 4)
    matching_is_count = 0
    for y in is_years:
        val_y = sub[sub["year"] == y][label_col].mean()
        lift = val_y - base_rates_by_year[y][label_col]
        if np.sign(lift) == target_lift_dir:
            matching_is_count += 1
            
    return matching_is_count >= min(3, len(is_years)) if len(is_years) > 0 else False


def run_walk_forward_scoring_full(df_all: pd.DataFrame, k: int = 500) -> pd.DataFrame:
    print(f"Running full walk-forward KNN scoring (k={k})...")
    scored_records = []
    
    years_to_score = [2022, 2023, 2024, 2025, 2026]
    dist_cols = [f"scaled_{col}" for col in NUMERIC_COLS]
    
    for year in years_to_score:
        df_yr = df_all[df_all["year"] == year].copy()
        if len(df_yr) == 0:
            continue
            
        # Build candidate database
        if year == 2021:
            db = df_all[df_all["year"] == 2021].copy()
        elif year < 2025:
            db = df_all[df_all["year"] < year].copy()
        else:
            db = df_all[df_all["year"] < 2025].copy()
            
        if len(db) < k:
            print(f"  (skipping year {year} - database too small)")
            continue
            
        # Standardize database
        means = db[NUMERIC_COLS].mean()
        stds = db[NUMERIC_COLS].std().replace(0.0, 1.0)
        
        db_scaled = db.copy()
        for col in NUMERIC_COLS:
            db_scaled[f"scaled_{col}"] = (db[col] - means[col]) / stds[col]
            
        # Standardize queries
        queries_scaled = df_yr.copy()
        for col in NUMERIC_COLS:
            queries_scaled[f"scaled_{col}"] = (df_yr[col] - means[col]) / stds[col]
            
        print(f"  Scoring {len(df_yr):,} queries for year {year} against database of size {len(db):,}...")
        
        # Segment by bar_index_in_regime for structural exact match
        for idx_val in sorted(df_yr["bar_index_in_regime"].unique()):
            cand_sub = db_scaled[db_scaled["bar_index_in_regime"] == idx_val]
            q_sub = queries_scaled[queries_scaled["bar_index_in_regime"] == idx_val]
            
            if len(cand_sub) < 10 or len(q_sub) == 0:
                continue
                
            X_cand = cand_sub[dist_cols].values.astype(np.float32)
            X_query = q_sub[dist_cols].values.astype(np.float32)
            
            actual_k = min(k + 50, len(cand_sub))
            nn = NearestNeighbors(n_neighbors=actual_k, algorithm="ball_tree", n_jobs=-1)
            nn.fit(X_cand)
            
            distances, indices = nn.kneighbors(X_query)
            
            # Outcome pools in candidates
            cand_regime_ids = cand_sub["regime_id"].values
            cand_c1 = cand_sub["next_bar_makes_continuation"].values
            cand_rec = cand_sub["next_3_bars_recover_prior_peak"].values
            cand_pt050 = cand_sub["pt050_before_sl050"].values
            cand_pt100 = cand_sub["pt100_before_sl100"].values
            cand_fwd_pnl = cand_sub["forward_pnl_to_regime_exit_dollars"].values
            cand_rem_mfe = cand_sub["remaining_regime_mfe_atr"].values
            cand_rem_mae = cand_sub["remaining_regime_mae_atr"].values
            cand_rem_dur = cand_sub["remaining_regime_duration_bars"].values
            
            # Query properties
            q_regime_ids = q_sub["regime_id"].values
            q_bar_ts = q_sub["bar_ts"].values
            q_checkpoint_px = q_sub["checkpoint_px"].values
            q_direction = q_sub["direction"].values
            q_atr_entry = q_sub["atr_1m_entry"].values
            q_curr_pnl_atr = q_sub["current_pnl_atr"].values
            q_bar_ret = q_sub["bar_return_atr"].values
            
            # Actual query outcomes
            q_c1 = q_sub["next_bar_makes_continuation"].values
            q_pt050 = q_sub["pt050_before_sl050"].values
            q_pt100 = q_sub["pt100_before_sl100"].values
            q_fwd_pnl = q_sub["forward_pnl_to_regime_exit_dollars"].values
            q_exit_in_1 = q_sub["regime_exit_in_next_1_bar"].values
            q_rem_bars = q_sub["remaining_regime_bars"].values
            q_fwd_exit_atr = q_sub["forward_pnl_to_regime_exit_atr"].values
            q_next_1s_open = q_sub["next_1s_open"].values
            
            for i in range(len(q_sub)):
                q_reg_id = q_regime_ids[i]
                cand_idxs = indices[i]
                
                # Exclude neighbors from same regime
                valid_mask = cand_regime_ids[cand_idxs] != q_reg_id
                valid_idxs = cand_idxs[valid_mask][:k]
                
                if len(valid_idxs) == 0:
                    continue
                    
                pred_c1 = cand_c1[valid_idxs].mean()
                pred_rec = cand_rec[valid_idxs].mean()
                pred_pt050 = cand_pt050[valid_idxs].mean()
                pred_pt100 = cand_pt100[valid_idxs].mean()
                pred_fwd_pnl = cand_fwd_pnl[valid_idxs].mean()
                pred_rem_mfe = cand_rem_mfe[valid_idxs].mean()
                pred_rem_mae = cand_rem_mae[valid_idxs].mean()
                pred_rem_dur = cand_rem_dur[valid_idxs].mean()
                
                scored_records.append({
                    "regime_id": q_reg_id,
                    "bar_ts": q_bar_ts[i],
                    "checkpoint_px": q_checkpoint_px[i],
                    "year": year,
                    "bar_index_in_regime": idx_val,
                    "direction": q_direction[i],
                    "atr_1m_entry": q_atr_entry[i],
                    "current_pnl_atr": q_curr_pnl_atr[i],
                    "bar_return_atr": q_bar_ret[i],
                    "is_oos": int(year >= 2025),
                    
                    # Actual outcomes
                    "actual_next_continuation": q_c1[i],
                    "actual_pt050": q_pt050[i],
                    "actual_pt100": q_pt100[i],
                    "actual_forward_pnl": q_fwd_pnl[i],
                    "regime_exit_in_next_1_bar": q_exit_in_1[i],
                    "remaining_regime_bars": q_rem_bars[i],
                    "forward_pnl_to_regime_exit_atr": q_fwd_exit_atr[i],
                    "next_1s_open": q_next_1s_open[i],
                    
                    # Predicted outcomes
                    "pred_c1": pred_c1,
                    "pred_rec": pred_rec,
                    "pred_pt050": pred_pt050,
                    "pred_pt100": pred_pt100,
                    "pred_fwd_pnl": pred_fwd_pnl,
                    "pred_rem_mfe": pred_rem_mfe,
                    "pred_rem_mae": pred_rem_mae,
                    "pred_rem_dur": pred_rem_dur
                })
                
    return pd.DataFrame(scored_records)


def compute_calibration(df_scored: pd.DataFrame, pred_col: str, actual_col: str) -> pd.DataFrame:
    bins = np.linspace(0.0, 1.0, 21)
    labels = [f"{bins[i]*100:.0f}–{bins[i+1]*100:.0f}%" for i in range(20)]
    
    df = df_scored.copy()
    df["bucket"] = pd.cut(df[pred_col], bins=bins, labels=labels, include_lowest=True)
    
    cal_rows = []
    for bucket_name, sub in df.groupby("bucket", observed=False):
        if len(sub) == 0:
            continue
        actual_rate = sub[actual_col].mean()
        cal_rows.append({
            "Predicted Bucket": bucket_name,
            "Count": len(sub),
            "Actual Rate": f"{actual_rate*100:.1f}%" if not pd.isna(actual_rate) else "N/A"
        })
    return pd.DataFrame(cal_rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=500)
    args = ap.parse_args()
    
    print("Loading datasets...")
    state_rows = OUT / "state_rows.parquet"
    fwd_labels = OUT / "forward_labels.parquet"
    if not state_rows.exists() or not fwd_labels.exists():
        print("Error: State rows or forward labels parquet files do not exist. Please build them first."); return
        
    df_states = pd.read_parquet(state_rows)
    df_labels = pd.read_parquet(fwd_labels)
    df_all = pd.merge(df_states, df_labels, on=["regime_id", "bar_ts"])
    
    print(f"Combined size: {len(df_all):,}")
    
    # Pre-calculate base rates by year for stability gate checks
    all_years = df_all["year"].unique()
    base_rates_by_year = {}
    for y in all_years:
        df_y = df_all[df_all["year"] == y]
        base_rates_by_year[y] = {
            "next_bar_makes_continuation": df_y["next_bar_makes_continuation"].mean(),
            "pt050_before_sl050": df_y["pt050_before_sl050"].mean(),
            "pt100_before_sl100": df_y["pt100_before_sl100"].mean()
        }
        
    # Always run walk-forward KNN scoring to ensure fresh features/labels are processed
    scored_path = OUT / "scored_state_rows.parquet"
    df_scored = run_walk_forward_scoring_full(df_all, k=args.k)
    
    # Calculate the three new expectancy-based scores
    df_scored["score_opportunity"] = df_scored["pred_rem_mfe"] - df_scored["pred_rem_mae"]
    df_scored["score_payoff"] = df_scored["pred_rem_mfe"] / (df_scored["pred_rem_mae"] + 1e-9)
    estimated_cost = 7.50 / (20.0 * df_scored["atr_1m_entry"])
    df_scored["score_cost_aware"] = df_scored["score_opportunity"] - estimated_cost
    
    df_scored.to_parquet(scored_path, index=False)
    print(f"Saved results/scored_state_rows.parquet. Size={len(df_scored):,}")
    
    # Compute score decile statistics for the OOS period
    print("Computing score decile calibration...")
    df_oos = df_scored[df_scored["is_oos"] == 1].copy()
    
    decile_dfs = []
    for score_col in ["score_opportunity", "score_payoff", "score_cost_aware"]:
        # Handle deciles
        df_oos[f"{score_col}_decile"] = pd.qcut(df_oos[score_col], q=10, labels=False, duplicates="drop") + 1
        for decile, sub in df_oos.groupby(f"{score_col}_decile"):
            decile_dfs.append({
                "Score Type": score_col,
                "Decile": int(decile),
                "Count": len(sub),
                "Min Score": float(sub[score_col].min()),
                "Max Score": float(sub[score_col].max()),
                "Mean Predicted Score": float(sub[score_col].mean()),
                "Mean Actual PnL ($)": float(sub["actual_forward_pnl"].mean()),
                "Actual Win Rate": float(sub["actual_next_continuation"].mean())
            })
            
    df_deciles = pd.DataFrame(decile_dfs)
    df_deciles.to_parquet(OUT / "payoff_score_deciles.parquet", index=False)
    print("Saved results/payoff_score_deciles.parquet")
    
    # Write oos_score_calibration.md report
    L_cal = []
    L_cal.append("# NQ Regime State memory - OOS Score Calibration Report")
    L_cal.append("")
    L_cal.append("This report evaluates the calibration of the three expectancy-based scores out-of-sample (2025–2026).")
    L_cal.append("A monotonic relationship between the decile rank and the actual PnL validates the predictive edge of the transition atlas.")
    L_cal.append("")
    
    for score_col in ["score_opportunity", "score_payoff", "score_cost_aware"]:
        L_cal.append(f"## {score_col.replace('_', ' ').title()}")
        L_cal.append("| Decile | Count | Min Score | Max Score | Mean Predicted | Mean Actual PnL ($) | Actual Win Rate |")
        L_cal.append("| --- | --- | --- | --- | --- | --- | --- |")
        sub_dec = df_deciles[df_deciles["Score Type"] == score_col]
        for _, r in sub_dec.iterrows():
            L_cal.append(f"| {r['Decile']} | {r['Count']:,} | {r['Min Score']:.4f} | {r['Max Score']:.4f} | {r['Mean Predicted Score']:.4f} | ${r['Mean Actual PnL ($)']:.2f} | {r['Actual Win Rate']*100:.1f}% |")
        L_cal.append("")
    
    (OUT / "oos_score_calibration.md").write_text("\n".join(L_cal), encoding="utf-8")
    print("Wrote results/oos_score_calibration.md")
    
    # Calibration summary
    print("Computing probability calibration curves...")
    cal_c1 = compute_calibration(df_scored[df_scored["is_oos"] == 1], "pred_c1", "actual_next_continuation")
    cal_pt050 = compute_calibration(df_scored[df_scored["is_oos"] == 1], "pred_pt050", "actual_pt050")
    cal_pt100 = compute_calibration(df_scored[df_scored["is_oos"] == 1], "pred_pt100", "actual_pt100")
    
    # Generate Top Similar-State Cells (discrete categorical cells)
    print("Compiling Top Similar-State Cells...")
    top_cells = []
    df_all["bucket_bar_index"] = pd.cut(
        df_all["bar_index_in_regime"],
        bins=[0, 1, 2, 3, 5, 10, 20, 30],
        labels=["1", "2", "3", "4–5", "6–10", "11–20", "21–30"]
    )
    
    for (bg, pat, align), sub in df_all.groupby(["bucket_bar_index", "last_3_bar_pattern", "regime_5s_aligned"], observed=False):
        sub_is = sub[sub["year"] < 2025]
        sub_oos = sub[sub["year"] >= 2025]
        
        n_is = len(sub_is)
        n_oos = len(sub_oos)
        
        if n_is < 500:
            continue
            
        for label in ["next_bar_makes_continuation", "pt050_before_sl050", "pt100_before_sl100"]:
            pred_rate = sub_is[label].mean()
            actual_rate = sub_oos[label].mean() if n_oos > 0 else np.nan
            
            df_is_all = df_all[df_all["year"] < 2025]
            base_is = df_is_all[label].mean()
            lift_is = pred_rate - base_is
            
            df_oos_all = df_all[df_all["year"] >= 2025]
            base_oos = df_oos_all[label].mean()
            lift_oos = actual_rate - base_oos if n_oos > 0 else np.nan
            
            stable = check_lift_stability(df_all, sub.index, label, base_rates_by_year, 1)
            if stable and lift_is >= 0.05:
                top_cells.append({
                    "bar_index_group": bg,
                    "last_3_pattern": pat,
                    "regime_5s_aligned": align,
                    "label": label,
                    "n_is": n_is,
                    "n_oos": n_oos,
                    "predicted_rate": pred_rate,
                    "actual_oos_rate": actual_rate,
                    "oos_lift": lift_oos,
                    "is_lift": lift_is,
                    "oos_net_ev_050": sub_oos["net_ev_050_primary"].mean() if (label == "pt050_before_sl050" and n_oos > 0) else np.nan,
                    "oos_net_ev_100": sub_oos["net_ev_100_primary"].mean() if (label == "pt100_before_sl100" and n_oos > 0) else np.nan
                })
                
    df_top = pd.DataFrame(top_cells)
    if not df_top.empty:
        df_top = df_top.sort_values("is_lift", ascending=False)
    df_top.to_parquet(OUT / "top_state_cells.parquet", index=False)
    print(f"Top cells found: {len(df_top)}")
    
    # Generate Opportunity Leaderboard (top 100 cells by IS opportunity score)
    print("Compiling Opportunity Leaderboard...")
    df_scored_all = pd.merge(df_scored, df_all[["regime_id", "bar_ts", "last_3_bar_pattern", "regime_5s_aligned", "bucket_bar_index"]], on=["regime_id", "bar_ts"])
    
    opp_cells = []
    for (bg, pat, align), sub in df_scored_all.groupby(["bucket_bar_index", "last_3_bar_pattern", "regime_5s_aligned"], observed=False):
        sub_is = sub[sub["year"] < 2025]
        sub_oos = sub[sub["year"] >= 2025]
        
        n_is = len(sub_is)
        n_oos = len(sub_oos)
        
        if n_is < 100:
            continue
            
        mean_opp_is = sub_is["score_opportunity"].mean()
        mean_opp_oos = sub_oos["score_opportunity"].mean() if n_oos > 0 else np.nan
        mean_payoff_is = sub_is["score_payoff"].mean()
        mean_payoff_oos = sub_oos["score_payoff"].mean() if n_oos > 0 else np.nan
        mean_cost_is = sub_is["score_cost_aware"].mean()
        mean_cost_oos = sub_oos["score_cost_aware"].mean() if n_oos > 0 else np.nan
        mean_pnl_is = sub_is["actual_forward_pnl"].mean()
        mean_pnl_oos = sub_oos["actual_forward_pnl"].mean() if n_oos > 0 else np.nan
        
        opp_cells.append({
            "bar_index_group": bg,
            "last_3_pattern": pat,
            "regime_5s_aligned": align,
            "n_is": n_is,
            "n_oos": n_oos,
            "mean_opportunity_is": mean_opp_is,
            "mean_opportunity_oos": mean_opp_oos,
            "mean_payoff_is": mean_payoff_is,
            "mean_payoff_oos": mean_payoff_oos,
            "mean_cost_aware_is": mean_cost_is,
            "mean_cost_aware_oos": mean_cost_oos,
            "mean_pnl_is": mean_pnl_is,
            "mean_pnl_oos": mean_pnl_oos
        })
        
    df_leaderboard = pd.DataFrame(opp_cells)
    if not df_leaderboard.empty:
        df_leaderboard = df_leaderboard.sort_values("mean_opportunity_is", ascending=False).head(100)
    df_leaderboard.to_parquet(OUT / "opportunity_leaderboard.parquet", index=False)
    print(f"Saved results/opportunity_leaderboard.parquet. Cells={len(df_leaderboard)}")
    
    # Write calibration reports
    L = []
    L.append("# NQ Regime State memory - Statistical Memory Summary")
    L.append("")
    L.append("## 1. Out-of-Sample Probability Calibration")
    L.append("We evaluated the calibration of predicted outcome probabilities computed using KNN (k=500) historical similarity. ")
    L.append("If predicted probabilities are close to actual OOS rates, the statistical memory has robust predictive content.")
    L.append("")
    
    L.append("### A. Next-Bar Continuation Calibration")
    L.append("| Predicted Bucket | Count | Actual Rate |")
    L.append("| --- | --- | --- |")
    for _, r in cal_c1.iterrows():
        L.append(f"| {r['Predicted Bucket']} | {r['Count']:,} | {r['Actual Rate']} |")
    L.append("")
    
    L.append("### B. 0.50 ATR Race Win Rate Calibration")
    L.append("| Predicted Bucket | Count | Actual Rate |")
    L.append("| --- | --- | --- |")
    for _, r in cal_pt050.iterrows():
        L.append(f"| {r['Predicted Bucket']} | {r['Count']:,} | {r['Actual Rate']} |")
    L.append("")
    
    L.append("### C. 1.00 ATR Race Win Rate Calibration")
    L.append("| Predicted Bucket | Count | Actual Rate |")
    L.append("| --- | --- | --- |")
    for _, r in cal_pt100.iterrows():
        L.append(f"| {r['Predicted Bucket']} | {r['Count']:,} | {r['Actual Rate']} |")
    L.append("")
    
    L.append("---")
    L.append("")
    L.append("## 2. Statistical Memory Adjudication")
    
    def extract_pct(val_str):
        if val_str == "N/A" or not isinstance(val_str, str):
            return np.nan
        return float(val_str.replace("%", ""))

    # MONEY-BASED ADJUDICATION (audit v5). A monotonic NEXT-BAR-CONTINUATION
    # calibration is near-tautological (the KNN exact-matches bar_index, so it
    # mostly re-reads "how young/strong is the regime") and does NOT imply a
    # tradeable edge. The edge claim therefore requires BOTH:
    #   (1) the TRADEABLE race calibration (PT-before-SL) to actually span, and
    #   (2) the top OOS opportunity-decile to be net-positive after cost.
    EST_COST = 7.50
    cal_pt100["act_pct"] = cal_pt100["Actual Rate"].apply(extract_pct)
    race_valid = cal_pt100.dropna()
    race_range = (race_valid["act_pct"].max() - race_valid["act_pct"].min()) if len(race_valid) >= 3 else 0.0
    race_spans = race_range > 3.0

    cont_valid = cal_c1.copy()
    cont_valid["act_pct"] = cont_valid["Actual Rate"].apply(extract_pct)
    cont_valid = cont_valid.dropna()
    cont_range = (cont_valid["act_pct"].max() - cont_valid["act_pct"].min()) if len(cont_valid) >= 3 else 0.0

    opp_dec = df_deciles[df_deciles["Score Type"] == "score_opportunity"].sort_values("Decile")
    top_dec_pnl = float(opp_dec["Mean Actual PnL ($)"].iloc[-1]) if len(opp_dec) else np.nan
    top_dec_net = top_dec_pnl - EST_COST
    n_dec_pos_net = int((opp_dec["Mean Actual PnL ($)"] - EST_COST > 0).sum()) if len(opp_dec) else 0

    tradeable = race_spans and (top_dec_net > 0)
    if tradeable:
        L.append("> [!TIP]\n"
                 f"> **Tradeable Edge (money-based).** The PT-before-SL race calibration spans "
                 f"{race_range:.1f}pp AND the top opportunity decile is net-positive after cost "
                 f"(${top_dec_net:+.2f}/trade). This warrants a costed walk-forward backtest.")
    else:
        L.append("> [!WARNING]\n"
                 f"> **No tradeable edge.** The next-bar continuation calibration spans {cont_range:.1f}pp, but "
                 f"this is near-tautological (KNN exact-matches `bar_index_in_regime`; it mostly re-reads regime "
                 f"age/strength). The **tradeable** PT-before-SL race calibration spans only {race_range:.1f}pp "
                 f"(flat), and the top OOS opportunity decile is **${top_dec_net:+.2f}/trade after cost** "
                 f"({n_dec_pos_net}/10 deciles net-positive). Monotonic continuation ≠ tradeable edge; see the "
                 "policy backtest for the deployment-grade money verdict.")
                 
    (OUT / "state_memory_summary.md").write_text("\n".join(L), encoding="utf-8")
    print("Wrote results/state_memory_summary.md")
    
    # Similar State Examples
    L_ex = []
    L_ex.append("# Similar State Examples")
    L_ex.append("This document shows specific query states and their K-Nearest Neighbors' outcomes.")
    L_ex.append("")
    
    # Pick 3 representative queries from OOS
    df_oos_queries = df_scored[df_scored["is_oos"] == 1]
    if not df_oos_queries.empty:
        sample_queries = df_oos_queries.sample(n=min(3, len(df_oos_queries)), random_state=42)
        for _, q_row in sample_queries.iterrows():
            L_ex.append(f"### Query: Regime {q_row['regime_id']} Bar {q_row['bar_index_in_regime']} ({'Long' if q_row['direction']==1 else 'Short'})")
            L_ex.append(f"- **Predicted Continuation Rate:** {q_row['pred_c1']*100:.1f}%")
            L_ex.append(f"- **Predicted 0.50 ATR Race Win Rate:** {q_row['pred_pt050']*100:.1f}%")
            L_ex.append(f"- **Predicted Forward PnL:** ${q_row['pred_fwd_pnl']:.2f}")
            L_ex.append(f"- **Actual Next Bar Continuation:** {'Yes' if q_row['actual_next_continuation'] else 'No'}")
            L_ex.append(f"- **Actual 0.50 ATR Race Win:** {'Yes' if q_row['actual_pt050'] else 'No'}")
            L_ex.append(f"- **Actual Forward PnL:** ${q_row['actual_forward_pnl']:.2f}")
            L_ex.append("")
            
    (OUT / "similar_state_examples.md").write_text("\n".join(L_ex), encoding="utf-8")
    print("Wrote results/similar_state_examples.md")


if __name__ == "__main__":
    main()
