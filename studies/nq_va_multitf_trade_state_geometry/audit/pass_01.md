# Causal audit — pass 01 — nq_va_multitf_trade_state_geometry

Packet `2535682dde214c22`, plan `82b230f28f71c69c`, execution composite
`346c71526660948d`, 159 closure files. Tests 158 passed / 0 failed.

Audited against the ten pre-seal checks the study owner specified, plus the standard invariants.

---

## 1. Population — CLEAR

`population.cadence` is a grid anchored on `regime_1m.start_ns`, `every_ns = 15e9`,
`max_age_ns = 300e9`, `qualify: null`, `direction: regime_1m.dir`,
`anchor_identity: regime_1m.start_ns`. No qualifier, no trigger graph
(`triggers: every_candidate`), so every confirmed 1m V_A transition enters the population and
nothing is filtered. This is the canonical flip-to-flip population, unchanged.

The regime definition is one capability at four timeframes with identical parameters
(`short_period 3`, `long_period 9`, `atr_period 14`), so the 1m population is the same engine the
prior V_A lineage used.

## 2. Entry — CLEAR

`outcome.entry_reference = next_bar_open`, the executable reference. `entry.decision_close` is
absent. The kernel resolves the entry as the OPEN of the first bar with `ts_init > T` and stamps
`entry_ts` at that bar's open instant. The decision-close defect found in the H050 lineage is not
reproduced here.

## 3. Terminal — CLEAR

`outcome.flip = {source: regime_1m, role: opposite, inclusive_start: true, horizon_ns: 86400e9}`.
The terminal is the qualifying **opposite** confirmed 1m flip; the 24h horizon is an observation
bound, not a time stop. The executable exit is the OPEN of the first bar strictly after the flip
instant — the same `next_bar_open` convention as the entry, not the decision-bar close. Verified
on the production path by `test_c1_terminal_outcome.py::test_terminal_exit_is_next_bar_open_not_the_decision_close`.

## 4. Three independent clocks — CLEAR

* Fixed feature checkpoints: grid `max_age_ns = 300e9` → T0/T15/…/T300 (21 checkpoints, containing
  the six required).
* Milestones: 16 arms, each `horizon_ns = 86400e9`, independent of `max_age_ns`.
  `LabelOutcomeKernel._complete` holds the row until every arm **and** the flip resolve, so arms are
  not truncated at T300 and keep resolving after the flip
  (`test_milestone_arms_keep_running_after_the_flip`; oracle case `milestone_past_T300` records
  first passage at 1201 s).
* Terminal: emitted from `p.flip_ts` directly and never conditioned on the composite disposition
  (`COMPOSITE_FLIP_TERMINAL_PRESERVED = PASS`, zero null terminals over six oracle cases).

No clock is derived from another and no single disposition stands for all three.

## 5. MTF causality — CLEAR (this was the main risk and it resolves cleanly)

The availability table shows an asymmetry that must be justified, not assumed:

| tracker | stream | visibility |
|---|---|---|
| `regime_1m` | `nq_1m` | strictly_before |
| `regime_5m` / `regime_15m` / `regime_1h` | `nq_5m` / `nq_15m` / `nq_1h` | **at_epoch** |
| `excursion_5m` / `excursion_15m` / `excursion_1h` | `nq_1m` | strictly_before |
| `excursion_1m` | `nq_1s` | at_epoch |

`nq_1m` is an **external** coarser stream, so the compiler forces it to `role: context` and the mux
queues it until an execution bar with a strictly later `ts_init` arrives — golden rule 3, enforced
in code (`compiler.py:283`).

`nq_5m`, `nq_15m` and `nq_1h` are **derived** `closed_window` buckets, and the compiled plan
re-points every one of them to `derived_from: nq_1s` (rule D1: derive from the coarsest external
stream that divides the timeframe and is visible at the epoch). A bucket closing exactly at T is
therefore assembled only from 1s bars with `ts_init <= T`, every one of which the epoch already
sees. `at_epoch` visibility confers no information the epoch does not already have, so it is not
look-ahead. Critically, these buckets never read `nq_1m`, so the conservative context-stream
treatment of 1m is not circumvented through the derived path.

The excursion trackers for 5m/15m/1h run on `nq_1m` and so inherit `strictly_before` — strictly
more conservative than required. `same_ts: unavailable` on every stream; no stream opts into
same-timestamp visibility.

## 6. MTF geometry reconstructability — CLEAR

Raw, unnormalised state is carried for every timeframe, so no distance is trapped in a ratio whose
denominator was discarded: per timeframe `start_price_*`, `highest_high_*`, `lowest_low_*`,
`start_ns_*`, and **both** ATR denominators (`atr_5m/15m/1h` live, `frozen_atr_5m/15m/1h` at regime
start), alongside `atr_entry_1m` (the frozen 1m reference ATR) and `atr_current_1m`. Any distance
can be reconstructed in the local higher-timeframe ATR or in the 1m reference ATR.

## 7. Terminal economics — CLEAR

`outcome.cost_points_per_side` is absent from the contract, so `terminal_cost_points`,
`terminal_net_pnl_points` and `terminal_net_pnl_atr` are emitted as explicit nulls and
`terminal_gross_pnl_points` / `terminal_gross_pnl_atr` are canonical. No cost assumption is
manufactured. Asserted by `test_net_is_unavailable_without_a_declared_cost`.

