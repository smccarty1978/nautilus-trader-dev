"""Regression tests for the four Red Team blockers plus the trust-chain warnings.

RT-1  a `--skip-tests` preflight reported CLEAR / READY_FOR_AUDIT while a mandatory
      check never ran. A check that does not execute cannot fail, so skipping one made
      the preflight *more* likely to advertise readiness.
RT-2  `from . import X` and the other relative forms never entered the execution
      closure, so a module could execute while changes to it left the composite -- and
      any seal -- untouched.
RT-3  deleting `audit/pass_ledger.json` (or the whole audit directory) reset a study's
      audit history and made pass 01 available again.
RT-4  the grandfather guard compared `baseline - registry`, which is empty precisely in
      the attack case: adding a new feature to BOTH the registry and the baseline.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

from scripts.research_preflight import (  # noqa: E402
    PreflightEvidenceError,
    REQUIRED_STUDY_CHECKS,
    assert_preflight_audit_ready,
)
from scripts.resolve_execution_manifest import (  # noqa: E402
    canonical_file_sha256,
    compute_ast_closure,
    resolve_execution_manifest,
)


# ===========================================================================
# RT-1 -- preflight completeness
# ===========================================================================

ES_STUDY = REPO_ROOT / "studies" / "es_wick_imbalance_acceptance_v2"


def _bound_study(tmp_path: Path, **overrides) -> Path:
    """A scratch study whose preflight evidence is genuinely BOUND to its own state.

    RT1-B1 made unbound evidence inadmissible, so these tests can no longer hand the
    consumer a bare `{...}` dict: that is now refused for the wrong reason
    (PREFLIGHT_EVIDENCE_OBSOLETE) and would stop exercising the completeness contract
    RT-1 is about. Each test therefore starts from valid, self-consistent evidence and
    changes exactly the one field under test -- recomputing the self-binding hash so
    the artifact stays internally consistent and the *completeness* check is what fires.
    """
    from scripts.research_preflight import compute_evidence_sha256
    from scripts.tests._preflight_fixture import plant_audit_ready_preflight

    s = tmp_path / "study"
    if not s.exists():
        shutil.copytree(ES_STUDY, s)
    p = plant_audit_ready_preflight(s)
    if overrides:
        data = json.loads(p.read_text(encoding="utf-8"))
        data.update(overrides)
        data["evidence_sha256"] = compute_evidence_sha256(data)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return s


def _write_preflight(study: Path, **fields) -> Path:
    (study / "audit").mkdir(parents=True, exist_ok=True)
    p = study / "audit" / "preflight.json"
    p.write_text(json.dumps(fields), encoding="utf-8")
    return p


def test_rt1_complete_and_passing_preflight_is_audit_ready(tmp_path):
    """1 -- all required checks pass -> READY_FOR_AUDIT."""
    s = _bound_study(tmp_path)
    assert assert_preflight_audit_ready(s, REPO_ROOT)["audit_ready"] is True


def test_rt2_skipped_mandatory_check_is_not_audit_ready(tmp_path):
    """2 -- mandatory check skipped -> NOT_READY, even with no failing gate."""
    s = _bound_study(
        tmp_path,
        status="INCOMPLETE", audit_ready=False,
        required_next_action="RUN_FULL_PREFLIGHT_BEFORE_AUDIT",
        required_checks_missing=["CAUSAL_INVARIANTS"], failed_gate=None,
        check_outcomes={c: "PASSED" for c in REQUIRED_STUDY_CHECKS
                        if c != "CAUSAL_INVARIANTS"} | {"CAUSAL_INVARIANTS": "SKIPPED"},
    )
    with pytest.raises(PreflightEvidenceError, match="PREFLIGHT_REQUIRED_CHECKS_INCOMPLETE"):
        assert_preflight_audit_ready(s, REPO_ROOT)


def test_rt1_timeout_is_not_audit_ready(tmp_path):
    """3 -- a timed-out mandatory check is incomplete, not passed."""
    s = _bound_study(
        tmp_path,
        status="BLOCKED", audit_ready=False, required_next_action="FIX_BEFORE_AUDIT",
        required_checks_missing=["CAUSAL_INVARIANTS"],
        check_outcomes={c: "PASSED" for c in REQUIRED_STUDY_CHECKS
                        if c != "CAUSAL_INVARIANTS"} | {"CAUSAL_INVARIANTS": "TIMEOUT"},
    )
    with pytest.raises(PreflightEvidenceError, match="PREFLIGHT_REQUIRED_CHECKS_INCOMPLETE"):
        assert_preflight_audit_ready(s, REPO_ROOT)


def test_rt1_obsolete_artifact_without_audit_ready_is_refused(tmp_path):
    """4 -- an artifact predating the contract cannot assert its own completeness."""
    s = tmp_path / "study"
    _write_preflight(s, status="CLEAR", required_next_action="READY_FOR_AUDIT")
    with pytest.raises(PreflightEvidenceError, match="PREFLIGHT_EVIDENCE_OBSOLETE"):
        assert_preflight_audit_ready(s, REPO_ROOT)


def test_rt1_missing_preflight_is_refused(tmp_path):
    s = tmp_path / "study"
    (s / "audit").mkdir(parents=True)
    with pytest.raises(PreflightEvidenceError, match="PREFLIGHT_EVIDENCE_MISSING"):
        assert_preflight_audit_ready(s, REPO_ROOT)


def test_rt1_corrupt_preflight_fails_closed(tmp_path):
    s = tmp_path / "study"
    (s / "audit").mkdir(parents=True)
    (s / "audit" / "preflight.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(PreflightEvidenceError, match="PREFLIGHT_EVIDENCE_MALFORMED"):
        assert_preflight_audit_ready(s, REPO_ROOT)


def test_rt1_diagnostic_run_cannot_masquerade_as_full_clear():
    """5 -- the real CLI: --skip-tests must not produce an audit-ready artifact."""
    study = REPO_ROOT / "studies" / "es_wick_imbalance_acceptance_v2"
    if not (study / "study.yaml").exists():
        pytest.skip("acceptance study absent")
    res = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "research_preflight.py"),
         "--study", str(study), "--skip-tests"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    data = json.loads((study / "audit" / "preflight.json").read_text(encoding="utf-8"))
    assert data["audit_ready"] is False
    assert data["status"] == "INCOMPLETE"
    assert data["required_next_action"] == "RUN_FULL_PREFLIGHT_BEFORE_AUDIT"
    assert "CAUSAL_INVARIANTS" in data["required_checks_missing"]
    assert data["check_outcomes"]["CAUSAL_INVARIANTS"] == "SKIPPED"
    assert res.returncode != 0, "a diagnostic preflight must not exit 0"


def test_rt1_audit_issuance_refuses_incomplete_preflight(tmp_path):
    """Downstream half: the issuer consults the preflight artifact."""
    import scripts.run_preexec_audits as rpa

    s = tmp_path / "study"
    _write_preflight(s, status="INCOMPLETE", audit_ready=False,
                     required_checks_missing=["CAUSAL_INVARIANTS"])
    src = Path(rpa.__file__).read_text(encoding="utf-8")
    assert "assert_preflight_audit_ready" in src
    with pytest.raises(PreflightEvidenceError):
        assert_preflight_audit_ready(s)


def test_rt1_seal_refuses_incomplete_preflight():
    import scripts.preexec_audit_seal as seal_mod

    src = Path(seal_mod.__file__).read_text(encoding="utf-8")
    assert "assert_preflight_audit_ready" in src, "seal must consult preflight evidence"


# ===========================================================================
# RT-2 -- relative imports in the execution closure
# ===========================================================================

def _mk(p: Path, body: bytes = b"") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)


@pytest.fixture()
def rel_repo(tmp_path: Path) -> Path:
    """Every relative-import form, each reaching a module nothing else imports."""
    root = (tmp_path / "repo").resolve()
    _mk(root / "features" / "__init__.py",
        b"from . import shadow_exec\nfrom .direct import D\nfrom .sub import deep\n")
    _mk(root / "features" / "shadow_exec.py", b"X = 1\n")
    _mk(root / "features" / "direct.py", b"D = 1\n")
    _mk(root / "features" / "sibling.py", b"S = 1\n")
    _mk(root / "features" / "sub" / "__init__.py",
        b"from .. import sibling\nfrom ..other import thing\nfrom ..other.nested import N\n")
    _mk(root / "features" / "sub" / "deep.py", b"Y = 1\n")
    _mk(root / "features" / "other" / "__init__.py", b"")
    _mk(root / "features" / "other" / "thing.py", b"T = 1\n")
    _mk(root / "features" / "other" / "nested.py", b"N = 1\n")
    _mk(root / "features" / "leaf.py", b"L = 1\n")
    _mk(root / "entry.py", b"from features.leaf import L\nimport features.direct\n")
    return root


def _closure(root: Path, seed: str = "entry.py"):
    visited, unresolved = compute_ast_closure([root / seed], root)
    return {p.resolve().relative_to(root).as_posix() for p in visited}, unresolved


@pytest.mark.parametrize("expected", [
    "features/shadow_exec.py",     # from . import X
    "features/direct.py",          # from .x import y
    "features/sub/deep.py",        # from .pkg import mod
    "features/sibling.py",         # from .. import y
    "features/other/thing.py",     # from ..pkg import y
    "features/other/nested.py",    # from ..pkg.mod import y
    "features/other/__init__.py",  # package init of a relatively-imported package
])
def test_rt2_relative_import_forms_enter_the_closure(rel_repo, expected):
    rel, _ = _closure(rel_repo)
    assert expected in rel, f"{expected} executes but is absent from the closure"


def test_rt2_absolute_forms_still_resolve(rel_repo):
    rel, _ = _closure(rel_repo)
    assert "features/leaf.py" in rel          # from x import y
    assert "features/__init__.py" in rel      # import x.y package init


def test_rt2_shadow_module_change_moves_the_composite(rel_repo):
    """An imported local module must be hash-bound, or edits are invisible."""
    import hashlib

    def composite():
        visited, _ = compute_ast_closure([rel_repo / "entry.py"], rel_repo)
        return hashlib.sha256(
            json.dumps(
                {p.resolve().relative_to(rel_repo).as_posix(): canonical_file_sha256(p)
                 for p in sorted(visited)},
                sort_keys=True,
            ).encode()
        ).hexdigest()

    before = composite()
    (rel_repo / "features" / "shadow_exec.py").write_bytes(b"X = 2  # mutated\n")
    assert composite() != before, "editing a relatively-imported module left the composite unchanged"


def test_rt2_unresolved_relative_base_is_reported(tmp_path):
    """Coverage must fall rather than report 100% when a relative BASE is unresolvable.

    The base is the right granularity. `from . import name` where the package resolves is
    legitimate even if `name` is not a submodule -- it may be an attribute defined in
    `__init__.py`, whose defining code is already in the closure. And if it is neither,
    Python raises ImportError, so nothing executes unsealed. An unresolvable *base*,
    by contrast, means the traversal genuinely could not follow the graph.
    """
    root = (tmp_path / "repo").resolve()
    _mk(root / "features" / "__init__.py", b"from .missing_pkg import thing\n")
    _mk(root / "features" / "leaf.py", b"L = 1\n")
    _mk(root / "entry.py", b"from features.leaf import L\n")
    _rel, unresolved = _closure(root)
    assert unresolved, "an unresolvable relative base must be recorded"
    assert any("missing_pkg" in u["import_target"] for u in unresolved)


def test_rt2_attribute_import_from_a_resolved_package_is_not_unresolved(tmp_path):
    """No false positive: `from . import CONSTANT` defined in __init__ is fine."""
    root = (tmp_path / "repo").resolve()
    _mk(root / "features" / "__init__.py", b"CONSTANT = 1\nfrom . import CONSTANT\n")
    _mk(root / "features" / "leaf.py", b"L = 1\n")
    _mk(root / "entry.py", b"from features.leaf import L\n")
    _rel, unresolved = _closure(root)
    assert unresolved == []


def test_rt2_unresolved_dependency_lowers_reported_coverage(tmp_path):
    """The manifest must not report 100% while a dependency is unresolved."""
    from scripts.resolve_execution_manifest import _coverage_pct

    assert _coverage_pct(10, 0) == 100.0
    assert _coverage_pct(10, 1) < 100.0


def test_rt2_closure_does_not_over_broaden(rel_repo):
    _mk(rel_repo / "features" / "never_imported.py", b"Z = 1\n")
    _mk(rel_repo / "unrelated.py", b"U = 1\n")
    rel, _ = _closure(rel_repo)
    assert "features/never_imported.py" not in rel
    assert "unrelated.py" not in rel


def test_rt2_real_study_closure_still_resolves():
    study = REPO_ROOT / "studies" / "es_wick_imbalance_acceptance_v2"
    if not (study / "study.yaml").exists():
        pytest.skip("acceptance study absent")
    _sha, _fh, md = resolve_execution_manifest(study, REPO_ROOT)
    assert md["coverage_pct"] == 100.0
    assert md["unresolved_dependencies"] == []


# ===========================================================================
# RT-3 -- durable audit lineage
# ===========================================================================

@pytest.fixture()
def lineage_env(tmp_path: Path):
    """A study plus an isolated repo root so the anchor lands in a temp dir."""
    import scripts.run_preexec_audits as rpa

    repo = tmp_path / "repo"
    study = repo / "studies" / "s1"
    (study / "audit").mkdir(parents=True)
    return rpa, study, repo


def _record(rpa, study, repo, audit_type, n, composite, sha):
    rpa.append_pass_ledger_entry(
        study, audit_type, n, composite, sha, "alice",
        {"provenance_strength": "DECLARED_IDENTITY_ONLY"}, repo,
    )


def test_rt3_same_pass_different_composite_is_refused(lineage_env):
    """1 -- same pass + different composite -> refuse."""
    rpa, study, repo = lineage_env
    _record(rpa, study, repo, "causal", 1, "A" * 64, "R1" * 32)
    with pytest.raises(rpa.AuditArtifactParseError, match="AUDIT_PASS_IMMUTABLE"):
        rpa.enforce_pass_immutability(study, "causal", 1, "B" * 64, "R2" * 32, repo)


def test_rt3_reused_lower_pass_is_refused(lineage_env):
    """2 -- lower/reused pass -> refuse."""
    rpa, study, repo = lineage_env
    _record(rpa, study, repo, "causal", 1, "A" * 64, "R1" * 32)
    _record(rpa, study, repo, "causal", 3, "B" * 64, "R2" * 32)
    with pytest.raises(rpa.AuditArtifactParseError, match="AUDIT_PASS_NUMBER_STALE"):
        rpa.enforce_pass_immutability(study, "causal", 2, "C" * 64, "R3" * 32, repo)


def test_rt3_identical_retry_is_idempotent(lineage_env):
    """3 -- byte-identical retry -> idempotent."""
    rpa, study, repo = lineage_env
    _record(rpa, study, repo, "causal", 1, "A" * 64, "R1" * 32)
    rpa.enforce_pass_immutability(study, "causal", 1, "A" * 64, "R1" * 32, repo)


def test_rt3_deleting_the_local_ledger_is_detected(lineage_env):
    """4 -- delete pass_ledger -> reset detected, history not erased."""
    rpa, study, repo = lineage_env
    _record(rpa, study, repo, "causal", 1, "A" * 64, "R1" * 32)
    (study / "audit" / rpa.PASS_LEDGER_NAME).unlink()

    with pytest.raises(rpa.AuditArtifactParseError, match="AUDIT_LINEAGE_RESET_DETECTED"):
        rpa.enforce_pass_immutability(study, "causal", 1, "Z" * 64, "R9" * 32, repo)


def test_rt3_deleting_the_whole_audit_directory_is_detected(lineage_env):
    """5 -- delete audit directory -> reset detected."""
    import shutil

    rpa, study, repo = lineage_env
    _record(rpa, study, repo, "causal", 1, "A" * 64, "R1" * 32)
    shutil.rmtree(study / "audit")
    (study / "audit").mkdir(parents=True)

    with pytest.raises(rpa.AuditArtifactParseError, match="AUDIT_LINEAGE_RESET_DETECTED"):
        rpa.enforce_pass_immutability(study, "causal", 1, "Z" * 64, "R9" * 32, repo)


def test_rt3_anchor_survives_audit_directory_deletion(lineage_env):
    """The anchor lives outside the study, so `rm -rf audit/` cannot reach it."""
    import shutil

    rpa, study, repo = lineage_env
    _record(rpa, study, repo, "causal", 2, "A" * 64, "R1" * 32)
    shutil.rmtree(study / "audit")

    anchor = rpa.read_lineage_anchor(study, repo)
    assert anchor is not None
    assert anchor["high_water"]["causal"] == 2


def test_rt3_copied_study_directory_is_explicit(lineage_env, tmp_path):
    """6 -- a copied study dir claims passes the anchor never recorded."""
    import shutil

    rpa, study, repo = lineage_env
    _record(rpa, study, repo, "causal", 1, "A" * 64, "R1" * 32)

    copy = repo / "studies" / "s1_copy"
    shutil.copytree(study, copy)

    # RT3-B1: this used to bootstrap SILENTLY from the copied ledger. Silent bootstrap is
    # indistinguishable from `rm audit_lineage/<id>.json`, which is exactly how the anchor
    # was reset. The copy now fails closed and the operator must state the intent --
    # `--adopt-ledger` (this identity owns that history) or `--fresh-identity` (it does
    # not). Guessing either way is a real failure: one launders history, the other loses it.
    with pytest.raises(rpa.AuditArtifactParseError, match="AUDIT_LINEAGE_ANCHOR_MISSING"):
        rpa.resolve_effective_lineage(copy, repo)

    rpa._write_lineage_anchor(copy, rpa._read_pass_ledger(copy), repo, bootstrapped=True)
    entries = rpa.resolve_effective_lineage(copy, repo)
    assert [(e["audit_type"], e["pass"]) for e in entries] == [("causal", 1)]
    anchor = rpa.read_lineage_anchor(copy, repo)
    assert anchor["study_id"] == "s1_copy"
    assert anchor["bootstrapped_from_local_ledger"] is True


def test_rt3_local_ledger_claiming_unanchored_passes_is_refused(lineage_env):
    """A hand-edited ledger cannot manufacture history the issuer never wrote."""
    rpa, study, repo = lineage_env
    _record(rpa, study, repo, "causal", 1, "A" * 64, "R1" * 32)

    ledger_p = study / "audit" / rpa.PASS_LEDGER_NAME
    data = json.loads(ledger_p.read_text(encoding="utf-8"))
    data["entries"].append({
        "audit_type": "causal", "pass": 9,
        "audited_execution_composite_sha256": "F" * 64,
        "audit_report_sha256": "F" * 64, "auditor": "mallory",
    })
    ledger_p.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(rpa.AuditArtifactParseError, match="AUDIT_LINEAGE_UNANCHORED"):
        rpa.resolve_effective_lineage(study, repo)


def test_rt3_corrupt_ledger_fails_closed(lineage_env):
    """7 -- corrupt ledger -> fail closed."""
    rpa, study, repo = lineage_env
    (study / "audit" / rpa.PASS_LEDGER_NAME).write_text("{broken", encoding="utf-8")
    with pytest.raises(rpa.AuditArtifactParseError, match="PASS_LEDGER_UNREADABLE"):
        rpa.enforce_pass_immutability(study, "causal", 1, "A" * 64, "R" * 64, repo)


def test_rt3_corrupt_anchor_fails_closed(lineage_env):
    rpa, study, repo = lineage_env
    _record(rpa, study, repo, "causal", 1, "A" * 64, "R1" * 32)
    rpa._lineage_path(study, repo).write_text("{broken", encoding="utf-8")
    with pytest.raises(rpa.AuditArtifactParseError, match="AUDIT_LINEAGE_UNREADABLE"):
        rpa.resolve_effective_lineage(study, repo)


def test_rt3_tampered_anchor_is_detected(lineage_env):
    """The anchor is integrity-bound, so silent edits are caught."""
    rpa, study, repo = lineage_env
    _record(rpa, study, repo, "causal", 3, "A" * 64, "R1" * 32)

    p = rpa._lineage_path(study, repo)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["entries"][0]["pass"] = 1            # roll the high-water mark back
    p.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(rpa.AuditArtifactParseError, match="AUDIT_LINEAGE_TAMPERED"):
        rpa.resolve_effective_lineage(study, repo)


def test_rt3_anchor_identity_mismatch_is_detected(lineage_env):
    rpa, study, repo = lineage_env
    _record(rpa, study, repo, "causal", 1, "A" * 64, "R1" * 32)
    p = rpa._lineage_path(study, repo)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["study_id"] = "some_other_study"
    data["integrity_sha256"] = rpa._lineage_integrity(data["entries"])
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(rpa.AuditArtifactParseError, match="AUDIT_LINEAGE_IDENTITY_MISMATCH"):
        rpa.resolve_effective_lineage(study, repo)


# ===========================================================================
# RT-4 -- feature grandfather baseline
# ===========================================================================

class _FDef:
    def __init__(self, name, status="verified", implementation="", tests=()):
        self.name = name
        self.status = status
        self.implementation = implementation
        self.tests = tests


def _baseline_file(tmp_path: Path, pinned, active):
    import hashlib

    p = tmp_path / "baseline.json"
    p.write_text(json.dumps({
        "pinned_original_verified": sorted(pinned),
        "baseline_verified": sorted(active),
    }), encoding="utf-8")
    return p


def test_rt4_existing_grandfathered_feature_is_accepted():
    """1 -- an existing grandfathered feature needs no fresh evidence."""
    from scripts.check_feature_promotion import check_feature_promotions, load_baseline

    base = load_baseline()
    sample = sorted(base)[0]
    report = check_feature_promotions(registry={sample: _FDef(sample)}, baseline=base)
    assert report["passed"], report["violations"]


def test_rt4_removing_a_grandfathered_name_is_allowed(tmp_path, monkeypatch):
    """2 -- the active set may shrink."""
    import scripts.check_feature_promotion as cfp

    pinned = {"a", "b", "c"}
    p = _baseline_file(tmp_path, pinned, {"a", "b"})     # 'c' removed
    monkeypatch.setattr(cfp, "BASELINE_PINNED_SHA256", cfp._name_set_hash(pinned))
    assert cfp.load_baseline(p) == {"a", "b"}


def test_rt4_new_registry_feature_alone_requires_evidence(tmp_path):
    """3 -- add to the registry only -> promotion evidence required."""
    from scripts.check_feature_promotion import check_feature_promotions, load_baseline

    reg = {"brand_new": _FDef("brand_new", implementation="", tests=())}
    report = check_feature_promotions(registry=reg, baseline=load_baseline())
    assert not report["passed"]
    codes = {v["code"] for v in report["violations"]}
    assert {"PROMOTION_EVIDENCE_ABSENT", "PROMOTION_RECORD_ABSENT"} & codes


def test_rt4_adding_to_registry_and_baseline_is_refused(tmp_path, monkeypatch):
    """4 -- the actual exploit: add the name to BOTH -> REFUSED.

    The old guard computed `baseline - registry`, which is empty in exactly this case.
    """
    import scripts.check_feature_promotion as cfp

    pinned = {"old_a", "old_b"}
    p = _baseline_file(tmp_path, pinned, pinned | {"brand_new"})
    monkeypatch.setattr(cfp, "BASELINE_PINNED_SHA256", cfp._name_set_hash(pinned))

    with pytest.raises(cfp.FeaturePromotionError, match="PROMOTION_BASELINE_EXTENDED"):
        cfp.load_baseline(p)


def test_rt4_editing_the_pinned_historical_set_is_detected(tmp_path, monkeypatch):
    """5 -- growing the pinned set breaks the code-side pin."""
    import scripts.check_feature_promotion as cfp

    pinned = {"old_a", "old_b"}
    monkeypatch.setattr(cfp, "BASELINE_PINNED_SHA256", cfp._name_set_hash(pinned))
    smuggled = pinned | {"brand_new"}
    p = _baseline_file(tmp_path, smuggled, smuggled)
    with pytest.raises(cfp.FeaturePromotionError, match="PROMOTION_BASELINE_TAMPERED"):
        cfp.load_baseline(p)


def test_rt4_real_baseline_matches_its_pin():
    from scripts.check_feature_promotion import load_baseline

    assert len(load_baseline()) == 502


def test_rt4_wick_remains_provisional():
    """6 -- wick stays provisional until valid promotion evidence exists."""
    from features.registry import FEATURE_REGISTRY
    from scripts.check_feature_promotion import load_baseline

    assert FEATURE_REGISTRY["latest_1m_wick_imbalance"].status == "provisional"
    assert "latest_1m_wick_imbalance" not in load_baseline()


# ===========================================================================
# W5 / W7 -- transcript semantics and seal reproducibility
# ===========================================================================

def test_w5_arbitrary_file_does_not_become_session_provenance(tmp_path):
    """An existing file proves the file exists, not that a review session happened."""
    import scripts.run_preexec_audits as rpa

    decoy = tmp_path / "README.md"
    decoy.write_bytes(b"not a transcript\n")
    prov = rpa.build_reviewer_provenance("alice", "cli_author", decoy)

    assert prov["provenance_strength"] == "DECLARED_IDENTITY_ONLY"
    assert prov["independence_proven"] is False
    assert prov["session_evidence"] is None
    assert prov["attached_artifact"]["sha256"]
    assert "NOT treated as authenticated session provenance" in \
        prov["attached_artifact"]["interpretation"]


def test_w5_absent_transcript_still_records_the_absence(tmp_path):
    import scripts.run_preexec_audits as rpa

    prov = rpa.build_reviewer_provenance("alice", "cli_author", None)
    assert prov["provenance_strength"] == "DECLARED_IDENTITY_ONLY"
    assert prov["attached_artifact"] is None
    assert any("absence of session evidence" in l.lower() for l in prov["limitations"])


def test_w7_text_hash_is_line_ending_independent(tmp_path):
    """A legitimate checkout under either git EOL policy yields one sealed identity."""
    lf, crlf = tmp_path / "a.py", tmp_path / "b.py"
    lf.write_bytes(b"import os\n\ndef f():\n    return 1\n")
    crlf.write_bytes(b"import os\r\n\r\ndef f():\r\n    return 1\r\n")
    assert canonical_file_sha256(lf) == canonical_file_sha256(crlf)


@pytest.mark.parametrize("ext", [".py", ".json", ".yaml", ".md", ".toml"])
def test_w7_all_source_extensions_are_canonicalised(tmp_path, ext):
    a, b = tmp_path / f"a{ext}", tmp_path / f"b{ext}"
    a.write_bytes(b"x\ny\n")
    b.write_bytes(b"x\r\ny\r\n")
    assert canonical_file_sha256(a) == canonical_file_sha256(b)


def test_w7_binary_artifacts_are_hashed_byte_exact(tmp_path):
    """Normalising a parquet would silently equate genuinely different files."""
    a, b = tmp_path / "a.parquet", tmp_path / "b.parquet"
    a.write_bytes(b"\x00\x01\r\n\x02")
    b.write_bytes(b"\x00\x01\n\x02")
    assert canonical_file_sha256(a) != canonical_file_sha256(b)


def test_w7_seal_and_manifest_share_one_hash_implementation():
    """Two hash functions would reintroduce the mismatch they were fixed to remove."""
    from scripts.preexec_audit_seal import _hash_file as seal_hash
    from scripts.resolve_execution_manifest import _hash_file as manifest_hash

    p = REPO_ROOT / "scripts" / "resolve_execution_manifest.py"
    assert seal_hash(p) == manifest_hash(p) == canonical_file_sha256(p)


# ===========================================================================
# W6 -- residual RTH duplication in sealed feature infrastructure
# ===========================================================================

@pytest.mark.parametrize("module_rel", ["features/engine.py", "features/library.py"])
def test_w6_no_inline_rth_end_at_1500(module_rel):
    """Both known duplicates ended RTH at 15:00 while the project window ends 15:15."""
    src = (REPO_ROOT / module_rel).read_text(encoding="utf-8")
    code = "\n".join(
        line.split("#", 1)[0] for line in src.splitlines()
        if not line.strip().startswith("#")
    )
    assert "dt.hour < 15" not in code, f"{module_rel} still re-derives RTH inline"
    assert "hour=15, minute=0" not in code, f"{module_rel} still ends RTH at 15:00"
    assert "is_in_session" in code, f"{module_rel} must use the canonical boundary"


def test_w6_engine_rth_matches_the_canonical_window():
    import pandas as pd
    from features.engine import _is_rth
    from utils.session_boundaries import is_in_session

    for hhmm in ("08:29", "08:31", "14:59", "15:00", "15:10", "15:15", "15:16"):
        ns = int(pd.Timestamp(f"2024-09-03 {hhmm}", tz="America/Chicago")
                 .tz_convert("UTC").value)
        assert _is_rth(ns) == is_in_session(ns, "RTH"), hhmm


def test_w6_1500_to_1515_band_is_rth_in_the_feature_engine():
    """The exact band the duplicates excluded."""
    import pandas as pd
    from features.engine import _is_rth

    for hhmm in ("15:00:01", "15:07:00", "15:15:00"):
        ns = int(pd.Timestamp(f"2024-09-03 {hhmm}", tz="America/Chicago")
                 .tz_convert("UTC").value)
        assert _is_rth(ns) is True, hhmm
