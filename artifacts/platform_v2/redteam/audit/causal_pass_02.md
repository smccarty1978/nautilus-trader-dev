# Look-Ahead & Timestamp Audit — Pass 02
**Date** 2026-09-03 · **Scope** research_workflow/host/outcomes.py,
research_workflow/target_replay_oracle.py, research_workflow/external_model_scoring.py,
features/trackers/host_bindings.py (base c366aac4..head 5ff9bc55, diffed against
`diff_causal_surfaces.patch`) · **Scope hash** execution composite
`95695753d5267bf985ff789058fa4ccafea28c00294095780e3720ba3b4208a4`
(`audit_packet_causal.json.identity.execution_composite_sha256`, matches
`.closure.composite_sha256` and `.tests.execution_composite_sha256`) · **Lint** not re-run
(no new lint-scoped surface; `audit_packet_causal.json.tests` = PASS, 0 failed) ·
**Verdict** CLEAR

## Summary            Critical: 0 · Warning: 0 · Note: 1

## Prior findings adjudicated

| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | `[CRITICAL C9/G2]` kernel `outcomes.py:329-331` + oracle `target_replay_oracle.py:119-121` — `first_bar_at_or_after` + `expiry:"negative"` manufactures NEGATIVE from zero in-session observation | **FIXED** | Both sites now unconditionally resolve `CENSORED/"SESSION_END"` before touching `_expire_arm`/`horizon_expiry_policy` — kernel `outcomes.py:333-335` (`self._resolve_arm(p, i, CENSORED, p.session_close, "SESSION_END"); continue`), oracle `target_replay_oracle.py:128-129` (`return {"disposition": "CENSORED", ..., "censor_reason": "SESSION_END"}`), both **before** the gap check and the touch/expiry evaluation. Regression test `test_redteam_v2_gap_precedence.py::test_expiry_negative_first_bar_at_or_after_session_gap_is_censored_not_negative` reproduces the exact pass-01 fixture (`expiry:"negative"`, gap straddling `session_close` at `arm_end`) and asserts `("CENSORED","SESSION_END")` in both kernel and oracle. Control `test_expiry_negative_strict_rule_horizon_elapsed_in_session_is_still_negative` proves the unambiguous in-session case still resolves `NEGATIVE` — the fix narrows the failure path, it does not disable `expiry:"negative"`. |
| 2 | `[WARNING C9]` `target_replay_oracle.py:169-241` — legacy `conditions`/`ordered_barrier` composite path (`_replay_ordered_barrier_condition`) never gained `first_bar_at_or_after`/gap-precedence, but shares the frozen "outcome" closure hash | **FIXED** (documentation + guard, per pass-01's own alternative remedy) | `_replay_ordered_barrier_condition` (`target_replay_oracle.py:177-201`) now carries an explicit "LEGACY V1 COMPOSITE PATH — frozen semantics, not reachable from the V2 grammar-compiled contract" docstring naming the exact unreachability argument pass-01 traced. `test_v2_host_path_never_routes_to_legacy_composite_replay` (source-inspects `outcomes.py` and `replay()` for any reference to `_replay_ordered_barrier_condition`/`replay_expression`) makes that unreachability a regression-checked invariant rather than a one-time trace. `grammar/compiler.py::_resolve_outcome` is unchanged by this diff — still emits only `arms`+`flip`. |
| 3 | `[WARNING B2]` `features/trackers/host_bindings.py:691` — sole production caller stamps `availability_ts == checkpoint_ts` for every input and never passes `score_evaluation_ts`, so the RT-B2 refusal branch was structurally unreachable from the wired call site | **FIXED** | `derive()` (`host_bindings.py:698-705`) now explicitly passes `score_evaluation_ts=ts` and `availability_source="checkpoint_ts_upper_bound"` (documented provenance label, not a silent default). `external_model_scoring.py` now computes `available_at_ns = max(latest_input_availability_ts, evaluation_ts)` and refuses when `available_at_ns > checkpoint_ts` (`external_model_scoring.py:114-121`), recording both on `DerivedScoreObservation`. Reachability through the binding itself (not just the scorer unit) is proven by `test_redteam_v2_model_authority.py::test_binding_refuses_a_synthetic_availability_later_than_checkpoint`, which monkeypatches the scorer to simulate a late per-input availability and asserts `ExternalModelScoringError` propagates out of `binding.derive()` uncaught — confirmed `derive()` (`host_bindings.py:682-706`) has no try/except around the `score()` call. Residual: production availability is still a conservative upper bound (`ts` for every input), not true per-column timestamps — pass-01 offered this as an acceptable alternative ("or add an explicit test/comment asserting the upstream-gating invariant"); the invariant is now both documented and test-proven reachable, so this closes at WARNING-remedy level. |
| 4 | `[NOTE C8]` `sessions.py:172-180` — ETH `halt_end_ns` not validated against `rth_close` | **NOT ADDRESSED** (unchanged; `sessions.py` is outside this fix commit's file set) | Still speculative-only per pass-01 (gated behind fail-closed table-hash verification, not reachable under the documented halt convention). Non-blocking; carried forward, not re-itemized as new. |

## Notes

### [C9] `research_workflow/host/outcomes.py:326-338`, `target_replay_oracle.py:119-131` — `expiry:"censor"` arms change `censor_reason` from `"TIMEOUT"` to `"SESSION_END"` under the same trigger condition
**Disposition-change inventory for this fix, precisely bounded to `horizon_end_rule: "first_bar_at_or_after"` AND the first post-horizon bar the kernel/oracle actually observes lying beyond `session_close`:**

| Arm `expiry` | Before | After | Disposition changed? | Reason changed? |
|---|---|---|---|---|
| `"negative"` | `NEGATIVE` (manufactured, zero observation) | `CENSORED` / `"SESSION_END"` | **Yes** — this is the fix | Yes |
| `"censor"` | `CENSORED` / `"TIMEOUT"` | `CENSORED` / `"SESSION_END"` | No | Yes |

No other branch is touched: the in-horizon per-bar path (`outcomes.py:353-358`, unchanged), the `strict` `horizon_end_rule` path (`outcomes.py:323-325`, unchanged, still routes straight to `_expire_arm` without a post-horizon observation because `strict` never reads an extension bar), and the entry-bar-beyond-close path (`outcomes.py:314`, unchanged, already resolved `SESSION_END` at arm initialization pre-fix) are all outside this diff's hunks and are exercised unchanged by `test_strict_rule_unaffected_by_gap_precedence_change` and `test_entry_bar_itself_beyond_session_close_is_censored_session_end`. The `"censor"`-arm reason relabel is a correctness improvement consistent with the study's own declared `resolution_precedence: [SESSION_END, GAP, BARRIER_TOUCH, HORIZON_EXPIRY]` (`audit_packet_causal.json.outcome.resolution_precedence`) — `TIMEOUT` was itself a mischaracterization under that precedence — but any downstream code keying behavior off the literal string `"TIMEOUT"` vs `"SESSION_END"` for `"censor"`-arm rows under `first_bar_at_or_after` would observe a value change. This study's own two arms (`tp1_sl1`, `tp1_sl05`) both declare `horizon_end_rule: "strict"` (`audit_packet_causal.json.outcome.horizon_end_rule`), so neither this relabel nor the original CRITICAL was ever live for `golden_barrier_redteam`'s own labels — the finding was, and remains, about the shared kernel/oracle that other studies compose.

## Referred to contract-checker
(none new this pass)

## Clean checks
A1-A5, B1-B10, C1-C3, F1-F4, G1-G4, H1-H4 unchanged from pass 01 scope; `test_host_core.py::test_first_bar_at_or_after_never_crosses_the_session_close` and `test_redteam_v2_gap_precedence.py` (14 tests: a-f gap-precedence + 3 C9/G2 regression + 1 legacy-path guard) all assert the corrected precedence in both kernel and oracle in lock-step — no divergence between the two independent implementations post-fix (kernel/oracle parity preserved, so this repair does not reintroduce the "population asymmetry" failure shape that hid the original defect). `test_redteam_v2_model_authority.py` B1 (10 tests) and B2 (5 tests, including the 2 new binding-level tests) all pass per file review.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "study": "golden_barrier_redteam", "auditor": "lookahead-auditor (causal pass 02, redteam-hardening)", "audited_execution_composite_sha256": "95695753d5267bf985ff789058fa4ccafea28c00294095780e3720ba3b4208a4", "critical": 0, "warning": 0, "note": 1}
<!-- AUDIT_SUMMARY_V2_END -->
