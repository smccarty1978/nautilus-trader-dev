import sys
from pathlib import Path
import json
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.preexec_audit_seal import verify_preexec_audit_seal, generate_preexec_audit_seal, PreexecAuditStaleError
from scripts.resolve_execution_manifest import (
    compute_ast_closure,
    resolve_execution_manifest,
    resolve_execution_file_paths,
)
from scripts.run_preexec_audits import issue_causal_audit_status_from_report, issue_contract_audit_status_from_report
from scripts.tests._preflight_fixture import plant_audit_ready_preflight
from scripts.tests._study_copy import copy_study_as_fresh_identity
from scripts.tests.test_round2_invariants import _plant_compliant_audit_reports

STUDY_DIR = REPO_ROOT / "studies" / "Gemini_clean_maturity_flip_rolling_5m_productivity"

# The CleanFlip study is the fixture used below for the dataset-authority seal tests
# (Finding SEAL_DEFECT / W7-A1): STUDY_DIR above declares no dataset_id, so its seal never
# exercises the `study:dataset:<id>` pseudo-scoped key that broke seal verification.
CLEAN_FLIP_STUDY = REPO_ROOT / "studies" / "Codex_clean_maturity_flip_rolling_5m_productivity"
NQ_DATASET_YAML = REPO_ROOT / "research" / "datasets" / "NQ_v0_2020_2026.yaml"
_clean_flip_present = (CLEAN_FLIP_STUDY / "study.yaml").exists() and NQ_DATASET_YAML.exists()


def _sealed_clean_flip_copy(tmp_path: Path) -> Path:
    """Copies CleanFlip to scratch space with a fresh identity and a valid, current seal."""
    tmp_study = tmp_path / "study"
    copy_study_as_fresh_identity(CLEAN_FLIP_STUDY, tmp_study)
    _plant_compliant_audit_reports(tmp_study)
    issue_causal_audit_status_from_report(tmp_study, pass_num=10, repo_root=REPO_ROOT)
    issue_contract_audit_status_from_report(tmp_study, pass_num=10, repo_root=REPO_ROOT)
    generate_preexec_audit_seal(tmp_study, repo_root=REPO_ROOT)
    return tmp_study



# The seal must FAIL CLOSED. It may do so for several distinct reasons, and after
# the B1/B2 repair the live `pass_11.md` / `contract_pass_10.md` are additionally
# rejected for declaring no `audit_type` / `study` / composite -- they predate that
# contract and are deliberately NOT backfilled here. Any of these codes is a
# correct refusal; what must never happen is a seal being issued.
FAIL_CLOSED_CODES = (
    "PREEXEC_AUDIT_STALE",
    "PREEXEC_AUDIT_PROVENANCE_INVALID",
    "AUDIT_TYPE_UNDECLARED",
    "INGEST_STUDY_UNDECLARED",
    "INGEST_COMPOSITE_UNDECLARED",
)


def assert_fails_closed(message: str) -> None:
    assert any(code in message for code in FAIL_CLOSED_CODES), (
        f"seal did not fail closed with a recognised code: {message}"
    )


def test_real_study_seal_state_is_either_valid_or_fails_closed():
    """The live seal must never be *silently* accepted while stale.

    It is currently STALE by design: the collector reseal is pending an
    independent Red Team (see BACKTEST_HARNESS_REMEDIATION_REPORT.md). This test
    asserts the only two acceptable states — verifies cleanly, or refuses with a
    recognised fail-closed code. Backfilling audit evidence to make it verify is
    explicitly out of scope.
    """
    try:
        seal = verify_preexec_audit_seal(STUDY_DIR, repo_root=REPO_ROOT)
    except PreexecAuditStaleError as err:
        assert_fails_closed(str(err))
    else:
        assert seal is not None and "composite_seal_hash" in seal


def test_audit_seal_valid_and_tamper_detection(tmp_path):
    # Tampering test: corrupt a hash in a copy of the seal
    seal_file = STUDY_DIR / "artifacts" / "preexec_audit_seal.json"
    with open(seal_file, "r") as f:
        data = json.load(f)

    # Modify one hash
    first_key = list(data["file_hashes"].keys())[0]
    data["file_hashes"][first_key] = "0000000000000000000000000000000000000000000000000000000000000000"

    tampered_seal = tmp_path / "artifacts" / "preexec_audit_seal.json"
    tampered_seal.parent.mkdir(parents=True, exist_ok=True)
    with open(tampered_seal, "w") as f:
        json.dump(data, f)

    # Verify fails closed with PreexecAuditStaleError
    with pytest.raises(PreexecAuditStaleError) as excinfo:
        verify_preexec_audit_seal(tmp_path, repo_root=REPO_ROOT)
    assert_fails_closed(str(excinfo.value))


