#!/usr/bin/env python3
from __future__ import annotations
import copy, hashlib, json, os, shutil, sys, uuid
from pathlib import Path
import yaml

ROOT = Path('.').resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features.candidate_authority import load_authority, ACTIVE_POINTER
from features.registry import (
    CANONICAL_FEATURE_DEFINITIONS,
    FeatureDefinition,
    FeatureInstance,
    validate_feature_instance,
)
from scripts.route_study_capabilities import route
from scripts.reconcile_study_capabilities import reconcile

RESULTS = {}
CREATED_STUDIES = []

def test_static_genericity_audit():
    print('\n=== 1. STATIC GENERICITY AUDIT ===')
    import re
    scripts_to_check = [
        ROOT / 'scripts' / 'reconcile_study_capabilities.py',
        ROOT / 'scripts' / 'route_study_capabilities.py',
        ROOT / 'scripts' / 'materialize_scoped_promotions.py',
        ROOT / 'scripts' / 'materialize_feature_candidate.py',
        ROOT / 'scripts' / 'prepare_feature_candidate.py',
        ROOT / 'scripts' / 'authorize_feature_candidate_activation.py',
        ROOT / 'features' / 'candidate_authority.py',
        ROOT / 'research_workflow' / 'feature_candidate_authority.py',
    ]
    findings = []
    for script in scripts_to_check:
        text = script.read_text(encoding='utf-8')
        lines = text.splitlines()
        for idx, line in enumerate(lines, 1):
            if 'deep_pullback' in line.lower():
                findings.append((str(script.relative_to(ROOT)), idx, line.strip(), 'deep_pullback'))
            if re.search(r'studies[\\/]deep_pullback', line):
                findings.append((str(script.relative_to(ROOT)), idx, line.strip(), 'hardcoded_study_path'))
    print(f'Checked {len(scripts_to_check)} core workflow files.')
    print(f'Matches found: {len(findings)}')
    for f in findings:
        print(f'  {f[0]}:{f[1]} -> {f[2]} ({f[3]})')
    RESULTS['STATIC_GENERICITY_AUDIT'] = {
        'passed': len(findings) == 0,
        'matches': findings,
    }

def test_existing_capability_fixture(tmp_dir: Path):
    print('\n=== 2. GENERIC EXISTING-CAPABILITY TEST ===')
    uid = uuid.uuid4().hex[:8]
    study_name = f'generic_existing_caps_{uid}'
    CREATED_STUDIES.append(study_name)
    study_dir = tmp_dir / study_name
    study_dir.mkdir(parents=True, exist_ok=True)
    
    authority_yaml = {
        'authority_id': f'{study_name}_auth_v1',
        'authority_type': 'feature_candidate',
        'candidate_features': [
            {
                'canonical_name': 'regime_efficiency',
                'parameters': {
                    'timeframe': '5m',
                    'context': 'prior',
                    'bar_state': 'completed',
                },
            },
            {
                'canonical_name': 'regime_range_atr',
                'parameters': {
                    'timeframe': '5m',
                    'context': 'prior',
                    'bar_state': 'completed',
                },
            },
        ],
        'semantics': {'bar_state': 'completed'},
        'implementation': 'features.trackers.generic_structural_geometry.GenericStructuralGeometryProvider',
        'evidence_requirements': [
            'features/tests/test_generic_provider_parameterization.py'
        ],
        'promotion_scope': ['FEATURE_DEFINITION', 'FEATURE_PARAMETER_VALUE'],
        'prohibited_scope_expansion': ['train_oos_data', 'unscoped_sibling_features'],
        'terminal_decision': 'PROMOTE',
    }
    (study_dir / 'feature_candidate.yaml').write_text(yaml.dump(authority_yaml), encoding='utf-8')
    
    res1 = reconcile(study_dir)
    print('Run 1 Result:', res1)
    
    res2 = reconcile(study_dir)
    print('Run 2 Result:', res2)
    
    passed = res1.get('state') == 'READY_TO_SCAFFOLD' and res2.get('state') == 'READY_TO_SCAFFOLD'
    RESULTS['EXISTING_CAPABILITY_FIXTURE'] = {
        'passed': passed,
        'state': res1.get('state'),
        'run2_state': res2.get('state'),
    }

def _with_registry_snippet(snippet: str):
    class RegistryContext:
        def __init__(self, code: str):
            self.code = code
            self.reg_path = ROOT / "features" / "registry.py"
            self.orig_text = ""
        def __enter__(self):
            import importlib
            self.orig_text = self.reg_path.read_text(encoding="utf-8")
            self.reg_path.write_text(self.orig_text + "\n" + self.code + "\n", encoding="utf-8")
            import features.registry; importlib.reload(features.registry)
            import scripts.check_feature_promotion; importlib.reload(scripts.check_feature_promotion)
        def __exit__(self, exc_type, exc_val, exc_tb):
            import importlib
            self.reg_path.write_text(self.orig_text, encoding="utf-8")
            import features.registry; importlib.reload(features.registry)
            import scripts.check_feature_promotion; importlib.reload(scripts.check_feature_promotion)
    return RegistryContext(snippet)

