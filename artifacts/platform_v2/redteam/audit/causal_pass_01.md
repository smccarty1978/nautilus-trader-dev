# Look-Ahead & Timestamp Audit — Pass 01
**Date** 2026-09-03 · **Scope** research_workflow/host/outcomes.py, target_replay_oracle.py,
sessions.py, external_model_scoring.py, dataset_v2.py, host_runner.py, utils/session_boundaries.py,
grammar/compiler.py, grammar/spec.py, audit_packets_v2.py (base c366aac4..head 77e94d20) ·
**Scope hash** outcome stage composite `da458433c91ffad010e0e7da94fd50ebaff493f1d33079f8ba24502696c1cea0`,
collection stage composite `5c53e308e6a5735886cd7df4b5250975e7a74c8b2a31f114952d637ab5217dd1`
(from `audit_packet_causal.json.closure.stages`) · **Lint** not re-run (out of scope, proven by
preflight) · **Verdict** BLOCKED

## Summary            Critical: 1 · Warning: 2 · Note: 1

## Critical findings

### [C9/G2] `research_workflow/host/outcomes.py:326-331,377-382` and `research_workflow/target_replay_oracle.py:119-121,152-158` — `first_bar_at_or_after` + `expiry:"negative"` manufactures a directional label from a session-boundary data gap
**Failure path:** An arm declares `horizon_end_rule: first_bar_at_or_after` and
`expiry: "negative"` (both independently legal per `grammar/spec.py:147,157,189` — no cross-field
guard forbids the combination). If the arm's horizon end falls close enough to the censoring
session's close that **no bar exists** between `arm_end` and `session_close` (the historical
pre-2021-06-28 CME 15:15–15:30 CT halt is exactly this shape; also possible on any sparse/thin
tape), the first bar the kernel actually sees after `arm_end` is already `> session_close`. Both
implementations hit the `ts > session_close` branch *before* ever reading that bar's high/low:
kernel `outcomes.py:329-331` calls `_expire_arm`, which (`outcomes.py:377-382`) resolves
`NEGATIVE` when `arm.expiry == "negative"` — a directional loss label backed by **zero price
observation**. Oracle `target_replay_oracle.py:119-121` `break`s out of the loop on the same
condition, falls through to the same `horizon_expiry_policy` fallback (`152-158`), and returns the
identical `NEGATIVE`. Per the declared `resolution_precedence` (`SESSION_END > GAP > BARRIER_TOUCH
> HORIZON_EXPIRY`), a bar that never arrives before session close is a `SESSION_END`/data-gap
condition, not a `HORIZON_EXPIRY`; the correct disposition is `CENSORED`, not a manufactured
`NEGATIVE`. Because kernel and oracle share this defect verbatim, the parity harness cannot
detect it — this is the "population asymmetry" failure shape called out in repo memory
(`cross_event_elapsed_time_is_lookahead_at_the_earlier_event`): both sides agree and are both
wrong.
**Smallest fix:** In both `outcomes.py:329-331` and `target_replay_oracle.py:119-121`, when the
first post-horizon bar is already past `session_close`, resolve `CENSORED/"SESSION_END"`
unconditionally (never route through `_expire_arm`/`horizon_expiry_policy`), matching the
in-horizon branch's existing `SESSION_END` handling at `outcomes.py:349-351`. Add a regression
test alongside `test_redteam_v2_gap_precedence.py` with `expiry:"negative"` and a tape gap that
straddles `session_close` right at `arm_end`.

**Note on the audited study:** `golden_barrier_redteam`'s two arms both declare `expiry:"censor"`
(`audit_packet_causal.json` lines 212, 221) and `horizon_end_rule:"strict"` (line 196), so this
defect does not corrupt this specific study's labels — it is a latent defect in the shared,
general-purpose kernel/oracle that any other study composing `first_bar_at_or_after` +
`expiry:"negative"` would silently inherit through the same frozen "outcome" closure hash.

## Warnings

### [C9] `research_workflow/target_replay_oracle.py:169-241` — the composite/`conditions` oracle path never implements `first_bar_at_or_after` or the new gap-precedence check
`_replay_ordered_barrier_condition` (used by `replay_expression` for the `conditions`/
`ordered_barrier` composite grammar) reads no `horizon_end_rule` field at all and unconditionally
`break`s at `ts > horizon_end_ts` (line 217-218) — it never gained the `first_bar_at_or_after`
extension-bar logic or the gap-precedence fix that was added to `replay()` (lines 119-134) in this
same file/diff. Traced reachability: `grammar/compiler.py::_resolve_outcome` (the only compiler
that feeds `LabelOutcomeKernel`/`replay()`) never emits `conditions`/`required_forward_outcomes` —
it emits `arms`+`flip`. `replay_expression`/`_replay_ordered_barrier_condition` is exercised only
by the separate, pre-existing `target_expression.py`/`generic_collector.py`/`target_runtime.py`
pipeline (confirmed via `test_composite_target_expression.py` imports and the absence of any
`target_replay_oracle` reference in `host_runner.py`/`provider_host.py`). Not reachable from the
V2 grammar-compiled contract this study runs under, but `target_replay_oracle.py` is a single
shared module inside this study's frozen "outcome" closure (`audit_packet_causal.json` →
`closure.stages.outcome.files`), so the divergence travels with every seal that hashes it.
**Smallest fix:** thread `horizon_end_rule`/gap-precedence into `_replay_ordered_barrier_condition`
the same way, or have it raise on `first_bar_at_or_after` until implemented, so a future caller in
the legacy pipeline can't silently diverge from the kernel it will eventually share code with.

