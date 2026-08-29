# Contract Review

{
  "checks": [
    {
      "name": "compiled_spec_present",
      "passed": true
    },
    {
      "name": "explicit_feature_instances",
      "passed": true
    },
    {
      "name": "declared_instance_count_matches_contract",
      "passed": true,
      "detail": "declared selection.feature_count=13, instances=13"
    },
    {
      "name": "declared_surface_matches_authorized",
      "passed": true,
      "detail": "declared 13 == authorized 13"
    },
    {
      "name": "generic_collector_binding",
      "passed": true
    },
    {
      "name": "deliverables_contract",
      "passed": true
    },
    {
      "name": "phase0_manifest",
      "passed": true
    },
    {
      "name": "legacy_aliases_excluded",
      "passed": true
    },
    {
      "name": "population_target_contracts",
      "passed": true
    },
    {
      "name": "derived_causal_inputs_bound",
      "passed": true,
      "checked": 0
    },
    {
      "name": "required_gates_declared_and_bound",
      "passed": true,
      "checked": 0,
      "malformed": []
    },
    {
      "name": "model_selection_binding_present",
      "passed": true,
      "detail": "TRAIN not yet frozen; nothing to bind yet"
    }
  ]
}

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "contract", "auditor": "research_workflow.contract_audit", "study": "clean_maturity_flip_model_180s_horizon", "verdict": "CLEAR", "blocking": 0, "critical": 0, "warning": 0, "not_verified": 0, "audited_execution_composite_sha256": "bd2e9cf145a7408cff84613fec65149a94c296eeafad6194b42d427df4203e0e"}
<!-- AUDIT_SUMMARY_V2_END -->
