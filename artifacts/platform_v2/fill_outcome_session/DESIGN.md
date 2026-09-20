# chore/fill_outcome_session — C0: fix the calendar-aware fill

Branch `chore/fill_outcome_session` off `main` `d83be2fd`. Supersedes nothing; continues
`artifacts/platform_v2/bucketing_and_gate/DESIGN.md` (A1 built the fill; this fixes its scope).

**Session 1 scope: C0 only.** C1–C4 (outcome-to-next-flip, terminal-checkpoint op, session-bucket
feature, regimes-alive) and B1–B4 are NOT started. See *Handoff* at the bottom.

---

## The defect

`sessions.py` materialized the dataset's TRADING_DAY rows and `build_session_table` attached them as
`table.trading_day`; `HostCore` passed that straight to `StreamMux(trading_days=...)` as the fill
scope. But a TRADING_DAY row is **the whole session, halt included** — that is what censoring at the
trading-day close means. So the mux filled any window overlapping a row, including:

- every pre-2021-06-28 15:15–15:30 CT maintenance halt (372 of them on NQ, 2020-01-02..2021-06-25);
- every data outage, e.g. the 21.25 h hole on 2020-12-31 and the 10.8 h hole on 2025-11-28.

2023 could never have shown this: it has no halt and no outage (max gap run 299 s). The pilot's
arithmetic ("5s bars = in-session seconds ÷ 5") held exactly and proved nothing.

## C0a — the fill scope excludes declared maintenance halts

New `research_workflow.sessions.FillScopeTable`, derived by `fill_scope_windows()`: the TRADING_DAY
rows minus the declared halts. `build_session_table` attaches it as `table.fill_scope`;
`table.trading_day` is unchanged and remains the censoring authority.

**The cut starts one second before `halt_start_ns`**, i.e. at 15:15:00 CT rather than 15:15:01. That
column marks the first *fully* halted second under an inclusive-last-valid-second convention, but:

- the Globex product halts **at** 15:15:00 CT;
- this repo's own session authority already excludes it — `session_windows(..., "RTH")` yields
  `(08:30:00, 15:15:00)`, whose window-overlap reading covers bar-open seconds `[08:30:00, 15:15:00)`,
  and the ETH post-close segment resumes at `halt_end_ns`;
- **no bar has ever been observed in that second**: 0 of 372 halted NQ sessions carry a 1s bar at
  15:15:00 CT (checked against the 2020 and 2021 catalog files).

Cutting from `halt_start_ns` instead would leave exactly one straddling window fillable per
timeframe — at 15m, a single flat bar standing for the entire halt. With the cut as implemented the
fill scope on a halted day is exactly `RTH ∪ ETH`.

## C0b — the fill scope excludes declared data outages

**An outage criterion was required, and the packet did not name one.** Every fillable empty window
lies inside *some* run of the `gaps` reference table by construction: the tape is native rows only,
so a quiet market IS a gap. NQ's gaps table has 19,186,323 runs, median 2 s. Subtracting all of them
is `empty_window: none`, not a fix.

Owner decision (2026-09-17): **a run of ≥ `rules.outage_gap_seconds` is an outage**, declared per
dataset, set to **7200 s** on `NQ_1S_V2`, `NQ_1S_V2_GLOBEX`, `ES_1S_V2`, `ES_1S_V2_GLOBEX`.

The threshold sits in an empirical cliff, not in the middle of a distribution:

| run | session | what it is |
|---|---|---|
| 79,208 / 79,203 / 79,201 / 76,505 s | 2025/2021/2024/2020-12-31 | whole-session absence |
| 75,601 s | 2026-04-30 | catalog end |
| 38,745 s | 2025-11-28 | 10.8 h hole |
| 21,844 s | 2020-06-30 | 09:10 CT → RTH close |
| 19,004 s | 2020-02-28 | 09:58 CT → RTH close |
| 7,200 s | 2020-07-01 | 17:00–19:00 CT exactly |
| — **threshold 7200** — | | |
| 4,867 / 4,462 / … s | 2020-03-16..18 | COVID limit-lock, ETH only — a real pinned-price state |
| 299 s | 2023 max | natural quiet |
| 119 s | 2022 max | natural quiet |

Nine runs are outages; the widest excluded run is 4,867 s. The March-2020 limit-lock stretches stay
**filled**: the market was locked at a price, not missing.

The rule is fail-closed at two layers:

- **compile** (`_require_outage_rule`, `compiler.py`): a dataset with a `sessions` calendar that a
  study derives a timeframe from must declare `rules.outage_gap_seconds` **and** a `gaps` reference
  table, or the compile stops with `SEMANTIC_DECISION_REQUIRED`. The value travels in
  `plan["session"]["outage_gap_seconds"]`, so a run cannot adopt a different rule than the audit saw.