def test_audit_seal_refuses_stale_audit_on_code_change(tmp_path):
    import shutil
    # Copy study to temp directory
    tmp_study = tmp_path / "study"
    copy_study_as_fresh_identity(STUDY_DIR, tmp_study)
    plant_audit_ready_preflight(tmp_study)

    # 1. Tamper status.json to have mismatched audited_execution_composite_sha256
    status_file = tmp_study / "audit" / "status.json"
    with open(status_file, "r") as f:
        status_data = json.load(f)

    status_data["audited_execution_composite_sha256"] = "stale_hash_from_previous_pass"
    with open(status_file, "w") as f:
        json.dump(status_data, f, indent=2)

    # 2. Attempt to generate seal must fail with PreexecAuditStaleError
    with pytest.raises(PreexecAuditStaleError) as excinfo:
        generate_preexec_audit_seal(tmp_study, repo_root=REPO_ROOT)
    assert_fails_closed(str(excinfo.value))


@pytest.mark.parametrize("rel_path", [
    "utils/causal_registration.py",
    "backtests/nt_runtime/modes/collect.py",
    "features/trackers/rolling_5m_productivity.py",
    "backtests/nt_runtime/data_plan.py",
    "strategies/flip_prediction_collector.py",
    "scripts/preexec_audit_seal.py",
    "scripts/generate_oos_unlock.py",
    "research/schemas/study_spec.py",
])
def test_seal_fails_closed_when_source_code_tampered(rel_path, tmp_path):
    """Mutates real source code on disk and verifies that the seal immediately rejects the tampered tree."""
    target_file = REPO_ROOT / rel_path
    assert target_file.exists(), f"Target source file must exist: {target_file}"

    original_bytes = target_file.read_bytes()

    try:
        # Append a harmless comment to mutate SHA-256
        target_file.write_text(original_bytes.decode("utf-8") + "\n# tamper_canary_test\n", encoding="utf-8")

        # verify_preexec_audit_seal MUST raise PreexecAuditStaleError
        with pytest.raises(PreexecAuditStaleError) as excinfo:
            verify_preexec_audit_seal(STUDY_DIR, repo_root=REPO_ROOT)
        assert_fails_closed(str(excinfo.value))
    finally:
        # Always restore original file content
        target_file.write_bytes(original_bytes)


def test_seal_covers_full_import_closure():
    """Asserts that resolve_execution_manifest dynamically resolves AST transitive closure."""
    seeds = [
        REPO_ROOT / "backtests" / "run_nt_study.py",
        REPO_ROOT / "backtests" / "nt_runtime" / "modes" / "collect.py",
        REPO_ROOT / "strategies" / "flip_prediction_collector.py",
    ]
    closure, unres = compute_ast_closure(seeds, REPO_ROOT)
    assert len(unres) == 0

    composite_sha, file_hashes, mdata = resolve_execution_manifest(STUDY_DIR, REPO_ROOT)

    for p in closure:
        rel = p.relative_to(REPO_ROOT).as_posix()
        assert f"repo:{rel}" in file_hashes, f"File {rel} missing from manifest file_hashes"


# ---------------------------------------------------------------------------
# SEAL_DEFECT regression: `study:dataset:<id>` pseudo-scoped closure keys (W7/A1).
#
# verify_preexec_audit_seal used to reconstruct a sealed entry's physical path by
# splitting its composite key on the first colon (`scope, rel = key.split(":", 1)`).
# For the ordinary `study:<relpath>` / `repo:<relpath>` cases that coincides with a real
# path; for `study:dataset:<id>` (the DatasetSpec-authority entry added to the closure by
# resolve_study_files) it does not -- the key names a semantic identity, and its physical
# file lives under research/datasets/, not under study_dir. Verification crashed with
# "Sealed file missing from disk: <study_dir>/dataset:<id>" for any study that declares a
# dataset_id, which blocks both backtests/nt_runtime/modes/collect.py and
# scripts/validate_smoke.py before they ever run.
# ---------------------------------------------------------------------------

pytestmark_clean_flip = pytest.mark.skipif(
    not _clean_flip_present, reason="CleanFlip study or NQ DatasetSpec absent"
)


@pytestmark_clean_flip
def test_dataset_authority_key_resolves_to_real_datasetspec_not_study_relative_path():
    """The authoritative resolver must map the key to research/datasets/<id>.yaml, not
    <study_dir>/dataset:<id> (which is what the old split-based reconstruction produced)."""
    exec_paths, _ = resolve_execution_file_paths(CLEAN_FLIP_STUDY, REPO_ROOT)
    key = "study:dataset:NQ_v0_2020_2026"
    assert key in exec_paths
    assert exec_paths[key] == NQ_DATASET_YAML.resolve()
    assert not (CLEAN_FLIP_STUDY / "dataset:NQ_v0_2020_2026").exists()


