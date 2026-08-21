"""Regressions for the final Red Team blockers: RT2-B1, RT2-B2, RT1-B1, RT3-B1, W-A, W-B.

Each group reproduces the attack that worked against commit `33f5ad1` and asserts the
control now refuses it. Where a control's guarantee has a boundary, the boundary is
asserted too -- a test that only proves the happy path is the kind of check that always
passes.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.research_preflight import (  # noqa: E402
    CAUSAL_INVARIANTS_BUDGET_SECONDS,
    CAUSAL_INVARIANTS_MEASURED_SECONDS,
    EVIDENCE_SCHEMA_VERSION,
    PASSING_OUTCOMES,
    REQUIRED_STUDY_CHECKS,
    PreflightEvidenceError,
    assert_preflight_audit_ready,
    compute_evidence_sha256,
)
from scripts.resolve_execution_manifest import (  # noqa: E402
    GOVERNANCE_AUTHORITY_DATA_FILES,
    compute_ast_closure,
    discover_subprocess_gate_scripts,
    resolve_execution_manifest,
)
from scripts.run_preexec_audits import (  # noqa: E402
    AuditArtifactParseError,
    _lineage_path,
    _write_lineage_anchor,
    append_pass_ledger_entry,
    resolve_effective_lineage,
    set_test_lineage_dir,
)
from scripts.tests._preflight_fixture import plant_audit_ready_preflight  # noqa: E402
from scripts.tests._study_copy import copy_study_as_fresh_identity

STUDY_DIR = REPO_ROOT / "studies" / "es_wick_imbalance_acceptance_v2"


# ===========================================================================
# GROUP 1 -- RT2-B1: multi-alias / namespace / relative import closure
# ===========================================================================

def _mini_repo(root: Path) -> None:
    """A repo-shaped tree exercising every ImportFrom form that must be followed.

    Uses the real repo-local root package name ``features`` so the resolver's
    repo-local heuristics apply exactly as they do in production.
    """
    (root / "features" / "trackers").mkdir(parents=True)          # PEP 420 namespace pkg
    (root / "features" / "__init__.py").write_text("", encoding="utf-8")
    for name in ("a", "b", "c"):
        (root / "features" / "trackers" / f"{name}.py").write_text(
            f"VAL = {name!r}\n", encoding="utf-8"
        )

    (root / "features" / "regular").mkdir(parents=True)           # regular package
    (root / "features" / "regular" / "__init__.py").write_text("", encoding="utf-8")
    for name in ("a", "b"):
        (root / "features" / "regular" / f"{name}.py").write_text(
            f"VAL = {name!r}\n", encoding="utf-8"
        )

    (root / "features" / "deep" / "inner").mkdir(parents=True)
    (root / "features" / "deep" / "__init__.py").write_text("", encoding="utf-8")
    (root / "features" / "deep" / "inner" / "__init__.py").write_text("", encoding="utf-8")
    for name in ("a", "b"):
        (root / "features" / "deep" / f"{name}.py").write_text(
            f"VAL = {name!r}\n", encoding="utf-8"
        )


IMPORT_FORMS = {
    # id: (seed relative path, seed source, modules that must enter the closure)
    "from_pkg_import_a_b": (
        "seed.py",
        "from features.regular import a, b\n",
        ["features/regular/a.py", "features/regular/b.py", "features/regular/__init__.py"],
    ),
    "from_namespace_pkg_import_a_b": (
        "seed.py",
        "from features.trackers import a, b\n",
        ["features/trackers/a.py", "features/trackers/b.py"],
    ),
    "from_dot_import_a_b": (
        "features/regular/seed.py",
        "from . import a, b\n",
        ["features/regular/a.py", "features/regular/b.py"],
    ),
    "from_dotdot_import_a_b": (
        "features/deep/inner/seed.py",
        "from .. import a, b\n",
        ["features/deep/a.py", "features/deep/b.py"],
    ),
}


@pytest.mark.parametrize("form_id", sorted(IMPORT_FORMS))
def test_rt2b1_every_alias_that_executes_enters_the_closure(form_id, tmp_path):
    """Python executes every alias in a multi-alias ImportFrom; so must the closure.

    The resolver used to ``break`` after the first alias that resolved, so
    ``from features.trackers import velocity, volume, wick`` would have put ONE tracker
    in the sealed identity and reported 100% coverage for all three.
    """
    seed_rel, source, expected = IMPORT_FORMS[form_id]
    root = tmp_path / "repo"
    root.mkdir()
    _mini_repo(root)
    seed_p = root / seed_rel
    seed_p.parent.mkdir(parents=True, exist_ok=True)
    seed_p.write_text(source, encoding="utf-8")

    # 1. What does the interpreter actually execute?
    probe = (
        "import sys, json\n"
        f"sys.path.insert(0, r'{root}')\n"
        f"__import__({str(seed_rel[:-3].replace('/', '.'))!r})\n"
        "print(json.dumps(sorted(m for m in sys.modules if m.startswith('features'))))\n"
    )
    res = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=str(root))
    assert res.returncode == 0, res.stderr
    executed = json.loads(res.stdout.strip().splitlines()[-1])

    # 2. Every executed repo-local module must be in the closure.
    visited, unresolved = compute_ast_closure([seed_p], root)
    closure_rel = {p.relative_to(root).as_posix() for p in visited}

    for rel in expected:
        assert rel in closure_rel, (
            f"{rel} executes but is absent from the closure "
            f"(closure={sorted(closure_rel)}, executed={executed})"
        )
    assert unresolved == [], unresolved

    # 3. Executed-module parity: nothing that ran is missing.
    for mod in executed:
        candidates = {f"{mod.replace('.', '/')}.py", f"{mod.replace('.', '/')}/__init__.py"}
        if not (candidates & {r for r in closure_rel}):
            # only namespace packages legitimately contribute no file
            assert not (root / mod.replace(".", "/") / "__init__.py").exists()
            assert not (root / f"{mod.replace('.', '/')}.py").exists()


@pytest.mark.parametrize("form_id", sorted(IMPORT_FORMS))
def test_rt2b1_changing_any_included_module_changes_the_composite(form_id, tmp_path):
    """A closure that does not move when an included module changes seals nothing."""
    seed_rel, source, expected = IMPORT_FORMS[form_id]
    root = tmp_path / "repo"
    root.mkdir()
    _mini_repo(root)
    seed_p = root / seed_rel
    seed_p.parent.mkdir(parents=True, exist_ok=True)
    seed_p.write_text(source, encoding="utf-8")

    def composite() -> str:
        from scripts.resolve_execution_manifest import canonical_file_sha256
        visited, _ = compute_ast_closure([seed_p], root)
        import hashlib
        payload = {
            p.relative_to(root).as_posix(): canonical_file_sha256(p) for p in visited
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

    baseline = composite()
    for rel in expected:
        target = root / rel
        original = target.read_bytes()
        try:
            target.write_text(
                original.decode("utf-8") + "\n# canary\n", encoding="utf-8"
            )
            assert composite() != baseline, f"editing {rel} did not move the composite"
        finally:
            target.write_bytes(original)
    assert composite() == baseline


def test_rt2b1_unresolved_alias_is_reported_even_when_a_sibling_resolves(tmp_path):
    """A first successful alias used to suppress the honesty signal for every later one."""
    root = tmp_path / "repo"
    root.mkdir()
    _mini_repo(root)
    seed = root / "seed.py"
    seed.write_text("from features.trackers import a, missing_module\n", encoding="utf-8")

    visited, unresolved = compute_ast_closure([seed], root)
    closure_rel = {p.relative_to(root).as_posix() for p in visited}
    assert "features/trackers/a.py" in closure_rel
    targets = [u["import_target"] for u in unresolved]
    assert "features.trackers.missing_module" in targets, unresolved


def test_rt2b1_relative_unresolved_alias_is_reported_from_a_namespace_base(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _mini_repo(root)
    seed = root / "features" / "trackers" / "seed.py"
    seed.write_text("from . import a, nope\n", encoding="utf-8")

    visited, unresolved = compute_ast_closure([seed], root)
    closure_rel = {p.relative_to(root).as_posix() for p in visited}
    assert "features/trackers/a.py" in closure_rel
    assert any(u["import_target"].endswith("nope") for u in unresolved), unresolved


def test_rt2b1_attribute_import_from_a_real_package_is_not_a_false_gap(tmp_path):
    """`from .pkg import SomeClass` must NOT be reported: the __init__ executes and the
    name is an attribute, not a module. Fail-closed must not mean cry-wolf."""
    root = tmp_path / "repo"
    root.mkdir()
    _mini_repo(root)
    (root / "features" / "regular" / "__init__.py").write_text(
        "class Thing:\n    pass\n", encoding="utf-8"
    )
    seed = root / "seed.py"
    seed.write_text("from features.regular import Thing\n", encoding="utf-8")
    _, unresolved = compute_ast_closure([seed], root)
    assert unresolved == [], unresolved


def test_rt2b1_material_case_all_nine_real_trackers_in_one_statement(tmp_path):
    """The Red Team's stated material consequence, against the real repository.

    One edit turning nine single-alias imports of `features/trackers/*` into a single
    multi-alias statement dropped eight trackers out of the sealed identity at 100%
    reported coverage.
    """
    trackers = sorted(
        p.stem for p in (REPO_ROOT / "features" / "trackers").glob("*.py")
        if not p.stem.startswith("_")
    )
    assert len(trackers) >= 5, trackers
    seed = tmp_path / "multi_alias_seed.py"
    seed.write_text(
        "from features.trackers import " + ", ".join(trackers) + "\n", encoding="utf-8"
    )

    visited, unresolved = compute_ast_closure([seed], REPO_ROOT)
    closure_rel = {
        p.relative_to(REPO_ROOT).as_posix() for p in visited
        if REPO_ROOT in p.parents or p.is_relative_to(REPO_ROOT)
    }
    for t in trackers:
        assert f"features/trackers/{t}.py" in closure_rel, t
    assert unresolved == [], unresolved


# ===========================================================================
# GROUP 2 -- RT2-B2: governance closure covers what mandatory gates execute
# ===========================================================================

def _governance_keys() -> set:
    _, file_hashes, _ = resolve_execution_manifest(STUDY_DIR, REPO_ROOT)
    return set(file_hashes)


def test_rt2b2_every_subprocess_invoked_gate_is_inside_the_governance_closure():
    """Derived from research_preflight.py's own source -- not a hand-maintained list.

    A second hand-written list is the same defect one edit later, so the assertion is
    that the DERIVED set is a subset of the closure. Adding a new subprocess gate to the
    preflight without sealing it fails here.
    """
    derived = discover_subprocess_gate_scripts(REPO_ROOT)
    assert derived, "no subprocess-invoked gates discovered; the extractor is broken"
    keys = _governance_keys()
    missing = [
        p.relative_to(REPO_ROOT).as_posix() for p in derived
        if f"repo:{p.relative_to(REPO_ROOT).as_posix()}" not in keys
    ]
    assert missing == [], f"mandatory gates execute from outside the seal: {missing}"


def test_rt2b2_extractor_agrees_with_the_preflight_source():
    """Cross-check the AST extractor against an independent read of the source.

    If the extractor silently stopped finding gates, the subset assertion above would
    pass vacuously. This is the falsifiability check on the check.
    """
    src = (REPO_ROOT / "scripts" / "research_preflight.py").read_text(encoding="utf-8")
    named = {
        m for m in [
            "causal_lint.py", "check_artifact_schema.py", "check_feature_promotion.py",
            "check_research_decision_fidelity.py", "check_spec_fidelity.py",
            "select_required_tests.py",
        ] if m in src
    }
    derived = {p.name for p in discover_subprocess_gate_scripts(REPO_ROOT)}
    assert named <= derived, f"extractor missed {sorted(named - derived)}"


@pytest.mark.parametrize("rel", [
    "scripts/select_required_tests.py",
    "scripts/check_feature_promotion.py",
    "features/feature_lifecycle_baseline.json",
])
def test_rt2b2_editing_a_governance_authority_moves_the_composite(rel, tmp_path):
    """These three changed mandatory verdicts while leaving every seal valid."""
    target = REPO_ROOT / rel
    assert target.exists(), rel
    original = target.read_bytes()
    baseline, _, _ = resolve_execution_manifest(STUDY_DIR, REPO_ROOT)
    try:
        if rel.endswith(".json"):
            data = json.loads(original.decode("utf-8"))
            data["_rt_canary"] = True
            target.write_text(json.dumps(data), encoding="utf-8")
        else:
            target.write_text(
                original.decode("utf-8") + "\n# rt_canary\n", encoding="utf-8"
            )
        mutated, _, _ = resolve_execution_manifest(STUDY_DIR, REPO_ROOT)
        assert mutated != baseline, f"editing {rel} did not move the composite"
    finally:
        target.write_bytes(original)
    restored, _, _ = resolve_execution_manifest(STUDY_DIR, REPO_ROOT)
    assert restored == baseline


def test_rt2b2_lifecycle_authority_data_files_are_sealed():
    keys = _governance_keys()
    for rel in GOVERNANCE_AUTHORITY_DATA_FILES:
        if (REPO_ROOT / rel).exists():
            assert f"repo:{rel}" in keys, rel


def test_rt2b2_narrowing_mandatory_test_selection_invalidates_the_seal(tmp_path):
    """Narrowing `select_required_tests.py` yielded CAUSAL_INVARIANTS: PASSED with an
    unchanged composite, so no existing seal was invalidated. It must now be stale."""
    from scripts.preexec_audit_seal import (
        PreexecAuditStaleError, generate_preexec_audit_seal, verify_preexec_audit_seal,
    )
    from scripts.run_preexec_audits import (
        issue_causal_audit_status_from_report, issue_contract_audit_status_from_report,
    )
    from scripts.tests.test_round2_invariants import _plant_compliant_audit_reports

    tmp_study = tmp_path / "study"
    copy_study_as_fresh_identity(STUDY_DIR, tmp_study)
    _plant_compliant_audit_reports(tmp_study)
    plant_audit_ready_preflight(tmp_study)
    issue_causal_audit_status_from_report(tmp_study, pass_num=10, repo_root=REPO_ROOT)
    issue_contract_audit_status_from_report(tmp_study, pass_num=10, repo_root=REPO_ROOT)
    generate_preexec_audit_seal(tmp_study, repo_root=REPO_ROOT)

    target = REPO_ROOT / "scripts" / "select_required_tests.py"
    original = target.read_bytes()
    try:
        # The exact attack: narrow the selection to one trivially-passing file.
        target.write_text(
            original.decode("utf-8")
            + "\n\ndef _rt_narrow():\n    return ['scripts/tests/test_resampling.py']\n",
            encoding="utf-8",
        )
        with pytest.raises(PreexecAuditStaleError):
            verify_preexec_audit_seal(tmp_study, repo_root=REPO_ROOT)
    finally:
        target.write_bytes(original)


# ===========================================================================
# GROUP 3 -- RT1-B1: preflight evidence binding
# ===========================================================================

@pytest.fixture()
def bound_study(tmp_path):
    """A scratch study copy carrying genuine, bound, audit-ready preflight evidence."""
    s = tmp_path / "study"
    copy_study_as_fresh_identity(STUDY_DIR, s)
    plant_audit_ready_preflight(s)
    return s


def test_rt1b1_bound_evidence_is_accepted(bound_study):
    data = assert_preflight_audit_ready(bound_study, REPO_ROOT)
    assert data["audit_ready"] is True


def test_rt1b1_two_key_stub_is_refused(tmp_path):
    """`{"audit_ready": true}` satisfied the gate that authorises audits and seals."""
    s = tmp_path / "study"
    (s / "audit").mkdir(parents=True)
    (s / "audit" / "preflight.json").write_text('{"audit_ready": true}', encoding="utf-8")
    with pytest.raises(PreflightEvidenceError) as e:
        assert_preflight_audit_ready(s, REPO_ROOT)
    assert "PREFLIGHT_EVIDENCE_OBSOLETE" in str(e.value)


def test_rt1b1_hand_edited_clear_artifact_is_refused(bound_study):
    """A genuinely BLOCKED artifact edited to say CLEAR no longer hashes to itself."""
    p = bound_study / "audit" / "preflight.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["check_outcomes"]["CAUSAL_INVARIANTS"] = "TIMEOUT"
    data["audit_ready"] = True          # attacker keeps the headline field true
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    with pytest.raises(PreflightEvidenceError) as e:
        assert_preflight_audit_ready(bound_study, REPO_ROOT)
    assert "PREFLIGHT_EVIDENCE_TAMPERED" in str(e.value)


def test_rt1b1_incomplete_check_set_is_refused_even_if_internally_consistent(bound_study):
    """The required SET comes from REQUIRED_STUDY_CHECKS, never from the artifact.

    The attacker rewrites `required_checks` to a subset AND recomputes `evidence_sha256`
    so the artifact is internally consistent. Reading expected and actual from the same
    mutable file would accept this.
    """
    p = bound_study / "audit" / "preflight.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["required_checks"] = ["CAUSAL_LINT"]
    data["check_outcomes"] = {"CAUSAL_LINT": "PASSED"}
    data["required_checks_missing"] = []
    data["evidence_sha256"] = compute_evidence_sha256(data)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    with pytest.raises(PreflightEvidenceError) as e:
        assert_preflight_audit_ready(bound_study, REPO_ROOT)
    assert "PREFLIGHT_REQUIRED_CHECKS_INCOMPLETE" in str(e.value)


def test_rt1b1_stale_composite_is_refused(bound_study):
    """Evidence from code state A must not authorise code state B."""
    p = bound_study / "audit" / "preflight.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["execution_composite_sha256"] = "0" * 64
    data["evidence_sha256"] = compute_evidence_sha256(data)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    with pytest.raises(PreflightEvidenceError) as e:
        assert_preflight_audit_ready(bound_study, REPO_ROOT)
    assert "PREFLIGHT_EVIDENCE_STALE" in str(e.value)


def test_rt1b1_real_code_edit_makes_existing_evidence_stale(bound_study):
    """Not just a doctored field: a genuine edit to closure code invalidates evidence."""
    target = REPO_ROOT / "scripts" / "select_required_tests.py"
    original = target.read_bytes()
    try:
        target.write_text(original.decode("utf-8") + "\n# rt_canary\n", encoding="utf-8")
        with pytest.raises(PreflightEvidenceError) as e:
            assert_preflight_audit_ready(bound_study, REPO_ROOT)
        assert "PREFLIGHT_EVIDENCE_STALE" in str(e.value)
    finally:
        target.write_bytes(original)


def test_rt1b1_evidence_from_another_study_is_refused(bound_study, tmp_path):
    other = tmp_path / "other_study"
    copy_study_as_fresh_identity(STUDY_DIR, other)
    shutil.copy2(
        bound_study / "audit" / "preflight.json", other / "audit" / "preflight.json"
    )
    with pytest.raises(PreflightEvidenceError) as e:
        assert_preflight_audit_ready(other, REPO_ROOT)
    assert "PREFLIGHT_EVIDENCE_FOREIGN" in str(e.value)


def test_rt1b1_live_blocked_failure_packet_contradicts_clear_evidence(bound_study):
    """A valid-looking CLEAR artifact beside a live BLOCKED packet: the failure wins."""
    (bound_study / "audit" / "failure_packet.json").write_text(
        json.dumps({
            "status": "BLOCKED", "superseded": False,
            "failed_gate": "CAUSAL_INVARIANTS", "preflight_run_id": "blocked-run",
        }),
        encoding="utf-8",
    )
    with pytest.raises(PreflightEvidenceError) as e:
        assert_preflight_audit_ready(bound_study, REPO_ROOT)
    assert "PREFLIGHT_CONTRADICTED_BY_FAILURE_PACKET" in str(e.value)


def test_rt1b1_superseded_failure_packet_does_not_block(bound_study):
    (bound_study / "audit" / "failure_packet.json").write_text(
        json.dumps({"status": "BLOCKED", "superseded": True}), encoding="utf-8"
    )
    assert assert_preflight_audit_ready(bound_study, REPO_ROOT)["audit_ready"] is True


def test_rt1b1_producer_emits_a_self_consistent_binding():
    """Whatever the producer writes must satisfy its own consumer's hash contract."""
    from scripts.research_preflight import EVIDENCE_BOUND_FIELDS
    assert "execution_composite_sha256" in EVIDENCE_BOUND_FIELDS
    assert "check_outcomes" in EVIDENCE_BOUND_FIELDS
    assert EVIDENCE_SCHEMA_VERSION >= 2
    assert set(REQUIRED_STUDY_CHECKS) and PASSING_OUTCOMES == ("PASSED",)


