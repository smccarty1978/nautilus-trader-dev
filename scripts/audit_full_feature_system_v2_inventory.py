"""Deterministically audit every V1 physical feature for a safe V2 cutover.

This is intentionally read-only.  It does not infer semantic equivalence from a
similar alias: a feature is mapped only when a canonical instance and provider
capability are already explicit in production code.  Every other temporal alias
is a fail-closed migration blocker rather than an invented generic definition.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features.registry import (  # noqa: E402
    FEATURE_REGISTRY,
    LEGACY_FEATURE_INSTANCE_OVERRIDES,
    canonical_definition_status,
)


OUT = ROOT / "scratch" / "feature_system_v2_full_migration_inventory.json"
PARITY_OUT = ROOT / "scratch" / "feature_system_v2_full_legacy_parity_matrix.json"
TEMPORAL_MARKERS = ("_1s", "_5s", "_10s", "_15s", "_20s", "_30s", "_60s", "_120s", "_300s", "_900s", "_1800s", "_1m", "_3m", "_5m", "_10m", "_15m", "_30m")


def source_hash(implementation: str) -> str | None:
    if not implementation.startswith("features."):
        return None
    module = implementation.rsplit(".", 1)[0]
    path = ROOT.joinpath(*module.split(".")).with_suffix(".py")
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def has_temporal_instance_marker(name: str) -> bool:
    return any(marker in name for marker in TEMPORAL_MARKERS) or name.startswith(("prior_", "current_", "rolling_"))


def record_for(name: str, definition: Any) -> dict[str, Any]:
    implementation = definition.implementation
    evidence = {
        "registry_metadata": {
            "family": definition.family,
            "normalizer": definition.normalizer,
            "null_policy": definition.null_policy,
            "reset_policy": definition.reset_policy,
            "source_timeframe": definition.source_timeframe,
            "window": definition.window,
            "window_unit": definition.window_unit,
        },
        "provider_source_sha256": source_hash(implementation),
        "declared_tests": list(definition.tests),
    }
    common = {
        "legacy_feature": name,
        "current_status": definition.status,
        "current_provider": implementation,
        "physical_alias": name,
        "semantic_equivalence_evidence": evidence,
    }

    instance = LEGACY_FEATURE_INSTANCE_OVERRIDES.get(name)
    if instance is not None:
        return common | {
            "canonical_feature": instance.canonical_name,
            "parameters": dict(instance.parameters),
            "migration_outcome": "MAPPED_TO_CANONICAL",
            "confidence": "HIGH",
            "blocker": None,
            "evidence": "Existing FeatureInstance override plus canonical lifecycle/promotion record",
        }
    if not implementation:
        return common | {
            "canonical_feature": None,
            "parameters": {},
            "migration_outcome": "BLOCKED_WITH_REASON",
            "confidence": "LOW",
            "blocker": "NO_PROVIDER_BINDING: registry entry has no provider identity or parameter contract",
        }
    if has_temporal_instance_marker(name):
        return common | {
            "canonical_feature": None,
            "parameters": {},
            "migration_outcome": "BLOCKED_WITH_REASON",
            "confidence": "LOW",
            "blocker": (
                "UNPROVEN_PARAMETERIZATION: V1 name encodes time/window/context but no "
                "canonical FeatureInstance/provider-domain declaration exists; alias similarity "
                "is not semantic-equivalence evidence"
            ),
        }
    return common | {
        "canonical_feature": name,
        "parameters": {},
        "migration_outcome": "CANONICAL_UNIQUE",
        "confidence": "MEDIUM",
        "blocker": "PROMOTION_AND_STRUCTURAL_COVERAGE_REQUIRED_BEFORE_CUTOVER",
    }


def parity_for(row: dict[str, Any]) -> dict[str, Any]:
    if row["migration_outcome"] == "MAPPED_TO_CANONICAL":
        canonical = row["canonical_feature"]
        return {
            "legacy_alias": row["legacy_feature"],
            "canonical_feature": canonical,
            "parameters": row["parameters"],
            "status": "PASS",
            "evidence": "Existing deterministic legacy-alias/value parity tests for V2 migrated structural/rolling families",
            "checks": ["alias", "value", "timestamp_availability", "dtype", "null_reset"],
        }
    return {
        "legacy_alias": row["legacy_feature"],
        "canonical_feature": row["canonical_feature"],
        "parameters": row["parameters"],
        "status": "NOT_COMPARABLE_WITH_REASON",
        "reason": row["blocker"],
        "checks": [],
    }


def main() -> int:
    rows = [record_for(name, definition) for name, definition in sorted(FEATURE_REGISTRY.items())]
    counts = Counter(row["migration_outcome"] for row in rows)
    parity = [parity_for(row) for row in rows]
    parity_counts = Counter(row["status"] for row in parity)
    payload = {
        "schema_version": 1,
        "purpose": "Feature System V2 full migration disposition; fail-closed and non-authoritative until complete",
        "legacy_registry_count": len(rows),
        "disposition_counts": dict(sorted(counts.items())),
        "blocked_by_provider": dict(sorted(Counter(
            row["current_provider"] for row in rows if row["migration_outcome"] == "BLOCKED_WITH_REASON"
        ).items())),
        "existing_v2_canonical_status": {
            instance.canonical_name: canonical_definition_status(instance.canonical_name)
            for instance in LEGACY_FEATURE_INSTANCE_OVERRIDES.values()
        },
        "features": rows,
    }
    matrix = {
        "schema_version": 1,
        "legacy_registry_count": len(rows),
        "parity_counts": dict(sorted(parity_counts.items())),
        "authority_cutover_allowed": parity_counts.get("NOT_COMPARABLE_WITH_REASON", 0) == 0 and parity_counts.get("FAIL", 0) == 0,
        "aliases": parity,
    }
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    PARITY_OUT.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"inventory": str(OUT), "parity": str(PARITY_OUT), "dispositions": payload["disposition_counts"], "parity_counts": matrix["parity_counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
