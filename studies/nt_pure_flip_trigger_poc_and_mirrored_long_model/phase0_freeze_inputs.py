"""Phase 0 -- freeze exact input artifacts (paths + hashes), per SPEC.md.

No model artifact was ever persisted (SPEC.md finding 3): the generator
script and its output score column are hashed instead, with the caveat
recorded explicitly in the manifest rather than a fabricated model hash.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PURE_FLIP = ROOT / "studies" / "short_rth_pure_flip_prediction_enriched"
ENTRY_POLICY = ROOT / "studies" / "short_rth_pure_flip_score_entry_policy"
ENRICHED_RETRAIN = ROOT / "studies" / "short_rth_enriched_volume_level_retrain"
PHASE2 = HERE / "phase2"
PHASE2.mkdir(parents=True, exist_ok=True)

SCORE_COL = "score_F3_volume_delta_plus_price_levels__gbt_raw"


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def sha256_series(s: pd.Series) -> str:
    return hashlib.sha256(s.to_numpy().tobytes()).hexdigest()


def git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def main() -> None:
    cutoffs = json.loads((ENTRY_POLICY / "_work" / "cutoffs.json").read_text(encoding="utf-8"))
    feature_sets = json.loads((ENRICHED_RETRAIN / "_work" / "feature_sets.json").read_text(encoding="utf-8"))
    train_manifest = json.loads(
        (PURE_FLIP / "results" / "train_and_evaluate_manifest.json").read_text(encoding="utf-8"))

    expected_top5, expected_top2p5 = 0.45049368433122905, 0.5064939282727833
    assert abs(cutoffs["top5"] - expected_top5) < 1e-12, "top5 cutoff mismatch vs SPEC"
    assert abs(cutoffs["top2.5"] - expected_top2p5) < 1e-12, "top2.5 cutoff mismatch vs SPEC"

    scored = pd.read_parquet(PURE_FLIP / "_work" / "scored_dev_2025.parquet", columns=[SCORE_COL])

    files_to_hash = {
        "pure_flip_train_and_evaluate_script": PURE_FLIP / "train_and_evaluate.py",
        "pure_flip_phase0_script": PURE_FLIP / "phase0_prepare_data.py",
        "entry_policy_trigger_logic": ENTRY_POLICY / "trigger_logic.py",
        "entry_policy_trigger_grid": ENTRY_POLICY / "trigger_grid.py",
        "scored_dev_2025_parquet": PURE_FLIP / "_work" / "scored_dev_2025.parquet",
        "feature_sets_json": ENRICHED_RETRAIN / "_work" / "feature_sets.json",
        "schedule_trig_B_top2p5": ENTRY_POLICY / "_work" / "schedule_trig_B_top2.5_2025.parquet",
        "schedule_trig_C30_top5": ENTRY_POLICY / "_work" / "schedule_trig_C30_top5_2025.parquet",
        "schedule_trig_B_top5": ENTRY_POLICY / "_work" / "schedule_trig_B_top5_2025.parquet",
    }
    hashes = {k: sha256_file(v) for k, v in files_to_hash.items()}

    manifest = {
        "model": "F3_volume_delta_plus_price_levels + HistGradientBoostingClassifier",
        "model_artifact_persisted": False,
        "model_artifact_persisted_note": (
            "train_and_evaluate.py computes scores in-memory and writes them to "
            "scored_{split}.parquet; the fitted model object itself is never "
            "pickled/joblib-dumped. Determinism (random_state=42) is the basis for "
            "reproducibility, not a saved-artifact hash. Empirically demonstrated "
            "earlier this session: an interrupted 8-combo training run was "
            "restarted from scratch and reproduced byte-identical diagnostics for "
            "every already-completed combo."
        ),
        "training_years": [2021, 2022, 2023, 2024],
        "train_rows": train_manifest["train_rows"],
        "feature_set": "F3_volume_delta_plus_price_levels",
        "n_features": feature_sets["F3_volume_delta_plus_price_levels"].__len__(),
        "frozen_cutoffs": cutoffs,
        "expected_top5": expected_top5, "expected_top2p5": expected_top2p5,
        "score_column": SCORE_COL,
        "score_column_sha256": sha256_series(scored[SCORE_COL]),
        "file_hashes_sha256": hashes,
        "git_commit": git_commit(),
        "git_commit_note": "not available -- no .git directory at repo root" if git_commit() is None else None,
    }
    (HERE / "results" / "phase0_frozen_inputs_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print("Frozen inputs verified and recorded.")
    print(json.dumps({k: v for k, v in manifest.items() if k != "file_hashes_sha256"}, indent=2, default=str))


if __name__ == "__main__":
    main()
