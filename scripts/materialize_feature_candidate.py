#!/usr/bin/env python3
"""Materialize the final inactive Feature System V2 candidate bundle."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "scratch" / "feature_system_v2_full_migration_inventory.json"
PARITY = ROOT / "scratch" / "feature_system_v2_full_legacy_parity_matrix.json"
PROMOTION = ROOT / "scratch" / "feature_system_v2_canonical_promotion_inventory.json"
OUT = ROOT / "features" / "authority" / "candidate"
STRUCTURAL_TESTS = (
    "features/tests/test_feature_system_v2.py",
    "features/tests/test_generic_provider_parameterization.py",
)


def _write(name: str, body: object) -> str:
    target = OUT / name
    encoded = json.dumps(body, indent=2, sort_keys=True) + "\n"
    target.write_text(encoded, encoding="utf-8")
    return hashlib.sha256(target.read_bytes()).hexdigest()


def main() -> int:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    parity = json.loads(PARITY.read_text(encoding="utf-8"))
    promotion = json.loads(PROMOTION.read_text(encoding="utf-8"))
    if parity.get("parity_counts", {}).get("PASS") != 693:
        raise SystemExit("CANDIDATE_REQUIRES_COMPLETE_LEGACY_PARITY")
    OUT.mkdir(parents=True, exist_ok=True)
    by_name: dict[str, list[dict]] = defaultdict(list)
    for row in promotion["definitions"]:
        by_name[row["canonical_name"]].append(row)
    definitions = []
    for name, rows in sorted(by_name.items()):
        aliases = sorted({alias for row in rows for alias in row["legacy_aliases"]})
        definitions.append({
            "canonical_name": name,
            "family": sorted({family for row in rows for family in row["families"]}),
            "dtype": "float64",
            "provider": rows[0]["provider"],
            "provider_sha256": rows[0]["provider_sha256"],
            "parameter_schema": sorted({key for row in rows for key in row["parameter_schema"]}),
            "input_availability_contracts": sorted({value for row in rows for value in row["input_availability_contracts"]}),
            "reset_policies": sorted({value for row in rows for value in row["reset_policies"]}),
            "null_policies": sorted({value for row in rows for value in row["null_policies"]}),
            "legacy_alias_count": len(aliases),
            "status": "verified",
        })
    alias_map = {row["legacy_feature"]: {"canonical_feature": row["canonical_feature"], "parameters": row["parameters"]}
                 for row in inventory["features"]}
    facts = {"schema_version": 1, "kind": "immutable_promotion_facts",
             "parity_artifact": "scratch/feature_system_v2_full_legacy_parity_matrix.json",
             "definitions": [{"canonical_name": item["canonical_name"], "provider": item["provider"],
                              "provider_sha256": item["provider_sha256"], "parameter_schema": item["parameter_schema"],
                              "lifecycle_schema_version": 1,
                              "lifecycle_status": "verified", "parity_passed_alias_count": item["legacy_alias_count"],
                              "parity_evidence": next(
                                  row["parity_evidence"] for row in by_name[item["canonical_name"]]
                              ),
                              # Evidence facts are immutable inputs.  Final preflight
                              # and audit authorization are deliberately external to
                              # this bundle so their creation cannot stale the freeze.
                              "structural_test_evidence": list(STRUCTURAL_TESTS),
                              "input_availability_contracts": item["input_availability_contracts"],
                              "reset_policies": item["reset_policies"],
                              "null_policies": item["null_policies"]}
                             for item in definitions]}
    hashes = {
        "canonical_registry.json": _write("canonical_registry.json", {"schema_version": 1, "definitions": definitions}),
        "legacy_alias_mapping.json": _write("legacy_alias_mapping.json", {"schema_version": 1, "aliases": alias_map}),
        "promotion_facts.json": _write("promotion_facts.json", facts),
    }
    _write("manifest.json", {"schema_version": 1, "canonical_definition_count": len(definitions),
                              "legacy_alias_count": len(alias_map), "file_sha256_map": hashes,
                              "bundle_composite_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()})
    print(json.dumps({"candidate": str(OUT), "definitions": len(definitions), "aliases": len(alias_map), "hashes": hashes}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
