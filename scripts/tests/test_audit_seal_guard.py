import sys
from pathlib import Path
import json
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.preexec_audit_seal import verify_preexec_audit_seal, generate_preexec_audit_seal, PreexecAuditStaleError
from scripts.resolve_execution_manifest import compute_ast_closure, resolve_execution_manifest

STUDY_DIR = REPO_ROOT / "studies" / "Gemini_clean_maturity_flip_rolling_5m_productivity"


def test_audit_seal_valid_and_tamper_detection(tmp_path):
    # 1. Verification of real study must pass
    seal = verify_preexec_audit_seal(STUDY_DIR, repo_root=REPO_ROOT)
    assert seal is not None and "composite_seal_hash" in seal

    # 2. Tampering test: corrupt a hash in a copy of the seal
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
    assert "PREEXEC_AUDIT_STALE" in str(excinfo.value)


def test_audit_seal_refuses_stale_audit_on_code_change(tmp_path):
    import shutil
    # Copy study to temp directory
    tmp_study = tmp_path / "study"
    shutil.copytree(STUDY_DIR, tmp_study)

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
    assert "PREEXEC_AUDIT_STALE" in str(excinfo.value)


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
        assert "PREEXEC_AUDIT_STALE" in str(excinfo.value)
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
