# Causal audit — pass 02 (delta) — nq_va_multitf_trade_state_geometry

Delta pass over `pass_01`. New composite `6bcee4347b33ab0d`, plan `247755a85abbf8fc`
(was `346c71526660948d` / `82b230f28f71c69c`). Tests 158 passed / 0 failed.

Only what changed is re-audited; everything else carries forward from pass_01, which was CLEAR.

---

## Δ1 — outcome session RTH → TRADING_DAY — CLEAR, and it closes WARNING C-1

`session.censor_session` is now `TRADING_DAY`; `population.session` remains `RTH`;
`session_end` remains `truncate`.

This is the fix for pass_01's WARNING C-1. RTH still decides who is a candidate and when the
fixed-time checkpoints fire, so the population definition is untouched. What changed is only the
outcome window: a lifecycle may now run past 15:15 CT to its natural opposite 1m flip, bounded by
the Globex trading day.

Causally this is **more** conservative about truncation and no less conservative about
information: widening the observation window forward cannot expose a candidate to anything before
its own decision epoch. The trading-day table is the dataset's own committed calendar
(`reference_digest e577a36165abd690`, unchanged from pass_01), and `TRADING_DAY` is exactly the
censoring authority the comparable atlas study uses. `session_end: truncate` remains correct: the
close ends the window rather than voiding it, so a flip at or before the close resolves at its own
instant.

Residual: a lifecycle still unresolved at the trading-day close is censored `SESSION_END` at the
close. That is a real bound, now at ~23h rather than ~6.75h, and it is self-reporting.

## Δ2 — chronology `train: [2023]` → `[2023, 2024]`, `dev: []` — CLEAR on causality, see K-note

No year moved into or out of the authorized set in a way that opens protected data: 2025 and 2026
remain `prohibited` and no stage reads them. 2024 moves from `dev` to `train`.

The causal question is whether 2024 can influence anything computed on 2023. It cannot, mechanically:
`model: null`, no fit, no tuning, no threshold, no feature selection, no derived input. There is no
parameter in this study for a second year to leak into. Each year is collected into its own
partition (`_work/controller/partitions/train/<year>/`) and the partitions are concatenated at
merge with per-year identity retained.

`assert_oos_open` is now vacuous rather than load-bearing, because `dev` is empty. The
discovery/replication separation is therefore a **contract obligation, not a runtime gate** — see
NOTE C-4.

## Δ3 — sink column parity and the merge persisted-schema assertion — CLEAR

`TERMINAL_OBSERVATION_COLUMNS` is a single source of truth that both `LabelOutcomeKernel` and the
compiler build from, so the kernel's `observation_columns` (which the sink buffers from) can no
longer drift from the plan's. Verified in the plan: 93 observation columns, 15 of them
`terminal_*`, and `observed_seconds` is still the last column (A5's invariant holds).

`merge()` now fails with `MERGE_PERSISTED_SCHEMA_MISSING_COLUMNS` if the persisted frame lacks any
declared observation column, and `identity.json` records both the declared and the persisted
column lists. No causal surface is touched by either change.

---

## Findings

### NOTE C-4 — the discovery/replication split is contractual, not enforced by a gate

With `dev: []` there is no `oos` door to hold 2024 shut, so nothing in the runtime stops a session
from reading 2024 while designing the atlas. The owner directed this configuration explicitly, and
forbade manufacturing a dummy model and a fake TRAIN freeze to obtain an ML-oriented gate that this
study has no use for.

The mitigation is stated plainly in `research_decision.yaml.two_year_replication_protocol`: every
cohort definition, lifecycle class, transformation, statistic, table and atlas view must be
committed *before* any 2024 result is inspected, the commit being the audit trail; the years are
not pooled until the year-by-year result is visible; and any post-2024 finding is labelled
EXPLORATORY and cannot alter the replication verdict.

What is genuinely at risk is the honesty of the replication claim, not the integrity of any fitted
artifact — because there is no fitted artifact. Recording it as a NOTE rather than a WARNING
because the exposure is procedural, bounded, declared, and directed.

### NOTE C-5 — pass_01 NOTE C-2 (shallow higher-timeframe history) now applies at two partition edges

Warmup is unchanged (`days_before_partition: 5`, `max_warmup_seconds: 50400`, `nq_1h: 14` bars).
The 2024 partition has its own warmup boundary, so the same shallow-1h-history effect at the start
of a partition now occurs twice. Candidate emission and target generation remain off during warmup.
Immaterial descriptively, but a year-over-year comparison should not read the first hours of either
partition as if 1h regime age were fully matured.

---

## Carried forward from pass_01 (unchanged surfaces)

Population definition, executable `next_bar_open` entry, opposite-flip terminal with executable
first-bar-open exit, the three independent clocks, MTF causality (derived `closed_window` buckets
re-pointed to `nq_1s`, external `nq_1m` held `strictly_before`), geometry reconstructability, and
gross-only economics: all CLEAR in pass_01 and untouched by this delta.

## Verdict

**CLEAR.** Zero critical, zero warning, two notes. pass_01's WARNING C-1 is resolved by Δ1.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "causal", "audited_execution_composite_sha256": "6bcee4347b33ab0d0c82ccd0cfd904b0a2ed0d269091c84b2718c4b1ad065853", "auditor": "claude-causal-pass02", "critical": 0, "note": 2, "study": "nq_va_multitf_trade_state_geometry", "verdict": "CLEAR", "warning": 0}
<!-- AUDIT_SUMMARY_V2_END -->
