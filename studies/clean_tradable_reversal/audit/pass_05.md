# Causal Review

{
  "checks": [
    {
      "name": "preflight",
      "passed": true
    },
    {
      "name": "readiness",
      "passed": true
    },
    {
      "name": "real_output_parity",
      "passed": true
    },
    {
      "name": "canonical_instances",
      "passed": true
    },
    {
      "name": "legacy_runtime_excluded",
      "passed": true
    },
    {
      "name": "derived_input_availability_causal",
      "passed": true,
      "checked": 1
    },
    {
      "name": "composite_target_label_only",
      "passed": true,
      "checked_columns": 53,
      "unaccounted": []
    },
    {
      "name": "causal_lint",
      "passed": true,
      "critical_findings": 0
    }
  ]
}

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "causal", "auditor": "research_workflow.causal_audit", "study": "clean_tradable_reversal", "verdict": "CLEAR", "critical": 0, "warning": 0, "note": 0, "audited_execution_composite_sha256": "b010f3c7d4599887279c1e988ecb463e23db9b9077047f288cc36244094d7fe9"}
<!-- AUDIT_SUMMARY_V2_END -->