# ===========================================================================
# GROUP 4 -- RT3-B1: durable audit lineage
# ===========================================================================

def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )


@pytest.fixture()
def git_study(tmp_path):
    """A real git repo containing a study, with the anchor stored inside it.

    Git is the durability substrate, so the tests must use a real one. The test-only
    anchor redirect is cleared for these tests precisely so the production path --
    anchor under `<repo_root>/audit_lineage/` -- is what gets exercised.
    """
    repo = tmp_path / "repo"
    (repo / "studies" / "s1" / "audit").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    set_test_lineage_dir(None)
    try:
        yield repo
    finally:
        set_test_lineage_dir(None)


def _issue(repo: Path, study: Path, pass_num: int, composite: str) -> None:
    append_pass_ledger_entry(
        study, "causal", pass_num, composite, f"report{pass_num}", "auditor",
        {"provenance_strength": "DECLARED_IDENTITY_ONLY"}, repo,
    )


def _commit_all(repo: Path, msg: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


def test_rt3b1_deleting_the_anchor_fails_closed(git_study):
    study = git_study / "studies" / "s1"
    _issue(git_study, study, 1, "a" * 64)
    _issue(git_study, study, 2, "b" * 64)
    _commit_all(git_study, "audits")

    _lineage_path(study, git_study).unlink()
    with pytest.raises(AuditArtifactParseError) as e:
        resolve_effective_lineage(study, git_study)
    assert "AUDIT_LINEAGE_ANCHOR_MISSING" in str(e.value)


def test_rt3b1_deleting_the_ledger_still_fails_closed(git_study):
    study = git_study / "studies" / "s1"
    _issue(git_study, study, 1, "a" * 64)
    _commit_all(git_study, "audits")
    (study / "audit" / "pass_ledger.json").unlink()
    with pytest.raises(AuditArtifactParseError) as e:
        resolve_effective_lineage(study, git_study)
    assert "AUDIT_LINEAGE_RESET_DETECTED" in str(e.value)


def test_rt3b1_deleting_both_fails_closed(git_study):
    """The attack that worked: remove the anchor AND the ledger, then reissue pass 01."""
    study = git_study / "studies" / "s1"
    _issue(git_study, study, 1, "a" * 64)
    _commit_all(git_study, "audits")
    _lineage_path(study, git_study).unlink()
    (study / "audit" / "pass_ledger.json").unlink()
    with pytest.raises(AuditArtifactParseError) as e:
        resolve_effective_lineage(study, git_study)
    assert "AUDIT_LINEAGE_ANCHOR_MISSING" in str(e.value)


def test_rt3b1_rolling_back_anchor_and_ledger_together_is_detected(git_study):
    """14b: both files rewound to the pass-01 snapshot, then pass 02 reissued against a
    different composite. Cryptographically indistinguishable before; caught now via the
    committed copy in HEAD plus the monotonic issuance counter."""
    study = git_study / "studies" / "s1"
    _issue(git_study, study, 1, "a" * 64)
    snapshot_anchor = _lineage_path(study, git_study).read_bytes()
    snapshot_ledger = (study / "audit" / "pass_ledger.json").read_bytes()

    _issue(git_study, study, 2, "b" * 64)
    _commit_all(git_study, "two passes")

    _lineage_path(study, git_study).write_bytes(snapshot_anchor)
    (study / "audit" / "pass_ledger.json").write_bytes(snapshot_ledger)
    with pytest.raises(AuditArtifactParseError) as e:
        resolve_effective_lineage(study, git_study)
    assert "AUDIT_LINEAGE_ROLLBACK_DETECTED" in str(e.value)


def test_rt3b1_rolling_back_the_anchor_only_is_detected(git_study):
    study = git_study / "studies" / "s1"
    _issue(git_study, study, 1, "a" * 64)
    snapshot_anchor = _lineage_path(study, git_study).read_bytes()
    _issue(git_study, study, 2, "b" * 64)
    _lineage_path(study, git_study).write_bytes(snapshot_anchor)
    with pytest.raises(AuditArtifactParseError) as e:
        resolve_effective_lineage(study, git_study)
    assert "AUDIT_LINEAGE_UNANCHORED" in str(e.value)


def test_rt3b1_rolling_back_the_ledger_only_is_detected(git_study):
    study = git_study / "studies" / "s1"
    _issue(git_study, study, 1, "a" * 64)
    snapshot_ledger = (study / "audit" / "pass_ledger.json").read_bytes()
    _issue(git_study, study, 2, "b" * 64)
    (study / "audit" / "pass_ledger.json").write_bytes(snapshot_ledger)
    with pytest.raises(AuditArtifactParseError) as e:
        resolve_effective_lineage(study, git_study)
    assert "AUDIT_LINEAGE_RESET_DETECTED" in str(e.value)


def test_rt3b1_foreign_anchor_is_refused(git_study):
    study = git_study / "studies" / "s1"
    other = git_study / "studies" / "s2"
    (other / "audit").mkdir(parents=True)
    _issue(git_study, other, 1, "a" * 64)
    shutil.copy2(_lineage_path(other, git_study), _lineage_path(study, git_study))
    with pytest.raises(AuditArtifactParseError) as e:
        resolve_effective_lineage(study, git_study)
    assert "AUDIT_LINEAGE_IDENTITY_MISMATCH" in str(e.value)


def test_rt3b1_corrupt_anchor_is_refused(git_study):
    study = git_study / "studies" / "s1"
    _issue(git_study, study, 1, "a" * 64)
    _lineage_path(study, git_study).write_text("{not json", encoding="utf-8")
    with pytest.raises(AuditArtifactParseError) as e:
        resolve_effective_lineage(study, git_study)
    assert "AUDIT_LINEAGE_UNREADABLE" in str(e.value)


def test_rt3b1_edited_anchor_entries_are_refused(git_study):
    study = git_study / "studies" / "s1"
    _issue(git_study, study, 1, "a" * 64)
    p = _lineage_path(study, git_study)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["entries"] = []
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(AuditArtifactParseError) as e:
        resolve_effective_lineage(study, git_study)
    assert "AUDIT_LINEAGE_TAMPERED" in str(e.value)


def test_rt3b1_environment_cannot_redirect_production_lineage(git_study, monkeypatch):
    """`export NT_AUDIT_LINEAGE_DIR=<empty dir>` removed anchor protection with no
    filesystem change and no trace. The env var no longer exists."""
    study = git_study / "studies" / "s1"
    _issue(git_study, study, 1, "a" * 64)
    _commit_all(git_study, "audit")
    elsewhere = git_study.parent / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("NT_AUDIT_LINEAGE_DIR", str(elsewhere))

    # The anchor must still resolve to the repository, not the env-named directory.
    assert _lineage_path(study, git_study).parent == git_study / "audit_lineage"
    entries = resolve_effective_lineage(study, git_study)
    assert len(entries) == 1

    # And no code path reads the environment to place the anchor. Checked on the AST of
    # `_lineage_path` itself so a mention in a comment (there is one, explaining the
    # removal) cannot make this pass or fail for the wrong reason.
    src = (REPO_ROOT / "scripts" / "run_preexec_audits.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "_lineage_path"
    )
    # Docstring excluded: it explains the removal, and matching prose would make this
    # pass or fail for the wrong reason.
    code = [n for n in fn.body if not (
        isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
        and isinstance(n.value.value, str)
    )]
    dumped = "".join(ast.dump(n) for n in code)
    assert "environ" not in dumped, "_lineage_path must not read the environment"
    assert "getenv" not in dumped


def test_rt3b1_test_override_refuses_outside_pytest():
    """The test-only hook must not be a production-reachable relocation."""
    import scripts.run_preexec_audits as rpa

    saved = rpa._TEST_LINEAGE_DIR
    real_pytest = sys.modules.pop("pytest", None)
    try:
        with pytest.raises(RuntimeError, match="LINEAGE_TEST_OVERRIDE_REFUSED"):
            rpa.set_test_lineage_dir(Path("/tmp/anywhere"))
    finally:
        if real_pytest is not None:
            sys.modules["pytest"] = real_pytest
        rpa._TEST_LINEAGE_DIR = saved


def test_rt3b1_fresh_study_with_no_history_is_not_blocked(git_study):
    """Fail-closed must not mean fail-always: a genuinely new study proceeds."""
    study = git_study / "studies" / "brand_new"
    (study / "audit").mkdir(parents=True)
    assert resolve_effective_lineage(study, git_study) == []


def test_rt3b1_copied_study_needs_explicit_bootstrap(git_study):
    """A copied identity carries the source's ledger. Silent adoption is what made
    `bootstrapped_from_local_ledger` an attack; the operator must now say which is true."""
    study = git_study / "studies" / "s1"
    _issue(git_study, study, 1, "a" * 64)
    _commit_all(git_study, "audit")

    copy = git_study / "studies" / "s1_copy"
    shutil.copytree(study, copy)
    with pytest.raises(AuditArtifactParseError) as e:
        resolve_effective_lineage(copy, git_study)
    assert "AUDIT_LINEAGE_ANCHOR_MISSING" in str(e.value)

    res = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "bootstrap_audit_lineage.py"),
         "--study", str(copy)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    assert "BOOTSTRAP_INTENT_REQUIRED" in res.stdout, res.stdout + res.stderr


