"""Red-team packet C3: same-model_id concurrent writes to the shared model store must be
atomic (never a half-written directory, never a lost update). Before this fix ``store_model``
wrote canonical bytes and the manifest directly into ``models/<id>/...`` with no promotion
barrier, so a concurrent second writer for the same id could observe a partially-written
directory or interleave with the first writer's manifest write."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from research_workflow import model_store as ms

ROOT = Path(__file__).resolve().parents[2]
FEATS = [f"f{i}" for i in range(4)]

_STORE_WORKER = textwrap.dedent("""
    import json, os, sys, time
    sys.path.insert(0, {root!r})
    import joblib
    from research_workflow import model_store as ms
    start_file, model_root, estimator_path, result_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    while not os.path.exists(start_file):
        time.sleep(0.005)
    est = joblib.load(estimator_path)
    lineage = ms.ModelLineage(study_id="redteam_c3", cell_id=None, direction=None, target_arm=None, fold_id=None,
                              config_id=None, seed=None, ordered_inputs={feats!r}, feature_contract_sha256=None,
                              preprocessing_contract_sha256=None, target_contract_sha256=None, target_frame_identity=None,
                              training_population_identity=None, family="logistic_regression")
    try:
        m = ms.store_model(model_id="c3_shared_id", estimator=est, lineage=lineage, tier="ledger",
                           selection_status="candidate", metrics={{"roc_auc": 0.5}}, golden_train_frame=None,
                           model_root=model_root)
        out = {{"ok": True, "pid": os.getpid(), "byte_sha256": m["canonical"]["byte_sha256"], "model_id": m["model_id"]}}
    except Exception as exc:
        out = {{"ok": False, "pid": os.getpid(), "error": f"{{type(exc).__name__}}: {{exc}}"}}
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(out, f)
""")

_EXPORT_WORKER = textwrap.dedent("""
    import json, os, sys, time
    sys.path.insert(0, {root!r})
    from research_workflow import model_store as ms
    start_file, model_root, result_path = sys.argv[1], sys.argv[2], sys.argv[3]
    while not os.path.exists(start_file):
        time.sleep(0.005)
    try:
        rec = ms.add_export("c3_shared_id", "joblib", model_root=model_root)
        out = {{"ok": True, "pid": os.getpid(), "status": rec.get("status")}}
    except Exception as exc:
        out = {{"ok": False, "pid": os.getpid(), "error": f"{{type(exc).__name__}}: {{exc}}"}}
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(out, f)
""")


def _fit_estimator() -> LogisticRegression:
    rng = np.random.default_rng(11)
    n = 200
    X = pd.DataFrame(rng.normal(size=(n, len(FEATS))), columns=FEATS)
    y = pd.Series(((X["f0"] + 0.3 * X["f1"]) > 0).astype(int))
    return LogisticRegression(random_state=0).fit(X, y)


def _launch_round(tmp_path: Path, script_text: str, args_after_root: list, n: int, tag: str) -> list[dict]:
    script = tmp_path / f"worker_{tag}.py"
    script.write_text(script_text, encoding="utf-8")
    start_file = tmp_path / f"start_{tag}"
    result_dir = tmp_path / f"results_{tag}"
    result_dir.mkdir()
    procs = []
    for i in range(n):
        result_path = result_dir / f"{i}.json"
        procs.append(subprocess.Popen([sys.executable, str(script), str(start_file), *args_after_root, str(result_path)]))
    start_file.write_text("go", encoding="utf-8")
    for p in procs:
        assert p.wait(timeout=60) == 0
    return [json.loads((result_dir / f"{i}.json").read_text(encoding="utf-8")) for i in range(n)]


def test_same_id_concurrent_store_model_is_atomic_and_idempotent(tmp_path):
    model_root = tmp_path / "model_root"
    est_path = tmp_path / "estimator.joblib"
    joblib.dump(_fit_estimator(), est_path)

    n = 6
    results = _launch_round(tmp_path, _STORE_WORKER.format(root=str(ROOT), feats=FEATS), [str(model_root), str(est_path)], n, "store")
    assert all(r["ok"] for r in results), results   # never MODEL_ID_COLLISION for identical bytes, never an unhandled crash

    models_dir = model_root / "models"
    model_dirs = [p for p in models_dir.iterdir() if p.is_dir() and p.name != ".staging"]
    assert [p.name for p in model_dirs] == ["c3_shared_id"]   # exactly one model directory
    staging = models_dir / ".staging"
    assert not staging.is_dir() or list(staging.iterdir()) == []   # no staging leftovers

    manifest = ms.read_manifest("c3_shared_id", model_root)
    assert manifest["model_id"] == "c3_shared_id"
    shas = {r["byte_sha256"] for r in results}
    assert shas == {manifest["canonical"]["byte_sha256"]}   # every process's canonical sha matches the persisted one
    assert (model_root / "models" / "c3_shared_id" / "canonical" / "estimator.joblib").is_file()


def test_concurrent_add_export_yields_exactly_one_joblib_record(tmp_path):
    model_root = tmp_path / "model_root"
    est_path = tmp_path / "estimator.joblib"
    joblib.dump(_fit_estimator(), est_path)

    n = 6
    store_results = _launch_round(tmp_path, _STORE_WORKER.format(root=str(ROOT), feats=FEATS), [str(model_root), str(est_path)], n, "store2")
    assert all(r["ok"] for r in store_results)

    export_results = _launch_round(tmp_path, _EXPORT_WORKER.format(root=str(ROOT)), [str(model_root)], n, "export")
    assert all(r["ok"] for r in export_results), export_results

    manifest = ms.read_manifest("c3_shared_id", model_root)
    joblib_exports = [e for e in manifest["exports"] if e.get("format") == "joblib"]
    assert len(joblib_exports) == 1   # read-modify-write on manifest.json is serialized, never duplicated/lost
