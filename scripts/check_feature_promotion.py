#!/usr/bin/env python3
"""Feature lifecycle promotion validator (Finding D).

``latest_1m_wick_imbalance`` was registered with ``status='verified'`` in the same change
that implemented it. ``FEATURE_REGISTRY_CONTRACT.md`` section 1 already required formula
review, warmup review, prefix-invariance testing, parity comparison and look-ahead
clearance before a feature may be called verified -- but that requirement lived only in
prose, so the registry entry could assert the outcome of a process that never ran.

The lifecycle this enforces:

    NEW FEATURE -> provisional -> deterministic evidence -> explicit promotion -> verified

The evidence bar is deliberately small and fully deterministic. A feature promoted to
``verified`` must have:

1. an ``implementation`` that resolves to a module that actually exists;
2. at least one declared test file that exists **and names the feature**. A test file
   that never mentions the feature is not evidence about that feature;
3. an explicit entry in ``features/feature_lifecycle_promotions.json`` naming the causal-audit artifact
   that cleared it.

Rule 3 is what makes the lifecycle real rather than advisory. The wick feature satisfies
rules 1 and 2 -- ``tests/test_feature_library.py`` does exercise the tracker by name --
yet it was still promoted in the same change that implemented it, before any look-ahead
audit had seen it. ``FEATURE_REGISTRY_CONTRACT.md`` s1 requires auditor clearance for
verified status, and auditor clearance is not something a registry entry can assert about
itself. It cannot be inferred from the tree either, so it is required as an explicit,
evidence-backed promotion step and fails closed in its absence.

Grandfathering
--------------
502 features already carried ``verified`` when this validator was written, and 398 of
them would fail rule 2. Retro-demoting them is a mass change unrelated to the confirmed
finding, which is about *new* features self-granting status. ``features/feature_lifecycle_baseline.json``
records that pre-existing set explicitly. Names may be removed from it (as evidence is
added); adding a name is refused, so the baseline cannot be used to launder a new feature.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BASELINE_PATH = REPO_ROOT / "features" / "feature_lifecycle_baseline.json"
PROMOTIONS_PATH = REPO_ROOT / "features" / "feature_lifecycle_promotions.json"

VALID_STATUSES = ("archived", "provisional", "verified", "deprecated")


class FeaturePromotionError(RuntimeError):
    """Raised when a feature claims a lifecycle status its evidence does not support."""


def load_baseline(baseline_path: Optional[Path] = None) -> Set[str]:
    """Loads the grandfathered verified set, failing closed if it is unreadable."""
    p = baseline_path or BASELINE_PATH
    if not p.is_file():
        raise FeaturePromotionError(
            f"PROMOTION_BASELINE_MISSING: {p} is absent. Without it every verified feature "
            f"would have to be re-evidenced at once; an absent baseline is not an empty one."
        )
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as err:
        raise FeaturePromotionError(f"PROMOTION_BASELINE_MALFORMED: {p}: {err}")
    names = data.get("baseline_verified")
    if not isinstance(names, list):
        raise FeaturePromotionError(
            f"PROMOTION_BASELINE_MALFORMED: {p} has no 'baseline_verified' list"
        )
    return set(names)


def load_promotions(promotions_path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Loads explicit promotion records keyed by feature name.

    A missing file means "no feature has been explicitly promoted yet", which is a
    legitimate state -- unlike a missing baseline, it denies rather than grants.
    """
    p = promotions_path or PROMOTIONS_PATH
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as err:
        raise FeaturePromotionError(f"PROMOTIONS_MALFORMED: {p}: {err}")
    records = data.get("promotions")
    if not isinstance(records, list):
        raise FeaturePromotionError(f"PROMOTIONS_MALFORMED: {p} has no 'promotions' list")

    out: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        if not isinstance(rec, dict) or not rec.get("feature"):
            raise FeaturePromotionError(f"PROMOTIONS_MALFORMED: {p} contains a record with no 'feature'")
        out[rec["feature"]] = rec
    return out


def _promotion_record_is_complete(rec: Dict[str, Any], repo_root: Path) -> Optional[str]:
    """Returns a reason string when a promotion record is not usable evidence."""
    audit_ref = rec.get("causal_audit_artifact")
    if not audit_ref:
        return "record names no 'causal_audit_artifact'"
    if not (repo_root / audit_ref).is_file():
        return f"named causal audit artifact {audit_ref!r} does not exist"
    if not rec.get("audited_execution_composite_sha256"):
        return "record names no 'audited_execution_composite_sha256'"
    if not rec.get("promoted_by"):
        return "record names no 'promoted_by'"
    return None


def _implementation_module_exists(implementation: str, repo_root: Path) -> bool:
    if not implementation:
        return False
    mod = implementation.rsplit(".", 1)[0]
    return (
        repo_root.joinpath(*mod.split(".")).with_suffix(".py").exists()
        or (repo_root.joinpath(*mod.split(".")) / "__init__.py").exists()
    )


def evidence_for_feature(name: str, fdef: Any, repo_root: Path) -> Dict[str, Any]:
    """Collects the deterministic evidence backing a promotion claim."""
    impl = getattr(fdef, "implementation", "") or ""
    tests = list(getattr(fdef, "tests", ()) or ())

    existing_tests = [t for t in tests if (repo_root / t).is_file()]
    naming_tests = []
    for t in existing_tests:
        try:
            if name in (repo_root / t).read_text(encoding="utf-8", errors="replace"):
                naming_tests.append(t)
        except OSError:
            continue

    return {
        "implementation": impl,
        "implementation_resolves": _implementation_module_exists(impl, repo_root),
        "declared_tests": tests,
        "existing_tests": existing_tests,
        "tests_naming_feature": naming_tests,
    }