def test_rt3b1_recreated_study_with_same_identity_cannot_reset(git_study):
    study = git_study / "studies" / "s1"
    _issue(git_study, study, 1, "a" * 64)
    _issue(git_study, study, 2, "b" * 64)
    _commit_all(git_study, "audits")
    shutil.rmtree(study / "audit")
    (study / "audit").mkdir()
    with pytest.raises(AuditArtifactParseError) as e:
        resolve_effective_lineage(study, git_study)
    assert "AUDIT_LINEAGE_RESET_DETECTED" in str(e.value)


def test_rt3b1_anchor_is_repository_visible_and_not_ignored():
    """The anchor must not be the ephemeral half of the pair."""
    assert (REPO_ROOT / "audit_lineage").is_dir()
    assert (REPO_ROOT / "audit_lineage" / "README.md").is_file()
    res = _git(REPO_ROOT, "check-ignore", "audit_lineage")
    assert res.returncode != 0, "audit_lineage must not be git-ignored"


def test_rt3b1_acceptance_study_has_a_durable_anchor():
    """The aggravating fact: the one study with a pass ledger had no anchor at all."""
    ledger = STUDY_DIR / "audit" / "pass_ledger.json"
    if not ledger.is_file():
        pytest.skip("acceptance study has no pass ledger")
    anchor = REPO_ROOT / "audit_lineage" / f"{STUDY_DIR.name}.json"
    assert anchor.is_file(), f"{anchor} missing: RT-3 is unarmed for this study"
    data = json.loads(anchor.read_text(encoding="utf-8"))
    assert data["study_id"] == STUDY_DIR.name
    assert data["high_water"]