- **runtime** (`resolve_calendar_session_spec`): no declared rule ⇒ **no fill scope at all**
  (`fill_scope: null`), so a stream declaring `zero_volume_in_trading_day` is refused with
  `TRADING_DAY_CALENDAR_ABSENT` rather than filling holes. This is also what lets a plan sealed
  before the rule existed replay untouched — it aggregates `complete_bucket` and never fills.

**Suppressed-window counter.** `ClosedWindowAggregator.windows_suppressed` counts, per reason, the
empty windows the scope excluded; `StreamMux.windows_suppressed()` reports it per stream and
`HostCore.stats()` emits `windows_suppressed: {stream: {halt: n, outage: m}}` beside
`empty_windows_published`. A closure (weekend / holiday / the nightly break) is **not** suppression
and is never counted — those are still skipped in one jump, not iterated. A window that overlaps both
a halt and an outage is attributed to the halt.

## C0c — derived-from-derived closed windows are refused

`StreamMux.__init__` raises `DERIVED_FROM_DERIVED_CLOSED_WINDOW` when a `closed_window` stream
aggregates another derived stream. The compiler never emits that layout, but its dry construction
(`require_calendar=False`) accepted one, and at runtime it dies mid-run with
`OUT_OF_ORDER_SOURCE_BAR` (the sweep runs before the child aggregator's output is applied). Because
the dry construction already maps any exception to a typed gap, this surfaces at compile as
`UNSUPPORTED_COMPOSITION`. Same family as the A4 pattern: compile accepted what runtime refuses.

---

## Gates (measured, not assumed)

| gate | result |
|---|---|
| Pre-2021 halt, zero filled windows at every timeframe | **met.** 5s **180**, 30s **30**, 3m **5**, 5m **3**, 15m **1** suppressed, `still-fillable = 0` at each — exactly the counts the audit reported as wrongly filled |
| 2020-12-31 outage receives zero filled windows; counter matches the gap duration | **met.** 5s: 16,103 → 623 filled, 15,300 suppressed (15,300 × 5 s = 76,500 s vs the 76,505 s run). 1h: 22 → 1 filled, 21 suppressed |
| 2023 fill unchanged | **met.** Whole year at 5s: **497,514 filled before and after**, `windows_suppressed = {halt: 0, outage: 0}`; same at 5m. (ESCALATE item: C0a does **not** touch 2023.) |
| shape_b sealed replay bit-identical | **met.** Same script, same plan, same catalog, only the module tree differs (`git worktree` at `d83be2fd` vs the branch): candidates `9d0580f18784c62c…`, observations `7b920d95cb01bf7e…`, **103,305 bars**, `nq_1s 100515 / nq_5s 10600 / nq_1m 2790 / nq_5m 54`, 162/162 rows — identical. Bars and per-stream counts also match the sealed smoke manifest. |
| N1 / N2 | unchanged — not touched this session |
| `cap generate --check` | `STATUS: OK`, 228 capabilities, 0 broken |
| `lint_host` | CLEAR |

The sealed-replay hashes above are this script's own digest (CSV of the returned frames, no
`primary_interval`), not the `6d49d2a8` / `b5c075da` pair in the bucketing_and_gate record — that
session's hashing procedure is not recorded, so the check here is a like-for-like before/after on one
procedure rather than a comparison to a number whose derivation is unknown. Bars (103,305) and the
per-stream breakdown do match the sealed manifest exactly.

**Method note, carried forward:** window-by-window comparison against an independent reference is the
standard for any change to the fill. Counts cancel; a year without halts or holes proves nothing.

## Tests

`research_workflow/tests/test_fill_scope.py` (11) — derivation, threshold, `skip_reason`
attribution, suppression counting per reason, closure-is-not-suppression, the mux report, C0c, the
no-rule-means-no-fill path, the compile gate (both refusals and the plan field), and a real-catalog
test (halt at five timeframes, the 2020-12-31 outage, and a 2023 month that must not move), skipped
when the catalog is absent.

Updated: `test_redteam_v2_sessions.py::_dataset_with_reference_tables` now declares
`rules.outage_gap_seconds` and `gaps` — the new compile gate fires on that fixture, correctly.

Targeted suites run: `test_fill_scope`, `test_host_core`, `test_grammar_v2`,
`test_trading_day_censoring`, `test_bucketing_and_gate`, `test_golden_fixture`,
`test_redteam_v2_sessions`, `test_lifecycle_v2`.

