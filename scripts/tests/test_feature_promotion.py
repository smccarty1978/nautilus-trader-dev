"""Regression tests for feature lifecycle promotion (Finding D).

``latest_1m_wick_imbalance`` was registered with ``status='verified'`` in the same change
that implemented it. ``FEATURE_REGISTRY_CONTRACT.md`` s1 already required look-ahead
auditor clearance before verified status -- but only in prose, so the registry entry was
able to assert the outcome of a review that had not happened.

Worth being precise about what was and was not missing: the declared test file
``tests/test_feature_library.py`` *does* exercise the tracker by name, so the feature was
not evidence-free. What it lacked was auditor clearance, which is not derivable from the
tree and therefore has to be recorded as an explicit promotion step.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_feature_promotion import (
    FeaturePromotionError,
    assert_baseline_not_extended,
    assert_feature_promotions,
    check_feature_promotions,
    load_baseline,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


class _FDef:
    def __init__(self, name, status="verified", implementation="", tests=()):
        self.name = name
        self.status = status
        self.implementation = implementation
        self.tests = tests


def _codes(report):
    return {v["code"] for v in report["violations"]}


@pytest.fixture()
def evidence_repo(tmp_path: Path) -> Path:
    """A repo with a real implementation module and a real test that names the feature."""
    (tmp_path / "features" / "trackers").mkdir(parents=True)
    (tmp_path / "features" / "trackers" / "thing.py").write_text("class T: pass\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_thing.py").write_text(
        "def test_x():\n    assert 'my_feature' == 'my_feature'\n", encoding="utf-8"
    )
    (tmp_path / "tests" / "test_unrelated.py").write_text("def test_y():\n    pass\n", encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# The core rule
# ---------------------------------------------------------------------------

def test_new_feature_cannot_self_grant_verified_without_evidence(evidence_repo: Path):
    """D.1 -- the exact historical shape: verified, with tests that never name it."""
    registry = {
        "my_feature": _FDef(
            "my_feature",
            status="verified",
            implementation="features.trackers.thing.T",
            tests=("tests/test_unrelated.py",),
        )
    }
    report = check_feature_promotions(registry=registry, baseline=set(), repo_root=evidence_repo)
    assert not report["passed"]
    assert "PROMOTION_EVIDENCE_UNBOUND" in _codes(report)


def test_new_feature_with_no_tests_at_all_is_refused(evidence_repo: Path):
    registry = {
        "my_feature": _FDef("my_feature", implementation="features.trackers.thing.T", tests=())
    }
    report = check_feature_promotions(registry=registry, baseline=set(), repo_root=evidence_repo)
    assert not report["passed"]
    assert "PROMOTION_EVIDENCE_ABSENT" in _codes(report)


def test_bound_tests_alone_do_not_promote(evidence_repo: Path):
    """D.2 -- naming tests satisfy rules 1-2 but not the explicit promotion step."""
    registry = {
        "my_feature": _FDef(
            "my_feature",
            implementation="features.trackers.thing.T",
            tests=("tests/test_thing.py",),
        )
    }
    report = check_feature_promotions(registry=registry, baseline=set(), repo_root=evidence_repo)
    # Tests bind, but auditor clearance is still required and is not present.
    assert not report["passed"]
    assert _codes(report) == {"PROMOTION_RECORD_ABSENT"}
    assert report["features_requiring_evidence"] == ["my_feature"]


def test_unresolvable_implementation_is_refused(evidence_repo: Path):
    registry = {
        "my_feature": _FDef(
            "my_feature",
            implementation="features.trackers.ghost.G",
            tests=("tests/test_thing.py",),
        )
    }
    report = check_feature_promotions(registry=registry, baseline=set(), repo_root=evidence_repo)
    assert not report["passed"]
    assert "PROMOTION_IMPLEMENTATION_UNRESOLVED" in _codes(report)


def test_provisional_feature_needs_no_promotion_evidence(evidence_repo: Path):
    """D.3 -- provisional is the correct home for a feature awaiting evidence."""
    registry = {
        "my_feature": _FDef("my_feature", status="provisional", implementation="", tests=())
    }
    report = check_feature_promotions(registry=registry, baseline=set(), repo_root=evidence_repo)
    assert report["passed"]
    assert report["features_requiring_evidence"] == []


def test_unknown_status_is_refused(evidence_repo: Path):
    registry = {"my_feature": _FDef("my_feature", status="blessed")}
    report = check_feature_promotions(registry=registry, baseline=set(), repo_root=evidence_repo)
    assert not report["passed"]
    assert "FEATURE_STATUS_INVALID" in _codes(report)


# ---------------------------------------------------------------------------
# The grandfather list cannot become the exploit
# ---------------------------------------------------------------------------

def test_grandfathered_feature_is_not_re_evidenced(evidence_repo: Path):
    registry = {"old_feature": _FDef("old_feature", implementation="", tests=())}
    report = check_feature_promotions(
        registry=registry, baseline={"old_feature"}, repo_root=evidence_repo
    )
    assert report["passed"]


def test_baseline_may_not_be_extended_with_a_name_the_registry_lacks():
    """D.4 -- pre-authorising a future feature via the baseline is refused."""
    with pytest.raises(FeaturePromotionError, match="PROMOTION_BASELINE_EXTENDED"):
        assert_baseline_not_extended(
            registry={"real": _FDef("real")}, baseline={"real", "smuggled_in"}
        )


def test_missing_baseline_fails_closed(tmp_path: Path):
    with pytest.raises(FeaturePromotionError, match="PROMOTION_BASELINE_MISSING"):
        load_baseline(tmp_path / "nope.json")


def test_malformed_baseline_fails_closed(tmp_path: Path):
    p = tmp_path / "b.json"
    p.write_text('{"wrong_key": []}', encoding="utf-8")
    with pytest.raises(FeaturePromotionError, match="PROMOTION_BASELINE_MALFORMED"):
        load_baseline(p)


# ---------------------------------------------------------------------------
# The real repository state
# ---------------------------------------------------------------------------

def test_real_registry_passes_the_promotion_gate():
    assert_feature_promotions()
    assert_baseline_not_extended()


def test_wick_feature_is_not_verified_without_evidence():
    """D.5 -- the feature at the centre of the finding sits at 'provisional'."""
    from features.registry import FEATURE_REGISTRY

    assert FEATURE_REGISTRY["latest_1m_wick_imbalance"].status == "provisional"


def test_wick_feature_is_absent_from_the_grandfather_baseline():
    """It must not have been quietly grandfathered instead of demoted."""
    assert "latest_1m_wick_imbalance" not in load_baseline()


def test_promoting_wick_to_verified_now_requires_auditor_clearance():
    """D.5 -- the wick feature's real gap was auditor clearance, not a missing test.

    ``tests/test_feature_library.py`` genuinely exercises the tracker by name, so rules 1
    and 2 are satisfied. What was never true is that a look-ahead auditor had cleared it,
    and that is exactly what the registry entry asserted by writing ``verified``.
    """
    from features.registry import FEATURE_REGISTRY

    forged = dict(FEATURE_REGISTRY)
    fdef = forged["latest_1m_wick_imbalance"]
    forged["latest_1m_wick_imbalance"] = _FDef(
        "latest_1m_wick_imbalance",
        status="verified",
        implementation=fdef.implementation,
        tests=tuple(fdef.tests),
    )
    report = check_feature_promotions(registry=forged, baseline=load_baseline())
    assert not report["passed"]
    assert "PROMOTION_RECORD_ABSENT" in _codes(report)


def test_complete_promotion_record_admits_a_new_feature(evidence_repo: Path, tmp_path: Path):
    """D.6 -- the explicit, evidence-backed promotion step is what unlocks verified."""
    audit_rel = "audit/pass_07.md"
    (evidence_repo / "audit").mkdir(parents=True, exist_ok=True)
    (evidence_repo / audit_rel).write_text("cleared\n", encoding="utf-8")

    registry = {
        "my_feature": _FDef(
            "my_feature",
            implementation="features.trackers.thing.T",
            tests=("tests/test_thing.py",),
        )
    }
    import hashlib
    from scripts.check_feature_promotion import feature_implementation_sha256

    impl_sha = feature_implementation_sha256(
        "my_feature", registry["my_feature"], evidence_repo
    )
    promotions = {
        "my_feature": {
            "feature": "my_feature",
            "causal_audit_artifact": audit_rel,
            "audited_execution_composite_sha256": "a" * 64,
            "promoted_by": "reviewer-name",
            "reviewed_implementation_sha256": impl_sha,
        }
    }
    report = check_feature_promotions(
        registry=registry, baseline=set(), repo_root=evidence_repo, promotions=promotions
    )
    assert report["passed"], report["violations"]


def test_promotion_does_not_survive_a_changed_implementation(evidence_repo: Path):
    """W3 -- old promotion evidence must not authorize changed feature code."""
    from scripts.check_feature_promotion import feature_implementation_sha256

    audit_rel = "audit/pass_07.md"
    (evidence_repo / "audit").mkdir(parents=True, exist_ok=True)
    (evidence_repo / audit_rel).write_bytes(b"cleared\n")

    registry = {
        "my_feature": _FDef(
            "my_feature",
            implementation="features.trackers.thing.T",
            tests=("tests/test_thing.py",),
        )
    }
    impl_sha = feature_implementation_sha256("my_feature", registry["my_feature"], evidence_repo)
    promotions = {
        "my_feature": {
            "feature": "my_feature",
            "causal_audit_artifact": audit_rel,
            "audited_execution_composite_sha256": "a" * 64,
            "promoted_by": "reviewer-name",
            "reviewed_implementation_sha256": impl_sha,
        }
    }
    assert check_feature_promotions(
        registry=registry, baseline=set(), repo_root=evidence_repo, promotions=promotions
    )["passed"]

    # The tracker is rewritten after promotion. The clearance must not follow it.
    (evidence_repo / "features" / "trackers" / "thing.py").write_bytes(
        b"class T:\n    def calculate(self):\n        return 1\n"
    )
    report = check_feature_promotions(
        registry=registry, baseline=set(), repo_root=evidence_repo, promotions=promotions
    )
    assert not report["passed"]
    assert "PROMOTION_RECORD_INCOMPLETE" in _codes(report)
    assert any("does not authorise changed feature code" in v["message"]
               for v in report["violations"])


def test_promotion_without_implementation_binding_is_refused(evidence_repo: Path):
    """A record that never says which code it reviewed is not composite-bound evidence."""
    audit_rel = "audit/pass_07.md"
    (evidence_repo / "audit").mkdir(parents=True, exist_ok=True)
    (evidence_repo / audit_rel).write_bytes(b"cleared\n")
    registry = {
        "my_feature": _FDef(
            "my_feature",
            implementation="features.trackers.thing.T",
            tests=("tests/test_thing.py",),
        )
    }
    promotions = {
        "my_feature": {
            "feature": "my_feature",
            "causal_audit_artifact": audit_rel,
            "audited_execution_composite_sha256": "a" * 64,
            "promoted_by": "x",
        }
    }
    report = check_feature_promotions(
        registry=registry, baseline=set(), repo_root=evidence_repo, promotions=promotions
    )
    assert not report["passed"]
    assert "PROMOTION_RECORD_INCOMPLETE" in _codes(report)


def test_incomplete_promotion_record_is_refused(evidence_repo: Path):
    """A record that names no audit artifact is not evidence of auditor clearance."""
    registry = {
        "my_feature": _FDef(
            "my_feature",
            implementation="features.trackers.thing.T",
            tests=("tests/test_thing.py",),
        )
    }
    promotions = {"my_feature": {"feature": "my_feature", "promoted_by": "x"}}
    report = check_feature_promotions(
        registry=registry, baseline=set(), repo_root=evidence_repo, promotions=promotions
    )
    assert not report["passed"]
    assert "PROMOTION_RECORD_INCOMPLETE" in _codes(report)


def test_promotion_record_naming_a_nonexistent_audit_is_refused(evidence_repo: Path):
    registry = {
        "my_feature": _FDef(
            "my_feature",
            implementation="features.trackers.thing.T",
            tests=("tests/test_thing.py",),
        )
    }
    promotions = {
        "my_feature": {
            "feature": "my_feature",
            "causal_audit_artifact": "audit/does_not_exist.md",
            "audited_execution_composite_sha256": "a" * 64,
            "promoted_by": "x",
        }
    }
    report = check_feature_promotions(
        registry=registry, baseline=set(), repo_root=evidence_repo, promotions=promotions
    )
    assert not report["passed"]
    assert "PROMOTION_RECORD_INCOMPLETE" in _codes(report)
