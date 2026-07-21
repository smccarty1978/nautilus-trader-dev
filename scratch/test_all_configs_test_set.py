import pandas as pd
import numpy as np
import math

OUT_DIR = pd.io.common.Path("studies/rl_regime_feasibility/results")
snaps = pd.read_parquet(OUT_DIR / "feature_snapshots.parquet")
labels = pd.read_parquet(OUT_DIR / "forward_labels.parquet")
preds = pd.read_parquet(OUT_DIR / "gate1_predictions.parquet")

df = snaps.merge(labels, on="observation_time", how="inner")
df = df.merge(preds.drop(columns=[c for c in preds.columns if c in df.columns and c != "observation_time"]), on="observation_time", how="left")

# Clean
valid_mask = df["observation_time"] <= df["episode_end_time"]
df = df[valid_mask].copy()

val_df = df[df["period"] == "val"].copy()
test_df = df[df["period"] == "test"].copy()

val_groups = [g.sort_values("step_index") for _, g in val_df.groupby("episode_id", sort=False)]
test_groups = [g.sort_values("step_index") for _, g in test_df.groupby("episode_id", sort=False)]

horizons_s = [5, 15, 30, 60, 120, 300]
models = ["ridge_log", "gbm"]
horizons = [5, 15, 30, 60, 120, 300]

def evaluate_config(train_split, test_split, model, h_s, threshold):
    prob_col = f"{model}_h{h_s}_prob"
    
    # Test simulation
    pnls = []
    traded = 0
    for ep_df in test_split:
        probs = ep_df[prob_col].values
        entry_idx = None
        for i, p in enumerate(probs):
            if math.isnan(p):
                continue
            if p >= threshold:
                entry_idx = i
                break
        if entry_idx is not None:
            pnl = ep_df.iloc[entry_idx][f"base__pnl_{h_s}s"]
            if not math.isnan(pnl):
                pnls.append(pnl)
                traded += 1
            else:
                pnls.append(0.0)
        else:
            pnls.append(0.0)
            
    pnl_arr = np.array(pnls)
    ev_all = pnl_arr.mean()
    ev_trade = pnl_arr.sum() / traded if traded > 0 else 0.0
    trade_rate = traded / len(test_split)
    
    # Win rate and PF
    trades = pnl_arr[pnl_arr != 0.0]
    win_rate = (trades > 0).mean() if len(trades) > 0 else 0.0
    pf = trades[trades > 0].sum() / abs(trades[trades < 0].sum()) if (trades < 0).any() else float("inf")
    
    return {
        "model": model,
        "horizon": h_s,
        "threshold": threshold,
        "trade_rate": trade_rate,
        "ev_all_usd": ev_all,
        "ev_all_pts": ev_all / 20.0,
        "ev_trade_usd": ev_trade,
        "ev_trade_pts": ev_trade / 20.0,
        "win_rate": win_rate,
        "pf": pf
    }

# Let's sweep validation best config for each model / horizon combination
results = []
for model in models:
    for h in horizons:
        prob_col = f"{model}_h{h}_prob"
        if prob_col not in val_df.columns:
            continue
        scores = val_df[prob_col].dropna().values
        if len(scores) == 0:
            continue
            
        # Find best threshold on validation for this model/horizon
        best_val_ev = -9999.0
        best_val_threshold = 0.5
        
        # Grid sweep of thresholds
        percentiles = np.linspace(0.1, 0.9, 17)
        for pct in percentiles:
            threshold = np.percentile(scores, pct * 100)
            pnls = []
            traded = 0
            for ep_df in val_groups:
                probs = ep_df[prob_col].values
                entry_idx = None
                for i, p in enumerate(probs):
                    if math.isnan(p):
                        continue
                    if p >= threshold:
                        entry_idx = i
                        break
                if entry_idx is not None:
                    pnl = ep_df.iloc[entry_idx][f"base__pnl_{h}s"]
                    if not math.isnan(pnl):
                        pnls.append(pnl)
                        traded += 1
                    else:
                        pnls.append(0.0)
                else:
                    pnls.append(0.0)
            ev = np.mean(pnls) if pnls else 0.0
            if ev > best_val_ev:
                best_val_ev = ev
                best_val_threshold = threshold
                
        # Run best on test set
        res = evaluate_config(val_groups, test_groups, model, h, best_val_threshold)
        res["val_ev_usd"] = best_val_ev
        results.append(res)
        
res_df = pd.DataFrame(results).sort_values("val_ev_usd", ascending=False)
print("Out-of-sample Test Results for all frozen model/horizon combinations:")
print(res_df.to_string(index=False))
