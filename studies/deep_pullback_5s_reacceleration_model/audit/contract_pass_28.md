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
      "detail": "declared selection.feature_count=34, instances=34"
    },
    {
      "name": "declared_surface_matches_authorized",
      "passed": true,
      "detail": "declared 34 == authorized 34"
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
      "checked": 1
    },
    {
      "name": "required_gates_declared_and_bound",
      "passed": true,
      "checked": 1,
      "malformed": []
    },
    {
      "name": "model_selection_binding_present",
      "passed": true,
      "search_method": "none"
    }
  ]
}

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "contract", "auditor": "research_workflow.contract_audit", "study": "deep_pullback_5s_reacceleration_model", "verdict": "CLEAR", "blocking": 0, "critical": 0, "warning": 0, "not_verified": 0, "audited_execution_composite_sha256": "6ba4183436e2cfa0ece9993bb7d4f260434695a2c04fc917150ac32c58d8b092"}
<!-- AUDIT_SUMMARY_V2_END -->
