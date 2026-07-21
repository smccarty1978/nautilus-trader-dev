"""Driver - assemble every model spec and freeze it.

Freezes:
  short_bearish_flip_top25_current_reference  PROVISIONAL  (COPIED, GBT)
  short_bearish_flip_top100_ref               FINAL        (COPIED, GBT)
  long_bullish_flip_top25                     FINAL        (RECONSTRUCTED, logreg)
  long_bullish_flip_top50                     FINAL        (RECONSTRUCTED, logreg)
  long_bullish_flip_top100                    FINAL        (RECONSTRUCTED, GBT)

The short-side model is PROVISIONAL because its own source manifest carries
status "candidate" and the NT parity smoke that consumes it has not published a
STUDY_REPORT - per the brief's stop condition, it is frozen as the current
reference but not marked final.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from freeze_models import (ART, GIT, LONG25, LONG100, NOW, RED, RESULTS, ROOT,  # noqa: E402
                           SHORT_PREP, SMOKE, VERSIONS, WORK, freeze, long_frames,
                           parity, reconstruct_long, sha256_file, sha256_list)

SHORT_TARGET = "bearish_regime_flip_within_300s"
LONG_TARGET = "bullish_regime_flip_within_300s"
SHORT_KEYS = ["regime_start_ns", "observation_time", "year", "confirm_flip_ns",
              "time_to_bearish_flip_s", SHORT_TARGET]
LONG_KEYS = ["regime_start_ns", "observation_time", "year", "confirm_flip_ns",
             "time_to_bullish_flip_s", LONG_TARGET]

CAUSAL_LONG = ("Strict: latest_source_ts_used < observation_time. Raw 1s bars are "
               "open-labelled ([t, t+1s)), so the last COMPLETED bar at "
               "observation_time has ts_event strictly before it. Corrected in "
               "long_rth_mirrored_surface_top100_training after a CRITICAL audit finding.")
CAUSAL_SHORT = ("INHERITED 1s LOOK-AHEAD (disclosed, NOT fixed): the upstream "
                "attach_features.py bar-snap uses searchsorted(..., side='right')-1, "
                "which includes a bar at ts_event == observation_time - a still-forming "
                "open-labelled bar. Affects the ohlcv+price features. The long side "
                "fixed this; this short artifact does not. Its metrics are therefore "
                "~1s optimistic. See long_rth_mirrored_surface_top100_training/audit/audit.md.")


def main() -> None:
    t0 = time.time()
    inventory, parity_rows, onnx_rows, coef_rows = [], [], [], []
    notes = []

    # ================= SHORT SIDE (existing fitted artifacts) =================
    short_prep = {y: pd.read_parquet(SHORT_PREP / f"prepared_{y}.parquet")
                  for y in (2021, 2022, 2023, 2024, 2025, 2026)}
    short_train = pd.concat([short_prep[y] for y in (2021, 2022, 2023, 2024)], ignore_index=True)
    short_frames = {"train": short_train, "2025": short_prep[2025], "2026": short_prep[2026]}
    short_labels = {k: v[SHORT_TARGET].astype(int).to_numpy() for k, v in short_frames.items()}

    binding = json.load(open(SMOKE / "config" / "model_binding.json"))
    frozen_thr = json.load(open(SMOKE / "config" / "frozen_thresholds.json"))

    short_specs = [
        ("short_bearish_flip_top25_current_reference", "F3_top25_gbt_v1", "TOP25",
         "PROVISIONAL", frozen_thr),
        ("short_bearish_flip_top100_ref", "F3_top100_gbt_v1", "TOP100", "FINAL", None),
    ]
    for mid, src_id, fsname, status, thr_src in short_specs:
        srcdir = RED / "artifacts" / "models" / src_id
        src_man = json.load(open(srcdir / "manifest.json"))
        src_metrics = json.load(open(srcdir / "metrics_2025.json"))
        feats = json.load(open(srcdir / "feature_list.json"))["ordered_features"]
        est = joblib.load(srcdir / "model.joblib")

        # Verify the SOURCE artifact hash matches what the source study recorded.
        src_sha = sha256_file(srcdir / "model.joblib")
        if src_sha != src_man["model_sha256"]:
            raise SystemExit(f"MODEL_FREEZE_BLOCKED_PARITY_FAILED: {src_id} model.joblib "
                             f"sha256 {src_sha} != recorded {src_man['model_sha256']}")

        if thr_src:
            thresholds = {
                "threshold_status": "PARTIAL_FROM_SOURCE",
                "threshold_source": str((SMOKE / "config" / "frozen_thresholds.json"
                                         ).relative_to(ROOT)).replace("\\", "/"),
                "threshold_source_sha256": sha256_file(SMOKE / "config" / "frozen_thresholds.json"),
                "threshold_selection_year": 2025,
                "threshold_selection_rule": thr_src["threshold_derivation_method"],
                "top20_cutoff": None, "top15_cutoff": None, "top10_cutoff": None,
                "top5_cutoff": thr_src["top_5pct_threshold"],
                "top2p5_cutoff": thr_src["top_2_5pct_threshold"],
                "not_provided_note": "top20/top15/top10 were NEVER selected upstream. "
                                     "Left null - not invented, not recomputed.",
                "selected_trigger_variants_using_this_model": [
                    "nt_reduced_f3_top25_population_parity_smoke (march_bounded_r5)"],
            }
        else:
            thresholds = {"threshold_status": "NOT_SELECTED",
                          "threshold_source": None, "threshold_selection_year": None,
                          "threshold_selection_rule": None,
                          "top20_cutoff": None, "top15_cutoff": None, "top10_cutoff": None,
                          "top5_cutoff": None, "top2p5_cutoff": None,
                          "selected_trigger_variants_using_this_model": []}

        spec = {
            "model_id": mid, "status": status, "provenance": "COPIED_EXISTING_FITTED_ARTIFACT",
            "estimator": est, "feature_order": feats, "model_type": "gbt",
            "model_family": src_man["model_family"], "direction": "short",
            "target": SHORT_TARGET, "feature_set_name": fsname,
            "n_raw_features": 25 if fsname == "TOP25" else 100,
            "raw_feature_list_sha256": src_man["ordered_feature_list_sha256"],
            "preprocessor_sha256": None,
            "score_frames": short_frames, "labels": short_labels, "key_cols": SHORT_KEYS,
            "reference_scores": {},   # no per-row refs stored upstream; see extra checks
            "expected_auc": {"train": src_metrics["train"]["auc"],
                             "2025": src_metrics["dev_2025"]["auc"]},
            "training_rows": src_man["training_row_count"],
            "dev_rows": src_man["development_row_count"], "test_rows": len(short_prep[2026]),
            "selected_on": 2025, "selected_metric": "2025 AUC (upstream reduction study)",
            "hyperparameters": src_man["hyperparameters"], "calibration_method": None,
            "source_study": "studies/runtime_constrained_f3_feature_reduction",
            "source_manifest_path": str((srcdir / "manifest.json").relative_to(ROOT)).replace("\\", "/"),
            "thresholds": thresholds,
            "current_regime_direction": 1, "predicted_flip_direction": "bearish",
            "entry_interpretation": "short counter-regime entry timing",
            "exit_warning_interpretation": "long exit warning",
            "causal_convention": CAUSAL_SHORT,
            "feature_meta": None,
        }
        man = freeze(spec, inventory, parity_rows, onnx_rows, coef_rows)

        # Extra bit-exact checks unique to the short side.
        s25 = spec["_scores"]["2025"]
        col_sha = hashlib.sha256(s25.tobytes()).hexdigest()
        if thr_src:
            ok = col_sha == thr_src["source_score_column_sha256"]
            parity_rows.append({"model_id": mid, "split": "2025",
                                "check": "score_column_sha256_vs_frozen_thresholds",
                                "provenance": spec["provenance"], "n_rows_compared": len(s25),
                                "max_abs_diff": 0.0 if ok else float("nan"),
                                "mean_abs_diff": 0.0 if ok else float("nan"),
                                "p99_abs_diff": 0.0 if ok else float("nan"),
                                "n_rows_over_tolerance": 0 if ok else len(s25),
                                "tolerance": 0.0, "status": "PASS" if ok else "FAIL"})
            print(f"  score-column sha256 vs frozen_thresholds: {'PASS' if ok else 'FAIL'}")
            if not ok:
                raise SystemExit(f"MODEL_FREEZE_BLOCKED_PARITY_FAILED: {mid} score column sha")
            for q, key in ((0.95, "top_5pct_threshold"), (0.975, "top_2_5pct_threshold")):
                got, exp = float(np.quantile(s25, q)), thr_src[key]
                tok = abs(got - exp) <= 1e-15
                parity_rows.append({"model_id": mid, "split": "2025",
                                    "check": f"threshold_recompute_q{q}",
                                    "provenance": spec["provenance"], "n_rows_compared": len(s25),
                                    "max_abs_diff": abs(got - exp), "mean_abs_diff": abs(got - exp),
                                    "p99_abs_diff": abs(got - exp),
                                    "n_rows_over_tolerance": 0 if tok else 1,
                                    "tolerance": 1e-15, "status": "PASS" if tok else "FAIL"})
            if binding["model_sha256"] != man["model_artifact_sha256"]:
                notes.append(f"{mid}: frozen copy sha256 equals source sha256 "
                             f"{man['model_artifact_sha256'][:12]}… (byte-identical copy)")

    notes.append("Short-side TOP50: NO such model exists. The short reduction ladder is "
                 "25/40/60/80/100/150/250 (studies/runtime_constrained_f3_feature_reduction/"
                 "artifacts/models/). The brief's 'TOP50/TOP100 references' requirement is "
                 "satisfied by TOP100. Recorded, not silently skipped.")

    del short_train, short_frames, short_prep
    import gc
    gc.collect()

    # ================= LONG SIDE (reconstruction, parity-proven) =================
    ltrain, (ldev, ltest) = long_frames()
    y_train = ltrain[LONG_TARGET].astype(int).to_numpy()
    long_frames_map = {"train": ltrain, "2025": ldev, "2026": ltest}
    long_labels = {k: v[LONG_TARGET].astype(int).to_numpy() for k, v in long_frames_map.items()}

    fsm = json.load(open(LONG25 / "results" / "feature_sets_manifest.json"))
    top100 = json.load(open(LONG100 / "results" / "top100_feature_manifest.json"))["feature_names_in_order"]
    sets = {"TOP25": fsm["feature_sets"]["TOP25"]["feature_names_in_order"],
            "TOP50": fsm["feature_sets"]["TOP50"]["feature_names_in_order"],
            "TOP100": top100}
    fmeta = pd.read_csv(LONG100 / "results" / "top100_feature_list.csv").set_index("feature_name")
    lmetrics = pd.read_csv(LONG25 / "results" / "model_metrics.csv").set_index(["feature_set", "model"])

    long_specs = [("long_bullish_flip_top25", "TOP25", "logreg"),
                  ("long_bullish_flip_top50", "TOP50", "logreg"),
                  ("long_bullish_flip_top100", "TOP100", "gbt")]

    for mid, fsname, kind in long_specs:
        feats = sets[fsname]
        ref = {}
        for split in ("2025", "2026"):
            rp = LONG25 / "_work" / f"pred_{fsname}_{kind}_{split}.parquet"
            if not rp.exists():
                raise SystemExit(f"MODEL_FREEZE_BLOCKED_MISSING_ARTIFACTS: no stored "
                                 f"reference predictions at {rp} - cannot prove parity")
            rdf = pd.read_parquet(rp)
            base = long_frames_map[split]
            if not (rdf["observation_time"].to_numpy() == base["observation_time"].to_numpy()).all():
                raise SystemExit(f"MODEL_FREEZE_BLOCKED_PARITY_FAILED: {mid} {split} row "
                                 f"order differs from prepared data - parity would be invalid")
            ref[split] = rdf["score"].to_numpy()

        print(f"\n[reconstructing {mid} ...]")
        est = reconstruct_long(feats, kind, ltrain, y_train)

        spec = {
            "model_id": mid, "status": "FINAL",
            "provenance": "RECONSTRUCTED_NO_FITTED_ARTIFACT_EXISTED",
            "estimator": est, "feature_order": feats, "model_type": kind,
            "model_family": type(est).__name__, "direction": "long",
            "target": LONG_TARGET, "feature_set_name": fsname,
            "n_raw_features": len(feats),
            "raw_feature_list_sha256": (fsm["feature_sets"][fsname]["ordered_list_sha256"]
                                        if fsname != "TOP100" else
                                        fsm["ordered_top100_feature_list_sha256"]),
            "preprocessor_sha256": None,
            "score_frames": long_frames_map, "labels": long_labels, "key_cols": LONG_KEYS,
            "reference_scores": ref,
            "expected_auc": {"2025": float(lmetrics.loc[(fsname, kind), "2025_auc"]),
                             "2026": float(lmetrics.loc[(fsname, kind), "2026_auc"])},
            "training_rows": len(ltrain), "dev_rows": len(ldev), "test_rows": len(ltest),
            "selected_on": 2025,
            "selected_metric": "2025 AUC (tie-break 2025 AP); 2026 never used for selection",
            "hyperparameters": ({"max_depth": 3, "learning_rate": 0.05, "max_iter": 200,
                                 "random_state": 42} if kind == "gbt" else
                                {"penalty": "l2", "C": 1.0, "max_iter": 1000,
                                 "solver": "lbfgs", "random_state": 42,
                                 "imputer": "median", "scaler": "StandardScaler"}),
            "calibration_method": None,
            "source_study": ("studies/long_rth_pure_flip_top50_top25_training"
                             if fsname != "TOP100" else
                             "studies/long_rth_mirrored_surface_top100_training"),
            "source_manifest_path": str((LONG25 / "results" / "model_manifest.json"
                                         ).relative_to(ROOT)).replace("\\", "/"),
            "thresholds": {"threshold_status": "NOT_SELECTED",
                           "threshold_source": None, "threshold_selection_year": None,
                           "threshold_selection_rule": None,
                           "top20_cutoff": None, "top15_cutoff": None, "top10_cutoff": None,
                           "top5_cutoff": None, "top2p5_cutoff": None,
                           "selected_trigger_variants_using_this_model": [],
                           "note": "No long-side trigger study has run. Thresholds must be "
                                   "chosen on 2025 (or new data) by a future study - never 2026."},
            "current_regime_direction": -1, "predicted_flip_direction": "bullish",
            "entry_interpretation": "long counter-regime entry timing",
            "exit_warning_interpretation": "short exit warning",
            "causal_convention": CAUSAL_LONG,
            "feature_meta": fmeta,
        }
        freeze(spec, inventory, parity_rows, onnx_rows, coef_rows)

    # ================= write study-level results =================
    pd.DataFrame(inventory).to_csv(RESULTS / "artifact_inventory.csv", index=False)
    pd.DataFrame(parity_rows).to_csv(RESULTS / "parity_checks.csv", index=False)
    pd.DataFrame(onnx_rows).to_csv(RESULTS / "onnx_export_report.csv", index=False)
    pd.DataFrame(coef_rows).to_csv(RESULTS / "coefficient_inventory.csv", index=False)
    (RESULTS / "freeze_manifest.json").write_text(json.dumps({
        "study": "freeze_reduced_flip_model_artifacts",
        "created_at": NOW, "git_commit": GIT, **VERSIONS,
        "n_models_frozen": len(inventory),
        "source_of_truth_format": "joblib (sklearn estimator/Pipeline)",
        "onnx_role": "secondary export only; never source of truth",
        "notes": notes,
        "tolerances": {"logreg_joblib": 1e-12, "gbt_joblib": 1e-9,
                       "onnx_preferred": 1e-6, "onnx_acceptable": 1e-5},
        "runtime_s": round(time.time() - t0, 1),
    }, indent=2), encoding="utf-8")
    print(f"\nfrozen {len(inventory)} models in {time.time()-t0:.1f}s")
    print(pd.DataFrame(parity_rows)[["model_id", "split", "check", "max_abs_diff", "status"]
                                    ].to_string(index=False))


if __name__ == "__main__":
    main()
