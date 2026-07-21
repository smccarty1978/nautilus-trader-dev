"""Freeze reduced pure-flip models into reproducible, loadable artifacts.

Two provenance classes, kept strictly separate and labelled as such:

  COPIED       - a fitted artifact already exists on disk (short side). We
                 byte-copy it, verify its recorded sha256, reload it, and prove
                 it reproduces the SOURCE STUDY'S OWN recorded numbers.
  RECONSTRUCTED- no fitted object was ever persisted (long side). We re-run the
                 exact original fit call path and prove the refit reproduces the
                 source study's STORED PER-ROW PREDICTIONS within tolerance.
                 Reconstruction happens ONLY because the artifact is missing and
                 is accepted ONLY on proven parity - per the brief.

Nothing outside studies/freeze_reduced_flip_model_artifacts/ is written.
No feature, threshold, or target is changed. 2026 is scored for reference only
and is never used to select or alter any model.
"""
from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = STUDY.parents[1]
ART, RESULTS, WORK = STUDY / "artifacts", STUDY / "results", STUDY / "_work"

RED = ROOT / "studies" / "runtime_constrained_f3_feature_reduction"
LONG100 = ROOT / "studies" / "long_rth_mirrored_surface_top100_training"
LONG25 = ROOT / "studies" / "long_rth_pure_flip_top50_top25_training"
SHORT_PREP = ROOT / "studies" / "short_rth_pure_flip_prediction_enriched" / "_work"
SMOKE = ROOT / "studies" / "nt_reduced_f3_top25_population_parity_smoke"
ENRICHED = ROOT / "studies" / "short_rth_enriched_volume_level_retrain"

TOL = {"logreg": 1e-12, "gbt": 1e-9}
NOW = datetime.now(timezone.utc).isoformat()


