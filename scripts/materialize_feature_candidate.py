#!/usr/bin/env python3
"""Materialize the final inactive Feature System V2 candidate bundle."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
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
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--scoped-records", type=Path)
    args = ap.parse_args()
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
        provider = rows[0]["provider"]
        provider_mod = provider.rsplit(".", 1)[0]
        provider_path = ROOT.joinpath(*provider_mod.split(".")).with_suffix(".py")
        provider_sha = hashlib.sha256(provider_path.read_bytes()).hexdigest() if provider_path.is_file() else rows[0]["provider_sha256"]
        definitions.append({
            "canonical_name": name,
            "family": sorted({family for row in rows for family in row["families"]}),
            "dtype": "float64",
            "provider": provider,
            "provider_sha256": provider_sha,
            "parameter_schema": sorted({key for row in rows for key in row["parameter_schema"]}),
            "input_availability_contracts": sorted({value for row in rows for value in row["input_availability_contracts"]}),
            "reset_policies": sorted({value for row in rows for value in row["reset_policies"]}),
            "null_policies": sorted({value for row in rows for value in row["null_policies"]}),
            "legacy_alias_count": len(aliases),
            "status": "verified",
        })
    # Include newly declared canonical provisional definitions in the same
    # generated candidate inventory.  They remain provisional until scoped
    # promotion evidence is supplied.
    from features.registry import CANONICAL_FEATURE_DEFINITIONS
    present = {d["canonical_name"] for d in definitions}
    for name, fdef in sorted(CANONICAL_FEATURE_DEFINITIONS.items()):
        if name in present or getattr(fdef, "status", "verified") == "verified":
            continue
        mod = str(getattr(fdef, "implementation", "")).rsplit(".", 1)[0]
        provider_path = ROOT.joinpath(*mod.split(".")).with_suffix(".py")
        definitions.append({"canonical_name": name, "family": [getattr(fdef, "family", "")],
                            "dtype": getattr(fdef, "dtype", "float64"),
                            "provider": getattr(fdef, "implementation", ""),
                            "provider_sha256": hashlib.sha256(provider_path.read_bytes()).hexdigest() if provider_path.is_file() else "",
                            "parameter_schema": list(getattr(fdef, "parameter_schema", ()) or ()),
                            "input_availability_contracts": [getattr(fdef, "source_timeframe", "")],
                            "reset_policies": [getattr(fdef, "reset_policy", "none")],
                            "null_policies": [getattr(fdef, "null_policy", "allow")],
                            "legacy_alias_count": 0, "status": "provisional"})
    definitions.sort(key=lambda x: x["canonical_name"])
    alias_map = {row["legacy_feature"]: {"canonical_feature": row["canonical_feature"], "parameters": row["parameters"]}
                 for row in inventory["features"]}
    facts = {"schema_version": 1, "kind": "immutable_promotion_facts",
             "parity_artifact": "scratch/feature_system_v2_full_legacy_parity_matrix.json",
             "definitions": [{"canonical_name": item["canonical_name"], "provider": item["provider"],
                              "provider_sha256": item["provider_sha256"], "parameter_schema": item["parameter_schema"],
                              "lifecycle_schema_version": 1,
                              "lifecycle_status": "verified", "parity_passed_alias_count": item["legacy_alias_count"],
                              "parity_evidence": (next((row["parity_evidence"] for row in by_name[item["canonical_name"]]), {"passed": False, "artifact": ""}) if item["canonical_name"] in by_name else {"passed": False, "artifact": ""}),
                              # Evidence facts are immutable inputs.  Final preflight
                              # and audit authorization are deliberately external to
                              # this bundle so their creation cannot stale the freeze.
                              "structural_test_evidence": list(STRUCTURAL_TESTS) if item["canonical_name"] in by_name else list(getattr(CANONICAL_FEATURE_DEFINITIONS.get(item["canonical_name"]), "tests", ()) or ()),
                              "input_availability_contracts": item["input_availability_contracts"],
                              "reset_policies": item["reset_policies"],
                              "null_policies": item["null_policies"]}
                             for item in definitions]}
    for fact, definition in zip(facts["definitions"], definitions):
        if definition.get("status") == "provisional":
            fact["lifecycle_status"] = "provisional"
    if args.scoped_records and args.scoped_records.is_file():
        scoped = json.loads(args.scoped_records.read_text(encoding="utf-8")).get("records", [])
        by_scope = {(r.get("canonical_name") or r.get("canonical_feature"), r.get("scope_type")): r for r in scoped if r.get("promotion_decision") == "PROMOTE"}
        for item in definitions:
            rec = by_scope.get((item["canonical_name"], "FEATURE_DEFINITION"))
            if rec:
                item["status"] = "verified"
        for fact in facts["definitions"]:
            rec = by_scope.get((fact["canonical_name"], "FEATURE_DEFINITION"))
            if rec:
                fact["lifecycle_status"] = "verified"
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
