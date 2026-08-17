"""Reproducibility: equal identity must produce equivalent artifacts.

`ANALYSIS_HARNESS_A0_CONTRACT.md` §6: "Equal identity must produce equivalent
artifacts; different identity must be visibly different." These tests assert both
directions, end to end, so a future change that quietly makes results
run-order-dependent or timestamp-dependent fails here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.analysis import modeling as MOD  # noqa: E402
from research.analysis import reporting as R  # noqa: E402
from research.analysis.loader import (  # noqa: E402
    get_features_targets_metadata, validate_collection, write_dataset_identity,
)
from research.analysis.spec import load_analysis_spec, parse_analysis_spec  # noqa: E402
from scripts.tests.analysis_fixtures import (  # noqa: E402
    FIXTURE_A_RUN, load_synthetic, make_synthetic_collection, resolve_real_runs_root,
)

VOLATILE = {"generated_utc", "fitted_utc", "frozen_utc"}


def strip_volatile(obj):
    """Removes wall-clock fields, which are provenance, not results."""
    if isinstance(obj, dict):
        return {k: strip_volatile(v) for k, v in obj.items() if k not in VOLATILE}
    if isinstance(obj, list):
        return [strip_volatile(v) for v in obj]
    return obj


def spec_for(bundle, **over):
    payload = {"analysis_id": "repro", "collection": {"run_id": bundle["run_id"]},
               "partitions": ["train"], "seed": 1234}
    payload.update(over)
    return parse_analysis_spec(payload)


def run_pipeline(bundle, tmp_path, spec):
    col = load_synthetic(bundle)
    report = validate_collection(col, spec)
    assert report.passed, [c.to_dict() for c in report.failures]
    X, y, meta = get_features_targets_metadata(col, spec, report)
    ident = write_dataset_identity(col, report, tmp_path / "dataset_identity.json", spec)

    models = MOD.fit_arms(X, y, spec, dataset_identity_sha256=ident["collection_identity_sha256"],
                          meta=meta)
    arm_scores = {name: MOD.score_and_record(m, X[list(m.provenance.ordered_features)])[0]
                  for name, m in models.items()}
    tables = R.build_standard_tables(
        y, meta, scores=arm_scores["A"], arm_scores=arm_scores,
        dataset_identity_sha256=ident["collection_identity_sha256"],
        analysis_spec_sha256=spec.analysis_spec_sha256,
    )
    manifest = MOD.write_model_manifest(models, tmp_path / "model_manifest.json")
    ctx = R.build_analysis_context(
        analysis_id=spec.analysis_id, question="repro check", dataset_identity=ident,
        analysis_spec_sha256=spec.analysis_spec_sha256, validation=report.to_dict(),
        tables=tables,
    )
    return {
        "identity": ident,
        "validation": report.to_dict(),
        "tables": {n: t.to_dict() for n, t in tables.items()},
        "model_manifest": manifest,
        "context": ctx,
        "scores": {k: np.asarray(v).tolist() for k, v in arm_scores.items()},
    }


ARMS = [
    {"name": "A", "features": ["f_alpha"]},
    {"name": "B", "features": ["f_alpha", "f_beta"]},
    {"name": "C", "features": ["f_alpha", "f_beta", "f_gamma"]},
]


def test_same_identity_and_seed_reproduces_equivalent_artifacts(tmp_path):
    bundle = make_synthetic_collection(tmp_path / "src", n_rows=300)
    spec = spec_for(bundle, model_arms=ARMS)

    first = run_pipeline(bundle, tmp_path / "run1", spec)
    second = run_pipeline(bundle, tmp_path / "run2", spec)

    assert strip_volatile(first["identity"]) == strip_volatile(second["identity"])
    assert strip_volatile(first["validation"]) == strip_volatile(second["validation"])
    assert strip_volatile(first["tables"]) == strip_volatile(second["tables"])
    assert strip_volatile(first["model_manifest"]) == strip_volatile(second["model_manifest"])
    assert first["scores"] == second["scores"]
    assert (first["context"]["identity"]["collection_identity_sha256"]
            == second["context"]["identity"]["collection_identity_sha256"])


def test_changed_seed_is_visibly_different(tmp_path):
    bundle = make_synthetic_collection(tmp_path / "src", n_rows=300)
    a = run_pipeline(bundle, tmp_path / "a", spec_for(bundle, seed=1, model_arms=ARMS))
    b = run_pipeline(bundle, tmp_path / "b", spec_for(bundle, seed=2, model_arms=ARMS))

    assert (a["context"]["identity"]["analysis_spec_sha256"]
            != b["context"]["identity"]["analysis_spec_sha256"])
    a_ids = {k: v["fit_identity_sha256"] for k, v in a["model_manifest"]["arms"].items()}
    b_ids = {k: v["fit_identity_sha256"] for k, v in b["model_manifest"]["arms"].items()}
    assert a_ids != b_ids


def test_changed_data_is_visibly_different(tmp_path):
    a_bundle = make_synthetic_collection(tmp_path / "a_src", n_rows=300, seed=1)
    b_bundle = make_synthetic_collection(tmp_path / "b_src", n_rows=300, seed=2)
    a = run_pipeline(a_bundle, tmp_path / "a", spec_for(a_bundle, model_arms=ARMS))
    b = run_pipeline(b_bundle, tmp_path / "b", spec_for(b_bundle, model_arms=ARMS))
    assert (a["identity"]["collection_identity_sha256"]
            != b["identity"]["collection_identity_sha256"])
    assert a["scores"] != b["scores"]


def test_arm_identities_differ_within_one_run(tmp_path):
    bundle = make_synthetic_collection(tmp_path / "src", n_rows=300)
    out = run_pipeline(bundle, tmp_path / "r", spec_for(bundle, model_arms=ARMS))
    ids = {v["fit_identity_sha256"] for v in out["model_manifest"]["arms"].values()}
    assert len(ids) == 3


def test_dataset_identity_json_is_byte_stable_across_runs(tmp_path):
    bundle = make_synthetic_collection(tmp_path / "src", n_rows=120)
    spec = spec_for(bundle)
    col = load_synthetic(bundle)
    report = validate_collection(col, spec)
    p1 = tmp_path / "one.json"
    p2 = tmp_path / "two.json"
    write_dataset_identity(col, report, p1, spec)
    write_dataset_identity(col, report, p2, spec)
    assert p1.read_bytes() == p2.read_bytes()


def test_shipped_example_spec_parses_and_is_train_only():
    spec = load_analysis_spec(REPO_ROOT / "analyses" / "fixture_a_structural_smoke.yaml")
    assert spec.run_id == FIXTURE_A_RUN
    assert spec.partitions == ("train",)
    assert spec.model_arms == ()          # declares no arms -> no fit, no threshold
    assert spec.allow_unsealed_collection is False
    assert len(spec.analysis_spec_sha256) == 64
