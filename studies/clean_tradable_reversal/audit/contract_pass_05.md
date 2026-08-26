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
      "detail": "declared 20 == authorized 20"
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
{"audit_type": "contract", "auditor": "research_workflow.contract_audit", "study": "clean_tradable_reversal", "verdict": "CLEAR", "blocking": 0, "critical": 0, "warning": 0, "not_verified": 0, "audited_execution_composite_sha256": "2517cee6c835bc373b5039415eb8e2f0778bd6d5b2dd8ced62015f4ae52a072b"}
<!-- AUDIT_SUMMARY_V2_END -->
