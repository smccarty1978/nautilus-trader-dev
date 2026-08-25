"""Generic-infrastructure regressions for two defects found on 2026-08-25.

Defect 1 -- `research_workflow/contract_audit.py` hardcoded `len(instances) == 13`.
That is the feature count of exactly one study
(`clean_maturity_flip_model_rolling_productivity`). Generic infrastructure asserting a
study-specific constant passes for that study and silently fails every other one, so the
audit was worthless as a gate the moment a second study used it. The expected surface is
now derived from the study's own contracts.

Defect 2 -- `scripts/tests/test_round2_invariants.py` hashed `validate_smoke.py` with a raw
`hashlib.sha256(read_bytes())` while the gate it tests uses `canonical_file_sha256`, which
normalises line endings (W7). On a CRLF checkout the two disagree permanently, so four
smoke-acceptance tests failed on Windows for a reason unrelated to what they assert.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research_workflow.contract_audit import _expected_feature_surface  # noqa: E402
from scripts.resolve_execution_manifest import canonical_file_sha256  # noqa: E402

REAL_STUDY = REPO_ROOT / "studies" / "clean_maturity_flip_model_rolling_productivity"


def _features_of(study: Path) -> dict:
    compiled = json.loads((study / "compiled_study.json").read_text(encoding="utf-8"))
    return compiled["spec"]["features"]


def _write_study(tmp_path: Path, instances: list[dict], *, declared_count=None,
                 authorized: list[str] | None = None) -> Path:
    """Build a minimal study whose contracts are self-describing."""
    study = tmp_path / "synthetic_study"
    (study / "artifacts").mkdir(parents=True, exist_ok=True)
    features = {
        "source": "canonical_verified_definition_universe",
        "instances": instances,
        "selection": {"mode": "none", "feature_count": declared_count},
    }
    (study / "compiled_study.json").write_text(
        json.dumps({"study_id": study.name, "spec": {"features": features}}), encoding="utf-8"
    )
    if authorized is not None:
        (study / "artifacts" / "phase0_source_manifest.json").write_text(
            json.dumps({"candidate_feature_universe": {"candidates": {a: {} for a in authorized}}}),
            encoding="utf-8",
        )
    return study


# --- A. the real 13-instance study still passes -----------------------------------

def test_real_thirteen_instance_study_passes():
    result = _expected_feature_surface(REAL_STUDY, _features_of(REAL_STUDY))
    assert result["count_matches"], result["count_detail"]
    assert result["surface_matches"], result["surface_detail"]
    assert "13" in result["count_detail"]


# --- B. a study with a different valid count also passes --------------------------

# Valid canonical instances, verified to resolve against the active bundle.
VALID_INSTANCES = [
    {"feature": "regime_efficiency", "parameters": {"timeframe": "1m", "context": "prior", "bar_state": "completed"}},
    {"feature": "regime_mfe_atr", "parameters": {"timeframe": "1m", "context": "prior", "bar_state": "completed"}},
    {"feature": "regime_range_atr", "parameters": {"timeframe": "5m", "context": "prior", "bar_state": "completed"}},
    {"feature": "regime_efficiency", "parameters": {"timeframe": "5m", "context": "prior", "bar_state": "completed"}},
    {"feature": "rolling_giveback_atr", "parameters": {"window": "300s", "update_every": "1s"}},
    {"feature": "rolling_max_progress_atr", "parameters": {"window": "300s", "update_every": "1s"}},
]


@pytest.mark.parametrize("n", [1, 3, 6])
def test_other_feature_counts_pass(tmp_path, n):
    """The count is whatever the study declares. 13 is not special."""
    instances = [dict(i) for i in VALID_INSTANCES[:n]]
    study = _write_study(tmp_path, instances, declared_count=n)
    result = _expected_feature_surface(study, _features_of(study))
    assert result["count_matches"], result["count_detail"]
    assert result["surface_matches"], result["surface_detail"]


# --- C. a genuine mismatch still fails --------------------------------------------

def test_declared_count_mismatch_fails(tmp_path):
    """Contract says 5 features, study declares 2. That is a finding."""
    study = _write_study(tmp_path, [dict(i) for i in VALID_INSTANCES[:2]], declared_count=5)
    result = _expected_feature_surface(study, _features_of(study))
    assert not result["count_matches"]
    assert "feature_count=5" in result["count_detail"] and "instances=2" in result["count_detail"]


def test_authorized_surface_mismatch_fails(tmp_path):
    """Phase zero authorized a surface the declared instances do not produce."""
    instances = [{"feature": "regime_efficiency",
                  "parameters": {"timeframe": "1m", "context": "prior", "bar_state": "completed"}}]
    study = _write_study(tmp_path, instances, declared_count=1,
                         authorized=["prior_1m_regime_efficiency", "some_extra_feature"])
    result = _expected_feature_surface(study, _features_of(study))
    assert not result["surface_matches"]
    assert "some_extra_feature" in result["surface_detail"]


def test_unresolvable_instance_fails(tmp_path):
    """An instance that cannot resolve is a finding, not an exception."""
    study = _write_study(tmp_path, [{"feature": "not_a_real_canonical_feature", "parameters": {}}],
                         declared_count=1)
    result = _expected_feature_surface(study, _features_of(study))
    assert not result["surface_matches"]
    assert "do not resolve" in result["surface_detail"]


def test_duplicate_instances_collapse_is_detected(tmp_path):
    """Two identical instances resolve to one alias; the surface is smaller than declared."""
    inst = {"feature": "regime_efficiency",
            "parameters": {"timeframe": "1m", "context": "prior", "bar_state": "completed"}}
    study = _write_study(tmp_path, [dict(inst), dict(inst)], declared_count=2)
    result = _expected_feature_surface(study, _features_of(study))
    assert not result["surface_matches"]
    assert "collapsed" in result["surface_detail"]


# --- D. no study-specific constant survives in generic infrastructure -------------

# `research_workflow/` is the generic research lifecycle; a study-specific constant here
# is the defect class this file exists for. `features/candidate_authority.py` is excluded
# deliberately: its `len(aliases) != 693` / `len(definitions) != 129` are bundle-integrity
# assertions guarding an atomic authority cutover, i.e. the exact reviewed bytes -- not a
# study assumption. `utils/visualizer*.py` compare string-split lengths.
GENERIC_ROOT = "research_workflow"

# Known offenders of the same class, found 2026-08-25 and tracked separately. Listing them
# keeps the invariant honest: the test still fails if a NEW one appears. Do not add to this
# list to make a failure go away -- fix the code.
KNOWN_STUDY_SPECIFIC_OFFENDERS = {
    # `self._is_targeted_60 = bool(config.feature_list and len(config.feature_list) == 60)`
    # A 60-feature surface flag baked into the generic collector. Same defect as `== 13`.
    "research_workflow/generic_collector.py:232",
}


def _generic_modules() -> list[Path]:
    base = REPO_ROOT / GENERIC_ROOT
    return [p for p in base.rglob("*.py")
            if "__pycache__" not in p.parts and "tests" not in p.parts]


def test_no_hardcoded_feature_count_in_generic_workflow():
    """A literal length comparison in the generic lifecycle is a study-specific assumption."""
    offenders = []
    for path in _generic_modules():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            if (isinstance(node.left, ast.Call) and isinstance(node.left.func, ast.Name)
                    and node.left.func.id == "len"
                    and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops)
                    and any(isinstance(c, ast.Constant) and isinstance(c.value, int) and c.value > 1
                            for c in node.comparators)):
                offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{node.lineno}")
    new = sorted(set(offenders) - KNOWN_STUDY_SPECIFIC_OFFENDERS)
    assert not new, (
        "generic research_workflow code compares a length against a magic number; derive it "
        f"from the study contract instead: {new}"
    )


def test_the_thirteen_feature_assumption_is_gone():
    """The specific defect: contract_audit.py hardcoded this study's feature count."""
    src = (REPO_ROOT / "research_workflow" / "contract_audit.py").read_text(encoding="utf-8")
    assert "== 13" not in src and "!= 13" not in src


