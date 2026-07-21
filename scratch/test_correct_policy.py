import pandas as pd
import numpy as np
import math

OUT_DIR = pd.io.common.Path("studies/rl_regime_feasibility/results")
snaps = pd.read_parquet(OUT_DIR / "feature_snapshots.parquet")
labels = pd.read_parquet(OUT_DIR / "forward_labels.parquet")
preds = pd.read_parquet(OUT_DIR / "gate1_predictions.parquet")
oracle = pd.read_parquet(OUT_DIR / "oracle_summary.parquet")

df = snaps.merge(labels, on="observation_time", how="inner")
df = df.merge(preds.drop(columns=[c for c in preds.columns if c in df.columns and c != "observation_time"]), on="observation_time", how="left")

val_df = df[df["period"] == "val"].copy()
test_df = df[df["period"] == "test"].copy()

horizons_s = [5, 15, 30, 60, 120, 300]

def simulate_correct_policy(data_split, model, h_s, threshold, cost_scenario="base"):
    prob_col = f"{model}_h{h_s}_prob"
    
    pnls = []
    traded_episodes = 0
    total_episodes = 0
    
    for ep_id, ep_df in data_split.groupby("episode_id", sort=False):
        ep_df = ep_df.sort_values("step_index")
        probs = ep_df[prob_col].values
        
        if len(probs) == 0 or math.isnan(probs[0]):
            continue
            
        total_episodes += 1
        
        # Correct Entry Condition: Only enter if initial score exceeds threshold
        if probs[0] < threshold:
            pnls.append(0.0)
            continue
            
        traded_episodes += 1
        
        # Find first step where prob < threshold (Exit A)
        exit_step = None
        for i, p in enumerate(probs):
            if math.isnan(p):
                continue
            if p < threshold:
                exit_step = i
                break
                
        if exit_step is None:
            exit_h = h_s
        else:
            exit_s = float(ep_df.iloc[exit_step]["seconds_since_flip"])
            exit_h = min(horizons_s, key=lambda x: abs(x - exit_s))
            
        first_row = ep_df.iloc[0]
        pnl = first_row[f"{cost_scenario}__pnl_{exit_h}s"]
        if not math.isnan(pnl):
            pnls.append(pnl)
        else:
            pnls.append(0.0)
            
    mean_all = np.mean(pnls) if pnls else 0.0
    mean_traded = np.sum(pnls) / traded_episodes if traded_episodes > 0 else 0.0
    
    return {
        "threshold": threshold,
        "total_eps": total_episodes,
        "traded_eps": traded_episodes,
        "trade_rate": traded_episodes / total_episodes if total_episodes > 0 else 0.0,
        "ev_all_usd": mean_all,
        "ev_all_pts": mean_all / 20.0,
        "ev_traded_usd": mean_traded,
        "ev_traded_pts": mean_traded / 20.0,
        "total_pnl_usd": np.sum(pnls)
    }

# Run sweep on validation and test for ridge_log_h300s
thresholds = [0.35, 0.38, 0.40, 0.42, 0.45, 0.48, 0.50, 0.52, 0.55]

print("=== VALIDATION SWEEP (ridge_log_h300s) ===")
val_rows = []
for thr in thresholds:
    res = simulate_correct_policy(val_df, "ridge_log", 300, thr)
    val_rows.append(res)
print(pd.DataFrame(val_rows).to_string(index=False))

print("\n=== TEST SWEEP (ridge_log_h300s) ===")
test_rows = []
for thr in thresholds:
    res = simulate_correct_policy(test_df, "ridge_log", 300, thr)
    test_rows.append(res)
print(pd.DataFrame(test_rows).to_string(index=False))
