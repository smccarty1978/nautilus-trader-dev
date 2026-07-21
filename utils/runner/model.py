import hashlib
from pathlib import Path
from typing import List, Sequence

import joblib
import pandas as pd


class PersistedModelRuntimeError(Exception):
    pass


class PersistedModelRuntime:
    """Manages model validation (SHA256, feature order) and inference scoring."""

    def __init__(self, model_path: Path, ordered_features: List[str], expected_sha256: str):
        self.model_path = Path(model_path)
        self.ordered_features = list(ordered_features)
        
        # Validate hash
        actual_sha256 = self.calculate_sha256(self.model_path)
        if actual_sha256 != expected_sha256:
            raise PersistedModelRuntimeError(
                f"Model hash mismatch: expected {expected_sha256}, got {actual_sha256}"
            )

        self.model = joblib.load(self.model_path)
        
        # Verify model has predict_proba
        if not hasattr(self.model, "predict_proba"):
            raise PersistedModelRuntimeError("Model is missing 'predict_proba' method")

        # Verify classes are binary [0, 1]
        if hasattr(self.model, "classes_") and list(self.model.classes_) != [0, 1]:
            raise PersistedModelRuntimeError(f"Unexpected classes_: {self.model.classes_}")

    @staticmethod
    def calculate_sha256(filepath: Path) -> str:
        """Calculates the SHA256 of the model file."""
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def score(self, feature_values: Sequence[float]) -> float:
        """Scores a list of feature values corresponding exactly to ordered_features."""
        if len(feature_values) != len(self.ordered_features):
            raise PersistedModelRuntimeError(
                f"Feature count mismatch: expected {len(self.ordered_features)}, got {len(feature_values)}"
            )

        # Build DataFrame with explicit columns to satisfy sklearn structure
        row = pd.DataFrame([feature_values], columns=self.ordered_features)
        proba = self.model.predict_proba(row)
        return float(proba[0, 1])

    def score_dict(self, feature_dict: dict) -> float:
        """Scores a feature dictionary by slicing it to match ordered_features."""
        missing = [f for f in self.ordered_features if f not in feature_dict]
        if missing:
            raise PersistedModelRuntimeError(f"Missing features: {missing}")

        feature_values = [feature_dict[f] for f in self.ordered_features]
        return self.score(feature_values)