def test_novel_implemented_feature_fixture(tmp_dir: Path):
    print("\n=== 3. GENERIC NOVEL-BUT-IMPLEMENTED FEATURE TEST ===")
    uid = uuid.uuid4().hex[:8]
    study_name = f"generic_novel_feat_{uid}"
    CREATED_STUDIES.append(study_name)
    study_dir = tmp_dir / study_name
    study_dir.mkdir(parents=True, exist_ok=True)

    test_feat = f"test_novel_feature_{uid}"
    snippet = f"""
CANONICAL_FEATURE_DEFINITIONS['{test_feat}'] = _canonical_definition(
    '{test_feat}', family='structural_regime_geometry',
    implementation='features.trackers.generic_structural_geometry.GenericStructuralGeometryProvider',
    tests=('features/tests/test_generic_provider_parameterization.py',),
    parameters=('timeframe', 'context', 'bar_state'),
    source_timeframe='1s+1m+5m',
    update_anchor='completed_5m_bar',
    normalizer='study_contract',
    window_unit='since_regime_flip',
    reset_policy='event_start',
    null_policy='allow',
    supported_timeframes=('5m',),
    supported_parameter_values={{'timeframe': ('5m',), 'context': ('prior',), 'bar_state': ('completed',)}},
    required_parameters=('timeframe', 'context', 'bar_state'),
    supported_parameter_combinations=({{'timeframe': '5m', 'context': 'prior', 'bar_state': 'completed'}},),
)
"""
    with _with_registry_snippet(snippet):
        authority_yaml = {
            "authority_id": f"{study_name}_auth_v1",
            "authority_type": "feature_candidate",
            "candidate_features": [
                {
                    "canonical_name": test_feat,
                    "parameters": {
                        "timeframe": "5m",
                        "context": "prior",
                        "bar_state": "completed",
                    },
                }
            ],
            "semantics": {"bar_state": "completed"},
            "implementation": "features.trackers.generic_structural_geometry.GenericStructuralGeometryProvider",
            "evidence_requirements": [
                "features/tests/test_generic_provider_parameterization.py"
            ],
            "promotion_scope": ["FEATURE_DEFINITION", "FEATURE_PARAMETER_VALUE"],
            "prohibited_scope_expansion": ["train_oos_data", "unscoped_sibling_features"],
            "terminal_decision": "PROMOTE",
        }
        (study_dir / "feature_candidate.yaml").write_text(yaml.dump(authority_yaml), encoding="utf-8")

        res = reconcile(study_dir)
        print("Reconcile Novel Feature Result:", res)
        
        active = load_authority("active")
        active_names = {x.get("canonical_name") for x in active["registry"].get("definitions", []) if x.get("status") == "verified"}
        is_promoted = test_feat in active_names
        print(f"Novel feature promoted to active verified: {is_promoted}")

        passed = res.get("state") == "READY_TO_SCAFFOLD" and is_promoted
        RESULTS["NOVEL_IMPLEMENTED_FEATURE_FIXTURE"] = {
            "passed": passed,
            "state": res.get("state"),
            "promoted": is_promoted,
        }