@pytestmark_clean_flip
def test_cleanflip_seal_generates_and_verifies_on_current_frozen_state(tmp_path):
    """The exact previously-failing scenario: a study whose frozen closure includes a
    dataset-authority entry must both seal-generate and seal-verify cleanly."""
    tmp_study = _sealed_clean_flip_copy(tmp_path)
    seal = verify_preexec_audit_seal(tmp_study, repo_root=REPO_ROOT)
    assert seal is not None and "composite_seal_hash" in seal

    # Ordinary study-relative and repo-scoped entries are still present and still verify
    # -- the fix must not narrow verification to only the dataset key.
    assert any(k == "study:study.yaml" for k in seal["file_hashes"])
    assert any(k.startswith("repo:backtests/nt_runtime/modes/collect.py") for k in seal["file_hashes"])
    assert "study:dataset:NQ_v0_2020_2026" in seal["file_hashes"]


@pytestmark_clean_flip
def test_post_freeze_referenced_dataset_spec_mutation_invalidates_seal(tmp_path):
    """Editing the referenced DatasetSpec after sealing must fail verification closed."""
    tmp_study = _sealed_clean_flip_copy(tmp_path)
    original = NQ_DATASET_YAML.read_bytes()
    try:
        NQ_DATASET_YAML.write_bytes(original + b"\n# seal-mutation-canary\n")
        with pytest.raises(PreexecAuditStaleError) as excinfo:
            verify_preexec_audit_seal(tmp_study, repo_root=REPO_ROOT)
        assert_fails_closed(str(excinfo.value))
    finally:
        NQ_DATASET_YAML.write_bytes(original)


@pytestmark_clean_flip
def test_post_freeze_referenced_dataset_spec_deletion_invalidates_seal(tmp_path):
    """Deleting the referenced DatasetSpec after sealing must fail verification closed,
    not raise a raw FileNotFoundError."""
    tmp_study = _sealed_clean_flip_copy(tmp_path)
    moved_aside = NQ_DATASET_YAML.with_name(NQ_DATASET_YAML.name + ".seal_test_removed")
    NQ_DATASET_YAML.rename(moved_aside)
    try:
        with pytest.raises(PreexecAuditStaleError) as excinfo:
            verify_preexec_audit_seal(tmp_study, repo_root=REPO_ROOT)
        assert_fails_closed(str(excinfo.value))
    finally:
        moved_aside.rename(NQ_DATASET_YAML)


@pytestmark_clean_flip
def test_unrelated_dataset_spec_mutation_does_not_invalidate_seal(tmp_path):
    """Mutating an unrelated instrument's DatasetSpec must not stale CleanFlip's seal."""
    unrelated = REPO_ROOT / "research" / "datasets" / "UNRELATED_SEAL_TEST_DATASET.yaml"
    unrelated.write_text("dataset_id: UNRELATED_SEAL_TEST_DATASET\n", encoding="utf-8")
    try:
        tmp_study = _sealed_clean_flip_copy(tmp_path)
        unrelated.write_text(
            "dataset_id: UNRELATED_SEAL_TEST_DATASET\nedited: true\n", encoding="utf-8"
        )
        seal = verify_preexec_audit_seal(tmp_study, repo_root=REPO_ROOT)
        assert seal is not None and "composite_seal_hash" in seal
    finally:
        unrelated.unlink(missing_ok=True)


@pytestmark_clean_flip
def test_malformed_seal_entry_key_fails_closed(tmp_path):
    """A seal entry whose key is neither part of the execution closure nor a recognised
    study:/repo: relative path must fail closed, not silently pass or raise unrelated
    errors. Uses a genuinely valid, frozen, sealed study (so verify_frozen_execution_identity
    itself passes first) to prove this specific branch -- not just any fail-closed reason
    -- is what actually fires."""
    tmp_study = _sealed_clean_flip_copy(tmp_path)

    seal_file = tmp_study / "artifacts" / "preexec_audit_seal.json"
    with open(seal_file, "r") as f:
        data = json.load(f)
    data["file_hashes"]["not_a_real_scope:nonsense"] = "0" * 68
    with open(seal_file, "w") as f:
        json.dump(data, f)

    with pytest.raises(PreexecAuditStaleError) as excinfo:
        verify_preexec_audit_seal(tmp_study, repo_root=REPO_ROOT)
    assert "Unresolvable sealed entry key" in str(excinfo.value)
    assert_fails_closed(str(excinfo.value))