def test_rt3b1_anchor_carries_a_monotonic_chain(git_study):
    study = git_study / "studies" / "s1"
    _issue(git_study, study, 1, "a" * 64)
    first = json.loads(_lineage_path(study, git_study).read_text(encoding="utf-8"))
    _issue(git_study, study, 2, "b" * 64)
    second = json.loads(_lineage_path(study, git_study).read_text(encoding="utf-8"))
    assert second["issuance_counter"] == first["issuance_counter"] + 1
    assert second["prev_chain_sha256"] == first["chain_sha256"]
    assert second["chain_sha256"] != first["chain_sha256"]


# ===========================================================================
# GROUP 5 -- W-A: sealed deliverable contract
# ===========================================================================

def test_wa_study_config_json_is_inside_the_sealed_identity():
    _, file_hashes, _ = resolve_execution_manifest(STUDY_DIR, REPO_ROOT)
    cfgs = sorted((STUDY_DIR / "config").glob("*.json"))
    assert cfgs, "study has no config contracts"
    for c in cfgs:
        assert f"study:config/{c.name}" in file_hashes, c.name


def test_wa_editing_deliverables_after_sealing_moves_the_composite(tmp_path):
    """The exact W-A attack: reduce deliverables_by_mode.collect after sealing."""
    tmp_study = tmp_path / "study"
    copy_study_as_fresh_identity(STUDY_DIR, tmp_study)
    baseline, _, _ = resolve_execution_manifest(tmp_study, REPO_ROOT)

    p = tmp_study / "config" / "deliverables_contract.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["deliverables_by_mode"]["collect"] = ["candidates.parquet"]
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")

    mutated, _, _ = resolve_execution_manifest(tmp_study, REPO_ROOT)
    assert mutated != baseline, "post-seal deliverable narrowing left the seal valid"