def test_parameter_verification_fixture(tmp_dir: Path):
    print("\n=== 4. GENERIC PARAMETER-VERIFICATION TEST ===")
    uid = uuid.uuid4().hex[:8]
    study_name = f"generic_param_verify_{uid}"
    CREATED_STUDIES.append(study_name)
    study_dir = tmp_dir / study_name
    study_dir.mkdir(parents=True, exist_ok=True)

    test_feat = f"test_param_verify_feat_{uid}"
    snippet = f"""
CANONICAL_FEATURE_DEFINITIONS['{test_feat}'] = _canonical_definition(
    '{test_feat}', family='structural_regime_geometry',
    implementation='features.trackers.generic_structural_geometry.GenericStructuralGeometryProvider',
    tests=('features/tests/test_generic_provider_parameterization.py',),
    parameters=('timeframe', 'threshold'),
    source_timeframe='1s',
    update_anchor='completed_1s',
    normalizer='study_contract',
    window_unit='seconds',
    reset_policy='none',
    null_policy='allow',
    supported_timeframes=('1m', '5m'),
    supported_parameter_values={{'timeframe': ('1m', '5m'), 'threshold': (1.0, 2.0)}},
    required_parameters=('timeframe', 'threshold'),
    supported_parameter_combinations=({{'timeframe': '1m', 'threshold': 1.0}}, {{'timeframe': '5m', 'threshold': 2.0}}),
)
"""
    with _with_registry_snippet(snippet):
        authority_yaml = {
            "authority_id": f"{study_name}_auth_v1",
            "authority_type": "feature_candidate",
            "candidate_features": [
                {
                    "canonical_name": test_feat,
                    "parameters": {
                        "timeframe": "1m",
                        "threshold": 1.0,
                    },
                }
            ],
            "semantics": {"bar_state": "completed"},
            "implementation": "features.trackers.generic_structural_geometry.GenericStructuralGeometryProvider",
            "evidence_requirements": [
                "features/tests/test_generic_provider_parameterization.py"
            ],
            "promotion_scope": ["FEATURE_DEFINITION", "FEATURE_PARAMETER_VALUE"],
            "prohibited_scope_expansion": ["train_oos_data", "unscoped_sibling_features"],
            "terminal_decision": "PROMOTE",
        }
        (study_dir / "feature_candidate.yaml").write_text(yaml.dump(authority_yaml), encoding="utf-8")

        res = reconcile(study_dir)
        print("Reconcile Parameter Verification Result:", res)

        passed = res.get("state") == "READY_TO_SCAFFOLD"
        RESULTS["PARAMETER_VERIFICATION_FIXTURE"] = {
            "passed": passed,
            "state": res.get("state"),
        }

def test_implementation_required_fixture(tmp_dir: Path):
    print("\n=== 5. IMPLEMENTATION_REQUIRED TEST ===")
    uid = uuid.uuid4().hex[:8]
    study_name = f"generic_missing_impl_{uid}"
    CREATED_STUDIES.append(study_name)
    study_dir = tmp_dir / study_name
    study_dir.mkdir(parents=True, exist_ok=True)

    test_feat = f"test_unimplemented_feat_{uid}"
    snippet = f"""
CANONICAL_FEATURE_DEFINITIONS['{test_feat}'] = _canonical_definition(
    '{test_feat}', family='missing_family',
    implementation='features.trackers.nonexistent_tracker.NonexistentTracker',
    tests=('features/tests/test_generic_provider_parameterization.py',),
    parameters=('timeframe',),
    source_timeframe='1s',
    update_anchor='completed_1s',
    normalizer='study_contract',
    window_unit='seconds',
    reset_policy='none',
    null_policy='allow',
    supported_timeframes=('5m',),
    supported_parameter_values={{'timeframe': ('5m',)}},
    required_parameters=('timeframe',),
    supported_parameter_combinations=({{'timeframe': '5m'}},),
)
"""
    with _with_registry_snippet(snippet):
        authority_yaml = {
            "authority_id": f"{study_name}_auth_v1",
            "authority_type": "feature_candidate",
            "candidate_features": [
                {
                    "canonical_name": test_feat,
                    "parameters": {"timeframe": "5m"},
                }
            ],
            "semantics": {"bar_state": "completed"},
            "implementation": "features.trackers.nonexistent_tracker.NonexistentTracker",
            "evidence_requirements": [
                "features/tests/test_generic_provider_parameterization.py"
            ],
            "promotion_scope": ["FEATURE_DEFINITION", "FEATURE_PARAMETER_VALUE"],
            "prohibited_scope_expansion": ["train_oos_data", "unscoped_sibling_features"],
            "terminal_decision": "PROMOTE",
        }
        (study_dir / "feature_candidate.yaml").write_text(yaml.dump(authority_yaml), encoding="utf-8")

        res = reconcile(study_dir)
        print("Missing Implementation Result:", res)

        passed = res.get("state") == "IMPLEMENTATION_REQUIRED"
        RESULTS["IMPLEMENTATION_REQUIRED_FIXTURE"] = {
            "passed": passed,
            "state": res.get("state"),
            "contract": res,
        }

def test_semantic_decision_fixture():
    print("\n=== 6. SEMANTIC_DECISION_REQUIRED TEST ===")
    req = {
        "capabilities": [
            {"feature": "ambiguous_fuzzy_momentum_signal", "parameters": {"window": "maybe_10"}}
        ]
    }
    routed = route(req)
    print("Routed Ambiguous Request:", routed)
    is_semantic = len(routed.get("SEMANTIC_REVIEW_REQUIRED", [])) == 1
    passed = is_semantic and not routed.get("EXISTING_VERIFIED") and not routed.get("TRUE_CAPABILITY_GAP")
    RESULTS["SEMANTIC_DECISION_FIXTURE"] = {
        "passed": passed,
        "terminal_state": "SEMANTIC_REVIEW_REQUIRED" if is_semantic else "UNKNOWN",
    }

