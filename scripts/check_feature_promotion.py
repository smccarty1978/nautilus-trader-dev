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
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BASELINE_PATH = REPO_ROOT / "features" / "feature_lifecycle_baseline.json"

# Durable pin for the grandfather set (RT-4).
#
# The previous guard compared `baseline - registry`, which flags a *stale* baseline name
# but is blind to the actual attack: adding a brand-new feature to BOTH features/registry.py
# and the baseline file, which granted it verified status with no evidence at all. The
# escape hatch was the exploit.
#
# The baseline file now carries two lists. `pinned_original_verified` is the immutable
# historical set, hashed here in source. `baseline_verified` is the ACTIVE set and must be
# a SUBSET of it -- so names may be removed as features earn real evidence, but never
# added. Growing the pinned set requires editing this constant, which lives in the
# governance closure: it moves the execution composite, invalidates seals and forces
# re-audit. That is the "explicit governed baseline migration".
BASELINE_PINNED_SHA256 = "434666ef18090f2eb4cc6a667aed8dd148d18fe7aeea5023f4dfae0f94a0c1d3"


def _name_set_hash(names) -> str:
    return hashlib.sha256(
        json.dumps(sorted(names), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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
    pinned = data.get("pinned_original_verified")
    if not isinstance(pinned, list):
        raise FeaturePromotionError(
            f"PROMOTION_BASELINE_MALFORMED: {p} has no 'pinned_original_verified' list. "
            f"Without the pinned historical set the active set cannot be shown not to have "
            f"grown."
        )

    # The pinned historical set must match the constant in this file.
    actual_pin = _name_set_hash(pinned)
    if actual_pin != BASELINE_PINNED_SHA256:
        raise FeaturePromotionError(
            f"PROMOTION_BASELINE_TAMPERED: {p} pinned_original_verified hashes to "
            f"{actual_pin[:12]}... but scripts/check_feature_promotion.py pins "
            f"{BASELINE_PINNED_SHA256[:12]}.... The grandfather set was edited outside a "
            f"governed migration."
        )

    # The active set may shrink, never grow.
    added = sorted(set(names) - set(pinned))
    if added:
        raise FeaturePromotionError(
            f"PROMOTION_BASELINE_EXTENDED: {added} appear in the active grandfather set but "
            f"not in the pinned historical set. The baseline records features that already "
            f"carried 'verified'; it is not a place to grandfather new ones. Leave the "
            f"feature 'provisional' and record real promotion evidence instead."
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


def feature_implementation_sha256(name: str, fdef: Any, repo_root: Path) -> Optional[str]:
    """Hash of the implementation module actually backing this feature.

    This is what a promotion is a statement *about*. Recording only the execution
    composite is too coarse in one direction and too brittle in the other: the composite
    moves whenever any governance file changes, yet says nothing specific about whether
    this feature's own code is the code that was reviewed.
    """
    impl = getattr(fdef, "implementation", "") or ""
    if not impl:
        return None
    mod = impl.rsplit(".", 1)[0]
    p = repo_root.joinpath(*mod.split(".")).with_suffix(".py")
    if not p.exists():
        p = repo_root.joinpath(*mod.split(".")) / "__init__.py"
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _promotion_record_is_complete(
    rec: Dict[str, Any],
    repo_root: Path,
    current_impl_sha256: Optional[str] = None,
) -> Optional[str]:
    """Returns a reason string when a promotion record is not usable evidence.

    W3: promotion evidence must identify the exact implementation that was reviewed, and
    must stop authorising it once that implementation changes. Otherwise a feature is
    promoted once and the clearance silently follows arbitrary later rewrites of its
    tracker -- the wick tracker's own body changed twice during this remediation.
    """
    audit_ref = rec.get("causal_audit_artifact")
    if not audit_ref:
        return "record names no 'causal_audit_artifact'"
    if not (repo_root / audit_ref).is_file():
        return f"named causal audit artifact {audit_ref!r} does not exist"
    if not rec.get("audited_execution_composite_sha256"):
        return "record names no 'audited_execution_composite_sha256'"
    if not rec.get("promoted_by"):
        return "record names no 'promoted_by'"

    reviewed_impl = rec.get("reviewed_implementation_sha256")
    if not reviewed_impl:
        return (
            "record names no 'reviewed_implementation_sha256'; promotion evidence must "
            "identify the exact feature implementation that was reviewed"
        )
    if current_impl_sha256 is None:
        return "the feature's implementation module could not be resolved to hash it"
    if reviewed_impl != current_impl_sha256:
        return (
            f"promotion reviewed implementation {reviewed_impl[:12]}... but the feature's "
            f"implementation is now {current_impl_sha256[:12]}.... Old promotion evidence "
            f"does not authorise changed feature code; re-review and re-record"
        )
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
            reason = _promotion_record_is_complete(
                rec, repo_root, feature_implementation_sha256(name, fdef, repo_root)
            )
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
    pinned: Optional[Set[str]] = None,
) -> None:
    """The grandfather set may shrink, never grow (RT-4).

    Growth is measured against the PINNED HISTORICAL set, not against the registry. The
    earlier version compared `baseline - registry`, which only ever caught a stale name;
    a new feature added to both the registry and the baseline sailed through, because the
    difference it computed was empty precisely in the attack case.
    """
    if pinned is None:
        p = BASELINE_PATH
        if not p.is_file():
            raise FeaturePromotionError(f"PROMOTION_BASELINE_MISSING: {p}")
        pinned = set(json.loads(p.read_text(encoding="utf-8")).get("pinned_original_verified", []))
    if baseline is None:
        baseline = load_baseline()

    added = sorted(set(baseline) - set(pinned))
    if added:
        raise FeaturePromotionError(
            f"PROMOTION_BASELINE_EXTENDED: {added} are not in the pinned historical "
            f"grandfather set. A new feature cannot become grandfathered by editing the "
            f"baseline file."
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