def test_wa_validate_smoke_consumes_the_sealed_authority():
    """The decision must be read from compiled_study.json, not the loose sidecar."""
    src = (REPO_ROOT / "scripts" / "validate_smoke.py").read_text(encoding="utf-8")
    idx = src.index("collect_deliverables =")
    preceding = src[:idx]
    assert "contracts" in preceding and "compiled_study.json" in preceding
    assert "DELIVERABLES_CONTRACT_DRIFT" in src


def test_wa_sidecar_drift_from_the_compiled_contract_is_refused(tmp_path):
    """SPEC / compiled deliverable identity cannot drift silently."""
    from scripts.validate_smoke import SmokeValidationError

    tmp_study = tmp_path / "study"
    copy_study_as_fresh_identity(STUDY_DIR, tmp_study)
    compiled = json.loads((tmp_study / "compiled_study.json").read_text(encoding="utf-8"))
    sidecar = json.loads(
        (tmp_study / "config" / "deliverables_contract.json").read_text(encoding="utf-8")
    )
    assert sidecar == compiled["contracts"]["deliverables_contract"], (
        "the sidecar and the sealed contract must agree in the committed tree"
    )
    assert SmokeValidationError is not None


def test_wa_compiled_contract_still_requires_the_collection_manifest():
    compiled = json.loads((STUDY_DIR / "compiled_study.json").read_text(encoding="utf-8"))
    collect = compiled["contracts"]["deliverables_contract"]["deliverables_by_mode"]["collect"]
    assert "collection_manifest.json" in collect


