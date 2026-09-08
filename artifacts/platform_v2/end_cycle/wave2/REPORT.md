# Wave 2 — partial completion and §E escalation

Status: BLOCKED, unmerged. Codex identity checked with --expect codex and lease claimed through ws chore claim --as codex. No lease files were edited. Main remains at 474cd650.

## Completed, in order

W2.1: f7e2606b changes new shadow declarations to sampled (1 in 4 deterministic seal seeds). Explicit every_run and old compiled-policy fallback remain unchanged. The owner-authorized acceptance decision and specific real/synthetic gate evidence are in WORKFLOW_REFERENCE_FACTS.md. UTF-8 IO habit added to WORKFLOW.md. Four targeted checks pass; see w21_checks.json.

W2.2a: e2e58fbf corrects all five classifier weaknesses. Before: 10 regression cases fail, 1 control passes. After: 14 pass through the corrected script, 3.993s wall, all 14 per-test phase timings recorded. Full pytest failure reports replace truncated terminal summaries. Acceptance requires matching nonempty failure text/outcome, per-entry scope, exact approved reference commit, and Python/platform/dependency environment. Pytest error exit codes cannot pass merely because some reports exist. No automatic environmental exemption remains for new missing-file/import/path failures. Evidence: w22a_before_after.json and w22a_test_delta.json. Baseline unchanged.

## Baseline readings and consequences

Reading A: enforce the requested matching conditions. The committed baseline is schema1 at 3cbc8d06, with 63 entries, 37 empty messages, no per-entry scope and no structured environment snapshot. Default exact reference is merge-base HEAD main (474cd650). Compatibility fails. Explicitly selecting the old reference resolves only the commit mismatch; missing scope/signature/environment evidence remains. See baseline_compatibility.json. All-pass targeted runs remain valid because they consume no baseline exemptions.

Reading B: accept ancestry, copy current environment onto old evidence, infer per-entry scope, or allow an empty/truncated message to match. This would make old exemptions usable but reintroduce the permissiveness W2.2a was instructed to remove. It is not implemented. A reviewed migration needs actual trusted failure/environment observations; branch failures must not be silently baselined. No migration or repeated broad run was performed.

## Scope and causal narrowing: non-impact not established

The old selector replay over Wave 1's 33-file diff chooses 72 scripts/tests files and misses F3. The full central test surface also includes research_workflow, research, features, collectors and root tests. intake_findings.json preserves exact selected paths. W2.2b is NOT implemented: this intake result is not proof that a new mapping protects the excluded tests. A conservative full fallback would include F3 but would not demonstrate the requested savings. No claim is made that a safe narrower mapping is impossible; it remains unproven. No narrowed-scope duration exists, and the 3.993s classifier check is not presented as a broad-to-narrow speedup.

For W2.3, V2StudyController._audit_current (governed_controller_v2.py) and V2Lifecycle.seal bind both reviews to the complete execution composite. Existing model/selection/lineage hashes are consumed by lifecycle/modeling, so a generic provenance exemption is not established. No existing comparison-pin/mirror field with proven noncausal consumption was identified.

Reading A: retain causal review for every unproven change. This obeys the fail-toward-auditing requirement but does not satisfy the requested no-re-audit exemption gate. Reading B: exclude fields merely called provenance, or substitute the replay reuse key. This risks missing selection/OOS/label/composition changes and is prohibited. Neither a new exemption nor reuse-key substitution was implemented. Required next input is a concrete artifact/field for the exemption and its actual consumers, or a revised gate; guessing a new field just to pass a fixture would not prove the requested protection.

## Remaining scope and handoff

W2.2b/c, W2.3 and W2.4 remain unfinished, preserving order. W2.5 skipped. No broad merge gate, cap-generation merge check, host-lint merge check, or merge was attempted. Wave 3 and study execution were not started.

The broad gate caught three findings including a real branch-introduced encoding regression; it is 74m41s, not 150 minutes. Future scope mapping must over-include and retain a generous complete fallback. Other newly surfaced issues are recorded here, not expanded into platform work.

Writer lease will be released after this handoff is committed. Result card is filed under runtime/result.json with BLOCKED status. Continue from the preserved branch; do not redo W2.1 or the five classifier regression gates.
