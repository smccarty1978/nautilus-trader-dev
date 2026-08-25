# Candidate Feature Authority Contract Review

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Candidate governs phase-zero, runtime collection, and OutputManager before activation through one explicit authority source | FAIL | `implementation/phase0.py:43-48,144-182` authenticates the candidate explicitly, but `implementation/collector.py:42-45,188,323-324` resolves and snapshots the default active universe at import time. `backtests/nt_runtime/modes/collect.py:167-174` constructs `OutputManager` without `feature_authority`, so `output_manager.py:293-300,430-432` also remains active. Observed resolution is 693 candidate aliases versus a 532-alias collector snapshot, leaving 161 candidate aliases unreachable. | `scripts/tests/test_readiness.py:416-424` tests a synthetic candidate-shaped dataframe only; targeted suite passed (5 tests) but no real candidate collector-route test exists. | Thread the explicit authority selected by the authenticated phase-zero manifest through collector universe construction and `OutputManager`, then assert real emitted/resolved candidate parity. |
| Activated authority fails closed with no dual-authority fallback | FAIL | `features/registry.py:1137-1147` catches every `CandidateAuthorityError` when `authority="active"` and falls back to the legacy resolver even when `active.json` exists. A missing/corrupt activated bundle therefore silently re-enables legacy authority after cutover. | `features/tests/test_candidate_authority.py:31-38,73-77` covers inactive behavior, not post-activation corruption/fallback. | Permit legacy only when the active pointer is absent; once present, propagate all active-bundle errors and add a corrupt-after-activation test. |
| Promotion gate authenticates frozen review evidence | FAIL | `scripts/authorize_feature_candidate_activation.py:24-35` accepts caller-selected JSON paths and checks only counters/verdict/composite. `features/candidate_authority.py:87-99` then trusts any authorization JSON with three matching public fields; it does not authenticate candidate-scoped report provenance, study binding, distinct reviewer identities, or evidence hashes. | `features/tests/test_candidate_authority.py:22-27,41-53` fabricates this minimal authorization and proves activation accepts it. | Make activation revalidate deterministic candidate-scoped audit evidence (including study, composite, reviewer separation, and report/status binding), or require and verify a sealed authorization artifact produced only from that evidence. |
| Frozen candidate bytes and immutable promotion facts | PASS | `features/candidate_authority.py:28-40,67-75,97-108`; freeze file pins all three byte hashes and bundle composite. `scripts/check_candidate_promotion.py:15-40` checks definition, provider, parameter schema, parity, and structural-test evidence. | Candidate preflight `feature_lifecycle.json` reports 129 definitions, no violations; targeted suite passed. | None. |
| Inactive legacy authority and atomic pointer cutover | PASS | `features/authority/active.json` is absent. `features/registry.py:1137-1147` preserves legacy while absent; `features/candidate_authority.py:100-108` uses `os.replace` and verifies cutover hashes. | `features/tests/test_candidate_authority.py:41-53,73-77`. | None beyond the fail-closed remediation above. |
| Legacy archive is non-runtime | PASS | `features/archive/legacy_registry_2026_08_22/manifest.json` declares `runtime_dependency: false`; runtime resolver paths are under `features/authority`, not `features/archive`. | No direct runtime-import test; execution manifest closure contains no archive path. | None. |
| Execution evidence closure and freeze binding | PASS | Candidate freeze binds execution composite `899c5bb92391e4887224acd946bba5aed5d7ac2da9c8ce1f36cb30f01e7e5e59`; candidate `execution_manifest.json` reports 105/105 combined files, 100% closure, and no unresolved dependencies. | Candidate `preflight.json` is CLEAR on the same composite; all required checks passed. | None. |
| Materialized collect deliverables | NOT APPLICABLE | `config/deliverables_contract.json` authorizes collect artifacts, but this is an inactive pre-execution candidate review and no candidate collection was authorized or run. | Not applicable. | Verify the literal collect contract at completion. |
| C4 walk-forward/model promotion, D1-D4 train/serve, E1-E5 backtest | NOT APPLICABLE | This review is limited to inactive Feature System V2 authority bootstrap; no model fit, serve deployment, or backtest was run. | Not applicable. | Re-audit when those modes execute or their surface changes. |

### BLOCKING: Candidate authority is not threaded through the real collection route

The authenticated candidate universe cannot govern the collector and OutputManager before activation; 161 candidate aliases are unreachable through the audited runtime path.

### BLOCKING: Activated authority can silently fall back to legacy

Any active-bundle resolution failure after pointer activation is swallowed and routed to the legacy resolver, leaving two effective authorities after cutover.

### BLOCKING: Activation authorization is forgeable from unauthenticated status JSON

The activation function accepts a hand-authored minimal authorization object and does not authenticate the underlying candidate-scoped reviews.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"BLOCKED","audit_type":"contract","auditor":"candidate_contract_review","blocking":3,"warning":0,"note":0,"study":"Codex_clean_maturity_flip_rolling_5m_productivity","audited_execution_composite_sha256":"899c5bb92391e4887224acd946bba5aed5d7ac2da9c8ce1f36cb30f01e7e5e59"}
<!-- AUDIT_SUMMARY_V2_END -->

## Blocking verdict

BLOCKED

The frozen bytes and closure are sound, but candidate governance is not reachable through the real collect path, active resolution can revert to legacy after cutover, and the review authorization can be synthesized without authentic audit evidence. Activation must not proceed.
