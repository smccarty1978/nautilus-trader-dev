# Causal audit — pass 03 (delta) — nq_va_multitf_trade_state_geometry

audit_type: "causal"

Delta pass over `pass_02` (CLEAR). New execution composite
`1c1b1b8a9493dcfe08c4a78beae1c2fcb6edab5982edd0dab763d5c75b9cdbc0`, plan
`c56d0ff18e15cd84bc93665ac3dfbcecf6d7f168fc0518f40b6435465a73e59e`. Tests 158 passed / 0
failed. Lint: 0 critical / 0 warning (preflight CLEAR, out of scope — not re-reported).

**Scope of this pass**: exactly the composite-truncate repair (commit `4139ae15` on
`chore/composite_truncate`, merged `8c3ad94d`) — `research_workflow/host/outcomes.py`,
`research_workflow/target_replay_oracle.py`, and the new
`research_workflow/tests/test_composite_session_end_truncate.py`. `study.yaml` is
byte-identical to the seal audited in pass_02 (verified by the packet's own diff); the
compiled-plan delta is 8 closure-hash lines only. Everything else carries forward.

---

## Δ1 — `session_end_rule: truncate` implemented for `kernel: barrier` / `kernel: composite`

Root cause and fix are exactly as described in `research_decision.yaml`
(`collection_v3_gate_failure`): pre-repair, `on_bar`'s arm-setup line and `_complete`'s
composite-flip branch both censored `SESSION_END` **at entry resolution**, the instant
`arm_end`/`flip_end` (T + 24h) exceeded `session_close` (~23h trading day) — true for every
row, hence 14,549/14,549 CENSORED with zero resolved outcomes.

Repaired behaviour (`outcomes.py:405-421` arm setup, `:351-361` `_flip_effective_end`,
`:534-559` `_complete`): `effective_end = min(horizon_end, session_close)`; the arm/flip
child is never decided before a bar is observed; a touch at or before the effective end
resolves at its own first-passage instant; only reaching the effective end untouched
produces `CENSORED SESSION_END`, stamped at the close, via `_expire_arm`'s
`arm_truncated` branch (never `TIMEOUT`, never `expiry: negative`).

**Q1 — forward exposure at T.** `effective_end` can only ever equal `horizon_end` or
`session_close`, both `> T` by construction (`session_close` is `session_table.session_close(T)`,
always the close of the session containing T or the next one). Widening never pulls the window
boundary backward past `T`, and the entry reference (`next_bar_open`, first bar with
`ts_init > T`) and the touch scan's starting point (`entry_ts`) are unchanged. **CLEAR** — no
candidate is exposed to anything at or before its own decision epoch.

**Q3 — resolution precedence SESSION_END > GAP > BARRIER_TOUCH > HORIZON_EXPIRY.** Verified
self-consistent across both rules: under `censor`, SESSION_END is decided *before* any GAP/touch
check (the window is void from birth, so nothing else is evaluated) — top of the chain,
unchanged. Under `truncate` there is no "void from birth" case; `SESSION_END` there is the
*truncated-horizon-expiry* outcome and correctly sits at the bottom of the chain: `on_bar:445-465`
checks `horizon_gap` (→ GAP) **before** calling `_expire_arm` (→ SESSION_END), so an unobserved
gap spanning the truncated end still wins over SESSION_END, exactly as `test_a_tape_gap_still_
outranks_session_end_under_truncate` asserts. `post_close` correctly degrades
`first_bar_at_or_after` to `strict` so an out-of-session bar's OHLC is never touch-eligible
(`outcomes.py:448-453`). **CLEAR.**

**Q4 — cross-candidate/cross-session state leak from longer pending life.** `prev_ts`,
`arm_end`, `session_close` are all per-`_Pending` scalars, reset only at `open()`/entry
resolution; `_flip_queue` is populated only when `contract.kernel == "flip"` (`outcomes.py:305-306`)
and is never touched by the composite path, so no ordering assumption from the flip-kernel queue
leaks into composite candidates that now live up to ~23h. `_complete`'s SESSION_END branch uses
the crossing bar's **timestamp only** (`now_ts >= p.session_close`) to detect the boundary and
stamps the disposition at the fixed `p.session_close`, never at that bar's price — no OHLC from
past the boundary is read to decide the flip child. **CLEAR.**

**Q5 — inert for `censor`/`ignore`/`kernel: flip`.** `censor`: the `if truncate: ... else:
self._resolve_arm(..., "SESSION_END")` branch at `outcomes.py:410-421` reproduces the exact
pre-existing at-setup line verbatim when `truncate` is `False`. `ignore`:
`session_end_censoring=False` ⇒ `session_close=None` at `open()` ⇒ every `p.session_close is
not None` guard is false throughout, so no SESSION_END logic of either flavour ever fires
(`test_ignore_still_sees_past_the_close`). `kernel: flip`: `_flip_effective_end` (the only new
composite-side helper) is called only from the composite `on_flip` branch and from `_complete`
guarded by `self.c.kernel == "composite"`; the flip-kernel's own truncate branches
(`on_flip:313-340`, `_sweep_flip`, `finalize`) are pre-existing and untouched by this diff.
Regression proven by `test_censor_still_voids_an_overlong_window_at_the_close`,
`test_censor_is_unchanged_for_a_horizon_that_fits_inside_the_session` (additivity: censor and
truncate agree exactly when the close doesn't bind). **CLEAR.**

## Δ2 — `target_replay_oracle.replay` gets the identical rule (+24 lines)

`session_end_rule` is read off the barrier/candidate/contract (`:80-82`), and the same
`min(horizon_end, session_close)` truncation, same GAP-before-SESSION_END-before-HORIZON_EXPIRY
precedence, and the same `first_bar_at_or_after`-degrades-to-`strict` past the close are
reproduced independently (`:118-207`). Cross-checked against the production kernel byte-for-byte
by `test_kernel_agrees_with_the_independent_replay_oracle_under_truncate` (0 mismatches over an
8-touch mixed path). The frozen V1 `_replay_ordered_barrier_condition` is explicitly and
correctly **not** touched (its own docstring asserts it is unreachable from the V2 host path;
`test_redteam_v2_gap_precedence.py` guards this). **CLEAR.**

**Note:** the oracle's `replay()` verifies barrier-arm disposition/censor_reason only — it does
not independently compute a C1 terminal exit price/timestamp, so the exit-fill question below
(Δ3) has no second-implementation cross-check, only kernel-internal unit tests.

## Δ3 — C1 terminal exit fill can now be sourced from a bar after the truncation boundary

**Q2, decided: WARNING, not CRITICAL.** Pre-repair, the composite C1 exit-fill code
(`outcomes.py:425-430`, unchanged by this diff) was dead for this contract shape: every 24h-horizon
composite candidate was censored at entry before `p.flip_ts` could ever be set, so `p.exit_ts`
was always `None`. Post-repair, a flip landing at or just before the truncated end **does** set
`p.flip_ts`, and the exit fill is still unconditionally "OPEN of the first bar strictly after
`flip_ts`" with **no session-boundary check** — only the pre-existing `max_gap_ns` (300s) guard
(`outcomes.py:426`: `(ts - p.flip_ts) > c1.max_gap_ns` → `exit_reason = "GAP"`). For a flip inside
the last ~5 minutes before the TRADING_DAY close, the next bar strictly after it could be the
first bar of the *next* Globex trading day, across the nightly maintenance break.

This is not look-ahead (the flip and the fill are both causally later than `T`), and it is
empirically safe: `sessions.py` documents the nightly break as time genuinely absent from the
tape ("closed — outside every trading day"; `FILL_SCOPE` explicitly never fills it), so the real
gap between a TRADING_DAY close and the next available bar is on the order of tens of minutes to
hours — always `> 300s` — meaning the `max_gap_ns` check reliably classifies this case as `GAP`
before a cross-session price is ever read. But that safety is an **empirical property of the
calendar data, not an explicit invariant enforced in code** (no `ts <= session_close` check
gates the exit fill), and no test in this delta or `test_c1_terminal_outcome.py` exercises
"flip in the last `max_gap_ns` seconds before the close, next bar after the nightly break" to
prove the GAP branch actually fires there. Matches the severity definition's
"enforced-in-practice-but-not-in-code invariant" — **WARNING, not blocking**: it cannot change
the current study's collected numbers (the guard is real and the calendar gap always exceeds it
on this dataset), but it is an unenforced assumption the next truncate-composite study should not
inherit silently.

### WARNING C-6 — C1 exit fill relies on calendar-gap duration, not an explicit session check, to avoid a cross-session fill on a late flip
**Failure path:** a qualifying flip lands inside the final `max_gap_ns` (300s) window before the
TRADING_DAY close; if a future dataset ever has `< 300s` between one TRADING_DAY row's close and
the next bar (e.g. a truncated/partial calendar gap, or a `max_gap_ns` raised above the true
break duration), `terminal_exit_price`/`terminal_gross_pnl_*` would be filled from a bar in the
next trading session.
**Smallest fix:** add `ts > p.session_close` as an explicit alternative trigger (alongside the
existing `max_gap_ns` check) for `exit_reason = "GAP"`/`SESSION_END` in the C1 exit-fill block at
`outcomes.py:425-430`, and add the missing "flip just before the close" oracle/kernel parity test.
Not required before this seal proceeds — no failure path exists against the current calendar.

## Δ4 — Q6: SESSION_END's meaning under `truncate` vs. the frames pass_01/pass_02 cleared

Under `censor` (never collected for this study) `SESSION_END` meant "window voided by
construction, zero observation." Under repaired `truncate` it means "observed in full to the
close, never touched" — a materially different, information-bearing disposition. This is not a
new defect (it is exactly what `session_end: truncate` was always documented to mean in
`study.yaml:151-169`) and it is disclosed at length in `research_decision.yaml`'s
`collection_v3_gate_failure` block and the new test file's module docstring
("a normal population is a MIXTURE"). No action needed; flagged here only because the question
was asked directly — **not a finding**.

## Q7 — pass_02 NOTE C-4 / NOTE C-5

Untouched. This delta is confined to `outcomes.py` / `target_replay_oracle.py` / the new test
file; it does not touch `study.yaml` chronology, warmup, or any discovery/replication boundary.
Both carry forward unchanged.

---

## Prior findings adjudicated

| # | Finding | Status | Evidence |
|---|---|---|---|
| C-1 | RTH-close selection against runner tail (pass_01 WARNING) | Resolved (pass_02 Δ1) | unchanged this pass |
| C-4 | Discovery/replication split is contractual (pass_02 NOTE) | Unchanged | Δ has no chronology/model surface |
| C-5 | Shallow 1h warmup at two partition edges (pass_02 NOTE) | Unchanged | Δ has no warmup surface |

## Carried forward from pass_01 / pass_02 (unchanged surfaces)

Population, executable `next_bar_open` entry, opposite-flip terminal definition, the three
independent clocks, MTF causality (derived `closed_window` buckets on `nq_1s`, external `nq_1m`
`strictly_before`), geometry reconstructability, gross-only economics, chronology
(`train: [2023, 2024]`, `prohibited: [2025, 2026]`), `model: null`: all CLEAR/adjudicated in prior
passes and untouched by this delta.

## Referred to contract-checker

- Compiled-plan delta (8 closure-hash lines vs. sealed plan) and the C1 exit-fill's missing
  second-implementation coverage in `target_replay_oracle.py` are deliverable/test-completeness
  questions, not causal ones.

## Clean checks

A1-A5, B1-B10, C1-C3, F1-F4, G1-G4, H1-H4 clean (unchanged surface; re-verified where this
delta's diff touches touch-eligibility (H1/H2), entry/exit fill convention (H4), and session
boundary handling (F1/F2) — see Δ1/Δ3 above).

## Verdict

**CLEAR.** Zero critical, one warning (C-6, non-blocking — no failure path against the current
calendar/contract), zero new notes. The repair correctly implements `truncate` for
`kernel: barrier`/`composite`, is inert for `censor`/`ignore`/`kernel: flip`, introduces no
look-ahead, and is independently cross-checked by the replay oracle for the barrier-arm surface.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "causal", "audited_execution_composite_sha256": "1c1b1b8a9493dcfe08c4a78beae1c2fcb6edab5982edd0dab763d5c75b9cdbc0", "auditor": "claude-causal-pass03", "critical": 0, "note": 0, "study": "nq_va_multitf_trade_state_geometry", "verdict": "CLEAR", "warning": 1}
<!-- AUDIT_SUMMARY_V2_END -->