def sha256_file(p: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while c := f.read(block):
            h.update(c)
    return h.hexdigest()


def sha256_list(names) -> str:
    return hashlib.sha256(("\n".join(names) + "\n").encode("utf-8")).hexdigest()


def git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


VERSIONS = {"python_version": platform.python_version(),
            "sklearn_version": sklearn.__version__,
            "numpy_version": np.__version__,
            "pandas_version": pd.__version__,
            "joblib_version": joblib.__version__}
GIT = git_commit()


# --------------------------------------------------------------------------
# Long-side reconstruction (exact original fit call path)
# --------------------------------------------------------------------------
def _load_module(name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


_te = _load_module("_enriched_te", ENRICHED / "train_and_evaluate.py")
assert _te.RANDOM_STATE == 42, "reused fit_* RANDOM_STATE must be 42"


def long_frames():
    tr = pd.concat([pd.read_parquet(LONG100 / "_work" / f"prepared_long_{y}.parquet")
                    for y in (2021, 2022, 2023, 2024)], ignore_index=True)
    return tr, (pd.read_parquet(LONG100 / "_work" / "prepared_long_2025.parquet"),
                pd.read_parquet(LONG100 / "_work" / "prepared_long_2026.parquet"))


def reconstruct_long(feats: list[str], kind: str, train_df, y_train):
    """Re-run the exact fit path used by the source studies."""
    X = train_df[feats]
    if kind == "logreg":
        model, imputer, scaler = _te.fit_logistic(X, y_train)
        return Pipeline([("imputer", imputer), ("scaler", scaler), ("model", model)])
    return _te.fit_gbt(X, y_train)


# --------------------------------------------------------------------------
# Parity
# --------------------------------------------------------------------------
def parity(new: np.ndarray, ref: np.ndarray, tol: float) -> dict:
    d = np.abs(new - ref)
    return {"n_rows_compared": int(len(d)), "max_abs_diff": float(d.max()),
            "mean_abs_diff": float(d.mean()), "p99_abs_diff": float(np.percentile(d, 99)),
            "n_rows_over_tolerance": int((d > tol).sum()), "tolerance": tol,
            "status": "PASS" if d.max() <= tol else "FAIL"}


# --------------------------------------------------------------------------
# Coefficient package (logreg only)
# --------------------------------------------------------------------------
def write_coefficient_package(outdir: Path, pipe: Pipeline, feats: list[str],
                              meta: pd.DataFrame) -> dict:
    imp, sc, lr = pipe.named_steps["imputer"], pipe.named_steps["scaler"], pipe.named_steps["model"]
    coefs = lr.coef_[0]
    rows = []
    for i, f in enumerate(feats):
        m = meta.loc[f] if f in meta.index else None
        rows.append({
            "rank": i + 1, "feature_name": f,
            "coefficient": float(coefs[i]), "abs_coefficient": float(abs(coefs[i])),
            "family": (m["family"] if m is not None else None),
            "mean_train": float(sc.mean_[i]), "std_train": float(sc.scale_[i]),
            "null_policy": f"median_impute={float(imp.statistics_[i]):.10g}",
            "timing_status": (m["timing_status"] if m is not None else None),
        })
    df = pd.DataFrame(rows)
    df.to_csv(outdir / "coefficients.csv", index=False)
    (outdir / "intercept.json").write_text(json.dumps({
        "intercept": float(lr.intercept_[0]), "n_features": len(feats),
        "positive_class_index": 1, "classes_": [int(c) for c in lr.classes_],
    }, indent=2), encoding="utf-8")
    (outdir / "score_formula.md").write_text(f"""# Score formula — `{outdir.name}`

Features **are standardized**. The full transform chain, in order, is exactly:

1. **Median impute** — missing values replaced per-feature by `null_policy` in
   `coefficients.csv` (the `SimpleImputer(strategy="median")` statistic fitted on
   the 2021–2024 train split).
2. **Standardize** — `x' = (x - mean_train) / std_train`, both columns in
   `coefficients.csv` (`StandardScaler` fitted on the same train split).
3. **Linear + logistic**:

```
z = intercept + Σ_i ( coefficient_i * x'_i )
p = 1 / (1 + exp(-z))
```

`intercept = {float(lr.intercept_[0]):.17g}` (see `intercept.json`).
`p` is the probability of class `1` = flip occurs within 300 s.

## Where the scaler lives

The imputer and scaler are **not** separate files — they are steps inside the
single `model.joblib` `Pipeline`
(`imputer` → `scaler` → `model`). `coefficients.csv` reproduces their fitted
parameters so the model can be audited and re-implemented in NT **without
unpickling anything**.

## Manual reimplementation check

Apply steps 1–3 to any row of `score_reference_2025.parquet` using only
`coefficients.csv` + `intercept.json`; the result matches the stored `score`
column. This is verified programmatically in `parity_checks.csv` as the
`manual_formula` check — it recomputes every row from the CSV alone.

Feature order is **significant** and frozen in `feature_order.csv`.
""", encoding="utf-8")
    return {"n_coefficients": len(feats), "intercept": float(lr.intercept_[0])}


def manual_formula_check(outdir: Path, X: pd.DataFrame, ref: np.ndarray) -> dict:
    """Recompute probabilities from coefficients.csv + intercept.json ALONE."""
    c = pd.read_csv(outdir / "coefficients.csv")
    b = json.load(open(outdir / "intercept.json"))["intercept"]
    fill = {r.feature_name: float(str(r.null_policy).split("=")[1]) for r in c.itertuples()}
    Xv = X[c["feature_name"].tolist()].astype(float).copy()
    Xv = Xv.fillna(pd.Series(fill))
    z = b + ((Xv.to_numpy() - c["mean_train"].to_numpy()) / c["std_train"].to_numpy()
             ) @ c["coefficient"].to_numpy()
    p = 1.0 / (1.0 + np.exp(-z))
    return parity(p, ref, 1e-9)


# --------------------------------------------------------------------------
# ONNX (secondary only)
# --------------------------------------------------------------------------
def try_onnx(outdir: Path, est, X: pd.DataFrame, ref: np.ndarray) -> dict:
    try:
        import onnx
        import onnxruntime as ort
        import skl2onnx
        from skl2onnx import to_onnx
    except ImportError as e:
        return {"onnx_status": "ONNX_NOT_ATTEMPTED_DEPENDENCY_MISSING", "detail": str(e)}
    try:
        Xs = X.to_numpy(dtype=np.float32)
        onx = to_onnx(est, Xs[:1], target_opset=17,
                      options={id(est): {"zipmap": False}})
        p = outdir / "model.onnx"
        p.write_bytes(onx.SerializeToString())
        sess = ort.InferenceSession(str(p), providers=["CPUExecutionProvider"])
        iname = sess.get_inputs()[0].name
        outs, B = [], 20000
        for i in range(0, len(Xs), B):
            r = sess.run(None, {iname: Xs[i:i + B]})
            prob = r[1]
            outs.append(np.asarray(prob)[:, 1] if np.asarray(prob).ndim == 2
                        else np.asarray([d[1] for d in prob]))
        got = np.concatenate(outs)
        par = parity(got, ref, 1e-6)
        rep = {"onnx_status": "PASS" if par["status"] == "PASS" else
               ("PASS_RELAXED" if par["max_abs_diff"] <= 1e-5 else "FAIL"),
               "opset": 17, "skl2onnx_version": skl2onnx.__version__,
               "onnx_version": onnx.__version__, "onnxruntime_version": ort.__version__,
               "input_dtype": "float32", "input_shape": f"[None, {X.shape[1]}]",
               "onnx_sha256": sha256_file(p), **par}
        if rep["onnx_status"] == "FAIL":
            p.unlink(missing_ok=True)
            rep["note"] = "model.onnx deleted - failed parity, not a usable export"
        (outdir / "onnx_parity_report.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
        return rep
    except Exception as e:  # conversion unsupported / runtime error
        return {"onnx_status": "FAIL", "detail": f"{type(e).__name__}: {e}"}


# --------------------------------------------------------------------------
# Freeze one model
# --------------------------------------------------------------------------
def freeze(spec: dict, inventory: list, parity_rows: list, onnx_rows: list, coef_rows: list):
    mid = spec["model_id"]
    outdir = ART / mid
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"\n=== {mid} ({spec['provenance']}) ===")

    est = spec["estimator"]
    feats = spec["feature_order"]
    joblib.dump(est, outdir / "model.joblib")
    pd.DataFrame({"order": range(1, len(feats) + 1), "feature_name": feats}
                 ).to_csv(outdir / "feature_order.csv", index=False)

    # Reload FROM DISK - everything below scores the reloaded object, not the
    # in-memory one, so the artifact itself is what is being certified.
    reloaded = joblib.load(outdir / "model.joblib")

    scores = {}
    for split, df in spec["score_frames"].items():
        s = reloaded.predict_proba(df[feats])[:, 1]
        scores[split] = s
        if split in ("2025", "2026"):
            out = df[spec["key_cols"]].copy()
            out["score"] = s
            out.to_parquet(outdir / f"score_reference_{split}.parquet", index=False)

    # ---- parity vs the source study's own stored reference ----
    for split, ref in spec["reference_scores"].items():
        r = parity(scores[split], ref, TOL[spec["model_type"]])
        r.update({"model_id": mid, "split": split, "check": "joblib_reload_vs_source",
                  "provenance": spec["provenance"]})
        parity_rows.append(r)
        print(f"  parity {split}: max_abs={r['max_abs_diff']:.3e} -> {r['status']}")
        if r["status"] == "FAIL":
            raise SystemExit(f"MODEL_FREEZE_BLOCKED_PARITY_FAILED: {mid} {split}")

    # ---- AUC cross-check against the source study's published metric ----
    for split, exp in spec.get("expected_auc", {}).items():
        got = float(roc_auc_score(spec["labels"][split], scores[split]))
        ok = abs(got - exp) < 1e-9
        parity_rows.append({"model_id": mid, "split": split, "check": "auc_vs_published",
                            "provenance": spec["provenance"], "n_rows_compared": len(scores[split]),
                            "max_abs_diff": abs(got - exp), "mean_abs_diff": abs(got - exp),
                            "p99_abs_diff": abs(got - exp), "n_rows_over_tolerance": 0 if ok else 1,
                            "tolerance": 1e-9, "status": "PASS" if ok else "FAIL"})
        print(f"  AUC {split}: {got:.10f} vs published {exp} -> {'PASS' if ok else 'FAIL'}")

    # ---- logreg coefficient package ----
    coef_info = {}
    if spec["model_type"] == "logreg":
        coef_info = write_coefficient_package(outdir, reloaded, feats, spec["feature_meta"])
        mf = manual_formula_check(outdir, spec["score_frames"]["2025"][feats], scores["2025"])
        mf.update({"model_id": mid, "split": "2025", "check": "manual_formula",
                   "provenance": spec["provenance"]})
        parity_rows.append(mf)
        print(f"  manual formula: max_abs={mf['max_abs_diff']:.3e} -> {mf['status']}")
        coef_rows.append({"model_id": mid, "n_coefficients": coef_info["n_coefficients"],
                          "intercept": coef_info["intercept"],
                          "manual_formula_status": mf["status"],
                          "manual_formula_max_abs_diff": mf["max_abs_diff"]})

    # ---- ONNX (secondary) ----
    orep = try_onnx(outdir, reloaded, spec["score_frames"]["2025"][feats], scores["2025"])
    orep_row = {"model_id": mid, "model_type": spec["model_type"], **orep}
    onnx_rows.append(orep_row)
    print(f"  onnx: {orep.get('onnx_status')} "
          f"{('max_abs=%.3e' % orep['max_abs_diff']) if 'max_abs_diff' in orep else orep.get('detail','')}")

    # ---- thresholds ----
    (outdir / "threshold_manifest.json").write_text(
        json.dumps(spec["thresholds"], indent=2), encoding="utf-8")

    # ---- manifest ----
    man = {
        "model_id": mid, "status": spec["status"], "provenance": spec["provenance"],
        "model_family": spec["model_family"], "direction": spec["direction"],
        "target": spec["target"], "feature_set_name": spec["feature_set_name"],
        "n_raw_features": spec["n_raw_features"], "n_model_columns": len(feats),
        "feature_order_sha256": sha256_list(feats),
        "raw_feature_list_sha256": spec["raw_feature_list_sha256"],
        "model_artifact_sha256": sha256_file(outdir / "model.joblib"),
        "preprocessor_sha256": spec["preprocessor_sha256"],
        "thresholds_sha256": hashlib.sha256(
            json.dumps(spec["thresholds"], sort_keys=True).encode()).hexdigest(),
        "training_rows": spec["training_rows"], "dev_rows": spec["dev_rows"],
        "test_rows": spec["test_rows"], "train_years": [2021, 2022, 2023, 2024],
        "dev_year": 2025, "test_year": 2026,
        "selected_on": spec["selected_on"], "selected_metric": spec["selected_metric"],
        **VERSIONS,
        "model_class": type(spec["estimator"]).__name__,
        "pipeline_steps": ([s for s, _ in spec["estimator"].steps]
                           if isinstance(spec["estimator"], Pipeline) else None),
        "hyperparameters": spec["hyperparameters"],
        "calibration_method": spec["calibration_method"],
        "score_method": "predict_proba(X[feature_order])[:, 1]",
        "positive_class_index": 1,
        "source_study": spec["source_study"],
        "source_manifest_path": spec["source_manifest_path"],
        "source_git_commit_or_null": GIT,
        "created_at": NOW,
        "current_regime_direction": spec["current_regime_direction"],
        "predicted_flip_direction": spec["predicted_flip_direction"],
        "entry_interpretation": spec["entry_interpretation"],
        "exit_warning_interpretation": spec["exit_warning_interpretation"],
        "causal_convention": spec["causal_convention"],
        "loading_trust_model": "TRUSTED_LOCAL_ONLY - joblib/pickle executes code on "
                               "load. Load only these files, only from this repo, "
                               "never from an untrusted source.",
    }
    (outdir / "manifest.json").write_text(json.dumps(man, indent=2, default=str), encoding="utf-8")

    inventory.append({
        "model_id": mid, "status": spec["status"], "provenance": spec["provenance"],
        "path": str(outdir.relative_to(ROOT)).replace("\\", "/"),
        "model_type": spec["model_type"], "direction": spec["direction"],
        "target": spec["target"], "n_raw_features": spec["n_raw_features"],
        "n_model_columns": len(feats),
        "model_artifact_sha256": man["model_artifact_sha256"],
        "feature_order_sha256": man["feature_order_sha256"],
        "onnx_status": orep.get("onnx_status"),
        "threshold_status": spec["thresholds"].get("threshold_status"),
    })
    spec["_scores"] = scores
    return man


__all__ = ["freeze", "sha256_file", "sha256_list", "parity", "VERSIONS", "GIT",
           "reconstruct_long", "long_frames", "ART", "RESULTS", "WORK", "ROOT",
           "RED", "LONG100", "LONG25", "SHORT_PREP", "SMOKE", "NOW"]
