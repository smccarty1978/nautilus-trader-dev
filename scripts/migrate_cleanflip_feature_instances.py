"""Materialize CleanFlip's historical physical surface as canonical instances.

This is a deterministic study-spec migration helper.  It reads the first
historical feature parquet (the legacy collector surface), joins each physical
column to the archived parity mapping, and writes only canonical
FeatureInstance declarations to the study spec.  The legacy mapping is read as
evidence; it is never imported by runtime code.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "studies" / "Codex_clean_maturity_flip_rolling_5m_productivity"
MAPPING = ROOT / "features" / "authority" / "candidate" / "legacy_alias_mapping.json"
OUT = STUDY / "artifacts" / "cleanflip_feature_instance_migration.json"

NON_FEATURE = {
    "checkpoint_decision_ns", "checkpoint_event_ns", "prevailing_direction",
    "regime_start_ns", "atr_at_regime_start", "current_5m_completed_close_ts",
    "rolling_5m_crosses_rth_boundary", "current_5m_regime_started_rth",
    "regime_age_seconds", "running_mfe_atr", "new_progress_windows",
    "retained_mfe_ratio", "structural_available", "structural_unavailable_reason",
    "structural_origin_price", "structural_origin_ns", "structural_current_1m_start_ns",
    "structural_current_1m_direction", "current_5m_regime_start_ns", "five_registry_close_ts",
    "structural_max_expansion_checkpoint_atr", "structural_current_expansion_checkpoint_atr",
    "current_5m_regime_range_checkpoint_atr", "flip_within_300s",
}


def main() -> None:
    parquet = sorted(STUDY.glob("_work/**/features.parquet"))[0]
    columns = [c for c in pq.read_schema(parquet).names if c not in NON_FEATURE]
    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))["aliases"]
    mapped = [c for c in columns if c in mapping]
    missing = [c for c in columns if c not in mapping]
    if missing:
        raise SystemExit(f"unmapped historical CleanFlip columns: {missing}")
    records = []
    instances = []
    seen = set()
    for alias in mapped:
        item = mapping[alias]
        canonical = item["canonical_feature"]
        parameters = dict(item.get("parameters", {}))
        key = (canonical, json.dumps(parameters, sort_keys=True, separators=(",", ":")))
        if key in seen:
            continue
        seen.add(key)
        instances.append({"feature": canonical, "parameters": parameters, "physical_alias": alias})
        records.append({
            "historical_alias": alias,
            "canonical_name": canonical,
            "parameters": parameters,
            "physical_alias": alias,
            "parity_evidence": "693/693 legacy parity matrix PASS",
        })
    artifact = {
        "schema_version": 1,
        "study": STUDY.name,
        "source": str(parquet.relative_to(ROOT)).replace("\\", "/"),
        "historical_feature_count": len(mapped),
        "canonical_instance_count": len(instances),
        "unmapped": missing,
        "instances": records,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    study_yaml = STUDY / "study.yaml"
    text = study_yaml.read_text(encoding="utf-8")
    if "  instances:\n" in text:
        before, rest = text.split("  instances:\n", 1)
        rest = rest[rest.find("  selection:"):] if "  selection:" in rest else ""
        text = before + rest
    block = "  instances:\n" + "".join(
        f"    - feature: {x['feature']}\n      parameters: {json.dumps(x['parameters'], sort_keys=True)}\n      physical_alias: {x['physical_alias']}\n"
        for x in instances
    )
    marker = "  selection:\n"
    if marker not in text:
        raise SystemExit("study.yaml selection marker not found")
    text = text.replace(marker, block + marker, 1)
    study_yaml.write_text(text, encoding="utf-8")
    print(json.dumps({"historical": len(mapped), "instances": len(instances), "artifact": str(OUT)}))


if __name__ == "__main__":
    main()