def test_no_study_id_hardcoded_in_generic_workflow():
    """The generic lifecycle must not name a specific study."""
    offenders = []
    for path in _generic_modules():
        text = path.read_text(encoding="utf-8")
        for study_id in ("clean_maturity_flip_model_rolling_productivity",
                         "Codex_clean_maturity_flip_rolling_5m_productivity"):
            if study_id in text:
                offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()} -> {study_id}")
    assert not offenders, f"generic research_workflow code references a specific study: {offenders}"


# --- E. canonical hashing is platform-independent ---------------------------------

def test_canonical_hash_is_line_ending_independent(tmp_path):
    """LF and CRLF representations of the same source hash identically.

    This is the contract the smoke-acceptance gate depends on: a fixture written on a CRLF
    checkout must not look stale to a gate that normalises.
    """
    lf = tmp_path / "lf.py"
    crlf = tmp_path / "crlf.py"
    body = "def f():\n    return 1\n"
    lf.write_bytes(body.encode())
    crlf.write_bytes(body.replace("\n", "\r\n").encode())

    assert lf.read_bytes() != crlf.read_bytes(), "fixture must actually differ in bytes"
    assert canonical_file_sha256(lf) == canonical_file_sha256(crlf)


def test_canonical_hash_still_detects_real_content_change(tmp_path):
    """Normalisation must not weaken the invariant."""
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_bytes(b"def f():\r\n    return 1\r\n")
    b.write_bytes(b"def f():\r\n    return 2\r\n")
    assert canonical_file_sha256(a) != canonical_file_sha256(b)


def test_binary_files_are_not_normalised(tmp_path):
    """Only text extensions normalise; for binary a byte difference IS a content difference."""
    a = tmp_path / "a.parquet"
    b = tmp_path / "b.parquet"
    a.write_bytes(b"\x00\x01\n\x02")
    b.write_bytes(b"\x00\x01\r\n\x02")
    assert canonical_file_sha256(a) != canonical_file_sha256(b)


def test_round2_invariants_uses_canonical_hash_only():
    """The regression itself: no ad-hoc file hashing may return to that suite."""
    src = (REPO_ROOT / "scripts" / "tests" / "test_round2_invariants.py").read_text(encoding="utf-8")
    assert "canonical_file_sha256" in src
    assert "hashlib.sha256" not in src, "ad-hoc file hashing reintroduced; use canonical_file_sha256"
