#!/usr/bin/env python3
"""Research Decision Contract Fidelity Gate.
=============================================
Validates that SPEC.md and study.yaml adhere strictly to the authoritative
research_decision.yaml contract, ensuring no unapproved feature discovery,
baseline mutation, or scope expansion occurs.

Precedence Hierarchy:
    research_decision.yaml > SPEC.md > study.yaml > compiled_study.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pydantic import BaseModel, Field


class BaselineSpec(BaseModel):
    short: str
    long: str


class FeatureSelectionSpec(BaseModel):
    mode: str = "none"  # "none", "train_only", "unconstrained"


class ChronologySpec(BaseModel):
    train: List[int]
    dev: List[int]
    prohibited: List[int] = Field(default_factory=list)


class ResearchDecisionContract(BaseModel):
    research_question: str
    baseline: BaselineSpec
    baseline_feature_selection: FeatureSelectionSpec
    model_arms: Dict[str, str]
    variable_being_tested: List[str]
    prohibited_changes: List[str] = Field(default_factory=list)
    allowed_changes: List[str] = Field(default_factory=list)
    chronology: ChronologySpec
    primary_comparison: Optional[str] = None
    terminal_question: Optional[str] = None


def check_research_decision_fidelity(study_dir: Path) -> Dict[str, Any]:
    decision_path = study_dir / "research_decision.yaml"
    spec_md_path = study_dir / "SPEC.md"
    study_yaml_path = study_dir / "study.yaml"

    findings = []

    if not decision_path.exists():
        return {
            "status": "SKIPPED",
            "reason": f"No research_decision.yaml found in {study_dir}",
            "findings": [],
        }

    try:
        with open(decision_path, "r", encoding="utf-8") as f:
            raw_decision = yaml.safe_load(f)
        decision = ResearchDecisionContract.model_validate(raw_decision)
    except Exception as e:
        return {
            "status": "BLOCKED",
            "findings": [
                {
                    "severity": "CRITICAL",
                    "code": "INVALID_RESEARCH_DECISION_SCHEMA",
                    "message": f"Failed to parse research_decision.yaml: {e}",
                }
            ],
        }

    # 1. Check study.yaml fidelity if present
    if study_yaml_path.exists():
        try:
            with open(study_yaml_path, "r", encoding="utf-8") as f:
                raw_study = yaml.safe_load(f)
        except Exception as e:
            findings.append({
                "severity": "CRITICAL",
                "code": "INVALID_STUDY_YAML",
                "message": f"Failed to parse study.yaml: {e}",
            })
            raw_study = {}

        # Check feature selection mode fidelity
        study_features = raw_study.get("features", {})
        study_selection = study_features.get("selection", {})
        study_sel_mode = study_selection.get("mode", "none") if isinstance(study_selection, dict) else "none"

        # The study's selection regime may be NARROWER than the decision contract
        # authorizes, never broader. Ranked by how much freedom each mode grants:
        #
        #   none / pre_frozen  -> 0  no new selection is performed
        #   train_only         -> 1  features are selected, on train data only
        #
        # Ranking rather than equality matters because a study that names an explicit
        # feature_list performs no selection at all (mode defaults to "none") while its
        # decision contract may legitimately declare "train_only" for the baseline. That
        # is narrower, not a violation.
        #
        # Previously only `mode == "none"` was compared, so a decision declaring
        # 'train_only' or 'pre_frozen' cross-checked nothing at all -- the gate silently
        # passed for two of its three modes (contract audit pass 01, WARNING).
        _SELECTION_FREEDOM = {None: 0, "none": 0, "pre_frozen": 0, "train_only": 1}
        decision_mode = decision.baseline_feature_selection.mode
        decision_rank = _SELECTION_FREEDOM.get(decision_mode)
        study_rank = _SELECTION_FREEDOM.get(study_sel_mode)

        if decision_rank is None or study_rank is None:
            findings.append({
                "severity": "CRITICAL",
                "code": "UNKNOWN_SELECTION_MODE",
                "message": (
                    f"Unrecognized feature selection mode (decision: {decision_mode!r}, "
                    f"study: {study_sel_mode!r}); known: {sorted(k for k in _SELECTION_FREEDOM if k)}"
                ),
            })
        elif study_rank > decision_rank:
            findings.append({
                "severity": "CRITICAL",
                "code": "UNAUTHORIZED_FEATURE_DISCOVERY",
                "message": (
                    f"study.yaml selection.mode '{study_sel_mode}' grants more feature-selection "
                    f"freedom than research_decision.yaml authorizes "
                    f"(baseline_feature_selection.mode: '{decision_mode}')"
                ),
            })

        if decision.baseline_feature_selection.mode == "none":
            if study_features.get("source") == "verified_registry_numeric_universe":
                findings.append({
                    "severity": "CRITICAL",
                    "code": "UNAUTHORIZED_UNIVERSE_EXPANSION",
                    "message": "research_decision.yaml prohibits full feature registry expansion, but study.yaml sources verified_registry_numeric_universe",
                })

        # Check prohibited changes against known schema
        KNOWN_PROHIBITIONS = {
            "rerank_baseline_features",
            "replace_frozen_top25",
            "modify_baseline_top25",
            "expand_to_full_feature_registry",
            "use_2024_to_change_model_design",
            "introduce_unconstrained_search",
            "unauthorized_feature_discovery",
            # Counterpart of exact bounded date authorization
            # (execution.data_requirements.authorized_dates, enforced in
            # backtests/nt_runtime/data_plan.py::enforce_authorized_dates). A study that
            # declares exact dates needs a way to say that widening them is prohibited;
            # without this token the decision contract could not express the constraint
            # the runtime enforces.
            "expansion_beyond_authorized_dates",
        }
        for prohibited in decision.prohibited_changes:
            if prohibited not in KNOWN_PROHIBITIONS:
                findings.append({
                    "severity": "CRITICAL",
                    "code": "UNKNOWN_PROHIBITION",
                    "message": f"research_decision.yaml specifies unrecognized prohibited_change: '{prohibited}' (known: {sorted(KNOWN_PROHIBITIONS)})",
                })
            if prohibited == "rerank_baseline_features" and study_sel_mode not in ("none", None):
                findings.append({
                    "severity": "CRITICAL",
                    "code": "PROHIBITED_CHANGE_VIOLATION",
                    "message": "Prohibited change 'rerank_baseline_features' violated by active selection mode in study.yaml",
                })
            if prohibited in ("expand_to_full_feature_registry", "introduce_unconstrained_search") and study_features.get("source") == "verified_registry_numeric_universe":
                findings.append({
                    "severity": "CRITICAL",
                    "code": "PROHIBITED_CHANGE_VIOLATION",
                    "message": "Prohibited change 'expand_to_full_feature_registry' violated by study.yaml features.source",
                })

        # Check baseline feature list binding if baseline is frozen to top25
        if decision.baseline_feature_selection.mode == "none":
            expected_base_sha = getattr(decision.baseline, "expected_baseline_sha", None)
            if not expected_base_sha and (
                "replace_frozen_top25" in (decision.prohibited_changes or [])
                or "TOP25" in decision.baseline.short
                or "codex_5.6" in decision.baseline.short
            ):
                expected_base_sha = "8bcfeb74ab3b5453635ad9895fa9d15fd65866044f23fa0415bfc796e5fd6299"

            if expected_base_sha:
                flist = study_features.get("feature_list", [])
                if len(flist) < 25:
                    findings.append({
                        "severity": "CRITICAL",
                        "code": "BASELINE_FEATURE_COUNT_INSUFFICIENT",
                        "message": f"study.yaml feature_list has {len(flist)} features, expected at least 25 for baseline",
                    })
                else:
                    base_25 = flist[:25]
                    base_sha = hashlib.sha256(json.dumps(base_25).encode("utf-8")).hexdigest()
                    if base_sha != expected_base_sha:
                        findings.append({
                            "severity": "CRITICAL",
                            "code": "BASELINE_FEATURE_HASH_MISMATCH",
                            "message": f"First 25 features in study.yaml (SHA: {base_sha}) do not match frozen baseline SHA ({expected_base_sha})",
                        })

        # Check chronology fidelity
        study_chronology = raw_study.get("chronology", {})
        if sorted(study_chronology.get("train", [])) != sorted(decision.chronology.train):
            findings.append({
                "severity": "CRITICAL",
                "code": "CHRONOLOGY_TRAIN_MISMATCH",
                "message": f"study.yaml train years {study_chronology.get('train')} != research_decision.yaml train years {decision.chronology.train}",
            })
        if sorted(study_chronology.get("dev", [])) != sorted(decision.chronology.dev):
            findings.append({
                "severity": "CRITICAL",
                "code": "CHRONOLOGY_DEV_MISMATCH",
                "message": f"study.yaml dev years {study_chronology.get('dev')} != research_decision.yaml dev years {decision.chronology.dev}",
            })

    # 2. Check SPEC.md fidelity if present
    if spec_md_path.exists():
        spec_text = spec_md_path.read_text(encoding="utf-8")
        if decision.baseline_feature_selection.mode == "none":
            if "fresh Top-25" in spec_text or "selected from 2021" in spec_text:
                findings.append({
                    "severity": "CRITICAL",
                    "code": "SPEC_INTENT_CONFLICT",
                    "message": "SPEC.md contains fresh feature discovery text, conflicting with baseline_feature_selection.mode: none",
                })

    status = "BLOCKED" if any(f["severity"] == "CRITICAL" for f in findings) else "PASSED"
    result = {
        "status": status,
        "study_dir": str(study_dir),
        "decision_contract": decision.model_dump(),
        "findings": findings,
    }

    # Persist report in artifacts/
    artifacts_dir = study_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    with open(artifacts_dir / "research_decision_fidelity_report.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Research Decision Contract Fidelity")
    parser.add_argument("--study", type=str, required=True, help="Path to study directory")
    parser.add_argument("--json", type=str, help="Path to output json report")
    args = parser.parse_args()

    study_dir = Path(args.study).resolve()
    res = check_research_decision_fidelity(study_dir)

    if args.json:
        out_p = Path(args.json)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)

    print(f"Research Decision Contract Fidelity: {res['status']}")
    if res["findings"]:
        for f in res["findings"]:
            print(f"  [{f['severity']}] {f['code']}: {f['message']}")

    return 0 if res["status"] in ("PASSED", "SKIPPED") else 1


if __name__ == "__main__":
    sys.exit(main())
