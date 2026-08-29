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
      "detail": "no selection.feature_count declared; cardinality not asserted"
    },
    {
      "name": "declared_surface_matches_authorized",
      "passed": true,
      "detail": "declared 5 == authorized 5"
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
      "search_method": "none"
    }
  ]
}

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "contract", "auditor": "research_workflow.contract_audit", "study": "workflow_canary_ordered_barrier_v1", "verdict": "CLEAR", "blocking": 0, "critical": 0, "warning": 0, "not_verified": 0, "audited_execution_composite_sha256": "0183b87056170622a7ecc6683c8d49705e303dd75ed4b6c9cb7cfac025fda9e8"}
<!-- AUDIT_SUMMARY_V2_END -->
