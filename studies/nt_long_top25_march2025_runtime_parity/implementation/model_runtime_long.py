"""Frozen long TOP25 logistic-regression runtime with TWO independent score
paths, so Phase 3 can validate them against each other and against the frozen
offline reference.

  joblib path   : Pipeline(imputer -> scaler -> LogisticRegression).predict_proba[:,1]
  explicit path : median-impute -> standardize -> logit = b + sum(coef*x) -> sigmoid,
                  computed ONLY from coefficients.csv + intercept.json
                  (no unpickling, exactly what an NT reimplementation would do)

The explicit path also returns per-feature contributions so score attribution is
auditable feature-by-feature -- the reason a logreg was chosen for NT.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Sequence

import joblib
import numpy as np
import pandas as pd


class ModelRuntimeError(Exception):
    pass


class LongModelRuntime:
    def __init__(self, model_path: Path, coefficients_path: Path,
                 intercept_path: Path, ordered_features: List[str],
                 expected_model_sha256: str, sha256_fn):
        actual = sha256_fn(model_path)
        if actual != expected_model_sha256:
            raise ModelRuntimeError(f"model hash mismatch: {actual} != {expected_model_sha256}")
        self.model = joblib.load(model_path)
        self.model_sha256 = actual
        self.ordered_features = list(ordered_features)

        coef = pd.read_csv(coefficients_path)
        if coef["feature_name"].tolist() != self.ordered_features:
            raise ModelRuntimeError(
                "coefficients.csv feature order does not match feature_order.csv")
        self.coef = coef["coefficient"].to_numpy(float)
        self.mean = coef["mean_train"].to_numpy(float)
        self.std = coef["std_train"].to_numpy(float)
        # null_policy is stored as "median_impute=<value>"
        self.fill = np.array([float(str(s).split("=")[1]) for s in coef["null_policy"]])
        self.intercept = float(json.loads(Path(intercept_path).read_text())["intercept"])

        clf = self.model.named_steps["model"] if hasattr(self.model, "named_steps") else self.model
        if list(clf.classes_) != [0, 1]:
            raise ModelRuntimeError(f"unexpected classes_: {clf.classes_}")
        if not np.isclose(float(clf.intercept_[0]), self.intercept, rtol=0, atol=0):
            raise ModelRuntimeError("intercept.json does not match the pickled estimator")

        # The CSV package is text, so it cannot be bit-identical to the pickled
        # float64s. Tolerances below are DOCUMENTED, measured, and deliberately
        # tight -- they exist to catch a wrong/stale CSV, not to paper over drift.
        #
        #   coefficient : 9.0e-17 abs (6.4e-14 rel) -- pandas to_csv round-trip
        #   mean_train  : 4.5e-13 abs               -- same
        #   std_train   : 3.6e-15 abs               -- same
        #   null_policy : 4.1e-07 abs               -- NOT round-trip. The freeze
        #       study wrote it as f"median_impute={v:.10g}", truncating the
        #       median-impute statistic to 10 significant digits.
        #
        # We deliberately keep the CSV-derived fill rather than reading
        # `imputer.statistics_`: the explicit path must reproduce what an NT
        # reimplementation working from the CSV alone would actually compute.
        # Impact is bounded and tiny (fill error / std_train * coefficient, and
        # only on rows where that feature is null) but it is REAL and is
        # reported in Phase 3 rather than hidden. See results/ for the measured
        # joblib-vs-explicit divergence.
        self._csv_tolerances = {"coefficient": 1e-15, "mean_train": 1e-11,
                                "std_train": 1e-12, "null_policy": 1e-5}
        checks = (("coefficient", clf.coef_[0], self.coef),
                  ("mean_train", self.model.named_steps["scaler"].mean_, self.mean),
                  ("std_train", self.model.named_steps["scaler"].scale_, self.std),
                  ("null_policy", self.model.named_steps["imputer"].statistics_, self.fill))
        self.csv_max_abs_diff = {}
        for name, pickled, from_csv in checks:
            d = float(np.abs(np.asarray(pickled, dtype=float) - from_csv).max())
            self.csv_max_abs_diff[name] = d
            if d > self._csv_tolerances[name]:
                raise ModelRuntimeError(
                    f"coefficients.csv '{name}' differs from the pickled estimator by "
                    f"{d:.3e} (> {self._csv_tolerances[name]:.0e}) - stale or wrong CSV")

    # ---------- path 1: the frozen artifact itself ----------
    def score_joblib(self, values: Sequence[float]) -> float:
        if len(values) != len(self.ordered_features):
            raise ModelRuntimeError(
                f"expected {len(self.ordered_features)} features, got {len(values)}")
        row = pd.DataFrame([list(values)], columns=self.ordered_features, dtype=float)
        return float(self.model.predict_proba(row)[0, 1])

    # ---------- path 2: explicit formula, no unpickling ----------
    def score_explicit(self, values: Sequence[float]) -> Dict[str, object]:
        x = np.array([np.nan if v is None else float(v) for v in values], dtype=float)
        imputed = np.where(np.isnan(x), self.fill, x)
        z = (imputed - self.mean) / self.std
        contrib = self.coef * z
        logit = float(self.intercept + contrib.sum())
        return {
            "logit": logit,
            "probability": float(1.0 / (1.0 + np.exp(-logit))),
            "contributions": contrib,
            "transformed": z,
            "imputed": imputed,
            "n_imputed": int(np.isnan(x).sum()),
        }

    def score_both(self, values: Sequence[float]) -> Dict[str, object]:
        ex = self.score_explicit(values)
        ex["probability_joblib"] = self.score_joblib(values)
        ex["abs_diff"] = abs(ex["probability_joblib"] - ex["probability"])
        return ex

    def score_dict(self, feature_dict: dict) -> Dict[str, object]:
        keys = list(feature_dict.keys())
        if keys != self.ordered_features:
            missing = [f for f in self.ordered_features if f not in feature_dict]
            extra = [k for k in keys if k not in self.ordered_features]
            raise ModelRuntimeError(
                f"feature_dict key order mismatch; missing={missing[:5]} extra={extra[:5]}")
        return self.score_both([feature_dict[f] for f in self.ordered_features])