# ===========================================================================
# GROUP 6 -- W-B: the mandatory gate must be executable
# ===========================================================================

def test_wb_budget_exceeds_the_recorded_measurement_with_margin():
    """A mandatory gate that cannot finish is operationally broken.

    The budget is derived from a recorded measurement, not chosen. If the suite grows
    past the margin this fails and forces a re-measurement rather than a quiet bump.
    """
    assert CAUSAL_INVARIANTS_BUDGET_SECONDS >= CAUSAL_INVARIANTS_MEASURED_SECONDS * 2, (
        f"budget {CAUSAL_INVARIANTS_BUDGET_SECONDS}s gives less than 2x headroom over "
        f"the measured {CAUSAL_INVARIANTS_MEASURED_SECONDS}s"
    )
    assert CAUSAL_INVARIANTS_BUDGET_SECONDS <= 1800, "budget must stay bounded"


def test_wb_preflight_uses_the_budget_constant_not_a_literal():
    src = (REPO_ROOT / "scripts" / "research_preflight.py").read_text(encoding="utf-8")
    assert "timeout=CAUSAL_INVARIANTS_BUDGET_SECONDS" in src
    assert "timeout=120," not in src


def test_wb_timeout_still_blocks(tmp_path, monkeypatch):
    """Raising the number must not have turned an overrun into a pass."""
    import scripts.research_preflight as rp

    tmp_study = tmp_path / "study"
    copy_study_as_fresh_identity(STUDY_DIR, tmp_study)
    monkeypatch.setattr(rp, "CAUSAL_INVARIANTS_BUDGET_SECONDS", 0.001)
    _, result = rp.run_preflight(tmp_study, [], out_json=tmp_path / "pf.json")
    assert result["check_outcomes"].get("CAUSAL_INVARIANTS") == "TIMEOUT"
    assert result["audit_ready"] is False
    assert result["status"] == "BLOCKED"
    assert "INVARIANT_TEST_TIMEOUT" in result["failure_ids"]