def test_true_capability_gap_fixture():
    print("\n=== 7. TRUE CAPABILITY GAP TEST ===")
    req = {
        "capabilities": [
            {"feature": "quantum_entangled_orderbook_telepathy", "requested_route": "true_capability_gap"}
        ]
    }
    routed = route(req)
    print("Routed Capability Gap:", routed)
    is_gap = len(routed.get("TRUE_CAPABILITY_GAP", [])) == 1
    passed = is_gap and not routed.get("EXISTING_VERIFIED") and not routed.get("SEMANTIC_REVIEW_REQUIRED")
    RESULTS["TRUE_CAPABILITY_GAP_FIXTURE"] = {
        "passed": passed,
        "terminal_state": "TRUE_CAPABILITY_GAP" if is_gap else "UNKNOWN",
    }

def test_stale_recovery_fixture(tmp_dir: Path):
    print("\n=== 8. STALE RECOVERY TEST ===")
    uid = uuid.uuid4().hex[:8]
    study_name = f"generic_stale_recovery_{uid}"
    CREATED_STUDIES.append(study_name)
    study_dir = tmp_dir / study_name
    study_dir.mkdir(parents=True, exist_ok=True)

    dummy_provider_path = ROOT / "features" / "trackers" / f"synthetic_test_tracker_{uid}.py"
    dummy_provider_path.write_text(
        f"class SyntheticTestTracker_{uid}:\n    VERSION = 1\n", encoding="utf-8"
    )

    test_feat = f"test_stale_feat_{uid}"
    snippet = f"""
CANONICAL_FEATURE_DEFINITIONS['{test_feat}'] = _canonical_definition(
    '{test_feat}', family='synthetic_stale_test',
    implementation='features.trackers.synthetic_test_tracker_{uid}.SyntheticTestTracker_{uid}',
    tests=('features/tests/test_generic_provider_parameterization.py',),
    parameters=('timeframe',),
    source_timeframe='1s',
    update_anchor='completed_1s',
    normalizer='study_contract',
    window_unit='seconds',
    reset_policy='none',
    null_policy='allow',
    supported_timeframes=('5m',),
    supported_parameter_values={{'timeframe': ('5m',)}},
    required_parameters=('timeframe',),
    supported_parameter_combinations=({{'timeframe': '5m'}},),
)
"""
    try:
        with _with_registry_snippet(snippet):
            authority_yaml = {
                "authority_id": f"{study_name}_auth_v1",
                "authority_type": "feature_candidate",
                "candidate_features": [
                    {"canonical_name": test_feat, "parameters": {"timeframe": "5m"}}
                ],
                "semantics": {"bar_state": "completed"},
                "implementation": f"features.trackers.synthetic_test_tracker_{uid}.SyntheticTestTracker_{uid}",
                "evidence_requirements": [
                    "features/tests/test_generic_provider_parameterization.py"
                ],
                "promotion_scope": ["FEATURE_DEFINITION", "FEATURE_PARAMETER_VALUE"],
                "prohibited_scope_expansion": ["train_oos_data", "unscoped_sibling_features"],
                "terminal_decision": "PROMOTE",
            }
            (study_dir / "feature_candidate.yaml").write_text(yaml.dump(authority_yaml), encoding="utf-8")

            res1 = reconcile(study_dir)
            print("Initial Reconcile:", res1.get("state"))

            dummy_provider_path.write_text(
                f"class SyntheticTestTracker_{uid}:\n    VERSION = 2\n    # Modified code\n", encoding="utf-8"
            )

            res2 = reconcile(study_dir)
            print("Rerun Reconcile after Mutation:", res2.get("state"))

            passed = res1.get("state") == "READY_TO_SCAFFOLD" and res2.get("state") == "READY_TO_SCAFFOLD"
            RESULTS["STALE_RECOVERY_FIXTURE"] = {
                "passed": passed,
                "initial_state": res1.get("state"),
                "recovered_state": res2.get("state"),
            }
    finally:
        if dummy_provider_path.is_file():
            dummy_provider_path.unlink()

def main():
    tmp_dir = ROOT / "scratch" / "_test_generic_reconciler_tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        test_static_genericity_audit()
        test_existing_capability_fixture(tmp_dir)
        test_novel_implemented_feature_fixture(tmp_dir)
        test_parameter_verification_fixture(tmp_dir)
        test_implementation_required_fixture(tmp_dir)
        test_semantic_decision_fixture()
        test_true_capability_gap_fixture()
        test_stale_recovery_fixture(tmp_dir)

        print("\n=== SUMMARY RESULTS ===")
        print(json.dumps(RESULTS, indent=2))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        for name in CREATED_STUDIES:
            p = ROOT / "audit_lineage" / f"{name}.json"
            if p.is_file():
                p.unlink()

if __name__ == "__main__":
    main()

