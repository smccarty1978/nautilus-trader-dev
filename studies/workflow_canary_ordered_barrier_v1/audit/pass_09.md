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
      "checked": 0
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
{"audit_type": "causal", "auditor": "research_workflow.causal_audit", "study": "workflow_canary_ordered_barrier_v1", "verdict": "CLEAR", "critical": 0, "warning": 0, "note": 0, "audited_execution_composite_sha256": "93b33fadc8d21d186e93995e28f761f1bc3bc9641a10eb99c6d9715675d1fa69"}
<!-- AUDIT_SUMMARY_V2_END -->