def test_wb_skip_tests_remains_non_audit_ready(tmp_path):
    import scripts.research_preflight as rp

    tmp_study = tmp_path / "study"
    copy_study_as_fresh_identity(STUDY_DIR, tmp_study)
    _, result = rp.run_preflight(
        tmp_study, [], out_json=tmp_path / "pf.json", skip_tests=True
    )
    assert result["audit_ready"] is False
    assert result["check_outcomes"]["CAUSAL_INVARIANTS"] == "SKIPPED"
    with pytest.raises(PreflightEvidenceError):
        assert_preflight_audit_ready(tmp_study, REPO_ROOT)


def test_wb_mandatory_selection_is_non_empty_and_discoverable():
    res = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "select_required_tests.py")],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0, res.stderr
    selected = [l.strip() for l in res.stdout.splitlines() if l.strip()]
    assert len(selected) >= 20, f"mandatory selection collapsed to {len(selected)} files"
    for rel in selected:
        assert (REPO_ROOT / rel).is_file(), rel


@pytest.mark.slow
def test_wb_full_mandatory_suite_completes_inside_the_configured_budget():
    """The end-to-end claim: the gate can actually finish.

    Marked slow so it is excluded from the very selection it measures (the gate runs
    `-m "not slow"`), which is also what stops it recursing into itself.
    """
    import time
    sel = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "select_required_tests.py")],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    ).stdout.split()
    start = time.time()
    res = subprocess.run(
        [sys.executable, "-m", "pytest", *sel, "-m", "not slow", "-q"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
        timeout=CAUSAL_INVARIANTS_BUDGET_SECONDS,
    )
    elapsed = time.time() - start
    assert elapsed < CAUSAL_INVARIANTS_BUDGET_SECONDS, elapsed
    assert res.returncode == 0, res.stdout[-3000:]
