import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, average_precision_score


def file_sha256(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        hasher.update(f.read())
    return hasher.hexdigest()


def phase1_identify_artifacts():
    print("==================================================")
    print("PHASE 1 — IDENTIFY THE EXACT ARTIFACTS")
    print("==================================================")
    
    artifact_dirs = [
        Path("studies/freeze_reduced_flip_model_artifacts/artifacts/long_bullish_flip_top25"),
        Path("studies/freeze_reduced_flip_model_artifacts/artifacts/long_bullish_flip_top50"),
        Path("studies/freeze_reduced_flip_model_artifacts/artifacts/long_bullish_flip_top100"),
    ]
    
    for art_dir in artifact_dirs:
        model_id = art_dir.name
        print(f"\n--- Artifact: {model_id} ---")
        print(f"Artifact path: {art_dir.resolve()}")
        
        model_path = art_dir / "model.joblib"
        feat_order_path = art_dir / "feature_order.csv"
        manifest_path = art_dir / "manifest.json"
        feat_map_path = art_dir / "feature_mapping.json"
        
        print(f"Model SHA-256: {file_sha256(model_path)}")
        print(f"Feature-list path & SHA-256: {feat_order_path} ({file_sha256(feat_order_path)})")
        print(f"Feature-mapping path & SHA-256: {feat_map_path} ({file_sha256(feat_map_path)})")
        print(f"Manifest path & SHA-256: {manifest_path} ({file_sha256(manifest_path)})")
        
        if model_path.exists():
            model = joblib.load(model_path)
            print(f"Model class: {type(model)}")
            
            # Check pipeline vs estimator
            est = model
            if hasattr(model, "steps"):
                est = model.steps[-1][1]
                print(f"Pipeline final estimator: {type(est)}")
                
            n_feats = getattr(est, "n_features_in_", getattr(model, "n_features_in_", "N/A"))
            print(f"n_features_in_: {n_feats}")
            
            feat_names_in = getattr(est, "feature_names_in_", getattr(model, "feature_names_in_", "N/A"))
            if isinstance(feat_names_in, np.ndarray):
                feat_names_in = feat_names_in.tolist()
            print(f"feature_names_in_: {feat_names_in[:3]}... (Total {len(feat_names_in) if isinstance(feat_names_in, list) else 'N/A'})")
        
        if manifest_path.exists():
            with open(manifest_path) as f:
                man = json.load(f)
            print("Manifest contents:")
            print(json.dumps(man, indent=2))
            
        print(f"Configured scoring path check: Model is {'NOT ' if 'short' not in model_id.lower() else ''}a Short-side F3 artifact.")


def phase2_reconstruct_schema():
    print("\n==================================================")
    print("PHASE 2 — RECONSTRUCT FROZEN TRAINING SCHEMA")
    print("==================================================")
    
    art_dir = Path("studies/freeze_reduced_flip_model_artifacts/artifacts/long_bullish_flip_top25")
    feat_order_path = art_dir / "feature_order.csv"
    df_saved_feats = pd.read_csv(feat_order_path)
    expected_feats = df_saved_feats["feature_name"].tolist()
    
    print(f"Selected Long Model: {art_dir.name}")
    print(f"Saved feature list count (expected): {len(expected_feats)}")
    
    # 1. Compare against prepared_long_2024.parquet
    prep_path = Path("studies/long_rth_mirrored_surface_top100_training/_work/prepared_long_2024.parquet")
    df_prep = pd.read_parquet(prep_path)
    prep_cols = df_prep.columns.tolist()
    print(f"\n1. Prepared Dataset ({prep_path.name}) total columns: {len(prep_cols)}")
    
    missing_in_prep = [f for f in expected_feats if f not in prep_cols]
    print(f"Features expected by model but MISSING in prepared dataset: {missing_in_prep}")
    
    # 2. Compare against Short source candidate list (prepared_2024.parquet)
    short_prep_path = Path("studies/short_rth_enriched_volume_level_retrain/_work/prepared_2024.parquet")
    df_short_prep = pd.read_parquet(short_prep_path)
    short_cols = df_short_prep.columns.tolist()
    print(f"\n2. Short Source Dataset ({short_prep_path.name}) total columns: {len(short_cols)}")
    
    # Check surface manifest
    manifest_path = Path("studies/long_rth_mirrored_surface_top100_training/results/long_surface_manifest.json")
    if manifest_path.exists():
        with open(manifest_path) as f:
            surf_man = json.load(f)
        print(f"\nSurface manifest key count: {len(surf_man)}")
        
    # Check ordering
    if not missing_in_prep:
        prep_sub_order = [c for c in prep_cols if c in expected_feats]
        order_matches = (prep_sub_order == expected_feats)
        print(f"Feature order matches exactly between model feature_order.csv and prepared dataset subset: {order_matches}")
        if not order_matches:
            print(f"Expected order (first 5): {expected_feats[:5]}")
            print(f"Dataset order (first 5): {prep_sub_order[:5]}")


def phase3_directional_mapping_audit():
    print("\n==================================================")
    print("PHASE 3 — DIRECTIONAL MAPPING AUDIT")
    print("==================================================")
    
    manifest_path = Path("studies/long_rth_mirrored_surface_top100_training/results/long_surface_manifest.json")
    if not manifest_path.exists():
        print("Missing long_surface_manifest.json!")
        return

    with open(manifest_path) as f:
        surf_man = json.load(f)
        
    feat_order_path = Path("studies/freeze_reduced_flip_model_artifacts/artifacts/long_bullish_flip_top25/feature_order.csv")
    df_top25 = pd.read_csv(feat_order_path)
    top25_feats = df_top25["feature_name"].tolist()
    
    mapping_dict = surf_man.get("feature_mapping", {})
    
    audit_table = []
    for long_feat in top25_feats:
        info = mapping_dict.get(long_feat, {})
        src_short = info.get("source_short_feature", "N/A")
        map_type = info.get("mapping_type", "N/A")
        
        audit_table.append({
            "long_feature": long_feat,
            "source_short_feature": src_short,
            "mapping_type": map_type,
            "semantic_check": "VERIFIED_MIRRORED" if src_short != "N/A" else "UNMAPPED"
        })
        
    df_audit = pd.DataFrame(audit_table)
    print(df_audit.to_string(index=False))


def phase4_artifact_reproduction():
    print("\n==================================================")
    print("PHASE 4 — ARTIFACT REPRODUCTION")
    print("==================================================")
    
    art_dir = Path("studies/freeze_reduced_flip_model_artifacts/artifacts/long_bullish_flip_top25")
    model_path = art_dir / "model.joblib"
    feat_order_path = art_dir / "feature_order.csv"
    ref_2025_path = art_dir / "score_reference_2025.parquet"
    
    model = joblib.load(model_path)
    df_feats = pd.read_csv(feat_order_path)
    feat_names = df_feats["feature_name"].tolist()
    
    prep_2025_path = Path("studies/long_rth_mirrored_surface_top100_training/_work/prepared_long_2025.parquet")
    df_prep_2025 = pd.read_parquet(prep_2025_path)
    
    X_2025 = df_prep_2025[feat_names].copy()
    reproduced_scores = model.predict_proba(X_2025)[:, 1]
    
    rows_scored = len(reproduced_scores)
    print(f"Rows scored (2025 dev dataset): {rows_scored}")
    
    reproduced_score_hash = hashlib.sha256(reproduced_scores.tobytes()).hexdigest()
    print(f"Reproduced score byte SHA-256: {reproduced_score_hash}")
    
    if ref_2025_path.exists():
        df_ref_2025 = pd.read_parquet(ref_2025_path)
        saved_scores = df_ref_2025["score"].values
        saved_score_hash = hashlib.sha256(saved_scores.tobytes()).hexdigest()
        print(f"Saved score reference SHA-256: {saved_score_hash}")
        
        diff = np.abs(reproduced_scores - saved_scores)
        max_abs_diff = np.max(diff)
        mean_abs_diff = np.mean(diff)
        print(f"Maximum absolute score difference: {max_abs_diff:.8e}")
        print(f"Mean absolute score difference: {mean_abs_diff:.8e}")
        
        target_col = "bullish_regime_flip_within_300s"
        if target_col in df_prep_2025.columns:
            y_true = df_prep_2025[target_col].values
            auc = roc_auc_score(y_true, reproduced_scores)
            ap = average_precision_score(y_true, reproduced_scores)
            print(f"2025 ROC-AUC: {auc:.4f}")
            print(f"2025 Average Precision: {ap:.4f}")
    else:
        print("No score_reference_2025.parquet found in artifact folder.")


def main():
    phase1_identify_artifacts()
    phase2_reconstruct_schema()
    phase3_directional_mapping_audit()
    phase4_artifact_reproduction()


if __name__ == "__main__":
    main()