## 8. Composite semantics — WARNING (analysis-facing, not a causal defect)

`outcome.composition` is `OR` over 17 children (16 arms + `event`). Because every arm that never
touches expires CENSORED under `expiry: censor`, and `_compose` returns CENSORED when any child is
unresolved, the row-level `disposition` is **structurally CENSORED on virtually every row** and
`censored == 1`. This is correct and intended, but it means the row-level composite columns carry
no lifecycle meaning. Analysis must read `terminal_*` for the trade outcome and `fp_*` for
milestones, and must never treat row-level `disposition`/`censored` as the trade result. Recorded
in `research_decision.yaml` under `first_passage_census_composed_and_proven.trap_for_analysis`.

## 9. One-sided encoding — CLEAR (documented debt)

Each arm parks its unused side at 99.0 ATR (~2,000–6,000 NQ points). `BarrierArm` requires both
levels and no native one-sided item exists. Oracle case `parked_side_never_fires` confirms the
parked side never resolves, and every arm's first-passage second matches an independent
brute-force oracle exactly. `FIRST_PASSAGE_INTEGRITY = PASS` over six cases. Carried as accepted
technical debt.

## 10. Fingerprint — CLEAR

Sealing against `execution_composite_sha256 = 346c71526660948d`, the study branch's platform
identity including the C1 repair (chore `7c4a2673`, merged `185554c2`). C1 is deliberately not on
`main`; the study branch is the authority for this seal. Any later platform-code change moves the
composite and invalidates the seal.

---

## Findings

### WARNING C-1 — the lifecycle terminal is bounded by the RTH close, which selects against the runner tail

`population.session = RTH` and `outcome.session = RTH` with `session_end: truncate`. Truncate is
the right semantic (censor would void every row against a 24h horizon), but the consequence is that
a trade whose opposite 1m flip occurs after the 15:15 CT close is **CENSORED SESSION_END at the
close** rather than followed to its terminal.

This is not a causal defect and it is recorded, not hidden: such rows carry
`terminal_flip_disposition = CENSORED` with `censor_reason = SESSION_END`, so the truncation rate is
measurable after collection. But the bias is not neutral for this study's purpose. The longest-lived
regimes are exactly the runner class the research question is about, and they are the ones most
likely to straddle the close, so the runner cohort will be depleted precisely where it is most
interesting.

The comparable atlas study (`nq_mtf_regime_atlas_pilot2023`) chose `population.session: ALL` with
`outcome.session: TRADING_DAY` for this reason.

Not raised to BLOCKED: the choice is declared, correctly implemented, self-reporting, and the owner
directed that a clean Phase B proceed to collection without a further permission stop. The
truncation rate should be the first number read out of the collected frame, and switching to
ALL/TRADING_DAY is a one-line change if it proves material.

### NOTE C-2 — higher-timeframe regime history is shallow at the partition edge

`warmup: {days_before_partition: 5, max_warmup_seconds: 50400}` with `per_stream_bars`
`nq_1h: 14`, `nq_15m: 14`. 14 hourly bars is exactly ATR(14)'s requirement, so the 1h tracker is
warm for ATR and for the 3/9 EMA pair, but its *prior-regime* fields and `age_s`/`bars_in_regime`
are shallow for the first 1h regimes of the partition. Candidate emission and target generation are
both off during warmup, so no row is emitted from unwarmed state; the effect is limited to
early-partition 1h context being younger than it truly was. Descriptive only, immaterial at the
scale of a full year.

### NOTE C-3 — `max_gap 300s` guards a 24h horizon

`horizon_end_rule: strict` with `max_gap_ns = 300e9` against arm horizons of 86400e9. The
compiler's WARN-3 rule (max_gap must be shorter than the smallest horizon) is satisfied with a wide
margin. Gaps longer than 5 minutes inside a lifecycle censor the affected arm with `GAP`, which is
the intended conservative behaviour for a 1s tape.

---

## Invariants

| invariant | status |
|---|---|
| completed bars only (`ts_init`) | CLEAR — every tracker `availability: completed_bar_ts_init` |
| context streams visible strictly before T | CLEAR — `nq_1m` is the only external coarser stream and is `strictly_before` |
| derived buckets complete-only | CLEAR — `closed_window` from `nq_1s` |
| outcome kernel resolves from bars strictly after T | CLEAR — entry and exit both `ts > T` / `ts > flip_ts` |
| label contract has no fill semantics | CLEAR — `contract: label`; the terminal fill is an emitted observation, not an order |
| `assert_oos_open` is the only OOS door | CLEAR — `train: [2023]`, `dev: [2024]`, `prohibited: [2025, 2026]`; no stage before `oos` reads 2024 |

## Verdict

**CLEAR.** No look-ahead, no leakage, no same-timestamp violation. One WARNING (C-1, an
RTH-boundary selection effect on the runner tail, declared and self-reporting) and two NOTEs.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "causal", "audited_execution_composite_sha256": "346c71526660948dbeda7549a1812a1cd700a459307d514c62656edccc45f1b8", "auditor": "claude-causal-pass01", "critical": 0, "note": 2, "study": "nq_va_multitf_trade_state_geometry", "verdict": "CLEAR", "warning": 1}
<!-- AUDIT_SUMMARY_V2_END -->
