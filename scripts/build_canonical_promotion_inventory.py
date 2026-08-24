#!/usr/bin/env python3
"""Generate provider-grouped canonical promotion evidence inventory.

This is a mechanical bridge from the 693-alias parity matrix to promotion
records.  It intentionally records causal evidence as pending until the named
causal audit has cleared each provider group.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "scratch" / "feature_system_v2_full_migration_inventory.json"
PARITY = ROOT / "scratch" / "feature_system_v2_full_legacy_parity_matrix.json"
OUT = ROOT / "scratch" / "feature_system_v2_canonical_promotion_inventory.json"


CANONICAL_PROVIDER = {
    "features.trackers.ohlcv_delta.OHLCVDeltaTracker": "features.trackers.generic_ohlcv_delta.GenericOHLCVDeltaProvider",
    "features.trackers.price_levels.PriceLevelTracker": "features.trackers.generic_price_levels.GenericPriceLevelProvider",
    "features.trackers.median_center.MedianCenterTracker": "features.trackers.generic_median_center.GenericMedianCenterCompatibilityProvider",
    "features.trackers.velocity.ArrivalVelocityTracker": "features.trackers.generic_arrival.GenericArrivalVelocityProvider",
    "features.trackers.volume.ArrivalVolumeTracker": "features.trackers.generic_arrival.GenericArrivalVolumeProvider",
    "features.trackers.pullback.PullbackTracker": "features.trackers.generic_pullback.GenericPullbackProvider",
    "features.trackers.rolling_5m_productivity.Rolling5mProductivityTracker": "features.trackers.generic_rolling_productivity.GenericRollingProductivityProvider",
    "features.trackers.structural_regime_geometry.StructuralRegimeGeometryTracker": "features.trackers.generic_structural_geometry.GenericStructuralGeometryProvider",
    "features.trackers.range_position.RangePositionTracker": "features.trackers.generic_bar_geometry.GenericRangePositionProvider",
    "features.trackers.wick.WickTracker": "features.trackers.generic_bar_geometry.GenericWickImbalanceProvider",
    "": "features.trackers.generic_context.GenericContextProvider",
}

MERGED_CANONICAL_PROVIDER = {
    "range_atr": "features.trackers.generic_bar_geometry.GenericRangeATRProvider",
}


def implementation_hash(path: str) -> str:
    module = path.rsplit(".", 1)[0]
    target = ROOT.joinpath(*module.split(".")).with_suffix(".py")
    return hashlib.sha256(target.read_bytes()).hexdigest()


def parameter_schema(rows: list[dict[str, Any]]) -> list[str]:
    return sorted({key for row in rows for key in (row.get("parameters") or {})})


def main() -> int:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    parity = json.loads(PARITY.read_text(encoding="utf-8"))
    parity_by_alias = {row["legacy_alias"]: row for row in parity["aliases"]}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in inventory["features"]:
        canonical = row["canonical_feature"]
        # The range/ATR collision is one operation with coverage policy supplied
        # in parameters; provider grouping remains separate for audit evidence.
        if canonical == "range_atr":
            canonical = "range_atr"
        provider = MERGED_CANONICAL_PROVIDER.get(canonical, CANONICAL_PROVIDER[row["current_provider"]])
        grouped[(canonical, provider)].append(row)
    definitions = []
    for (canonical, provider), rows in sorted(grouped.items()):
        aliases = sorted(row["legacy_feature"] for row in rows)
        parity_rows = [parity_by_alias[alias] for alias in aliases]
        definitions.append({
            "canonical_name": canonical,
            "provider": provider,
            "provider_sha256": implementation_hash(provider),
            "families": sorted({row["semantic_equivalence_evidence"]["registry_metadata"]["family"] for row in rows}),
            "dtype": sorted({"float64" for _ in rows}),
            "parameter_schema": parameter_schema(rows),
            "input_availability_contracts": sorted({row["semantic_equivalence_evidence"]["registry_metadata"]["source_timeframe"] for row in rows}),
            "reset_policies": sorted({row["semantic_equivalence_evidence"]["registry_metadata"]["reset_policy"] for row in rows}),
            "null_policies": sorted({row["semantic_equivalence_evidence"]["registry_metadata"]["null_policy"] for row in rows}),
            "legacy_aliases": aliases,
            "parity_evidence": {"artifact": str(PARITY.relative_to(ROOT)).replace("\\", "/"), "passed": all(item["status"] == "PASS" for item in parity_rows), "alias_count": len(aliases)},
            "current_lifecycle_status": "provisional",
            "causal_evidence_status": "PENDING_NAMED_CAUSAL_AUDIT",
            "promotion_eligible": False,
        })
    groups: dict[str, list[str]] = defaultdict(list)
    for definition in definitions:
        provider = definition["provider"]
        # range_atr is the same completed-bar geometry group as range position;
        # its shared primitive does not create another causal-audit unit.
        if provider.endswith(".GenericRangeATRProvider"):
            provider = provider.removesuffix("GenericRangeATRProvider") + "GenericRangePositionProvider"
        groups[provider].append(definition["canonical_name"])
    payload = {
        "schema_version": 1,
        "legacy_alias_count": len(inventory["features"]),
        "canonical_definition_count_after_dedup": len({definition["canonical_name"] for definition in definitions}),
        "provider_audit_group_count": len(groups),
        "provider_audit_groups": [{"provider": provider, "definitions": sorted(names)} for provider, names in sorted(groups.items())],
        "definitions": definitions,
    }
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "definitions": payload["canonical_definition_count_after_dedup"], "provider_groups": payload["provider_audit_group_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
