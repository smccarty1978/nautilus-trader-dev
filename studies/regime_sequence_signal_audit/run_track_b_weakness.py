import os
import json
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, average_precision_score

import sys
PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
OUT_DIR = PROJECT_ROOT / "studies/regime_sequence_signal_audit/results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

NQ_MULTIPLIER = 20.0

def classify_session(ts_ns: int) -> str:
    ts = pd.Timestamp(ts_ns, unit='ns', tz='UTC').tz_convert('America/Chicago')
    if ts.weekday() >= 5:
        return "ETH"
    from datetime import time
    t = ts.time()
    return "RTH" if time(8, 30, 0) <= t <= time(15, 15, 0) else "ETH"

def compute_pf(pnl):
    wins = pnl[pnl > 0].sum()
    losses = abs(pnl[pnl < 0].sum())
    return wins / losses if losses > 0 else (float("inf") if wins > 0 else 0.0)

# Feature families
from studies.regime_sequence_chop_context.train_weakness_model import LOCAL_FEATS, CENTER_FEATS, SEQUENCE_FEATS

def main():
    print("Running Track B: Within-Regime Weakness Exit Policy...")
    
    # Load weakness checkpoints atlas
    atlas_path = PROJECT_ROOT / "studies/regime_sequence_chop_context/results/weakness_checkpoint_atlas.parquet"
    if not atlas_path.exists():
        print(f"Error: {atlas_path} not found.")
        return
        
    cols_to_load = list(set(
        ["observation_time", "regime_age", "opp_flip_in_120s", "terminal_deterioration", "direction", "median_center_5m", "aligned_price_minus_center_5m", "close", "high", "low", "atr"] +
        LOCAL_FEATS + CENTER_FEATS + SEQUENCE_FEATS
    ))
    df_weak = pd.read_parquet(atlas_path, columns=cols_to_load)
    
    # Downcast float64 to float32 column by column to save memory safely
    for col in df_weak.select_dtypes(include=['float64']).columns:
        df_weak[col] = df_weak[col].astype('float32')
    
    # Assign regime_start_time
    df_weak["regime_start_time"] = df_weak["observation_time"] - (df_weak["regime_age"] * 1e9).astype(int)
    
    # Clean NaNs in place
    df_weak.dropna(subset=["aligned_price_minus_center_5m"], inplace=True)
    
    # Assign target
    df_weak["target_weakness_120s"] = ((df_weak["opp_flip_in_120s"] == 1) | (df_weak["terminal_deterioration"] == 1)).astype(int)
    
    # Assign walk-forward periods
    dt = pd.to_datetime(df_weak["observation_time"], unit="ns", utc=True)
    df_weak["period"] = "train"
    df_weak.loc[dt.dt.year == 2025, "period"] = "val"
    df_weak.loc[dt.dt.year == 2026, "period"] = "test"
    
    train = df_weak[df_weak["period"] == "train"].copy()
    val = df_weak[df_weak["period"] == "val"].copy()
    test = df_weak[df_weak["period"] == "test"].copy()
    
    print(f"  Chronology firewall splits - Train: {len(train):,}, Val: {len(val):,}, Test: {len(test):,}")
    
    # Fit specifications W0 to W4 on train
    y_tr = train["target_weakness_120s"].values
    y_vl = val["target_weakness_120s"].values
    y_te = test["target_weakness_120s"].values
    
    spec_features = {
        "W0": LOCAL_FEATS,
        "W1": CENTER_FEATS,
        "W2": SEQUENCE_FEATS,
        "W3": CENTER_FEATS + SEQUENCE_FEATS,
        "W4": CENTER_FEATS + SEQUENCE_FEATS + LOCAL_FEATS
    }
    
    val_probs = {}
    test_probs = {}
    
    comparison_metrics = []
    
    for name, feats in spec_features.items():
        print(f"  Fitting {name}...")
        clf = HistGradientBoostingClassifier(
            max_iter=100, max_depth=5, learning_rate=0.05, random_state=42
        )
        clf.fit(train[feats].values, y_tr)
        
        p_vl = clf.predict_proba(val[feats].values)[:, 1]
        p_te = clf.predict_proba(test[feats].values)[:, 1]
        
        val_probs[name] = p_vl
        test_probs[name] = p_te
        
        # Calculate standard checkpoint-weighted AUC
        auc_vl = roc_auc_score(y_vl, p_vl)
        auc_te = roc_auc_score(y_te, p_te)
        
        # Calculate event-weighted AUC (using reciprocal of checkpoint count per episode as sample weight)
        val_cnts = val.groupby(["direction", "regime_start_time"])["observation_time"].transform("count").values
        test_cnts = test.groupby(["direction", "regime_start_time"])["observation_time"].transform("count").values
        
        w_vl = 1.0 / val_cnts
        w_te = 1.0 / test_cnts
        
        ev_auc_vl = roc_auc_score(y_vl, p_vl, sample_weight=w_vl)
        ev_auc_te = roc_auc_score(y_te, p_te, sample_weight=w_te)
        
        comparison_metrics.append({
            "model": name,
            "val_checkpoint_auc": float(auc_vl),
            "test_checkpoint_auc": float(auc_te),
            "val_event_auc": float(ev_auc_vl),
            "test_event_auc": float(ev_auc_te)
        })
        
    df_comparison = pd.DataFrame(comparison_metrics)
    df_comparison.to_parquet(OUT_DIR / "weakness_spec_comparison.parquet", index=False)
    
    # Save test W4 probability on val/test/train set and save predictions parquet
    train = train.copy()
    train["w4_prob"] = clf.predict_proba(train[spec_features["W4"]].values)[:, 1]
    
    val = val.copy()
    val["w4_prob"] = val_probs["W4"]
    
    test = test.copy()
    test["w4_prob"] = test_probs["W4"]
    
    df_pred_all = pd.concat([train, val, test])
    pred_cols = ["direction", "regime_start_time", "observation_time", "w4_prob", "regime_age", "current_pnl", "giveback", "median_center_5m"]
    df_pred_all[pred_cols].to_parquet(OUT_DIR / "weakness_checkpoint_predictions.parquet", index=False)
    print(f"  Saved weakness checkpoint predictions to {OUT_DIR / 'weakness_checkpoint_predictions.parquet'}")

    
    # Load flip atlas to get baseline trades and runner labels
    df_all = pd.read_parquet(PROJECT_ROOT / "studies/regime_sequence_chop_context/results/flip_context_atlas.parquet")
    df_all["regime_start_time"] = df_all["observation_time"] - 60_000_000_000
    
    val_f2 = df_all[(df_all["population"] == "F2") & (pd.to_datetime(df_all["observation_time"], unit="ns", utc=True).dt.year == 2025)].copy()
    val_f2 = val_f2.dropna(subset=["pnl_base"]).copy()
    test_f2 = df_all[(df_all["population"] == "F2") & (pd.to_datetime(df_all["observation_time"], unit="ns", utc=True).dt.year == 2026)].copy()
    test_f2 = test_f2.dropna(subset=["pnl_base"]).copy()
    
    # Runner thresholds frozen on 2025
    runner_90_val = np.percentile(val_f2["pnl_base"].dropna(), 90) if len(val_f2) > 0 else 0.0
    runner_95_val = np.percentile(val_f2["pnl_base"].dropna(), 95) if len(val_f2) > 0 else 0.0
    loser_10_val = np.percentile(val_f2["pnl_base"].dropna(), 10) if len(val_f2) > 0 else 0.0
    
    print(f"  Frozen 2025 Runner 90th percentile: {runner_90_val:.2f}")
    print(f"  Frozen 2025 Loser 10th percentile: {loser_10_val:.2f}")
    
    # --- GRID SEARCH FOR OPTIMAL (THETA, N) ON 2025 VALIDATION SET ---
    print("  Running Warning Threshold & Persistence Grid Search on Val...")
    thetas = [0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8]
    persistences = [1, 2, 4, 6, 8, 10, 12, 15, 20] # 5s cadence: N * 5 seconds
    
    grid_results = []
    
    # Group validation checkpoints by episode
    val_groups = val.sort_values(["direction", "regime_start_time", "observation_time"]).groupby(["direction", "regime_start_time"])
    val_episodes = {}
    for key, df_ep in val_groups:
        val_episodes[key] = {
            "probs": df_ep["w4_prob"].values,
            "closes": df_ep["close"].values,
            "pnls": df_ep["current_pnl"].values,
            "atr": df_ep["atr"].iloc[0],
            "times": df_ep["observation_time"].values,
            "median_centers": df_ep["median_center_5m"].values
        }
        
    best_val_pnl = -np.inf
    best_theta = 0.6
    best_N = 10
    
    # Load val baseline trades
    val_f2_map = { (row.direction, int(row.regime_start_time)): row for row in val_f2.itertuples() }
    
    for theta in thetas:
        for N in persistences:
            # Simulate policy B1 on validation set
            pnl_sum = 0.0
            retained_runners = 0
            total_runners = 0
            acted_episodes = 0
            
            for key, ep in val_episodes.items():
                # Find if/when warning qualifies
                warn_streak = 0
                qualified_i = -1
                for i in range(len(ep["probs"])):
                    if ep["probs"][i] >= theta:
                        warn_streak += 1
                    else:
                        warn_streak = 0
                    if warn_streak >= N:
                        qualified_i = i
                        break
                        
                trade = val_f2_map.get(key)
                if trade is None:
                    continue
                    
                is_runner = trade.pnl_base >= runner_90_val
                if is_runner:
                    total_runners += 1
                    
                if qualified_i != -1:
                    # Exited on warning
                    acted_episodes += 1
                    exit_pnl = ep["pnls"][qualified_i] * NQ_MULTIPLIER - 5.0
                    pnl_sum += exit_pnl
                    if is_runner:
                        # Runner is damaged if exited early and exit PnL is worse than final PnL
                        # Let's count if we kept it as a runner (exit PnL >= runner threshold)
                        if exit_pnl >= runner_90_val:
                            retained_runners += 1
                else:
                    # Kept baseline trade
                    pnl_sum += trade.pnl_base
                    if is_runner:
                        retained_runners += 1
                        
            ev_lift = pnl_sum / len(val_f2) if len(val_f2) > 0 else 0.0
            runner_ret = retained_runners / total_runners if total_runners > 0 else 1.0
            
            grid_results.append({
                "theta": theta,
                "persistence_N": N,
                "persistence_s": N * 5,
                "val_pnl_sum": pnl_sum,
                "val_ev_lift": ev_lift,
                "runner_retention": runner_ret
            })
            
            # Select best configuration: maximize EV lift, subject to runner retention >= 85%
            if runner_ret >= 0.85 and pnl_sum > best_val_pnl:
                best_val_pnl = pnl_sum
                best_theta = theta
                best_N = N
                
    df_grid = pd.DataFrame(grid_results)
    df_grid.to_parquet(OUT_DIR / "warning_threshold_persistence_grid.parquet", index=False)
    
    print(f"  Optimal Frozen Parameters - Theta: {best_theta}, Persistence: {best_N} ticks ({best_N*5}s), Val EV Lift: {df_grid[(df_grid['theta'] == best_theta) & (df_grid['persistence_N'] == best_N)]['val_ev_lift'].iloc[0]:.4f}")
    
    # Save frozen configuration
    frozen_config = {
        "optimal_theta": float(best_theta),
        "optimal_persistence_N": int(best_N),
        "optimal_persistence_s": int(best_N * 5)
    }
    with open(OUT_DIR / "warning_policy_frozen_config.json", "w") as f:
        json.dump(frozen_config, f, indent=2)
        
    # --- EVALUATE POLICY LADDER ON 2026 TEST SET ---
    print("  Evaluating Policy Ladder on Test Set...")
    # Group test checkpoints by episode
    test_groups = test.sort_values(["direction", "regime_start_time", "observation_time"]).groupby(["direction", "regime_start_time"])
    test_episodes = {}
    for key, df_ep in test_groups:
        test_episodes[key] = {
            "probs": df_ep["w4_prob"].values,
            "closes": df_ep["close"].values,
            "pnls": df_ep["current_pnl"].values,
            "atr": df_ep["atr"].iloc[0],
            "times": df_ep["observation_time"].values,
            "highs": df_ep["high"].values,
            "lows": df_ep["low"].values,
            "median_centers": df_ep["median_center_5m"].values
        }
        
    test_f2_map = { (row.direction, int(row.regime_start_time)): row for row in test_f2.itertuples() }
    
    # Policies simulation
    # B0: Baseline
    # B1: Immediate exit
    # B2: Arms Price Confirmation (Rule 2c chosen on Val: retracement from peak)
    # B3: Tighten stop (Stop moved to close_i - direction * 0.5 * atr)
    # B4: Partial Exit (average of B1 and baseline)
    # B5: Gated Exit (exit on warning close through 5m center)
    
    policy_records = []
    
    for key, ep in test_episodes.items():
        trade = test_f2_map.get(key)
        if trade is None:
            continue
            
        direction = int(key[0])
        entry_px = float(trade.entry_price)
        atr_val = float(ep["atr"])
        baseline_pnl = float(trade.pnl_base)
        baseline_exit_px = float(trade.exit_price)
        
        # Check warning qualification
        warn_streak = 0
        warn_i = -1
        for i in range(len(ep["probs"])):
            if ep["probs"][i] >= best_theta:
                warn_streak += 1
            else:
                warn_streak = 0
            if warn_streak >= best_N:
                warn_i = i
                break
                
        # Simulate each policy
        # B0: Baseline
        pnl_B0 = baseline_pnl
        exit_px_B0 = baseline_exit_px
        
        if warn_i == -1:
            # No warning triggered
            pnl_B1 = pnl_B2 = pnl_B3 = pnl_B4 = pnl_B5 = baseline_pnl
            exit_px_B1 = exit_px_B2 = exit_px_B3 = exit_px_B4 = exit_px_B5 = baseline_exit_px
        else:
            warn_close = ep["closes"][warn_i]
            
            # B1: Immediate exit
            exit_px_B1 = warn_close
            pnl_B1 = direction * (exit_px_B1 - entry_px) * NQ_MULTIPLIER - 5.0
            
            # B2: Confirmation exit (retracement from peak since flip)
            exit_px_B2 = baseline_exit_px
            pnl_B2 = baseline_pnl
            peak_px = float(ep["closes"][0])
            for j in range(warn_i + 1, len(ep["closes"])):
                if direction == 1:
                    peak_px = max(peak_px, ep["highs"][j])
                    ret = peak_px - ep["closes"][j]
                else:
                    peak_px = min(peak_px, ep["lows"][j])
                    ret = ep["closes"][j] - peak_px
                if ret >= 0.25 * atr_val:
                    exit_px_B2 = ep["closes"][j]
                    pnl_B2 = direction * (exit_px_B2 - entry_px) * NQ_MULTIPLIER - 5.0
                    break
                    
            # B3: Tighten stop
            exit_px_B3 = baseline_exit_px
            pnl_B3 = baseline_pnl
            stop_px = warn_close - direction * 0.50 * atr_val
            for j in range(warn_i + 1, len(ep["closes"])):
                if (direction == 1 and ep["lows"][j] <= stop_px) or (direction == -1 and ep["highs"][j] >= stop_px):
                    exit_px_B3 = stop_px
                    pnl_B3 = direction * (exit_px_B3 - entry_px) * NQ_MULTIPLIER - 5.0
                    break
                    
            # B4: Partial Exit
            pnl_B4 = 0.5 * pnl_B1 + 0.5 * baseline_pnl
            exit_px_B4 = 0.5 * exit_px_B1 + 0.5 * baseline_exit_px
            
            # B5: Gated exit
            exit_px_B5 = baseline_exit_px
            pnl_B5 = baseline_pnl
            closes_fwd = ep["closes"]
            centers_fwd = ep["median_centers"]
            for j in range(warn_i + 1, len(closes_fwd)):
                if direction * (centers_fwd[j] - closes_fwd[j]) < 0:
                    exit_px_B5 = closes_fwd[j]
                    pnl_B5 = direction * (exit_px_B5 - entry_px) * NQ_MULTIPLIER - 5.0
                    break
                    
        policy_records.append({
            "direction": direction,
            "regime_start_time": key[1],
            "pnl_base": baseline_pnl,
            "pnl_B0": pnl_B0,
            "pnl_B1": pnl_B1,
            "pnl_B2": pnl_B2,
            "pnl_B3": pnl_B3,
            "pnl_B4": pnl_B4,
            "pnl_B5": pnl_B5,
            "warn_i": warn_i
        })
        
    df_policies = pd.DataFrame(policy_records)
    df_policies.to_parquet(OUT_DIR / "track_b_policy_episodes.parquet", index=False)
    
    # Build dictionary map for fast lookup: (direction, regime_start_time) -> row
    policies_map = { (int(row.direction), int(row.regime_start_time)): row for row in df_policies.itertuples() }
    
    # Calculate summary statistics for policy ladder on 2026 Test Set
    ladder_summary = []
    
    for pol in ["B0", "B1", "B2", "B3", "B4", "B5"]:
        pnls = df_policies[f"pnl_{pol}"].values
        ev = float(pnls.mean())
        pf = float(compute_pf(pnls))
        wr = float((pnls > 0).mean())
        
        # Calculate runner retention on test
        test_runners = test_f2[test_f2["pnl_base"] >= runner_90_val]
        total_test_runners = len(test_runners)
        retained_test_runners = 0
        for r_row in test_runners.itertuples():
            pol_row = policies_map.get((int(r_row.direction), int(r_row.regime_start_time)))
            if pol_row is not None:
                val = getattr(pol_row, f"pnl_{pol}")
                if val >= runner_90_val:
                    retained_test_runners += 1
                
        runner_ret = retained_test_runners / total_test_runners if total_test_runners > 0 else 1.0
        
        # Calculate loser-tail avoidance
        test_losers = test_f2[test_f2["pnl_base"] < loser_10_val]
        total_test_losers = len(test_losers)
        avoided_test_losers = 0
        for l_row in test_losers.itertuples():
            pol_row = policies_map.get((int(l_row.direction), int(l_row.regime_start_time)))
            if pol_row is not None:
                val = getattr(pol_row, f"pnl_{pol}")
                if val > l_row.pnl_base:
                    avoided_test_losers += 1
                
        loser_avoid = avoided_test_losers / total_test_losers if total_test_losers > 0 else 0.0
        
        ladder_summary.append({
            "policy": pol,
            "test_EV": ev,
            "profit_factor": pf,
            "win_rate": wr,
            "runner_retention_rate": runner_ret,
            "loser_avoidance_rate": loser_avoid
        })
        
    df_ladder = pd.DataFrame(ladder_summary)
    df_ladder.to_parquet(OUT_DIR / "track_b_policy_metrics.parquet", index=False)
    
    # Calculate first-qualified-action metrics for W4
    y_first = []
    p_first = []
    
    for key, ep in test_episodes.items():
        warn_streak = 0
        qual_i = -1
        for i in range(len(ep["probs"])):
            if ep["probs"][i] >= best_theta:
                warn_streak += 1
            else:
                warn_streak = 0
            if warn_streak >= best_N:
                qual_i = i
                break
        
        trade = test_f2_map.get(key)
        if trade is None:
            continue
        is_weak = int(trade.outcome_class in ["EARLY_ROTATIONAL_FAILURE", "LOW_PROGRESS_REGIME"])
        
        if qual_i != -1:
            p_first.append(ep["probs"][qual_i])
            y_first.append(is_weak)
        else:
            p_first.append(0.0)
            y_first.append(is_weak)
            
    first_action_auc = roc_auc_score(y_first, p_first)
    print(f"  First-qualified-action AUC on test: {first_action_auc:.4f}")
    
    # Save first action metrics
    pd.DataFrame([{"first_qualified_action_auc": first_action_auc}]).to_parquet(OUT_DIR / "track_b_first_action_auc.parquet", index=False)
    
    # Write report
    report_md = f"""# Track B: W4 Terminal Weakness Policy Translation Report

## W4 Model Quality comparison (AUC)
| Model Specification | Test Checkpoint AUC | Test Event-Weighted AUC |
|---|---|---|
"""
    for r in comparison_metrics:
        report_md += f"| {r['model']} | {r['test_checkpoint_auc']:.4f} | {r['test_event_auc']:.4f} |\n"
        
    report_md += f"""
## First-Qualified-Action Quality
* **W4 First-Qualified-Action AUC**: {first_action_auc:.4f}

## Policy Ladder Performance Summary (Test Set 2026)
| Policy | Test EV ($) | Win Rate | Profit Factor | Runner Retention Rate | Loser Avoidance Rate |
|---|---|---|---|---|---|
"""
    for r in ladder_summary:
        report_md += f"| {r['policy']} | ${r['test_EV']:.2f} | {r['win_rate']:.2%} | {r['profit_factor']:.2f} | {r['runner_retention_rate']:.2%} | {r['loser_avoidance_rate']:.2%} |\n"
        
    report_md += f"""
## Final Track B Decision:
`ECONOMICALLY_UNRESOLVED`
"""
    with open(OUT_DIR / "track_b_report.md", "w") as f:
        f.write(report_md)
        
    print("Track B analysis completed successfully.")

if __name__ == "__main__":
    main()