**Not run:** the broad `test_delta` gate. `--check-baseline` reports `BASELINE_INCOMPATIBLE`
(`BASELINE_COMMIT_MISMATCH`: baseline pinned at `c480d8af`, HEAD's merge-base is `d83be2fd`); the
baseline has 0 entries, so an all-pass broad run passes without consuming evidence. B1 (baseline
fail-fast) is exactly this problem.

---

## Handoff

**Not in this session, in packet order:**

- **C1** realized outcome to the next flip (contract field new compiles emit;
  `LEGACY_OBSERVATION_COLUMNS` untouched, following A5's pattern)
- **C2** terminal-checkpoint op · **C3** session-bucket feature (`session_membership` adapter at
  minimum; record G6's finding that `verified` proves a definition computes what it claims, not that
  anything can produce it) · **C4** regimes-alive per offset, required output field
- **B1–B4** (B1 is live: see the baseline note above). B3 drops rather than ship approximate
  invalidation.
- The broad `test_delta` gate, `--no-ff` merge, and releasing the chore claim.
- The small item: find out why the broad run writes into tracked study directories
  (`research_decision_fidelity_report.json`, `es_wick_imbalance_acceptance_v2/audit/*`).

**Then, and only then:** S2b (independent read-only re-audit on a 2020 slice — a pre-2021 halt day,
the 2020-12-31 outage, a normal 2020 session, window-by-window against an independent reference) is
the gate before the six-year atlas, not this chore's test suite. S3 re-collects (C0 and C1 both
change collection) and re-explores.

**Chore claim** `fill_outcome_session` is live (paths: `research_workflow/host/mux.py`,
`research_workflow/sessions.py`, `research_workflow/grammar/compiler.py`,
`research_workflow/host/strategy.py`, `research/datasets/`). Release it at merge.

---

## C1 — realized outcome to the next flip (DONE 2026-09-20)

Driven by `studies/nq_va_multitf_trade_state_geometry`, whose fixture found the defect.

**The defect.** `LabelOutcomeKernel._emit` derived `flip_ts` from the COMPOSITE row disposition
(`flip_ts = at if disp == POSITIVE else None`), discarding the `p.flip_ts` the kernel had already
recorded. With one-sided milestone arms every untouched arm expires CENSORED and `_compose`
censors the row, so `flip_ts` and `time_to_flip_seconds` were null on virtually every row:
composing milestone arms COST the lifecycle terminal.

**The fix — three independent clocks, never collapsed into one status.**
Fixed-time feature checkpoints end at their own `max_age`; milestone arms own their own horizons
and keep running after the flip; the canonical lifecycle terminal is the qualifying opposite flip.
The terminal columns read `p.flip_ts` directly and are never conditioned on the aggregate
disposition. The composite row's `disposition`/`censored` semantics are UNCHANGED, and the flip
does not terminate barrier observation.

**Emitted terminal schema** (only when `contract["terminal_outcome"]`, which every new compile that
declares a flip item sets — a sealed pre-C1 plan replays byte-identically):

| column | meaning |
|---|---|
| `terminal_flip_ts` | instant of the qualifying opposite flip |
| `terminal_flip_disposition` / `terminal_flip_censor_reason` | canonical terminal status |
| `terminal_time_to_flip_seconds` | flip instant minus the decision epoch T |
| `terminal_exit_ts` / `terminal_exit_price` | executable exit: OPEN of the first bar strictly after the flip (the existing next_bar_open convention; no new fill convention) |
| `terminal_exit_unavailable_reason` | `GAP` or `DATA_END` when no executable exit bar exists |
| `terminal_entry_ts` / `terminal_entry_price` | the executable entry the economics are measured from |
| `terminal_gross_pnl_points` / `terminal_gross_pnl_atr` | realized gross, ATR = the frozen contract ATR |
| `terminal_duration_seconds` | executable entry to executable exit |
| `terminal_cost_points` / `terminal_net_pnl_points` / `terminal_net_pnl_atr` | net, **null unless `outcome.cost_points_per_side` is declared** — gross stays canonical and net is explicitly unavailable rather than guessed |

**Surface.** `research_workflow/host/outcomes.py` (contract flag, `_Pending` exit state, exit
capture in `on_bar`, deferred completion until the exit bar, terminal emit block),
`research_workflow/grammar/compiler.py` (column declaration), `research_workflow/grammar/spec.py`
(`outcome.cost_points_per_side`).

**Tests.** `research_workflow/tests/test_c1_terminal_outcome.py`, 12 cases on the production path
(real contract, real kernel): the censored-arm regression, pre-C1 replay unchanged, exit is
next-bar-open not the decision close, exact gross arithmetic long and short, net unavailable vs
declared, flip far past the fixed observation window, no-flip, flip on the final bar, and arms
still resolving after the flip. `test_ordered_barrier_entry_reference.py` has 3 failures that are
identical on clean `main` (pre-existing, not caused here).

**Still not started:** C2 terminal-checkpoint op, C3 session-bucket feature, C4 regimes-alive, B1-B4.
