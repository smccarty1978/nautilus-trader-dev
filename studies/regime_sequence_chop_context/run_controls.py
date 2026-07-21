import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.metrics import roc_auc_score
from sklearn.ensemble import HistGradientBoostingClassifier
import json

def run_controls_and_ablations(
    df_atlas: pd.DataFrame,
    features_list: list,
    medians: np.ndarray,
    out_dir: Path
) -> pd.DataFrame:
    print("Running Phase Controls and Sensitivity...")
    
    # Filter valid rows
    df_valid = df_atlas.dropna(subset=['aligned_price_minus_center_5m']).copy()
    
    # Split
    train = df_valid[df_valid['period'] == 'train'].copy()
    test = df_valid[df_valid['period'] == 'test'].copy()
    
    # Targets for Track A early failure
    y_tr = (train['outcome_class'] == 'EARLY_ROTATIONAL_FAILURE').astype(int).values
    y_te = (test['outcome_class'] == 'EARLY_ROTATIONAL_FAILURE').astype(int).values
    
    # Prepare base arrays
    X_train_raw = train[features_list].values
    X_test_raw = test[features_list].values
    X_tr = np.where(np.isnan(X_train_raw), medians, X_train_raw)
    X_te = np.where(np.isnan(X_test_raw), medians, X_test_raw)
    
    # Train base model
    base_clf = HistGradientBoostingClassifier(max_iter=50, max_depth=4, learning_rate=0.05, random_state=42)
    base_clf.fit(X_tr, y_tr)
    base_auc = roc_auc_score(y_te, base_clf.predict_proba(X_te)[:, 1])
    
    control_results = []
    control_results.append({
        "control_name": "Base Model (No Control)",
        "test_auc": base_auc,
        "description": "Baseline GBM early failure model on test set."
    })
    
    # C1: Median-center shuffle
    # Shuffle only median-center features in the test set
    center_indices = [i for i, f in enumerate(features_list) if "center" in f or "slope" in f or "spread" in f or "ordering" in f or "cross" in f]
    X_te_c1 = X_te.copy()
    for idx in center_indices:
        np.random.seed(42)
        np.random.shuffle(X_te_c1[:, idx])
    auc_c1 = roc_auc_score(y_te, base_clf.predict_proba(X_te_c1)[:, 1])
    control_results.append({
        "control_name": "C1: Median-Center Shuffle",
        "test_auc": auc_c1,
        "description": "Shuffled median-center features in test set."
    })
    
    # C2: Regime-sequence shuffle
    # Shuffle only sequence features in the test set
    seq_indices = [i for i, f in enumerate(features_list) if "seq_" in f]
    X_te_c2 = X_te.copy()
    for idx in seq_indices:
        np.random.seed(42)
        np.random.shuffle(X_te_c2[:, idx])
    auc_c2 = roc_auc_score(y_te, base_clf.predict_proba(X_te_c2)[:, 1])
    control_results.append({
        "control_name": "C2: Regime-Sequence Shuffle",
        "test_auc": auc_c2,
        "description": "Shuffled regime-sequence features in test set."
    })
    
    # C3: Regime-count-only control
    # Train only on regime count features
    count_feats = [f for f in features_list if "activity_regime_count" in f or "activity_flip_count" in f]
    count_indices = [features_list.index(f) for f in count_feats]
    X_tr_c3 = X_tr[:, count_indices]
    X_te_c3 = X_te[:, count_indices]
    clf_c3 = HistGradientBoostingClassifier(max_iter=50, max_depth=4, learning_rate=0.05, random_state=42)
    clf_c3.fit(X_tr_c3, y_tr)
    auc_c3 = roc_auc_score(y_te, clf_c3.predict_proba(X_te_c3)[:, 1])
    control_results.append({
        "control_name": "C3: Regime-Count-Only Control",
        "test_auc": auc_c3,
        "description": "Trained only on regime counts and flip counts."
    })
    
    # C4: Center-slope-only control
    # Train only on center slope features
    slope_feats = [f for f in features_list if "slope" in f]
    slope_indices = [features_list.index(f) for f in slope_feats]
    X_tr_c4 = X_tr[:, slope_indices]
    X_te_c4 = X_te[:, slope_indices]
    clf_c4 = HistGradientBoostingClassifier(max_iter=50, max_depth=4, learning_rate=0.05, random_state=42)
    clf_c4.fit(X_tr_c4, y_tr)
    auc_c4 = roc_auc_score(y_te, clf_c4.predict_proba(X_te_c4)[:, 1])
    control_results.append({
        "control_name": "C4: Center-Slope-Only Control",
        "test_auc": auc_c4,
        "description": "Trained only on center slopes."
    })
    
    # C6: Future positive control (using future price change / future 5m center as a feature)
    # We will simulate look-ahead by adding the actual future 300s PnL to the features in training and testing
    # Expect very high AUC
    X_tr_c6 = np.column_stack([X_tr, train['E0_regime_exit_pnl'].fillna(0.0).values])
    X_te_c6 = np.column_stack([X_te, test['E0_regime_exit_pnl'].fillna(0.0).values])
    clf_c6 = HistGradientBoostingClassifier(max_iter=50, max_depth=4, learning_rate=0.05, random_state=42)
    clf_c6.fit(X_tr_c6, y_tr)
    auc_c6 = roc_auc_score(y_te, clf_c6.predict_proba(X_te_c6)[:, 1])
    control_results.append({
        "control_name": "C6: Future Positive Control",
        "test_auc": auc_c6,
        "description": "Included future regime PnL as look-ahead feature."
    })
    
    # C7: 1s vs 5s sensitivity
    # Compute median difference between 1s rolling median and 5s rolling median
    sens_diff = np.nanmedian(np.abs(test['median_center_5m'] - test['median_center_5m_5s_sampled']))
    control_results.append({
        "control_name": "C7: Sampling Sensitivity (1s vs 5s diff)",
        "test_auc": base_auc, # AUC doesn't change directly but we report difference
        "description": f"Median absolute difference between 1s and 5s centers: {sens_diff:.4f} points."
    })
    
    # C8: Lookback ablation
    # Remove separately: 5m, 15m, 30m, last-3, last-5, last-8, last-12
    ablations = [
        ("No 5m center", [f for f in features_list if "5m" not in f]),
        ("No 15m center", [f for f in features_list if "15m" not in f]),
        ("No 30m center", [f for f in features_list if "30m" not in f]),
        ("No last-3 regimes", [f for f in features_list if "seq_3r_" not in f]),
        ("No last-5 regimes", [f for f in features_list if "seq_5r_" not in f]),
        ("No last-8 regimes", [f for f in features_list if "seq_8r_" not in f]),
        ("No last-12 regimes", [f for f in features_list if "seq_12r_" not in f]),
    ]
    
    for ab_name, ab_feats in ablations:
        ab_indices = [features_list.index(f) for f in ab_feats]
        X_tr_ab = X_tr[:, ab_indices]
        X_te_ab = X_te[:, ab_indices]
        clf_ab = HistGradientBoostingClassifier(max_iter=50, max_depth=4, learning_rate=0.05, random_state=42)
        clf_ab.fit(X_tr_ab, y_tr)
        auc_ab = roc_auc_score(y_te, clf_ab.predict_proba(X_te_ab)[:, 1])
        control_results.append({
            "control_name": f"C8 Ablation: {ab_name}",
            "test_auc": auc_ab,
            "description": f"Ablated feature family: {ab_name}."
        })
        
    df_controls = pd.DataFrame(control_results)
    df_controls.to_parquet(out_dir / "control_results.parquet", index=False)
    
    print("Done running controls and ablations.")
    return df_controls
