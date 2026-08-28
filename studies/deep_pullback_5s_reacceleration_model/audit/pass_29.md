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
      "checked_columns": 62,
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
{"audit_type": "causal", "auditor": "research_workflow.causal_audit", "study": "deep_pullback_5s_reacceleration_model", "verdict": "CLEAR", "critical": 0, "warning": 0, "note": 0, "audited_execution_composite_sha256": "675baa3de792f8392383189abdd509f9abf00922744d49cc4b0ddf40a9a22ebf"}
<!-- AUDIT_SUMMARY_V2_END -->
