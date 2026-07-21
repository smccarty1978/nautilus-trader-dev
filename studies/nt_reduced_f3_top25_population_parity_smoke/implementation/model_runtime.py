"""Loads the persisted joblib model, validates hash/feature-order/classes at
construction, and rejects missing/extra/misordered columns at score time.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Sequence

import joblib
import numpy as np
import pandas as pd


class ModelRuntimeError(Exception):
    pass


class ModelRuntime:
    def __init__(self, model_path: Path, ordered_features: List[str],
                expected_model_sha256: str, actual_model_sha256_fn):
        actual_hash = actual_model_sha256_fn(model_path)
        if actual_hash != expected_model_sha256:
            raise ModelRuntimeError(
                f"model hash mismatch: {actual_hash} != {expected_model_sha256}")
        self.model = joblib.load(model_path)
        if list(self.model.classes_) != [0, 1]:
            raise ModelRuntimeError(f"unexpected classes_: {self.model.classes_}")
        self.ordered_features = list(ordered_features)
        self.model_sha256 = actual_hash

    def score(self, feature_values: Sequence[float]) -> float:
        if len(feature_values) != len(self.ordered_features):
            raise ModelRuntimeError(
                f"expected {len(self.ordered_features)} features, got {len(feature_values)}")
        row = pd.DataFrame([feature_values], columns=self.ordered_features)
        proba = self.model.predict_proba(row)
        if proba.shape[1] != 2:
            raise ModelRuntimeError(f"unexpected predict_proba shape {proba.shape}")
        return float(proba[0, 1])

    def score_dict(self, feature_dict: dict) -> float:
        missing = [f for f in self.ordered_features if f not in feature_dict]
        if missing:
            raise ModelRuntimeError(f"missing features: {missing[:5]}")
        extra = [k for k in feature_dict if k not in self.ordered_features]
        if extra:
            raise ModelRuntimeError(f"unexpected extra features: {extra[:5]}")
        ordered_keys = list(feature_dict.keys())
        # dict insertion order must match self.ordered_features exactly --
        # callers build feature_dict via ReducedFeatureEngine.snapshot(),
        # which iterates self.ordered_features itself, so this should always
        # hold; checked explicitly rather than assumed.
        if ordered_keys != self.ordered_features:
            raise ModelRuntimeError("feature_dict key order does not match ordered_features")
        return self.score([feature_dict[f] for f in self.ordered_features])
