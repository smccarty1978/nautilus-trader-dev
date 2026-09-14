# Look-Ahead & Timestamp Audit — Pass 04 (delta)
**Date** 2026-09-14 · **Scope** delta since pass 03: `compiled_plan.json` `outcome.session_end_rule: censor -> truncate` (only substantive delta; re-read `research_workflow/host/outcomes.py` on_flip/_sweep_flip/finalize truncate branches, `research_workflow/grammar/compiler.py:242-269,1600-1621` visibility-default logic) · **Scope hash** `plan_sha256 ed2b9dfa279902944a1c02fc588bf68b45bd72cdd554bb37df792574f75c421c`, `execution_composite_sha256 041379f7e433a637beba1e687fd70124f7d0c79a34e010c6b6de5cc53d13da7c` (unchanged from pass 03) · **Lint** `audit/preflight.json` reports `status: CLEAR`, 0 critical/0 warning, but is **stale**: `plan_sha256` inside it is still `bed51b460286e18d...` (pass 03's plan), not `ed2b9dfa...` — see Warning below · **Verdict** CLEAR

`audit_type: causal`
`study: nq_mtf_regime_atlas_pilot2023`
`audited_execution_composite_sha256: 041379f7e433a637beba1e687fd70124f7d0c79a34e010c6b6de5cc53d13da7c`
`auditor: claude-lookahead-auditor-pass04`

## Summary            Critical: 0 · Warning: 4 · Note: 1

## Prior findings adjudicated
| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | pass 03 R2/R4 absent (WARNING) | **OPEN, carried** | `audit/readiness.json` unchanged (same `generated_at_utc` 2026-09-12T13:34:32Z, same checks R1/R3/R5/R8/R9/R10 only, still `plan_sha256 bed51b46...`). |
| 2 | pass 03 `[B-scope/prose]` hardcoded `same_timestamp_rule`/invariants text (WARNING) | **OPEN, carried** | `compiler.py:1621` still emits the constant string unconditionally; no diff to this site since pass 03. |
| 3 | pass 03 `[B9]` `bar_volume` 1s-tracker/1m-cadence mis-scale (WARNING) | **OPEN, carried** | `features/trackers/ohlcv_delta.py`, `study.yaml:89,93` untouched by this delta. |
| 4 | pass 03 `session_end: censor` censored 100% of candidates, referred to contract-checker | **RESOLVED (mechanism), reachability not re-verified** | `session_end_rule` now `truncate`; `outcomes.py:267-284` gives POSITIVE reachability within-session. Terminal-label reachability numbers are contract-checker's C4, not re-derived here. |

## Critical findings
None.

## Warnings

### [C1-C3/governance] `audit/preflight.json`, `audit/readiness.json`, `artifacts/preexec_audit_seal.json`, `audit/frozen_execution_manifest.json`, `artifacts/smoke_acceptance.json`, `artifacts/replay_closure_trace.json` — all six still bound to the superseded plan hash
**Correction to packet Facts:** the packet states preflight "regenerated it at b3b45d4c" — false. All six artifacts carry `plan_sha256 bed51b460286e18d...` (pass 03's, `generated_at_utc 2026-09-12T13:34:...`); the compiled plan on this branch head is `ed2b9dfa279902944a...` (`compiled_plan.json:1928`). None was regenerated after the `censor->truncate` edit.
**Why not CRITICAL / independently checked:** `session_end_rule` is an outcome-kernel parameter, not a column-schema field — `outcome.observation_columns` (`compiled_plan.json:1899-1913`) is disjoint from every candidate/feature id in `availability.rows` (trackers `regime_*`, `excursion_1m`, feature rows) under both values, so `FORWARD_OUTCOME_GUARD`/`leaked_outcome_columns:[]` would almost certainly still hold — but this is my inference from direct inspection, not a fresh gate run, and the gate's `CLEAR` cannot be cited as proof for the plan actually on disk.
**Smallest fix:** re-run preflight/readiness/seal generation against `ed2b9dfa...` before treating `b3b45d4c` as audited-and-sealed.

### [carried] R2/R4 still not proven on real bars for this plan
Unchanged from pass 03; the epoch/visibility surface this delta touches (none — see Note) does not narrow this gap.

### [carried] `compiler.py:1621` hardcoded `same_timestamp_rule` / invariants text
Unchanged from pass 03; not touched by this delta.

### [carried] `bar_volume` 1s-tracker vs 1m-cadence mis-scale
Unchanged from pass 03; not touched by this delta.

## Notes

### [N1] at_epoch scope re-confirmed by default-assignment logic, not a literal plan diff (no shell/git tool in this session)
Could not run `git show c84b9ad1:...` (no Bash tool available this session); substituted source inspection, which is at least as strong here: `compiler.py:259` sets `visibility = "at_epoch" if role == "execution" else "strictly_before"` for **every** stream unconditionally at first assignment — so all 9 `role: execution` streams (`nq_1s/5s/30s/3m/5m/15m/30m/1h/4h`) are `at_epoch` by that rule alone, independent of cadence. `nq_1m` is the only `role: context` stream in this plan; its `at_epoch` value can only come from `_mark_epoch_bearing_stream` (pass 03's finding, one call site, keyed to `population.cadence.stream`). Availability rows: only `regime_1m` and `excursion_1m` (both `stream: nq_1m`) inherit the flipped value (`compiled_plan.json:21-28,77-84`); every other tracker row sits on an execution stream already `at_epoch` regardless. Feature rows are hardcoded `at_epoch` (`compiler.py:1614`) — carry no scope information, confirmed. **Conclusion unchanged from pass 03: single, scoped override site.**

## Referred to contract-checker
- Terminal-label (POSITIVE) reachability under `truncate` for the real 2023 tape — mechanism is causally sound (see Clean checks) but the actual resolved/censored split is a completeness question, contract-checker's C4.
- `plan_sha256` mismatch across seal/manifest/smoke-acceptance artifacts (Warning above) also bears on lifecycle-state validity — contract-checker's scope for whether `b3b45d4c` may legitimately be "READY_TO_SMOKE".
- gap_inventory G0/G3-G7 and `stage: collect` — unchanged from pass 03.

## Clean checks
- **`session_end_rule: truncate` — causally sound.** `on_flip` (`outcomes.py:267-276`): a qualifying flip resolves POSITIVE at `flip_ts` only via the `elif` reached after the `flip_ts > p.session_close` branch is exhausted, i.e. only when `flip_ts <= session_close`; a flip observed after the close censors at the close (a pre-known calendar timestamp, not derived from the flip's price/time). `_sweep_flip` (`:453-481`) retires front-of-queue candidates only once a bar's `ts_init` has actually reached/passed `flip_end` or `session_close` — no resolution fires before the observation that proves it. `finalize` (`:484-497`) stamps unresolved end-of-data candidates `SESSION_END`/`session_close` (truncate) using only the pre-known calendar boundary, or `DATA_END`/`now` — no post-`now` price information is read either way.
- **Truncate touches outcome/observation columns only.** `on_flip`/`_sweep_flip`/`finalize` write exclusively `p.flip_state/flip_at/flip_reason/flip_ts`, which feed only `outcome.observation_columns` (`compiled_plan.json:1899-1913`). No candidate or feature column is written from this code path; features/trackers are computed in `strategy.py`/`host_bindings.py`, untouched by this delta.
- **Kernel-open timing unaffected.** `open()` (`outcomes.py:242-249`) is unchanged; a candidate still opens only at `T` with no pre-`T` read, per pass 03 C1-C3.
- **`session_close` is calendar-derived.** `self.session_table.session_close(T)` (`outcomes.py:246`) — `sessions.py` unchanged since pass 03 (CLEAN, R3 PASS, digest `e577a361...`); not touched by this delta.
- **at_epoch relaxation scope — CLEAN**, see N1.
- **A1-A5, B1-B10 (less carried B9), C1-C3, F1-F4, G1-G4, H1-H4** otherwise clean at the plan/closure level for this delta; execution composite unchanged, chronology unchanged (`train [2023]`, `prohibited [2026]`).

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "causal", "audited_execution_composite_sha256": "041379f7e433a637beba1e687fd70124f7d0c79a34e010c6b6de5cc53d13da7c", "auditor": "claude-lookahead-auditor-pass04", "critical": 0, "note": 1, "study": "nq_mtf_regime_atlas_pilot2023", "verdict": "CLEAR", "warning": 4}
<!-- AUDIT_SUMMARY_V2_END -->
