"""``verified`` has exactly one writer: ``features/promotion.py``.

Until 2026-09-10 the V1->V2 migration bundle could be re-materialized and re-activated by a
study-side ceremony (``scripts/_legacy_reconcile_study_capabilities.py`` ->
``materialize_feature_candidate.py`` -> ``features.candidate_authority.activate_*``), which wrote
``status: verified`` / ``lifecycle_status: verified`` straight into the authority bundle and
re-pointed ``features/authority/active.json``.  That door required a sealed authorizing study,
which a new definition can never have (the loop THE REHEARSAL hit).  These tests keep it shut.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ONLY_WRITER = "features/promotion.py"
REMOVED = (
    "scripts/materialize_feature_candidate.py",
    "scripts/prepare_feature_candidate.py",
    "scripts/activate_feature_pipeline_v2.py",
    "scripts/authorize_feature_candidate_activation.py",
    "scripts/materialize_scoped_promotions.py",
    "scripts/_legacy_reconcile_study_capabilities.py",
)
# A literal assignment of the feature lifecycle status.  ``lifecycle_status`` is the bundle's
# field and is unique to it; the bare ``status`` spelling is checked only in modules that
# touch the bundle files (model exports use ``status: verified`` for an unrelated concept).
LIFECYCLE_WRITE = re.compile(
    r"""(\[\s*['"]lifecycle_status['"]\s*\]\s*=\s*['"]verified['"])|(['"]lifecycle_status['"]\s*:\s*['"]verified['"])"""
)
BUNDLE_STATUS_WRITE = re.compile(r"""\[\s*['"]status['"]\s*\]\s*=\s*['"]verified['"]""")
BUNDLE_MARKERS = ("canonical_registry", "promotion_facts", "legacy_alias_mapping")
# A write to the active-authority pointer.
POINTER_WRITE = re.compile(r"""ACTIVE_POINTER\s*\.\s*(write_text|write_bytes|open)|os\.replace\([^)]*ACTIVE_POINTER|active\.json['"][^\n]*write""")


def _tracked_python() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    keep = []
    for rel in out:
        parts = Path(rel).parts
        if "tests" in parts or "archive" in parts or parts[0] in {"scratch", "studies", "artifacts", "notebooks"}:
            continue
        keep.append(ROOT / rel)
    return keep


def test_candidate_authority_is_a_reader_only():
    import features.candidate_authority as authority
    for name in ("freeze_candidate", "activate_frozen_candidate", "activate_pipeline_candidate"):
        assert not hasattr(authority, name), name
    assert callable(authority.load_authority)


@pytest.mark.parametrize("rel", REMOVED)
def test_removed_ceremony_entry_points_are_gone(rel):
    assert not (ROOT / rel).exists(), rel


def test_no_module_but_promotion_writes_verified_or_repoints_active_authority():
    offenders = []
    for path in _tracked_python():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        touches_bundle = any(m in text for m in BUNDLE_MARKERS)
        if (LIFECYCLE_WRITE.search(text) or POINTER_WRITE.search(text)
                or (touches_bundle and BUNDLE_STATUS_WRITE.search(text))):
            offenders.append(rel)
    assert offenders == [] or offenders == [ONLY_WRITER], offenders


def test_promotion_module_is_the_only_writer_of_promotion_records():
    """The promotion record directory is written by features/promotion.py and nothing else."""
    writers = []
    for path in _tracked_python():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        if "definitions/promotions" in text or "PROMOTIONS_DIR" in text:
            if re.search(r"(PROMOTIONS_DIR|promotion_path\([^)]*\)).*\.(write_text|write_bytes|mkdir)", text) or ("definitions/promotions" in text and "write_text" in text and rel != ONLY_WRITER and "promotion" in rel):
                writers.append(rel)
    assert writers == [ONLY_WRITER], writers


def test_workflow_engine_capability_leaf_is_a_typed_refusal(tmp_path):
    from scripts.reconcile_study_capabilities import CAPABILITY_RECONCILIATION_RETIRED, reconcile
    before = sorted(p.as_posix() for p in ROOT.rglob("features/authority/*.json"))
    result = reconcile(tmp_path)
    assert result["state"] == "TRUE_CAPABILITY_GAP" and result["error"] == CAPABILITY_RECONCILIATION_RETIRED
    assert "feature promote" in result["detail"]
    assert sorted(p.as_posix() for p in ROOT.rglob("features/authority/*.json")) == before
    assert not list(tmp_path.iterdir())
