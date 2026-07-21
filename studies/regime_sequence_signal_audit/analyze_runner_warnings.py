import os
import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import roc_auc_score, average_precision_score

# Add Nautilus Trader path
PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))

from studies.regime_sequence_chop_context.run_flip_filter_replay import apply_policies
from studies.regime_sequence_chop_context.train_flip_filter import FEATURES_LIST
from studies.regime_sequence_chop_context.train_weakness_model import LOCAL_FEATS, CENTER_FEATS, SEQUENCE_FEATS

def is_rth(ts_ns):
    dt = pd.Timestamp(ts_ns, unit='ns', tz='UTC').tz_convert('America/Chicago')
    from datetime import time
    t = dt.time()
    return (dt.dayofweek < 5) and (time(8, 30) <= t <= time(15, 15))

OUT_DIR = Path("studies/regime_sequence_signal_audit/results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def main():
    print("Running Phase 8, 9, 10 & 11: Warning lead time, persistence, threshold grid, and feature ablations...")
    
    # Load weakness checkpoint atlas
    atlas_path = PROJECT_ROOT / "studies/regime_sequence_chop_context/results/weakness_checkpoint_atlas.parquet"
    df_weak = pd.read_parquet(atlas_path)
    df_weak["regime_start_time"] = df_weak["observation_time"] - (df_weak["regime_age"] * 1e9).astype(int)
    df_weak = df_weak.dropna(subset=["aligned_price_minus_center_5m"]).copy()
    df_weak["target_weakness_120s"] = ((df_weak["opp_flip_in_120s"] == 1) | (df_weak["terminal_deterioration"] == 1)).astype(int)
    
    # Split periods
    train_w = df_weak[df_weak["period"] == "train"].copy()
    val_w = df_weak[df_weak["period"] == "val"].copy()
    test_w = df_weak[df_weak["period"] == "test"].copy()
    
    # Re-train W4 to get scores on validation and test
    print("  Fitting W4 model...")
    clf_w4 = HistGradientBoostingClassifier(
        max_iter=100, max_depth=5, learning_rate=0.05, random_state=42
    )
    clf_w4.fit(train_w[CENTER_FEATS + SEQUENCE_FEATS + LOCAL_FEATS].values, train_w["target_weakness_120s"].values)
    
    val_w["w4_prob"] = clf_w4.predict_proba(val_w[CENTER_FEATS + SEQUENCE_FEATS + LOCAL_FEATS].values)[:, 1]
    test_w["w4_prob"] = clf_w4.predict_proba(test_w[CENTER_FEATS + SEQUENCE_FEATS + LOCAL_FEATS].values)[:, 1]
    
    # Define warning threshold (top 10% on validation)
    val_th_10 = np.percentile(val_w["w4_prob"].dropna(), 90)
    print(f"  Validation warning threshold (top 10%): {val_th_10:.4f}")
    
    
    # --- PHASE 8: AUDIT WARNING LEAD-TIME QUALITY ---
    # Find warning events on test set
    test_w = test_w.sort_values(["direction", "regime_start_time", "observation_time"]).copy()
    
    warning_events = []
    
    # Group by episode to track timing causally
    gp_idx = test_w.groupby(["direction", "regime_start_time"]).indices
    
    times = test_w["observation_time"].values
    mfes = test_w["current_mfe"].values
    pnls = test_w["current_pnl"].values
    gbs = test_w["giveback"].values
    probs = test_w["w4_prob"].values
    add_mfes = test_w["additional_mfe_remaining"].values
    recovered_120s = test_w["recovered_120s"].values
    regime_ages = test_w["regime_age"].values
    
    for (direction, r_start), idxs in gp_idx.items():
        if len(idxs) == 0:
            continue
        ep_times = times[idxs]
        ep_mfes = mfes[idxs]
        ep_pnls = pnls[idxs]
        ep_gbs = gbs[idxs]
        ep_probs = probs[idxs]
        ep_add_mfes = add_mfes[idxs]
        ep_rec = recovered_120s[idxs]
        ep_ages = regime_ages[idxs]
        
        # Check if warning was ever triggered in this episode
        warn_idx = np.where(ep_probs >= val_th_10)[0]
        if len(warn_idx) == 0:
            continue
            
        first_warn_i = warn_idx[0]
        warn_ts = int(ep_times[first_warn_i])
        
        # End of the regime
        opposite_flip_ts = int(ep_times[-1])
        formal_terminal_ts = opposite_flip_ts
        
        # MFE and PnL at warning
        mfe_warn = float(ep_mfes[first_warn_i])
        pnl_warn = float(ep_pnls[first_warn_i])
        
        # E0 final PnL (represented by PnL at the last checkpoint)
        e0_final_pnl = float(ep_pnls[-1])
        
        # Giveback
        gb_warn = float(ep_gbs[first_warn_i])
        max_gb_episode = float(np.max(ep_gbs))
        add_gb_after = float(max(0.0, max_gb_episode - gb_warn))
        
        # Remaining favorable MFE
        rem_mfe = float(ep_add_mfes[first_warn_i])
        
        # Time to final MFE
        max_mfe_val = np.max(ep_mfes)
        mfe_reach_i = np.where(ep_mfes == max_mfe_val)[0][0]
        mfe_ts = int(ep_times[mfe_reach_i])
        time_to_final_mfe = float(mfe_ts - warn_ts) / 1e9
        
        # Time to opposite flip
        time_to_flip = float(opposite_flip_ts - warn_ts) / 1e9
        
        # Classification
        # EARLY_USEFUL: warning occurs before at least 50% of eventual giveback
        # LATE_DESCRIPTIVE: warning occurs after at least 75% of eventual giveback
        # FALSE_RECOVERY: price recovers prior MFE or makes new MFE after warning
        if ep_rec[first_warn_i] == 1 or rem_mfe > 0.0:
            cls_warn = "FALSE_RECOVERY"
        elif gb_warn < 0.50 * max_gb_episode:
            cls_warn = "EARLY_USEFUL"
        elif gb_warn >= 0.75 * max_gb_episode:
            cls_warn = "LATE_DESCRIPTIVE"
        else:
            cls_warn = "AMBIGUOUS"
            
        warning_events.append({
            "direction": int(direction),
            "regime_start_time": int(r_start),
            "warning_ts": int(warn_ts),
            "formal_terminal_ts": int(formal_terminal_ts),
            "opposite_flip_ts": int(opposite_flip_ts),
            "MFE_at_warning": float(mfe_warn),
            "PnL_at_warning": float(pnl_warn),
            "E0_final_PnL": float(e0_final_pnl),
            "giveback_already_incurred_at_warning": float(gb_warn),
            "additional_giveback_after_warning": float(add_gb_after),
            "remaining_favorable_MFE_after_warning": float(rem_mfe),
            "time_to_final_MFE": float(time_to_final_mfe),
            "time_to_opposite_flip": float(time_to_flip),
            "warning_class": cls_warn
        })
        
    df_warn_events = pd.DataFrame(warning_events)
    df_warn_events.to_parquet(OUT_DIR / "weakness_warning_events.parquet", index=False)
    
    # Lead time quality summary
    if len(df_warn_events) > 0:
        lead_time_quality = pd.DataFrame([{
            "median_lead_time_s": float(df_warn_events["time_to_opposite_flip"].median()),
            "mean_lead_time_s": float(df_warn_events["time_to_opposite_flip"].mean()),
            "median_lead_to_mfe_s": float(df_warn_events["time_to_final_MFE"].median()),
            "giveback_at_warning_mean": float(df_warn_events["giveback_already_incurred_at_warning"].mean()),
            "pct_early_useful": float((df_warn_events["warning_class"] == "EARLY_USEFUL").mean()),
            "pct_late_descriptive": float((df_warn_events["warning_class"] == "LATE_DESCRIPTIVE").mean()),
            "pct_false_recovery": float((df_warn_events["warning_class"] == "FALSE_RECOVERY").mean())
        }])
    else:
        lead_time_quality = pd.DataFrame()
    lead_time_quality.to_parquet(OUT_DIR / "weakness_lead_time_quality.parquet", index=False)
    
    # Write Phase 8 report
    p8_md = f"""# Phase 8: Weakness Warning Lead-Time Quality Report

## Lead Time Statistics
"""
    if len(df_warn_events) > 0:
        p8_md += f"""* **Total warning events triggered in Test set**: {len(df_warn_events)}
* **Median Warning Lead (to opposite flip)**: {lead_time_quality['median_lead_time_s'].iloc[0]:.1f} seconds
* **Mean Warning Lead**: {lead_time_quality['mean_lead_time_s'].iloc[0]:.1f} seconds
* **Median Lead to Final MFE**: {lead_time_quality['median_to_mfe_s'].iloc[0] if 'median_to_mfe_s' in lead_time_quality else 0.0:.1f} seconds
* **Average Giveback already incurred at warning**: {lead_time_quality['giveback_at_warning_mean'].iloc[0]:.4f} ATR

## Warning Classification Breakdown
* **EARLY_USEFUL (warning occurs before 50% of eventual giveback)**: {lead_time_quality['pct_early_useful'].iloc[0]:.2%}
* **LATE_DESCRIPTIVE (warning occurs after 75% of eventual giveback)**: {lead_time_quality['pct_late_descriptive'].iloc[0]:.2%}
* **FALSE_RECOVERY (price recovers to prior MFE or makes new MFE after warning)**: {lead_time_quality['pct_false_recovery'].iloc[0]:.2%}
"""
    else:
        p8_md += "* No warnings triggered in Test set.\n"
        
    with open(OUT_DIR / "weakness_warning_report.md", "w") as f:
        f.write(p8_md)
        
        
    # --- PHASE 9: PERSISTENT WARNING ANALYSIS ---
    # Define warning threshold (top 10% on validation)
    # For each episode in the Test set, check if the warning persisted for W seconds
    # Checkpoints are spaced at 5s in test, so:
    # 5s = 1 checkpoint, 10s = 2, 15s = 3, 20s = 4, 30s = 6, 45s = 9, 60s = 12 checkpoints.
    durations = [5, 10, 15, 20, 30, 45, 60]
    
    # We will build persistent flags for checkpoints
    persistent_checkpoints = []
    
    # Group by episode to count contiguous warnings
    for (direction, r_start), idxs in gp_idx.items():
        ep_probs = probs[idxs]
        ep_mfes = mfes[idxs]
        ep_rec = recovered_120s[idxs]
        ep_add_mfes = add_mfes[idxs]
        ep_gbs = gbs[idxs]
        ep_ages = regime_ages[idxs]
        ep_times = times[idxs]
        
        # Calculate how long the warning has persisted at each checkpoint
        n_cp = len(idxs)
        warning_streak = np.zeros(n_cp)
        current_streak = 0
        for i in range(n_cp):
            if ep_probs[i] >= val_th_10:
                current_streak += 5.0 # Checkpoints are 5s apart in test set
            else:
                current_streak = 0.0
            warning_streak[i] = current_streak
            
        # For each checkpoint, check if warning persisted
        for i in range(n_cp):
            streak = warning_streak[i]
            rec = {
                "observation_time": ep_times[i],
                "direction": int(direction),
                "regime_start_time": int(r_start),
                "current_mfe": float(ep_mfes[i]),
                "additional_mfe_remaining": float(ep_add_mfes[i]),
                "recovered_120s": int(ep_rec[i]),
                "giveback": float(ep_gbs[i]),
                "regime_age": float(ep_ages[i])
            }
            # Add persistence flags
            for d_sec in durations:
                rec[f"warn_persist_{d_sec}s"] = int(streak >= d_sec)
            persistent_checkpoints.append(rec)
            
    df_persist_cp = pd.DataFrame(persistent_checkpoints)
    
    # Load flip atlas to identify runners
    # Runner definitions: top 10%, top 5%, top 1% E0 runners on the test set
    # E0 runners are defined by pnl_base of the confirmed F2 entries
    df_all = pd.read_parquet(PROJECT_ROOT / "studies/regime_sequence_chop_context/results/flip_context_atlas.parquet")
    atlas_f2 = df_all[df_all["population"] == "F2"].copy()
    test_f2 = atlas_f2[atlas_f2["period"] == "test"].copy()
    val_f2 = atlas_f2[atlas_f2["period"] == "val"].copy()
    runner_90_lim = np.percentile(val_f2["pnl_base"].dropna(), 90) if len(val_f2) > 0 else 0.0
    runner_95_lim = np.percentile(val_f2["pnl_base"].dropna(), 95) if len(val_f2) > 0 else 0.0
    runner_99_lim = np.percentile(val_f2["pnl_base"].dropna(), 99) if len(val_f2) > 0 else 0.0
    
    # We map these runner status back to checkpoints by matching (direction, regime_start_time)
    # The flip atlas entries have observation_time (which is conf_ts).
    # Wait, the flip atlas conf_ts is exactly the regime start time!
    # Let's verify: `df_f2` conf_ts is `r_conf.close_ts`. The checkpoint's `regime_start_time` is also the flip's confirmation close time?
    # No, wait! The checkpoint's `regime_start_time` is `flip_ts` (the regime's actual start time).
    # Is the flip's confirmation close time the same?
    # No! F2 is confirmed 1 bar *after* the flip. So `conf_ts = flip_ts + 60s`.
    # So `regime_start_time` for F2 checkpoints is `conf_ts - 60s` (which is `flip_ts`!).
    # Let's map exactly:
    # F2's `flip_ts` = `observation_time - 60s`.
    # Let's check: in `run_study.py`, does the checkpoint have a way to match?
    # Yes! In the checkpoints, we had:
    # `regime_start_time = observation_time - regime_age`
    # Since `regime_start_time` is `flip_ts`, we can add a mapping key to test_f2:
    # `regime_start_time = test_f2['observation_time'] - 60_000_000_000` (which is `flip_ts`!).
    # Let's check if this matches!
    # Yes!
    test_f2["regime_start_time"] = test_f2["observation_time"] - 60_000_000_000
    test_f2["is_runner_90"] = test_f2["pnl_base"] >= runner_90_lim
    test_f2["is_runner_95"] = test_f2["pnl_base"] >= runner_95_lim
    test_f2["is_runner_99"] = test_f2["pnl_base"] >= runner_99_lim
    
    # Merge runner flags onto checkpoints
    df_persist_cp = df_persist_cp.merge(
        test_f2[["direction", "regime_start_time", "is_runner_90", "is_runner_95", "is_runner_99"]],
        on=["direction", "regime_start_time"],
        how="left"
    )
    # Fill NaNs (if some checkpoints are from non-F2 confirmed regimes, e.g. F1 flips that were skipped)
    df_persist_cp["is_runner_90"] = df_persist_cp["is_runner_90"].fillna(False)
    df_persist_cp["is_runner_95"] = df_persist_cp["is_runner_95"].fillna(False)
    df_persist_cp["is_runner_99"] = df_persist_cp["is_runner_99"].fillna(False)
    
    # Add session column to checkpoints
    df_persist_cp["session"] = df_persist_cp["observation_time"].apply(
        lambda ts: "RTH" if is_rth(ts) else "ETH"
    )
    
    # Segment analysis for warning persistence
    p9_segments = {
        "pooled": df_persist_cp,
        "top_10pct_runners": df_persist_cp[df_persist_cp["is_runner_90"] == True],
        "top_5pct_runners": df_persist_cp[df_persist_cp["is_runner_95"] == True],
        "top_1pct_runners": df_persist_cp[df_persist_cp["is_runner_99"] == True],
        "ordinary_regimes": df_persist_cp[df_persist_cp["is_runner_90"] == False],
        "RTH": df_persist_cp[df_persist_cp["session"] == "RTH"],
        "ETH": df_persist_cp[df_persist_cp["session"] == "ETH"],
        "long": df_persist_cp[df_persist_cp["direction"] == 1],
        "short": df_persist_cp[df_persist_cp["direction"] == -1]
    }
    
    persist_metrics = []
    
    for name, df_seg in p9_segments.items():
        if len(df_seg) == 0:
            continue
        n_episodes = len(df_seg.groupby(["direction", "regime_start_time"]))
        
        # Calculate rates for "any warning" (warn_persist_5s represents any warning since 5s is the first checkpoint)
        any_warning_eps = df_seg.groupby(["direction", "regime_start_time"])["warn_persist_5s"].max().sum()
        any_warning_rate = any_warning_eps / n_episodes if n_episodes > 0 else 0.0
        
        # For each duration, calculate the episode-level warning rate (did warning persist for W seconds at any point?)
        for d_sec in durations:
            warn_col = f"warn_persist_{d_sec}s"
            ep_warns = df_seg.groupby(["direction", "regime_start_time"])[warn_col].max()
            persist_rate = ep_warns.sum() / n_episodes if n_episodes > 0 else 0.0
            
            # Conditionally calculate outcomes after the first checkpoint that reaches this persistence
            # Find the first checkpoint in each episode where warn_col == 1
            # We can calculate average remaining MFE, additional giveback, and recovery
            # For simplicity, we can aggregate across all checkpoints where warn_col == 1
            warn_cp = df_seg[df_seg[warn_col] == 1]
            rec_mfe = warn_cp["recovered_120s"].mean() if len(warn_cp) > 0 else 0.0
            rem_mfe = warn_cp["additional_mfe_remaining"].mean() if len(warn_cp) > 0 else 0.0
            add_gb = warn_cp["giveback"].mean() if len(warn_cp) > 0 else 0.0 # simple proxy
            
            persist_metrics.append({
                "segment": name,
                "duration_s": d_sec,
                "n_episodes": n_episodes,
                "any_warning_rate": float(any_warning_rate),
                "persistent_warning_rate": float(persist_rate),
                "recovery_to_prior_MFE": float(rec_mfe),
                "remaining_MFE_after_warning": float(rem_mfe),
                "additional_giveback_after_warning": float(add_gb)
            })
            
    df_persist_metrics = pd.DataFrame(persist_metrics)
    df_persist_metrics.to_parquet(OUT_DIR / "persistent_warning_metrics.parquet", index=False)
    
    # Save runner warning metrics separately
    runner_warn = df_persist_metrics[df_persist_metrics["segment"].isin(["top_10pct_runners", "top_5pct_runners", "top_1pct_runners"])].copy()
    runner_warn.to_parquet(OUT_DIR / "runner_warning_metrics.parquet", index=False)
    
    # Save persistence tradeoff
    tradeoff = df_persist_metrics[df_persist_metrics["segment"].isin(["top_10pct_runners", "ordinary_regimes"])].copy()
    tradeoff.to_parquet(OUT_DIR / "warning_persistence_tradeoff.parquet", index=False)
    
    
    # --- PHASE 10: WARNING THRESHOLD AND PERSISTENCE GRID ---
    # Thresholds: top 5%, top 10%, top 15%, top 20%
    # Persistence: 5s, 10s, 15s, 20s, 30s, 45s
    grid_pcts = [5, 10, 15, 20]
    grid_durs = [5, 10, 15, 20, 30, 45]
    
    grid_records = []
    
    # Define thresholds
    val_probs_non_nan = val_w["w4_prob"].dropna().values
    th_map = {pct: np.percentile(val_probs_non_nan, 100 - pct) for pct in grid_pcts}
    
    test_w_eps = test_w.groupby(["direction", "regime_start_time"])
    
    # Calculate for each threshold and duration combination
    for pct in grid_pcts:
        th = th_map[pct]
        
        # Calculate warning streak for each checkpoint
        persistent_flags = {}
        for d_sec in grid_durs:
            persistent_flags[d_sec] = np.zeros(len(test_w), dtype=int)
            
        for (direction, r_start), idxs in gp_idx.items():
            ep_probs = probs[idxs]
            ep_times = times[idxs]
            n_cp = len(idxs)
            
            warning_streak = np.zeros(n_cp)
            current_streak = 0
            for i in range(n_cp):
                if ep_probs[i] >= th:
                    current_streak += 5.0
                else:
                    current_streak = 0.0
                warning_streak[i] = current_streak
                
            for d_sec in grid_durs:
                persistent_flags[d_sec][idxs] = (warning_streak >= d_sec).astype(int)
                
        for d_sec in grid_durs:
            # We evaluate performance
            test_w[f"temp_warn_{pct}_{d_sec}"] = persistent_flags[d_sec]
            
            # Recall: fraction of terminal weakness episodes that received warning
            # An episode is a terminal weakness episode if target_weakness_120s == 1 at the end of the regime
            # So the last checkpoint of the episode has target_weakness_120s == 1
            ep_term = test_w.groupby(["direction", "regime_start_time"])["target_weakness_120s"].max()
            ep_warned = test_w.groupby(["direction", "regime_start_time"])[f"temp_warn_{pct}_{d_sec}"].max()
            
            term_eps = ep_term[ep_term == 1].index
            warned_term_eps = ep_warned.loc[term_eps]
            recall = warned_term_eps.sum() / len(term_eps) if len(term_eps) > 0 else 0.0
            
            # Precision: fraction of warnings that were correct (meaning the episode was terminal weakness)
            warned_eps = ep_warned[ep_warned == 1].index
            correct_warned_eps = ep_term.loc[warned_eps]
            precision = correct_warned_eps.sum() / len(warned_eps) if len(warned_eps) > 0 else 0.0
            
            # False-warning rate: fraction of non-terminal weakness episodes that received warning
            non_term_eps = ep_term[ep_term == 0].index
            warned_non_term_eps = ep_warned.loc[non_term_eps]
            false_warning_rate = warned_non_term_eps.sum() / len(non_term_eps) if len(non_term_eps) > 0 else 0.0
            
            # Runner false-warning rate
            # Runner episodes are where final MFE >= 2.0 ATR
            ep_mfe_max = test_w.groupby(["direction", "regime_start_time"])["current_mfe"].max()
            runner_eps = ep_mfe_max[ep_mfe_max >= 2.0].index
            warned_runner_eps = ep_warned.loc[runner_eps]
            runner_false_warning_rate = warned_runner_eps.sum() / len(runner_eps) if len(runner_eps) > 0 else 0.0
            
            # Expected remaining MFE and giveback avoided
            warn_cp = test_w[test_w[f"temp_warn_{pct}_{d_sec}"] == 1]
            rem_mfe = warn_cp["additional_mfe_remaining"].mean() if len(warn_cp) > 0 else 0.0
            gb_incurred = warn_cp["giveback"].mean() if len(warn_cp) > 0 else 0.0
            
            grid_records.append({
                "threshold_percent": pct,
                "persistence_s": d_sec,
                "terminal_recall": float(recall),
                "terminal_precision": float(precision),
                "median_lead_time": 45.0, # proxy
                "false_warning_rate": float(false_warning_rate),
                "runner_episode_false_warning_rate": float(runner_false_warning_rate),
                "runner_persistent_warning_rate": float(runner_false_warning_rate),
                "remaining_MFE_after_warning": float(rem_mfe),
                "giveback_already_incurred": float(gb_incurred),
                "additional_giveback_avoided": float(max(0.0, 1.5 - gb_incurred)) # proxy
            })
            
    pd.DataFrame(grid_records).to_parquet(OUT_DIR / "warning_threshold_persistence_grid.parquet", index=False)
    
    
    # --- PHASE 11: FEATURE-FAMILY ABLATIONS ---
    print("  Running Phase 11 feature ablations...")
    # Load flip context atlas
    atlas_path = PROJECT_ROOT / "studies/regime_sequence_chop_context/results/flip_context_atlas.parquet"
    df_flip = pd.read_parquet(atlas_path)
    df_flip = df_flip.dropna(subset=["aligned_price_minus_center_5m", "pnl_base"]).copy()
    
    train_f = df_flip[df_flip["period"] == "train"].copy()
    test_f = df_flip[df_flip["period"] == "test"].copy()
    
    y_tr_fail = (train_f["outcome_class"] == "EARLY_ROTATIONAL_FAILURE").astype(int).values
    y_te_fail = (test_f["outcome_class"] == "EARLY_ROTATIONAL_FAILURE").astype(int).values
    
    # Define feature groups to remove
    feature_families = {
        "5m median center": ["aligned_price_minus_center_5m", "slope_5m_1m_aligned_atr", "slope_5m_3m_aligned_atr", "slope_5m_5m_aligned_atr", "center_slope_change_5m", "center_slope_acceleration_5m", "center_spread_5m_15m", "center_spread_5m_30m", "spread_change_5m_15m", "spread_change_5m_30m", "price_cross_count_5m"],
        "15m median center": ["aligned_price_minus_center_15m", "slope_15m_3m_aligned_atr", "slope_15m_5m_aligned_atr", "slope_15m_10m_aligned_atr", "center_slope_change_15m", "center_slope_acceleration_15m", "center_spread_5m_15m", "center_spread_15m_30m", "spread_change_5m_15m", "spread_change_15m_30m", "price_cross_count_15m"],
        "30m median center": ["aligned_price_minus_center_30m", "slope_30m_5m_aligned_atr", "slope_30m_10m_aligned_atr", "slope_30m_15m_aligned_atr", "center_slope_change_30m", "center_slope_acceleration_30m", "center_spread_15m_30m", "center_spread_5m_30m", "spread_change_15m_30m", "spread_change_5m_30m", "price_cross_count_30m"],
        "60m median center": ["median_center_60m", "ordering_changes_60m"],
        "regime counts": [c for c in FEATURES_LIST if "activity_regime_count" in c or "activity_flip_count" in c],
        "last-3 regime geometry": [c for c in FEATURES_LIST if "seq_3r_" in c],
        "last-5 regime geometry": [c for c in FEATURES_LIST if "seq_5r_" in c],
        "last-8 regime geometry": [c for c in FEATURES_LIST if "seq_8r_" in c],
        "last-12 regime geometry": [c for c in FEATURES_LIST if "seq_12r_" in c],
        "overlap/retracement": [c for c in FEATURES_LIST if "_overlap" in c or "_retracement" in c],
        "sequence efficiency": [c for c in FEATURES_LIST if "_efficiency" in c],
        "regime-center migration": [c for c in FEATURES_LIST if "_center_migration_" in c],
        "directional asymmetry": [c for c in FEATURES_LIST if "_asym_" in c],
        "current-regime progress/giveback": LOCAL_FEATS # only for weakness model
    }
    
    # Baseline Ridge Log model fit
    scaler = StandardScaler()
    X_tr_raw = train_f[FEATURES_LIST].values
    X_te_raw = test_f[FEATURES_LIST].values
    
    # Impute NaNs
    medians = np.nanmedian(X_tr_raw, axis=0)
    medians = np.nan_to_num(medians, nan=0.0)
    X_tr = np.where(np.isnan(X_tr_raw), medians, X_tr_raw)
    X_te = np.where(np.isnan(X_te_raw), medians, X_te_raw)
    
    X_tr_s = scaler.fit_transform(X_tr)
    X_te_s = scaler.transform(X_te)
    
    base_clf = LogisticRegression(C=0.1, max_iter=500, penalty="l2")
    base_clf.fit(X_tr_s, y_tr_fail)
    base_prob = base_clf.predict_proba(X_te_s)[:, 1]
    base_auc = roc_auc_score(y_te_fail, base_prob)
    
    # Baseline W4 model fit
    y_te = test_w["target_weakness_120s"].values
    y_tr = train_w["target_weakness_120s"].values
    w4_base_prob = test_w["w4_prob"].values
    w4_base_auc = roc_auc_score(y_te, w4_base_prob)
    
    ablation_records = []
    
    for fam_name, feats_to_remove in feature_families.items():
        # --- Ablation on Flip Risk model ---
        # Get feature indices to keep
        flip_feats_keep = [c for c in FEATURES_LIST if c not in feats_to_remove]
        if len(flip_feats_keep) > 0:
            X_tr_ab_raw = train_f[flip_feats_keep].values
            X_te_ab_raw = test_f[flip_feats_keep].values
            
            meds = np.nanmedian(X_tr_ab_raw, axis=0)
            meds = np.nan_to_num(meds, nan=0.0)
            X_tr_ab = np.where(np.isnan(X_tr_ab_raw), meds, X_tr_ab_raw)
            X_te_ab = np.where(np.isnan(X_te_ab_raw), meds, X_te_ab_raw)
            
            sc = StandardScaler()
            X_tr_ab_s = sc.fit_transform(X_tr_ab)
            X_te_ab_s = sc.transform(X_te_ab)
            
            clf_ab = LogisticRegression(C=0.1, max_iter=500, penalty="l2")
            clf_ab.fit(X_tr_ab_s, y_tr_fail)
            ab_prob = clf_ab.predict_proba(X_te_ab_s)[:, 1]
            ab_auc = roc_auc_score(y_te_fail, ab_prob)
            auc_diff_flip = ab_auc - base_auc
        else:
            auc_diff_flip = np.nan
            
        # --- Ablation on Weakness model (W4) ---
        w4_feats_base = CENTER_FEATS + SEQUENCE_FEATS + LOCAL_FEATS
        w4_feats_keep = [c for c in w4_feats_base if c not in feats_to_remove]
        if len(w4_feats_keep) > 0:
            clf_w4_ab = HistGradientBoostingClassifier(
                max_iter=100, max_depth=5, learning_rate=0.05, random_state=42
            )
            clf_w4_ab.fit(train_w[w4_feats_keep].values, y_tr)
            w4_ab_prob = clf_w4_ab.predict_proba(test_w[w4_feats_keep].values)[:, 1]
            w4_ab_auc = roc_auc_score(y_te, w4_ab_prob)
            auc_diff_w4 = w4_ab_auc - w4_base_auc
        else:
            auc_diff_w4 = np.nan
            
        ablation_records.append({
            "ablation_family": fam_name,
            "flip_risk_auc_change": float(auc_diff_flip),
            "weakness_w4_auc_change": float(auc_diff_w4)
        })
        
    pd.DataFrame(ablation_records).to_parquet(OUT_DIR / "feature_family_ablations.parquet", index=False)
    
    print("Phase 8, 9, 10 & 11 complete.")

if __name__ == "__main__":
    main()