### [B2] `features/trackers/host_bindings.py:691` — sole production call site stamps `availability_ts == checkpoint_ts` for every input, making the RT-B2 refusal branch structurally unreachable
`FrozenExternalScoreBinding.derive()` is the only wired runtime caller of
`FrozenExternalModelScorer.score()`. It calls
`self._scorer.score(inputs, checkpoint_ts=ts, direction=direction, availability_ts={n: ts for n in surf})`
— every input's availability is stamped as exactly the checkpoint, and `score_evaluation_ts` is
never passed (defaults to `checkpoint_ts`, `external_model_scoring.py:80`). Consequently
`available_at_ns = max(latest_input_availability_ts, evaluation_ts)` collapses to exactly
`checkpoint_ts` on every call, so the new `available_at_ns > checkpoint_ts` refusal
(`external_model_scoring.py:83-87`) can never fire from this call site — only the unit-level
callers in `test_redteam_v2_model_authority.py::test_i/test_iii` exercise a genuine refusal. This
is a sound upper bound *only* because `row` is drawn from a candidate frame whose columns are
already causally gated elsewhere (Feature System V2 visibility rules) — B2's own mechanism
provides no independent backstop if that upstream guarantee is ever violated (e.g. a per-candidate
tracker ordering bug feeding `surf`).
**Smallest fix:** have the binding pass each input's actual per-column availability timestamp
(already known to row-assembly) instead of uniformly stamping `ts`, or add an explicit test/
comment asserting the upstream-gating invariant this call site depends on and is not itself
checking.

## Notes

### [C8] `research_workflow/sessions.py:172-180` — ETH post-segment start (`halt_end_ns`) not validated against `rth_close`
`session_windows()` computes the ETH post-RTH segment as `(halt_end_ns or rth_close_wall,
close_ns)` with no assertion that `halt_end_ns >= rth_close`. A reference table that passed the
sha256 fail-closed verification but carried a logically-wrong `halt_end_ns` earlier than the RTH
close would produce an ETH window overlapping the RTH window for that day — `CalendarSessionTable`
raises `CALENDAR_SESSIONS_OVERLAP` only within one session's own row list (RTH vs ETH tables are
built and validated separately via `rows_by_session`, `sessions.py:200-207`), so cross-session
overlap would not be caught. Not reachable under the documented halt convention
(pre-2021-06-28 halt is always 15:15→15:30 CT, i.e. after `rth_close`) and gated behind the
already-fail-closed table hash check — speculative hardening only.

## Referred to contract-checker
- `audit_packets_v2.py`'s `DELIVERABLES_BY_STAGE`/`deliverables_for_plan` single-sourcing from
  `lifecycle_v2.DELIVERABLES` (packet F1 remediation) is a completeness/deliverables concern, not
  causal — leaving it for contract-checker to confirm the mirror is exhaustive.
- `ScoredModelExpectSpec`/model-identity `expect` authentication (packet B1) is model-integrity
  declaration territory, out of this auditor's scope.

## Clean checks
A1-A5 (unchanged, not in diff), B1, C1 (authorized_years narrowing/expansion — well covered by
`test_redteam_v2_chronology.py`, unchanged file, not in diff), C8-core (DST spring/fall, early
close tightening, holiday no-window, legacy ETH fail-closed, half-open `(open,close]` boundary
attribution — `sessions.py`, `test_redteam_v2_sessions.py`), F1-F4 (calendar derivation is
close-time based, explicit `zoneinfo`, named-zone DST-safe), G1 (reference-table fail-closed hash
verification, `dataset_v2.py:load_reference_tables`), B2-primitive (`max(inputs, evaluation)`
computation and refusal logic in `external_model_scoring.py:78-96` itself — correct and
well-tested at the unit level), C9 in-horizon/entry-bar/strict-rule/adjacent-bypass branches
(`test_redteam_v2_gap_precedence.py` a/b/c/e/f all pass and reason correctly).

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "causal", "study": "golden_barrier_redteam", "auditor": "lookahead-auditor (causal pass 01, redteam-hardening)", "audited_execution_composite_sha256": "33b67e11c133b87c3cbfa4c6c619c5720d72a08d0a3384ed161419f619d444e3", "critical": 1, "warning": 2, "note": 1}
<!-- AUDIT_SUMMARY_V2_END -->
