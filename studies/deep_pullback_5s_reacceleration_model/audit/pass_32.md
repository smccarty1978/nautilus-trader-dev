# Causal Review

{
  "checks": [
    {
      "name": "preflight",
      "passed": true
    },
    {
      "name": "readiness",
      "passed": false
    },
    {
      "name": "real_output_parity",
      "passed": false
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
{"audit_type": "causal", "auditor": "research_workflow.causal_audit", "study": "deep_pullback_5s_reacceleration_model", "verdict": "BLOCKED", "critical": 1, "warning": 0, "note": 0, "audited_execution_composite_sha256": "5058373070c6c4cf11c74189a4317c3c3db363b4dad7ccdf1c86e7be40142892"}
<!-- AUDIT_SUMMARY_V2_END -->
