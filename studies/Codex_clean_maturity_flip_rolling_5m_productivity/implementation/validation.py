"""Fail-closed validation, result sealing, and promotion for the frozen study."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from .contracts import DIRECTIONS, MODELS, REQUIRED_MANIFESTS, TERMINAL_LABELS, expected_directional_cells, expected_pooled_cells
from .phase0 import authenticate as authenticate_phase0

ROOT = Path(__file__).resolve().parents[3]

SEAL_INPUTS = tuple(item for item in REQUIRED_MANIFESTS if item not in {
    "artifacts/result_seal.json", "artifacts/promotion_gate.json",
})
TERMINAL_FIELDS = {"auc_delta_vs_baseline", "economics_nonworse", "economic_tail_improves", "rolling_delta_vs_structural"}
REQUIRED_VALIDATION_CHECKS = {
    "source_authenticity", "temporal_split", "forbidden_year_access",
    "availability_timestamps", "target_interval", "artifact_hash_completeness",
    "directional_grid", "pooled_grid", "primary_cell_denominators",
}
VALIDATION_EVIDENCE = (
    "artifacts/phase0_source_manifest.json", "artifacts/collection_manifest.json",
    "artifacts/frozen_feature_manifest.json", "artifacts/score_manifest.json",
    "artifacts/model_manifest.json", "artifacts/crossing_manifest.json",
    "artifacts/decile_manifest.json",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence_hash(root: Path) -> str:
    payload = {item: _sha(root / item) for item in VALIDATION_EVIDENCE if (root / item).is_file()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _hash_file_map(root: Path, records: Iterable[dict]) -> bool:
    """Authenticate every declared partition/artifact against its bytes."""
    try:
        records = list(records)
        return bool(records) and all(
            isinstance(item["path"], str) and isinstance(item["sha256"], str)
            and (root / item["path"]).is_file() and _sha(root / item["path"]) == item["sha256"]
            for item in records
        )
    except (KeyError, TypeError):
        return False


def _feature_freeze_valid(frozen: dict) -> bool:
    try:
        directions = frozen["directional_feature_lists"]
        return (frozen["selection_years"] == [2021, 2022, 2023]
            and frozen["2024_not_read_before_freeze"] is True
            and frozen["ranking_method"] == "univariate_roc_auc_absolute_distance_from_half"
            and isinstance(frozen["candidate_inventory_sha256"], str)
            and len(frozen["candidate_inventory_sha256"]) == 64
            and isinstance(frozen["temporal_folds"], list) and frozen["temporal_folds"]
            and _hash_file_map(ROOT, [frozen["imputer_fit"]]) and all(
            isinstance(directions[direction]["features"], list)
            and len(directions[direction]["features"]) == 25
            and len(set(directions[direction]["features"])) == 25
            and directions[direction]["feature_hash"] == hashlib.sha256(
                json.dumps(directions[direction]["features"], separators=(",", ":")).encode()).hexdigest()
            and directions[direction]["selection_rows"] > 0
            and directions[direction]["selection_positives"] > 0
            for direction in ("SHORT", "LONG")))
    except (KeyError, TypeError):
        return False


def _model_manifest_valid(root: Path, model: dict, frozen_hash: str) -> bool:
    try:
        if model["frozen_feature_manifest_sha256"] != frozen_hash or not _hash_file_map(root, model["artifacts"]):
            return False
        models = model["models"]
        required_grid = {(name, direction) for name in MODELS for direction in DIRECTIONS}
        if {(item.get("model"), item.get("direction")) for item in models} != required_grid or len(models) != len(required_grid):
            return False
        return all({"model", "direction", "artifact_path", "sha256", "preprocessing_path", "preprocessing_sha256", "train_years", "params", "feature_block"} <= set(item)
                   and item["train_years"] == [2021, 2022, 2023]
                   and item["params"] == {"max_depth": 3, "learning_rate": 0.05, "max_iter": 200, "random_state": 42}
                   and (root / item["artifact_path"]).is_file()
                   and _sha(root / item["artifact_path"]) == item["sha256"]
                   and (root / item["preprocessing_path"]).is_file()
                   and _sha(root / item["preprocessing_path"]) == item["preprocessing_sha256"]
                   for item in models)
    except (KeyError, TypeError):
        return False


def build_validation(root: Path) -> dict:
    """Compute, do not accept, every frozen validation check from artifacts."""
    paths = {item: root / item for item in VALIDATION_EVIDENCE}
    if not all(path.is_file() for path in paths.values()):
        checks = {name: False for name in REQUIRED_VALIDATION_CHECKS}
    else:
        phase0 = json.loads(paths["artifacts/phase0_source_manifest.json"].read_text())
        collection = json.loads(paths["artifacts/collection_manifest.json"].read_text())
        frozen = json.loads(paths["artifacts/frozen_feature_manifest.json"].read_text())
        score = json.loads(paths["artifacts/score_manifest.json"].read_text())
        model = json.loads(paths["artifacts/model_manifest.json"].read_text())
        directional, pooled = score.get("directional_rows", []), score.get("pooled_rows", [])
        grid = validate_score_grid(directional, pooled)
        collection_partitions = collection.get("partitions", [])
        observed_years = {item.get("year") for item in collection_partitions}
        phase0_valid = phase0 == json.loads(json.dumps(authenticate_phase0(), sort_keys=True))
        collection_valid = _hash_file_map(root, collection_partitions)
        frozen_valid = _feature_freeze_valid(frozen)
        model_valid = _model_manifest_valid(root, model, _sha(paths["artifacts/frozen_feature_manifest.json"]))
        score_sources_valid = score.get("source_hashes", {}) == {
            "collection_manifest": _sha(paths["artifacts/collection_manifest.json"]),
            "frozen_feature_manifest": _sha(paths["artifacts/frozen_feature_manifest.json"]),
            "model_manifest": _sha(paths["artifacts/model_manifest.json"]),
        }
        checks = {
            "source_authenticity": phase0_valid,
            "temporal_split": frozen_valid and score.get("oos_year") == 2024 and _hash_file_map(root, [score["oos_partition"]]),
            "forbidden_year_access": collection_valid and observed_years <= {2021, 2022, 2023, 2024},
            "availability_timestamps": collection_valid and all(item.get("completed_1s_only") is True and item.get("completed_5m_only") is True and item.get("rth_5s_grid") is True for item in collection_partitions),
            "target_interval": score.get("target") == "prevailing_1m_regime_flip_in_(T,T+300s]",
            "artifact_hash_completeness": model_valid and score_sources_valid,
            "directional_grid": grid["missing_directional"] == [] and grid["duplicate_directional"] == 0,
            "pooled_grid": grid["missing_pooled"] == [] and grid["duplicate_pooled"] == 0,
            "primary_cell_denominators": grid["pass"],
        }
    report = {"builder": "deterministic_validation_v1", "checks": checks,
              "evidence_sha256": _evidence_hash(root), "pass": all(checks.values())}
    output = root / "artifacts" / "validation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True))
    return report


def validate_score_grid(directional_rows: Iterable[dict], pooled_rows: Iterable[dict]) -> dict:
    """Require exactly the frozen A/B/C directional and pooled report grids."""
    directional = list(directional_rows)
    pooled = list(pooled_rows)
    dkeys = [(row.get("model"), row.get("direction"), row.get("maturity_bucket")) for row in directional]
    pkeys = [(row.get("model"), row.get("maturity_bucket")) for row in pooled]
    required_metrics = {"n", "positives", "roc_auc", "pr_auc", "brier", "timing_metric"}
    missing_metrics = [key for key, row in zip(dkeys, directional) if not required_metrics <= set(row)]
    expected_d, expected_p = expected_directional_cells(), expected_pooled_cells()
    return {
        "pass": set(dkeys) == expected_d and len(dkeys) == len(set(dkeys))
        and set(pkeys) == expected_p and len(pkeys) == len(set(pkeys))
        and not missing_metrics and all(row["n"] > 0 and row["positives"] > 0 for row in directional),
        "missing_directional": sorted(expected_d - set(dkeys)),
        "duplicate_directional": len(dkeys) - len(set(dkeys)),
        "missing_pooled": sorted(expected_p - set(pkeys)),
        "duplicate_pooled": len(pkeys) - len(set(pkeys)),
        "missing_metrics": missing_metrics,
    }


def write_result_seal(root: Path) -> dict:
    # Promotion consumes a sealed result; it cannot be an input to the seal it
    # writes without creating a circular, unverifiable dependency.
    paths = list(SEAL_INPUTS)
    missing = [item for item in paths if not (root / item).is_file()]
    payload = {"schema_version": 1, "artifacts": {item: _sha(root / item) for item in paths if (root / item).is_file()}, "missing": missing}
    payload["seal_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (root / "artifacts" / "result_seal.json").write_text(json.dumps(payload, indent=2, sort_keys=True))
    return payload


def verify_result_seal(root: Path) -> bool:
    path = root / "artifacts" / "result_seal.json"
    if not path.is_file(): return False
    seal = json.loads(path.read_text())
    body = {key: seal.get(key) for key in ("schema_version", "artifacts", "missing")}
    if seal.get("missing") or hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != seal.get("seal_sha256"):
        return False
    if set(seal.get("artifacts", {})) != set(SEAL_INPUTS):
        return False
    return all((root / item).is_file() and _sha(root / item) == digest for item, digest in seal.get("artifacts", {}).items())


def derive_terminal_label(validation: dict, directional_rows: Iterable[dict]) -> str:
    """Classify only materialized directional evidence; pooled rows cannot enter."""
    rows = list(directional_rows)
    if not validation.get("pass") or not rows or any(not TERMINAL_FIELDS <= set(row) for row in rows):
        return "ABORT_CONTRACT_OR_CAUSAL_FAILURE"
    improvements = [row for row in rows if row.get("auc_delta_vs_baseline", 0.0) >= 0.001]
    economics_nonworse = all(row.get("economics_nonworse", False) for row in improvements)
    young = [r for r in improvements if r["maturity_bucket"] in {"300-600s", "600-900s"}]
    if len(improvements) >= 2 and economics_nonworse: return "R1_CLEAN_BROAD_IMPROVEMENT"
    if young and economics_nonworse: return "R2_YOUNG_REGIME_IMPROVEMENT"
    if improvements: return "R3_TIMING_IMPROVES_ECONOMICS_DO_NOT"
    if any(row.get("economic_tail_improves", False) for row in rows): return "R4_ECONOMIC_TAIL_WITHOUT_LARGE_AUC_GAIN"
    if all(row.get("rolling_delta_vs_structural", 0.0) == 0.0 for row in rows): return "R5_ROLLING_PRODUCTIVITY_ADDS_NOTHING"
    return "R6_NO_CLEAN_INCREMENTAL_INFORMATION"


def _rows_by_key(rows: Iterable[dict]) -> dict[tuple[str, str, str], dict]:
    return {(row["model"], row["direction"], row["maturity_bucket"]): row for row in rows}


def derive_terminal_evidence(score_rows: Iterable[dict], crossing_rows: Iterable[dict], decile_rows: Iterable[dict]) -> list[dict]:
    """Derive every terminal input from sealed raw metric/economic rows."""
    scores = _rows_by_key(score_rows)
    crossings = _rows_by_key(crossing_rows)
    deciles = _rows_by_key(decile_rows)
    required = set(scores)
    if set(crossings) != required or set(deciles) != required:
        raise RuntimeError("sealed score/crossing/decile cell grids do not agree")
    out = []
    for (model, direction, bucket), score in scores.items():
        baseline = scores.get(("BASELINE", direction, bucket))
        structural = scores.get(("BASELINE_PLUS_STRUCTURAL", direction, bucket))
        crossing, decile = crossings[(model, direction, bucket)], deciles[(model, direction, bucket)]
        for row, fields in ((score, {"roc_auc"}), (crossing, {"median_eventual_opposite_mfe", "median_return_at_confirmation"}),
                            (decile, {"top_decile_eventual_opposite_mfe"})):
            if not fields <= set(row):
                raise RuntimeError(f"terminal evidence missing fields: {sorted(fields - set(row))}")
        base_crossing = crossings[("BASELINE", direction, bucket)]
        base_decile = deciles[("BASELINE", direction, bucket)]
        out.append({
            "model": model, "direction": direction, "maturity_bucket": bucket,
            "auc_delta_vs_baseline": float(score["roc_auc"]) - float(baseline["roc_auc"]),
            "economics_nonworse": float(crossing["median_eventual_opposite_mfe"]) >= float(base_crossing["median_eventual_opposite_mfe"])
                and float(crossing["median_return_at_confirmation"]) >= float(base_crossing["median_return_at_confirmation"]),
            "economic_tail_improves": float(decile["top_decile_eventual_opposite_mfe"]) > float(base_decile["top_decile_eventual_opposite_mfe"]),
            "rolling_delta_vs_structural": (float(score["roc_auc"]) - float(structural["roc_auc"]))
                if model == "BASELINE_PLUS_STRUCTURAL_PLUS_ROLLING_5M" else 0.0,
        })
    return out


def _report_terminal_label(report_path: Path) -> str | None:
    for line in report_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("terminal_label:"):
            return line.partition(":")[2].strip()
    return None


def promotion_gate(root: Path) -> dict:
    """Promote only materialized, sealed score evidence and persisted checks."""
    materialized_validation = root / "artifacts" / "validation.json"
    score_manifest_path = root / "artifacts" / "score_manifest.json"
    causal_path = root / "audit" / "status.json"
    contract_path = root / "audit" / "contract_status.json"
    if not all(path.is_file() for path in (materialized_validation, score_manifest_path, causal_path, contract_path)):
        validation, causal_status, contract_status = {"pass": False}, {"critical": 1}, {"blocking": 1}
        directional, pooled, crossing, decile = [], [], [], []
    else:
        validation = json.loads(materialized_validation.read_text())
        score_manifest = json.loads(score_manifest_path.read_text())
        directional = score_manifest.get("directional_rows", [])
        pooled = score_manifest.get("pooled_rows", [])
        crossing = json.loads((root / "artifacts" / "crossing_manifest.json").read_text()).get("directional_rows", [])
        decile = json.loads((root / "artifacts" / "decile_manifest.json").read_text()).get("directional_rows", [])
        causal_status = json.loads(causal_path.read_text())
        contract_status = json.loads(contract_path.read_text())
        recomputed = validate_score_grid(directional, pooled)
        checks = validation.get("checks", {})
        validation = {**validation, "pass": validation.get("builder") == "deterministic_validation_v1"
                      and validation.get("evidence_sha256") == _evidence_hash(root)
                      and bool(validation.get("pass"))
                      and REQUIRED_VALIDATION_CHECKS <= set(checks)
                      and all(checks.get(name) is True for name in REQUIRED_VALIDATION_CHECKS)
                      and recomputed["pass"], "grid": recomputed}
    try:
        terminal = derive_terminal_label(validation, derive_terminal_evidence(directional, crossing, decile))
    except (KeyError, RuntimeError, TypeError, ValueError):
        terminal = "ABORT_CONTRACT_OR_CAUSAL_FAILURE"
    report_label = _report_terminal_label(root / "STUDY_REPORT.md") if (root / "STUDY_REPORT.md").is_file() else None
    passed = (validation["pass"] and verify_result_seal(root)
              and causal_status.get("critical") == 0 and contract_status.get("blocking") == 0
              and terminal in TERMINAL_LABELS and not terminal.startswith("ABORT")
              and report_label == terminal)
    result = {"status": "PASS" if passed else "BLOCKED", "terminal_label": terminal,
              "report_terminal_label": report_label, "validation": validation,
              "pooled_rows_used_for_terminal": False}
    output = root / "artifacts" / "promotion_gate.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2))
    return result
