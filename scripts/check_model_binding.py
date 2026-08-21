"""Model Binding & Feature Order Alignment Validator.
===================================================

Validates:
  1. Model SHA256 matches manifest/config.
  2. Model n_features_in_ matches exact feature list length.
  3. Ordered feature list matches feature_names_in_ (if present).
  4. Classes are binary [0, 1] and predict_proba is supported.
  5. All features exist in the central registry (features/registry.py).

Usage:
  python scripts/check_model_binding.py --model path/to/model.joblib --features feat1,feat2,...
  python scripts/check_model_binding.py --config path/to/config.yaml

Exit codes:
  0: MODEL_BINDING_CLEAR
  1: MODEL_BINDING_BLOCKED
  2: Invocation error
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib

REPO_ROOT = Path(__file__).resolve().parent.parent


def calculate_sha256(filepath: Path) -> str:
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def get_registered_features() -> set[str]:
    reg_file = REPO_ROOT / "features" / "registry.py"
    if not reg_file.exists():
        return set()
    content = reg_file.read_text(encoding="utf-8")
    import re
    matches = re.findall(r"['\"]([a-zA-Z0-9_]+)['\"]\s*:\s*FeatureDefinition", content)
    return set(matches)


def validate_model_binding(
    model_path: Path,
    expected_features: List[str],
    expected_sha256: Optional[str] = None,
) -> Tuple[bool, str, List[str]]:
    """Validates model artifact against feature requirements."""
    errors: List[str] = []

    if not model_path.exists():
        return False, "MODEL_NOT_FOUND", [f"Model file not found: {model_path}"]

    # 1. SHA256 validation
    actual_sha = calculate_sha256(model_path)
    if expected_sha256 and actual_sha != expected_sha256:
        errors.append(f"Model hash mismatch: expected {expected_sha256}, got {actual_sha}")

    # 2. Load model
    try:
        model = joblib.load(model_path)
    except Exception as e:
        return False, "MODEL_LOAD_FAILED", [f"Cannot load model file: {e}"]

    # 3. Method support
    if not hasattr(model, "predict_proba"):
        errors.append("Model is missing 'predict_proba' method")

    # 4. Classes check
    if hasattr(model, "classes_"):
        classes = list(model.classes_)
        if classes not in ([0, 1], [False, True]):
            errors.append(f"Invalid model classes_: {classes}; expected [0, 1]")

    # 5. Feature count
    n_expected = len(expected_features)
    if hasattr(model, "n_features_in_") and model.n_features_in_ != n_expected:
        errors.append(f"Feature count mismatch: model.n_features_in_={model.n_features_in_} != len(features)={n_expected}")

    # 6. Feature names order
    if hasattr(model, "feature_names_in_"):
        model_names = list(model.feature_names_in_)
        if model_names != expected_features:
            errors.append(f"FEATURE_ORDER_MISMATCH: model expected {model_names[:5]}... but got {expected_features[:5]}...")

    # 7. Central registry check
    registered = get_registered_features()
    if registered:
        unregistered = [f for f in expected_features if f not in registered]
        if unregistered:
            errors.append(f"Unregistered features used: {unregistered}")

    if errors:
        code = "FEATURE_ORDER_MISMATCH" if any("FEATURE_ORDER" in e for e in errors) else "MODEL_BINDING_BLOCKED"
        return False, code, errors

    return True, "MODEL_BINDING_CLEAR", []


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate model artifact binding")
    ap.add_argument("--model", type=str, help="Path to model file (.joblib)")
    ap.add_argument("--features", type=str, help="Comma-separated list of expected features")
    ap.add_argument("--sha256", type=str, help="Expected SHA256 hash")
    ap.add_argument("--config", type=str, help="Path to YAML config specifying model and features")
    args = ap.parse_args()

    model_path = None
    expected_features = []
    expected_sha = args.sha256

    if args.config:
        cfg_p = Path(args.config)
        if not cfg_p.exists():
            print(f"Error: config path not found: {cfg_p}", file=sys.stderr)
            return 2
        import yaml
        with open(cfg_p, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        if isinstance(cfg, dict):
            model_path = Path(cfg.get("model_path", ""))
            expected_features = cfg.get("features", [])
            expected_sha = cfg.get("model_sha256", expected_sha)

    if args.model:
        model_path = Path(args.model)
    if args.features:
        expected_features = [f.strip() for f in args.features.split(",") if f.strip()]

    if not model_path or not expected_features:
        print("Error: must supply --model and --features or --config", file=sys.stderr)
        return 2

    valid, code, errors = validate_model_binding(model_path, expected_features, expected_sha)

    if valid:
        print(f"Verdict: {code}")
        return 0
    else:
        print(f"Verdict: {code}", file=sys.stderr)
        for err in errors:
            print(f"  -> {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