def check_feature_promotions(
    registry: Optional[Dict[str, Any]] = None,
    baseline: Optional[Set[str]] = None,
    repo_root: Optional[Path] = None,
    promotions: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Validates every verified feature that is not grandfathered."""
    if repo_root is None:
        repo_root = REPO_ROOT
    if registry is None:
        from features.registry import FEATURE_REGISTRY as registry  # noqa: N806
    if baseline is None:
        baseline = load_baseline()
    if promotions is None:
        promotions = load_promotions()

    violations: List[Dict[str, Any]] = []
    checked: List[str] = []
    evidence: Dict[str, Any] = {}

    for name, fdef in sorted(registry.items()):
        status = getattr(fdef, "status", None)
        if status not in VALID_STATUSES:
            violations.append({
                "feature": name,
                "code": "FEATURE_STATUS_INVALID",
                "message": f"'{name}' declares unknown status {status!r}; valid: {list(VALID_STATUSES)}",
            })
            continue
        if status != "verified" or name in baseline:
            continue

        checked.append(name)
        ev = evidence_for_feature(name, fdef, repo_root)
        evidence[name] = ev

        if not ev["implementation_resolves"]:
            violations.append({
                "feature": name,
                "code": "PROMOTION_IMPLEMENTATION_UNRESOLVED",
                "message": f"'{name}' is verified but implementation {ev['implementation']!r} "
                           f"does not resolve to a module on disk",
            })
        if not ev["declared_tests"]:
            violations.append({
                "feature": name,
                "code": "PROMOTION_EVIDENCE_ABSENT",
                "message": f"'{name}' is verified but declares no tests. A registry entry may "
                           f"not assert the outcome of a validation that left no artifact.",
            })
        elif not ev["tests_naming_feature"]:
            violations.append({
                "feature": name,
                "code": "PROMOTION_EVIDENCE_UNBOUND",
                "message": f"'{name}' is verified and declares tests {ev['declared_tests']}, but "
                           f"none of them mention '{name}'. A test that never names the feature "
                           f"is not evidence about that feature.",
            })

        # Auditor clearance cannot be derived from the tree, so it is required explicitly.
        rec = promotions.get(name)
        ev["promotion_record"] = rec
        if rec is None:
            violations.append({
                "feature": name,
                "code": "PROMOTION_RECORD_ABSENT",
                "message": f"'{name}' is verified but has no entry in features/feature_lifecycle_promotions.json. "
                           f"Verified status requires look-ahead auditor clearance "
                           f"(FEATURE_REGISTRY_CONTRACT.md s1), which a registry entry cannot "
                           f"assert about itself. Leave the feature 'provisional' until an "
                           f"evidence-backed promotion is recorded.",
            })
        else:
            reason = _promotion_record_is_complete(rec, repo_root)
            if reason:
                violations.append({
                    "feature": name,
                    "code": "PROMOTION_RECORD_INCOMPLETE",
                    "message": f"'{name}' promotion record is not usable evidence: {reason}",
                })

    return {
        "passed": not violations,
        "baseline_size": len(baseline),
        "promotion_records": sorted(promotions),
        "features_requiring_evidence": checked,
        "violations": violations,
        "evidence": evidence,
    }


def assert_feature_promotions(**kwargs) -> Dict[str, Any]:
    """Fail-closed wrapper used by the preflight gate."""
    report = check_feature_promotions(**kwargs)
    if not report["passed"]:
        detail = "; ".join(f"[{v['code']}] {v['message']}" for v in report["violations"])
        raise FeaturePromotionError(f"FEATURE_PROMOTION_UNSUPPORTED: {detail}")
    return report


def assert_baseline_not_extended(
    registry: Optional[Dict[str, Any]] = None,
    baseline: Optional[Set[str]] = None,
) -> None:
    """The grandfather list may shrink, never grow.

    Otherwise the escape hatch becomes the exploit: adding a new feature's name to the
    baseline would grant it verified status with no evidence at all.
    """
    if registry is None:
        from features.registry import FEATURE_REGISTRY as registry  # noqa: N806
    if baseline is None:
        baseline = load_baseline()
    unknown = sorted(baseline - set(registry))
    if unknown:
        raise FeaturePromotionError(
            f"PROMOTION_BASELINE_EXTENDED: {unknown} appear in the grandfather baseline but not "
            f"in the registry. The baseline records features that already existed; it is not a "
            f"place to pre-authorise new ones."
        )


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate feature lifecycle promotions")
    ap.add_argument("--json", help="Write the promotion report to this path")
    args = ap.parse_args()

    report = check_feature_promotions()
    try:
        assert_baseline_not_extended()
    except FeaturePromotionError as err:
        report["passed"] = False
        report["violations"].append({"feature": None, "code": "PROMOTION_BASELINE_EXTENDED",
                                     "message": str(err)})

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 60)
    print(f"FEATURE PROMOTION VALIDATION: {'PASS' if report['passed'] else 'BLOCKED'}")
    print(f"Grandfathered baseline:      {report['baseline_size']}")
    print(f"Requiring fresh evidence:    {len(report['features_requiring_evidence'])}")
    for v in report["violations"]:
        print(f"  [{v['code']}] {v['message']}")
    print("=" * 60)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
