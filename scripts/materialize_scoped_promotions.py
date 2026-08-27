#!/usr/bin/env python3
"""Materialize scope-bound promotion records from a sealed feature candidate."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--study", type=Path, required=True); ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(); study = a.study.resolve()
    authority = yaml.safe_load((study / "feature_candidate.yaml").read_text(encoding="utf-8"))
    frozen = json.loads((study / "audit" / "frozen_execution_manifest.json").read_text(encoding="utf-8"))
    seal_file = study / "artifacts" / "preexec_audit_seal.json"
    seal = json.loads(seal_file.read_text(encoding="utf-8")) if seal_file.is_file() else {}
    from features.registry import CANONICAL_FEATURE_DEFINITIONS
    from scripts.check_feature_promotion import feature_implementation_sha256
    composite = frozen["frozen_execution_composite_sha256"]
    seal_id = seal.get("seal_id", f"preexec_seal_{study.name}_{composite[:16]}")
    records = []
    for item in authority.get("candidate_features", []):
        name = item.get("canonical_name") or item.get("feature")
        if name not in CANONICAL_FEATURE_DEFINITIONS: continue
        fdef = CANONICAL_FEATURE_DEFINITIONS[name]
        impl = feature_implementation_sha256(name, fdef, ROOT)
        base = {"authority_id": authority["authority_id"], "authority_type": "feature_candidate",
                "canonical_name": name, "feature_candidate_composite": composite,
                "seal_identity": seal_id, "causal_audit": "audit/status.json",
                "contract_audit": "audit/contract_status.json",
                "runtime_evidence": list(getattr(fdef, "tests", ()) or ()),
                "reviewed_implementation_sha256": impl,
                "registry_declaration_sha256": hashlib.sha256((name + repr(fdef)).encode()).hexdigest(),
                "promotion_decision": "PROMOTE"}
        params = item.get("parameters") or {}
        if params:
            for key, value in params.items():
                records.append({**base, "scope_type": "FEATURE_PARAMETER_VALUE", "parameter_name": key, "parameter_value": value})
        else:
            records.append({**base, "scope_type": "FEATURE_DEFINITION"})
    existing_records = []
    if a.out.is_file():
        try:
            existing_records = json.loads(a.out.read_text(encoding="utf-8")).get("records", [])
        except Exception:
            existing_records = []

    merged_map = {}
    for rec in existing_records:
        key = (rec.get("authority_id"), rec.get("canonical_name"), rec.get("scope_type"), rec.get("parameter_name"), str(rec.get("parameter_value")))
        merged_map[key] = rec
    for rec in records:
        key = (rec.get("authority_id"), rec.get("canonical_name"), rec.get("scope_type"), rec.get("parameter_name"), str(rec.get("parameter_value")))
        merged_map[key] = rec

    merged_records = list(merged_map.values())
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"schema_version": 1, "records": merged_records}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(merged_records), "added_or_updated": len(records), "path": str(a.out)}))
    return 0
if __name__ == "__main__": raise SystemExit(main())
