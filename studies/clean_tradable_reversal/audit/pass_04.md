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
{"audit_type": "causal", "auditor": "research_workflow.causal_audit", "study": "clean_tradable_reversal", "verdict": "CLEAR", "critical": 0, "warning": 0, "note": 0, "audited_execution_composite_sha256": "2517cee6c835bc373b5039415eb8e2f0778bd6d5b2dd8ced62015f4ae52a072b"}
<!-- AUDIT_SUMMARY_V2_END -->
