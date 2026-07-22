import hashlib
from pathlib import Path
import joblib
import numpy as np
import pandas as pd


def audit_model(model_dir: Path, name: str):
    print(f"=== Auditing Model: {name} ===")
    print(f"Artifact Path: {model_dir.resolve()}")
    
    model_path = model_dir / "model.joblib"
    feat_order_path = model_dir / "feature_order.csv"
    
    # Check sha256 hash
    hasher = hashlib.sha256()
    with open(model_path, "rb") as f:
        hasher.update(f.read())
    print(f"Model sha256: {hasher.hexdigest()}")
    
    # Load features
    df_feats = pd.read_csv(feat_order_path)
    print(f"Feature count: {len(df_feats)}")
    print(f"Features: {df_feats['feature_name'].tolist()[:5]}...")
    
    # Load model
    model = joblib.load(model_path)
    print(f"Model type: {type(model)}")
    if hasattr(model, "classes_"):
        print(f"Model classes_: {model.classes_}")
    else:
        print("Model has no classes_ attribute")
        
    print("-" * 50)


def main():
    short_dir = Path("studies/freeze_reduced_flip_model_artifacts/artifacts/short_bearish_flip_top25_current_reference")
    long_dir = Path("studies/freeze_reduced_flip_model_artifacts/artifacts/long_bullish_flip_top25")
    
    audit_model(short_dir, "Short-RTH Model")
    audit_model(long_dir, "Long-RTH Model")


if __name__ == "__main__":
    main()
