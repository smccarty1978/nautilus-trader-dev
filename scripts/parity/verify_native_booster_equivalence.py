#!/usr/bin/env python3
"""Prove a study's committed LightGBM native boosters reproduce their joblib estimators.

This is the evidence a ``native_booster_sha256`` re-record must be backed by. The model
store treats the native booster as a model's CANONICAL representation and hashes its bytes
as identity (``studies/model_registry/<id>.json`` ``native_booster_sha256``,
``model_store.save_canonical`` ``canonical.byte_sha256``). If those bytes are re-exported
after the hash is recorded, the recorded hash matches nothing and every governed reuse path
fails closed -- correctly, because a hash mismatch is indistinguishable from a substituted
model until something proves otherwise. That proof is what this script produces: the booster
and the joblib estimator must score a large real population IDENTICALLY.

Run it as its own process. LightGBM's fatal handler ABORTS the process on a malformed model
file rather than raising, so a parse failure must not be able to take down its caller. (That
is exactly what a CRLF-translated booster does -- see the repo ``.gitattributes``.)

    python scripts/parity/verify_native_booster_equivalence.py \
        --study clean_maturity_flip_model_180s_horizon \
        --bytes-root "/path/to/a/checkout/that/has/the/untracked/joblibs" \
        --out artifacts/parity/native_booster_equivalence_<study>.json

``--bytes-root`` exists because ``.joblib`` and the candidate frames are NOT git-tracked:
only ``.booster.txt`` and ``.golden.json`` are. The boosters are read from THIS worktree
(they are the bytes whose identity is being established); the joblibs and the scoring frame
are read from the checkout named by ``--bytes-root``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    import joblib
    import lightgbm as lgb
    import numpy as np
    import pandas as pd

    ap = argparse.ArgumentParser()
    ap.add_argument("--study", required=True)
    ap.add_argument("--bytes-root", required=True,
                    help="checkout holding the untracked .joblib artifacts and candidate frames")
    ap.add_argument("--frame", default="artifacts/train_candidates_merged.parquet",
                    help="study-relative parquet of real rows to score")
    ap.add_argument("--max-rows", type=int, default=200_000)
    ap.add_argument("--out", required=True)
    ns = ap.parse_args()

    study_dir = ROOT / "studies" / ns.study
    bytes_dir = Path(ns.bytes_root) / "studies" / ns.study
    models = study_dir / "artifacts" / "models"
    joblibs = bytes_dir / "artifacts" / "models"
    registry = ROOT / "studies" / "model_registry"

    frame = pd.read_parquet(bytes_dir / ns.frame)
    report = {
        "schema_version": 1,
        "kind": "native_booster_equivalence",
        "study_id": ns.study,
        "scoring_frame": ns.frame,
        "scoring_frame_rows_available": int(len(frame)),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "models": [],
    }

    failures = []
    for booster_path in sorted(models.glob("*.booster.txt")):
        model_id = booster_path.name.split(".", 1)[0]
        record = json.loads((registry / f"{model_id}.json").read_text(encoding="utf-8"))
        golden = json.loads((models / f"{model_id}.golden.json").read_text(encoding="utf-8"))
        inputs = list(golden["ordered_inputs"])

        bundle = joblib.load(joblibs / f"{model_id}.joblib")
        arm = golden.get("arm") or next(iter(bundle))
        cell = bundle[arm]
        estimator = cell["estimator"]
        booster = lgb.Booster(model_file=str(booster_path))

        rows = frame[inputs].dropna()
        n = int(min(len(rows), ns.max_rows))
        X = rows.iloc[:n]
        from_joblib = np.asarray(estimator.predict_proba(X)[:, 1], dtype=float)
        from_booster = np.asarray(booster.predict(X), dtype=float)
        delta = float(np.max(np.abs(from_joblib - from_booster))) if n else None

        golden_x = pd.DataFrame(golden["rows"], columns=inputs)
        golden_delta = float(np.max(np.abs(
            np.asarray(booster.predict(golden_x), dtype=float)
            - np.asarray(golden["expected_scores"], dtype=float))))

        entry = {
            "model_id": model_id,
            "arm": arm,
            "model_role": record.get("model_role"),
            "bundle_fit_identity_sha256": cell.get("fit_identity_sha256"),
            "n_trees": int(booster.num_trees()),
            "n_estimators_declared": (record.get("hyperparameters") or {}).get("n_estimators"),
            "ordered_inputs": inputs,
            "rows_scored": n,
            "max_abs_delta_booster_vs_joblib": delta,
            "max_abs_delta_booster_vs_golden_expected": golden_delta,
            "equivalent": bool(delta == 0.0 and golden_delta == 0.0),
            "recorded_native_booster_sha256": record.get("native_booster_sha256"),
            "current_native_booster_sha256": _sha(booster_path),
            "recorded_artifact_sha256": record.get("artifact_sha256"),
            "current_artifact_sha256": _sha(joblibs / f"{model_id}.joblib"),
            "booster_has_crlf": b"\r\n" in booster_path.read_bytes(),
        }
        entry["artifact_sha256_matches"] = entry["recorded_artifact_sha256"] == entry["current_artifact_sha256"]
        entry["native_booster_sha256_matches"] = (
            entry["recorded_native_booster_sha256"] == entry["current_native_booster_sha256"])
        if not entry["equivalent"]:
            failures.append(model_id)
        report["models"].append(entry)

    report["all_equivalent"] = not failures
    report["failed_model_ids"] = failures

    out = ROOT / ns.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"STATUS": "OK" if not failures else "FAIL", "out": ns.out,
                      "models": len(report["models"]), "all_equivalent": report["all_equivalent"]},
                     sort_keys=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
