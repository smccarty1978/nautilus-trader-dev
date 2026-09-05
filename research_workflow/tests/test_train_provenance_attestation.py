"""Additive TRAIN provenance repair, and the booster-byte corruption that motivated it.

A historical TRAIN freeze written before the ``provenance: "TRAIN_ONLY"`` marker existed cannot be
edited -- a closed study's artifacts are immutable. The marker is therefore carried by a SEPARATE
attestation that binds the freeze bytes, the model bytes and the parent's audited authority by
exact hash.

The whole value of that mechanism is that it is exact. These tests exist to prove it is not a
back door: every binding it makes must be checkable, and every mismatch must fail closed. There is
deliberately no "missing provenance means TRAIN" path.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import joblib
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from research.analysis.identity import canonical_sha256
from research.schemas.study_spec import DerivedCausalInputSpec
from research_workflow.external_model_scoring import ExternalModelScoringError, FrozenExternalModelScorer

REPO_ROOT = Path(__file__).resolve().parents[2]
PARENT_ID = "clean_maturity_flip_model_180s_horizon"
REAL_PARENT = REPO_ROOT / "studies" / PARENT_ID
COMPOSITE = "09b5c66db8ec72bbf05f539c6a877dc8c9198774f4c4b7117fdea72fd618f48a"


def file_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# 1. the corruption that started this: CRLF checkout must not touch booster bytes
# --------------------------------------------------------------------------- #
def test_gitattributes_protects_booster_bytes_from_eol_conversion():
    """LightGBM's native format is line-oriented text. Without a rule, core.autocrlf rewrites it
    on checkout, which both breaks the recorded hash AND makes the file unparseable."""
    ga = REPO_ROOT / ".gitattributes"
    assert ga.is_file(), ".gitattributes is required: it is the only thing preventing EOL conversion"
    assert any(line.split("#")[0].strip() in ("*.booster.txt -text", "*.booster.txt binary")
               for line in ga.read_text(encoding="utf-8").splitlines()), \
        "*.booster.txt must be declared -text"
    r = subprocess.run(["git", "check-attr", "text", "--", "x.booster.txt"],
                       cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert "text: unset" in r.stdout, f"git does not consider *.booster.txt binary: {r.stdout!r}"


def test_committed_boosters_are_byte_identical_in_the_working_tree():
    """A clean checkout must reproduce the committed bytes exactly, or every recorded
    native_booster_sha256 is meaningless."""
    boosters = sorted(REPO_ROOT.glob("studies/*/artifacts/models/*.booster.txt"))
    if not boosters:
        pytest.skip("no preserved native boosters in this checkout")
    checked = 0
    for path in boosters:
        rel = path.relative_to(REPO_ROOT).as_posix()
        blob = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=str(REPO_ROOT), capture_output=True)
        if blob.returncode != 0:
            continue                                    # untracked, nothing to compare against
        raw = path.read_bytes()
        assert b"\r\n" not in raw, f"{rel} was CRLF-converted on checkout"
        assert hashlib.sha256(raw).hexdigest() == hashlib.sha256(blob.stdout).hexdigest(), \
            f"{rel} differs from its committed bytes"
        checked += 1
    assert checked, "no tracked boosters were actually compared"


def test_the_known_bad_booster_record_is_preserved_not_rewritten():
    """The historical failure must stay visible: the recorded hash matches no byte state that
    exists, and re-recording it would erase the evidence that it ever did."""
    registry = REPO_ROOT / "studies" / "model_registry"
    for model_id, recorded in (
        ("ccd587dfed77d1c87029bcd779abb1f6b70fa63beab5c99f5439653746963b0c",
         "3686a5d2b25b15ef3bb31d24483ddd808c6812e4142baa3d124cd45dbdba7f86"),
        ("209da0ff0c922e02ab02f78408d0591bd0b2e762a71ecd3ed010856ca45051e6",
         "dc134a9aecb6bb9303095d7a8eee0ec5a105f516e30237d0e1d2f17016ad1aac"),
    ):
        record_path = registry / f"{model_id}.json"
        if not record_path.is_file():
            pytest.skip("legacy model registry not present in this checkout")
        assert json.loads(record_path.read_text(encoding="utf-8"))["native_booster_sha256"] == recorded


def test_a_mismatched_native_booster_is_still_rejected(tmp_path):
    """The byte check must not have been relaxed while unblocking the child study."""
    from research_workflow.model_artifacts import ModelArtifactError, assert_scientific_status_reusable  # noqa: F401
    from research_workflow import model_artifacts
    studies = tmp_path / "studies"
    mdir = studies / "p" / "artifacts" / "models"
    mdir.mkdir(parents=True)
    (mdir / "m.joblib").write_bytes(b"artifact")
    (mdir / "m.golden.json").write_text("{}", encoding="utf-8")
    (mdir / "m.booster.txt").write_text("tree\n", encoding="utf-8")
    rec = {"model_id": "m", "artifact_path": "p/artifacts/models/m.joblib",
           "artifact_sha256": file_sha(mdir / "m.joblib"),
           "golden_fixture_path": "p/artifacts/models/m.golden.json",
           "golden_fixture_sha256": file_sha(mdir / "m.golden.json"),
           "native_booster_path": "p/artifacts/models/m.booster.txt",
           "native_booster_sha256": "0" * 64,
           "scientific_status": "VALID_PRIMARY", "reuse_status": "PERMITTED",
           "preprocessing_identity": {"kind": "identity"}}
    (studies / "model_registry").mkdir(parents=True)
    (studies / "model_registry" / "m.json").write_text(json.dumps(rec), encoding="utf-8")
    with pytest.raises(model_artifacts.ModelArtifactError, match="NATIVE_BOOSTER_CORRUPT"):
        model_artifacts.resolve_model("m", registry_root=studies / "model_registry")


# --------------------------------------------------------------------------- #
# 2. a hermetic parent with an un-stamped TRAIN freeze
# --------------------------------------------------------------------------- #
def _parent(tmp_path: Path, *, provenance=None) -> tuple[Path, dict]:
    parent = tmp_path / "studies" / "parent"
    (parent / "artifacts").mkdir(parents=True)
    (parent / "audit").mkdir(parents=True)
    model = LogisticRegression().fit([[0.0, 0.0], [1.0, 1.0]], [0, 1])
    joblib.dump({"C": {"estimator": model, "fit_identity_sha256": "fit-c"}}, parent / "artifacts/models.joblib")
    (parent / "artifacts/preprocessing.json").write_text('{"identity":"prep"}', encoding="utf-8")
    freeze = {"study_id": "parent", "partition": "train",
              "model_hashes": {"C": "fit-c"}, "feature_sets": {"C": ["a", "b"]},
              "preprocessing_hash": "prep-identity",
              "thresholds": {"C": {"p90": {"threshold": 0.5, "derivation_population": "train"}}},
              "deciles": {"C": {"derivation": "TRAIN_ONLY"}}}
    if provenance is not None:
        freeze["provenance"] = provenance
    (parent / "artifacts/freeze.json").write_text(json.dumps(freeze, sort_keys=True), encoding="utf-8")

    closure = {"schema_version": 1, "study_id": "parent", "status": "CLOSED",
               "bound_evidence": {"execution_composite_sha256": COMPOSITE,
                                  "train_freeze_sha256": "tf",
                                  "causal_audit": {"verdict": "CLEAR", "pass": 1, "auditor": "a"},
                                  "contract_audit": {"verdict": "CLEAR", "pass": 1, "auditor": "b"}}}
    closure["closure_identity_sha256"] = canonical_sha256(closure)
    (parent / "artifacts/study_closure.json").write_text(json.dumps(closure, sort_keys=True), encoding="utf-8")
    for name in ("status.json", "contract_status.json"):
        (parent / "audit" / name).write_text(json.dumps(
            {"verdict": "CLEAR", "audited_execution_composite_sha256": COMPOSITE}), encoding="utf-8")
    return parent, freeze


def _write_attestation(parent: Path) -> Path:
    r = subprocess.run([sys.executable, str(REPO_ROOT / "scripts/write_train_provenance_attestation.py"),
                        "--study", str(parent),
                        "--cell", "LONG=artifacts/freeze.json:artifacts/models.joblib:C"],
                       cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return parent / "artifacts/train_provenance_attestation.json"


def _spec(parent: Path, freeze: dict, **over) -> DerivedCausalInputSpec:
    body = {"name": "parent_score", "parent_study_id": "parent",
            "parent_train_freeze_artifact": "artifacts/freeze.json",
            "parent_train_freeze_artifact_sha256": file_sha(parent / "artifacts/freeze.json"),
            "parent_frozen_execution_composite_sha256": COMPOSITE,
            "model_hashes": {"C": "fit-c"}, "preprocessing_hash": "prep-identity",
            "model_artifact_path": "artifacts/models.joblib",
            "model_artifact_sha256": file_sha(parent / "artifacts/models.joblib"),
            "preprocessing_artifact_path": "artifacts/preprocessing.json",
            "preprocessing_artifact_sha256": file_sha(parent / "artifacts/preprocessing.json"),
            "ordered_feature_surfaces": {"C": ["a", "b"]},
            "direction_arm_mapping": {"LONG": "C", "SHORT": "C"}}
    body.update(over)
    return DerivedCausalInputSpec.model_validate(body)


def _attested(parent: Path, att: Path, **over) -> dict:
    return {"parent_provenance_attestation_path": "artifacts/train_provenance_attestation.json",
            "parent_provenance_attestation_sha256": file_sha(att),
            "parent_provenance_cell_id": "LONG_C", **over}


# --------------------------------------------------------------------------- #
# 3. the repair itself
# --------------------------------------------------------------------------- #
def test_missing_provenance_with_no_attestation_is_rejected(tmp_path):
    """The load-bearing negative: absence of the marker never means TRAIN."""
    parent, freeze = _parent(tmp_path)
    with pytest.raises(ExternalModelScoringError, match="not TRAIN_ONLY"):
        FrozenExternalModelScorer.bind(_spec(parent, freeze), parent_dir=parent)


def test_a_valid_exact_bound_attestation_is_accepted(tmp_path):
    parent, freeze = _parent(tmp_path)
    att = _write_attestation(parent)
    scorer = FrozenExternalModelScorer.bind(_spec(parent, freeze, **_attested(parent, att)), parent_dir=parent)
    assert scorer.train_provenance["source"] == "additive_provenance_attestation"
    assert scorer.train_provenance["attestation"]["cell_id"] == "LONG_C"
    obs = scorer.score({"a": 1.0, "b": 0.0}, checkpoint_ts=10, direction="LONG", availability_ts={"a": 8, "b": 9})
    assert 0.0 <= obs.score <= 1.0


def test_a_freeze_that_declares_train_only_needs_no_attestation(tmp_path):
    parent, freeze = _parent(tmp_path, provenance="TRAIN_ONLY")
    scorer = FrozenExternalModelScorer.bind(_spec(parent, freeze), parent_dir=parent)
    assert scorer.train_provenance["source"] == "freeze_declares_train_only"


@pytest.mark.parametrize("mutate,match", [
    (lambda b: b.__setitem__("cells", [{**b["cells"][0], "original_freeze_path": "artifacts/other.json"}]),
     "FREEZE_MISMATCH"),
    (lambda b: b.__setitem__("cells", [{**b["cells"][0], "original_freeze_canonical_sha256": "0" * 64}]),
     "FREEZE_MISMATCH"),
    # a descriptive field is NOT a binding, and the artifact must not pretend otherwise
    (lambda b: b["cells"][0]["descriptive_only"].__setitem__("freeze_declared_freeze_sha256", "0" * 64), None),
    (lambda b: b["cells"][0].pop("original_freeze_canonical_sha256"), "MALFORMED"),
    (lambda b: b.__setitem__("cells", [{**b["cells"][0], "model_artifact_sha256": "0" * 64}]),
     "MODEL_ARTIFACT_MISMATCH"),
    (lambda b: b.__setitem__("cells", [{**b["cells"][0], "fit_identity_sha256": "other"}]),
     "MODEL_ARTIFACT_MISMATCH"),
    (lambda b: b.__setitem__("cells", [{**b["cells"][0], "preprocessing_hash": "other"}]),
     "PREPROCESSING_MISMATCH"),
    (lambda b: b["parent_authority"].__setitem__("execution_composite_sha256", "1" * 64),
     "EXECUTION_COMPOSITE_MISMATCH"),
    (lambda b: b["parent_authority"]["audits"]["causal"].__setitem__("verdict", "BLOCKED"),
     "AUDIT_EVIDENCE_MISSING"),
    (lambda b: b["parent_authority"]["audits"]["contract"].__setitem__(
        "audited_execution_composite_sha256", "2" * 64), "AUDIT_EVIDENCE_MISSING"),
    (lambda b: b.__setitem__("parent_study_id", "someone_else"), "STUDY_MISMATCH"),
    (lambda b: b.__setitem__("assertion", "ANYTHING"), "MALFORMED"),
    (lambda b: b.__setitem__("kind", "not_an_attestation"), "MALFORMED"),
])
def test_every_broken_binding_fails_closed(tmp_path, mutate, match):
    """`match=None` marks a field the attestation carries but does NOT bind: changing it must
    be harmless, which is the whole point of keeping it under `descriptive_only`."""
    parent, freeze = _parent(tmp_path)
    att = _write_attestation(parent)
    body = json.loads(att.read_text(encoding="utf-8"))
    mutate(body)
    att.write_text(json.dumps(body, indent=2, sort_keys=True) + chr(10), encoding="utf-8")
    spec = _spec(parent, freeze, **_attested(parent, att))
    if match is None:
        bound = FrozenExternalModelScorer.bind(spec, parent_dir=parent)
        assert bound.train_provenance["source"] == "additive_provenance_attestation"
        return
    with pytest.raises(ExternalModelScoringError, match=match):
        FrozenExternalModelScorer.bind(spec, parent_dir=parent)


def test_a_tampered_or_foreign_attestation_fails_closed(tmp_path):
    parent, freeze = _parent(tmp_path)
    att = _write_attestation(parent)
    good = _attested(parent, att)
    # bytes changed after the sha was declared
    with pytest.raises(ExternalModelScoringError, match="SHA_MISMATCH"):
        FrozenExternalModelScorer.bind(
            _spec(parent, freeze, **{**good, "parent_provenance_attestation_sha256": "0" * 64}), parent_dir=parent)
    # a cell that is not in the attestation
    with pytest.raises(ExternalModelScoringError, match="CELL_MISMATCH"):
        FrozenExternalModelScorer.bind(
            _spec(parent, freeze, **{**good, "parent_provenance_cell_id": "SHORT_C"}), parent_dir=parent)
    # an attestation outside the parent study
    outside = tmp_path / "elsewhere.json"
    outside.write_text(att.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ExternalModelScoringError, match="FOREIGN|MISSING"):
        FrozenExternalModelScorer.bind(
            _spec(parent, freeze, **{**good, "parent_provenance_attestation_path": "../elsewhere.json",
                                     "parent_provenance_attestation_sha256": file_sha(outside)}), parent_dir=parent)


def test_the_generator_refuses_a_freeze_that_is_not_train_only(tmp_path):
    """The attestation must be PROVEN from the freeze, never merely asserted."""
    parent, _ = _parent(tmp_path)
    freeze_path = parent / "artifacts/freeze.json"
    body = json.loads(freeze_path.read_text(encoding="utf-8"))
    body["thresholds"]["C"]["p90"]["derivation_population"] = "oos"
    freeze_path.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    r = subprocess.run([sys.executable, str(REPO_ROOT / "scripts/write_train_provenance_attestation.py"),
                        "--study", str(parent), "--cell", "LONG=artifacts/freeze.json:artifacts/models.joblib:C"],
                       cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert r.returncode != 0 and "THRESHOLDS_NOT_TRAIN_DERIVED" in r.stdout


def test_attestation_fields_are_refused_on_a_model_id_binding():
    """The attestation repairs a freeze binding; a model_id binding reads no freeze at all."""
    with pytest.raises(ValueError, match="BINDING_XOR"):
        DerivedCausalInputSpec.model_validate({
            "name": "s", "model_id": "a" * 64,
            "parent_provenance_attestation_path": "artifacts/x.json",
            "parent_provenance_attestation_sha256": "b" * 64,
            "parent_provenance_cell_id": "LONG_C"})


def test_attestation_fields_must_be_declared_together(tmp_path):
    parent, freeze = _parent(tmp_path)
    with pytest.raises(ValueError, match="ATTESTATION_INCOMPLETE"):
        _spec(parent, freeze, parent_provenance_attestation_path="artifacts/x.json")


# --------------------------------------------------------------------------- #
# 4. the real parent's historical artifacts are untouched
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not REAL_PARENT.is_dir(), reason="parent study not in this checkout")
def test_real_parent_freeze_bytes_are_unchanged_and_still_unstamped():
    """The repair is additive: the originals still say what they always said."""
    for rel, expected in (
        ("artifacts/train_experiment_freeze_long.json",
         "852af589d43f365b0ee24a7fcd82d5ccae75e690aa370ba42cca5cdb8852e95e"),
        ("artifacts/train_experiment_freeze_short.json",
         "55d430213fc4fe44e1bb1a1e0b1e39e05ba9f8e1a5ba38f0e2a7fc4dcb1e4b3f"),
    ):
        path = REAL_PARENT / rel
        if not path.is_file():
            pytest.skip(f"{rel} absent")
        body = json.loads(path.read_text(encoding="utf-8"))
        assert body.get("provenance") is None, "an original closed-study freeze was stamped in place"
        assert body.get("partition") == "train"
        # Content, not bytes: tracked JSON is EOL-converted on checkout, so only the canonical
        # content identity is a checkout-independent statement about the artifact.
        rel_posix = path.relative_to(REPO_ROOT).as_posix()
        blob = subprocess.run(["git", "show", f"HEAD:{rel_posix}"], cwd=str(REPO_ROOT), capture_output=True)
        if blob.returncode == 0:
            assert canonical_sha256(body) == canonical_sha256(json.loads(blob.stdout.decode("utf-8"))),                 f"{rel} content differs from the committed artifact"


@pytest.mark.skipif(not (REAL_PARENT / "artifacts/train_provenance_attestation.json").is_file(),
                    reason="attestation not present")
def test_real_attestation_is_reproducible_and_binds_the_real_artifacts():
    att = json.loads((REAL_PARENT / "artifacts/train_provenance_attestation.json").read_text(encoding="utf-8"))
    assert att["assertion"] == "TRAIN_ONLY" and att["parent_study_id"] == PARENT_ID
    assert att["declarations"] == {"NO_RETRAIN": True, "NO_MODEL_BYTE_CHANGE": True,
                                   "NO_SCORE_CHANGE": True, "NO_SCIENTIFIC_AUTHORITY_CHANGE": True}
    assert canonical_sha256({k: v for k, v in att.items()
                             if k not in ("attestation_sha256", "created_at_utc")}) == att["attestation_sha256"]
    for cell in att["cells"]:
        freeze = REAL_PARENT / cell["original_freeze_path"]
        assert canonical_sha256(json.loads(freeze.read_text(encoding="utf-8"))) == cell["original_freeze_canonical_sha256"]
        # unverified context must be quarantined where a reader cannot mistake it for a binding
        assert "descriptive_only" in cell
        assert "freeze_authorization_sha256" not in cell
        model = REAL_PARENT / cell["model_artifact_path"]
        if model.is_file():                              # .joblib is machine-local (gitignored)
            assert file_sha(model) == cell["model_artifact_sha256"]


# --------------------------------------------------------------------------- #
# 5. null-input policy: reproducing a frozen model means reproducing how it was USED
# --------------------------------------------------------------------------- #
def _lgbm_parent(tmp_path):
    """A parent whose estimator handles missing values natively, as LightGBM does."""
    import lightgbm as lgb
    import numpy as np
    parent = tmp_path / "studies" / "parent"
    (parent / "artifacts").mkdir(parents=True)
    (parent / "audit").mkdir(parents=True)
    rng = np.random.default_rng(3)
    X = pd.DataFrame(rng.random((200, 2)), columns=["a", "b"])
    y = (X["a"] + X["b"] > 1.0).astype(int)
    est = lgb.LGBMClassifier(n_estimators=8, num_leaves=3, verbosity=-1).fit(X, y)
    joblib.dump({"C": {"estimator": est, "fit_identity_sha256": "fit-c"}}, parent / "artifacts/models.joblib")
    (parent / "artifacts/preprocessing.json").write_text('{"identity":"prep"}', encoding="utf-8")
    freeze = {"study_id": "parent", "partition": "train", "provenance": "TRAIN_ONLY",
              "model_hashes": {"C": "fit-c"}, "feature_sets": {"C": ["a", "b"]},
              "preprocessing_hash": "prep-identity",
              "thresholds": {"C": {"p90": {"threshold": 0.5, "derivation_population": "train"}}},
              "deciles": {"C": {"derivation": "TRAIN_ONLY"}}}
    (parent / "artifacts/freeze.json").write_text(json.dumps(freeze, sort_keys=True), encoding="utf-8")
    return parent, est


def _lgbm_spec(parent, **over):
    body = {"name": "s", "parent_study_id": "parent",
            "parent_train_freeze_artifact": "artifacts/freeze.json",
            "parent_train_freeze_artifact_sha256": file_sha(parent / "artifacts/freeze.json"),
            "parent_frozen_execution_composite_sha256": COMPOSITE,
            "model_hashes": {"C": "fit-c"}, "preprocessing_hash": "prep-identity",
            "model_artifact_path": "artifacts/models.joblib",
            "model_artifact_sha256": file_sha(parent / "artifacts/models.joblib"),
            "preprocessing_artifact_path": "artifacts/preprocessing.json",
            "preprocessing_artifact_sha256": file_sha(parent / "artifacts/preprocessing.json"),
            "ordered_feature_surfaces": {"C": ["a", "b"]},
            "direction_arm_mapping": {"LONG": "C", "SHORT": "C"}}
    body.update(over)
    return DerivedCausalInputSpec.model_validate(body)


def test_the_default_null_policy_still_refuses_to_score_a_null_input(tmp_path):
    """The safe default must not move: a null input yields no score unless a study says otherwise."""
    parent, _ = _lgbm_parent(tmp_path)
    spec = _lgbm_spec(parent)
    assert spec.null_input_policy == "refuse"
    scorer = FrozenExternalModelScorer.bind(spec, parent_dir=parent)
    with pytest.raises(ExternalModelScoringError, match="null values"):
        scorer.score({"a": 1.0, "b": float("nan")}, checkpoint_ts=10, direction="LONG",
                     availability_ts={"a": 9, "b": 9})


def test_model_native_reproduces_the_estimator_on_missing_inputs_exactly(tmp_path):
    """The reason the policy exists: the frozen 180s models were USED with null rolling features
    (73% of the parent's own candidates), so refusing them would drop most of the population a
    child study is trying to reproduce. Passing the null through must equal the estimator."""
    import numpy as np
    parent, est = _lgbm_parent(tmp_path)
    scorer = FrozenExternalModelScorer.bind(_lgbm_spec(parent, null_input_policy="model_native"),
                                            parent_dir=parent)
    snap = {"a": 0.4, "b": float("nan")}
    obs = scorer.score(snap, checkpoint_ts=10, direction="LONG", availability_ts={"a": 9, "b": 9})
    expected = float(est.predict_proba(pd.DataFrame([[0.4, np.nan]], columns=["a", "b"]))[0][1])
    assert obs.score == expected
    assert obs.null_inputs == 1 and obs.null_input_policy == "model_native"


def test_a_score_over_missing_inputs_is_never_anonymous(tmp_path):
    """Provenance: how many inputs were missing, and under which policy, travels with the score."""
    parent, _ = _lgbm_parent(tmp_path)
    scorer = FrozenExternalModelScorer.bind(_lgbm_spec(parent, null_input_policy="model_native"),
                                            parent_dir=parent)
    clean = scorer.score({"a": 0.4, "b": 0.6}, checkpoint_ts=10, direction="LONG",
                         availability_ts={"a": 9, "b": 9})
    assert clean.null_inputs == 0 and clean.null_input_policy == "model_native"


def test_model_native_on_a_family_without_missing_support_fails_closed(tmp_path):
    """It can never silently coerce a null to zero: an estimator that cannot take NaN raises."""
    parent, _ = _parent(tmp_path, provenance="TRAIN_ONLY")      # sklearn LogisticRegression
    scorer = FrozenExternalModelScorer.bind(_spec(parent, {}, null_input_policy="model_native"),
                                            parent_dir=parent)
    with pytest.raises(Exception):
        scorer.score({"a": 1.0, "b": float("nan")}, checkpoint_ts=10, direction="LONG",
                     availability_ts={"a": 9, "b": 9})


def test_a_row_with_nothing_observed_never_produces_a_score(tmp_path):
    """Binding-level guard (causal pass 04, NOTE 2). `model_native` means "missingness is
    information the model can use", not "score anything". A checkpoint where EVERY input is null
    has nothing observed at all, and must yield no score under either policy."""
    from features.trackers.host_bindings import FrozenExternalScoreBinding

    class Epoch:
        T = 10

    parent, _ = _lgbm_parent(tmp_path)
    spec = _lgbm_spec(parent, null_input_policy="model_native")
    binding = FrozenExternalScoreBinding(
        {"spec": spec.model_dump(), "direction": "r.dir", "studies_root": str(tmp_path / "studies")}, {})
    resolve = lambda ref, e: 1

    assert binding.derive({"a": None, "b": None}, Epoch(), resolve) is None
    assert binding.derive({"a": float("nan"), "b": float("nan")}, Epoch(), resolve) is None
    partial = binding.derive({"a": 0.4, "b": None}, Epoch(), resolve)
    assert partial is not None and 0.0 <= partial <= 1.0      # one observed input IS information

    refusing = FrozenExternalScoreBinding(
        {"spec": _lgbm_spec(parent).model_dump(), "direction": "r.dir",
         "studies_root": str(tmp_path / "studies")}, {})
    assert refusing.derive({"a": 0.4, "b": None}, Epoch(), resolve) is None   # default unchanged
