# Decisions — `regime_complete_canonical_store_v1`

Every decision below was made before implementation and is frozen into
`REGIME_COMPLETE_CANONICAL_STORE_SPEC.md`. Reversing one requires a spec revision,
not a code change.

---

## DECISION-1 — ETH checkpoints are scored, and flagged out-of-contract

**Date:** 2026-07-27 · **Authority:** user · **Spec:** §5.2.3

**Context.** All 5,665,103 rows of the accepted score artifact are RTH. Four of the
25 frozen features (`rth_elapsed_seconds`, `rth_vol_cum`, `rth_abs_delta_cum`,
`opening_range_30m_*`) are RTH accumulators reset at RTH open by
`engine.reset_rth()` and closed by `engine.end_rth()`. Outside RTH they are past
their reset boundary, so an ETH probability is numerically defined but semantically
undefined. Both models' frozen contracts state
`session: [08:30:00,15:00:00) America/Chicago`.

**Options considered.** (a) suppress ETH scores and emit explicit
`OUT_OF_FROZEN_SESSION_CONTRACT` rows with null probabilities; (b) score ETH anyway
with an out-of-contract flag; (c) restrict everything to RTH.

**Decision.** (b). Emit real probabilities on the full-session 5s grid, with
`session_contract_status = "OUT_OF_FROZEN_SESSION_CONTRACT"` and
`in_domain = false` on every non-RTH row.

**Why.** Retaining the number costs nothing and cannot be recovered later without a
full recollection, whereas discarding it is irreversible. The risk is a downstream
consumer treating an ETH probability as comparable to an RTH one — mitigated by the
flag being mandatory and non-nullable, and by a negative test asserting that no
in-domain row carries `session != "RTH"`.

**Consequence.** Score table grows from 5,665,103 to ~12,156,904 rows (+6,491,801).
ETH probabilities may never qualify an entry.

**Phase 2 empirical outcome — the frozen contract enforces the boundary itself.**
Scoring ETH yields almost nothing: in the 2025-03 pilot, 117,024 ETH checkpoints
produced essentially no computable scores, because `rth_elapsed_seconds`,
`rth_vol_cum`, and `rth_abs_delta_cum` return `None` once
`OHLCVDeltaTracker.end_rth()` clears `_rth_active`. The frozen adapters decline
to score, so the vector is incomplete and the probability is null.

This is the honest result and it is better than either option considered: the
ETH rows are retained in full (regime state, price, ATR, path linkage, null
masks), and their absence of a score is *mechanically derived from the frozen
feature contract* rather than imposed by a collector-side session gate. Nothing
was discarded, and nothing was fabricated.

**Defect this exposed.** Widening the session broke an implicit assumption in the
inherited in-domain predicate. See DECISION-7.

---

## DECISION-2 — Confirmation columns hold the established-gate onset

**Date:** 2026-07-27 · **Authority:** user · **Spec:** §2.2, §5.1

**Context.** The study request assumed a raw-flip/confirmation split. The canonical
`RegimeEngine` has none: the sticky V_A flip *is* the confirmation. Because the rule
has no exit condition, regimes tile time and strictly alternate, making
`next_opposing_flip == regime_end == next regime start` an identity. Verified: 7
consecutive same-direction pairs out of 137,880 (0.005%), all month-boundary
artifacts.

The four requested events are therefore regime-*sequence* positions, not sub-events:
raw flip = `regime_start(R)`; intended-direction confirmation = `regime_start(R+1)`
(the existing `confirm_flip_ns`); opposing exit = `regime_start(R+2)` (the existing
`fallback_exit_flip_ns`).

**Options considered.** (a) repurpose the columns for the established-gate onset;
(b) materialize denormalized successor pointers matching the requested field names;
(c) both.

**Decision.** (a). Store `regime_established_decision_ns` and `established_reached`.
No confirmation-pointer columns. Trade-relative confirmation comes from
`regime_sequence_number` arithmetic.

**Why.** Denormalized pointers would be exactly derivable from
`regime_sequence_number`, so they add no information and create two representations
that can disagree after a partial rebuild. The established gate is the only real
within-regime milestone, and it is already the predicate defining
`bullish_in_domain` / `bearish_in_domain` — so the column has a single, already-frozen
meaning.

**Consequence.** Any query wanting "hold to the opposing confirmed regime" joins
`regime_sequence_number + 1` or `+ 2`. 2.0% of regimes are under 120s and can never
establish; `established_reached = false` for those, and no value is invented.

---

## DECISION-3 — All six percentiles materialized under the existing overlap waiver

**Date:** 2026-07-27 · **Authority:** user · **Spec:** §7 · **Status:** implemented

**Context.** Frozen thresholds existed only for bullish Top-10/5/2.5 and bearish
Top-5/2.5. Phase 0 established that both calibration populations reconstruct exactly
(171,334 and 163,397 rows) and that rescoring them with the frozen model binaries
reproduces **all five frozen thresholds bit-exactly**. So Top-20/1/0.5 and the
previously-unavailable bearish Top-10 are derivable with the identical recorded
method.

The obstacle is provenance, not capability: both calibration populations are
calendar-2025, which sits **inside** the 2021–2025 evaluation window. The study
request required calibration to predate evaluation.

**Options considered.** (a) materialize all six under the existing waiver;
(b) materialize only the five already frozen and mark the rest
`MISSING_NOT_RECONSTRUCTABLE`; (c) rebuild calibration on 2021–2024.

**Decision.** (a). All 12 rows written, each carrying
`overlaps_evaluation_window = true`, the disclosure text, and a pointer to
`full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`.

**Why.** (b) would block the Top-1% and Top-0.5% capability demonstrations the study
requires. (c) has cleaner provenance but produces thresholds that do *not* reproduce
the frozen values, which would fork the 5,836-trade backward-parity reference into
two threshold sets. (a) preserves exact backward parity and extends an overlap that
was already disclosed and authorized, rather than introducing a new one.

**Consequence.** Every result computed from these thresholds is descriptive and must
not be represented as threshold-out-of-sample for 2025. The disclosure is
non-nullable on every row so it cannot be dropped downstream.

**Guard.** `build_threshold_contracts.py` aborts the build if any previously-frozen
value fails to reproduce exactly. `test_threshold_contracts.py` asserts bit-exact
reproduction, per-model independence, monotonicity in tail fraction, complete
provenance hashes, and that no calibration window touches 2026.

---

## DECISION-4 — One path row per second, not one path per regime

**Date:** 2026-07-27 · **Authority:** implementer (reversible, storage-layout only)
· **Spec:** §4.1

**Context.** The request asked for "one full 1s path per regime", extended through
the opposing confirmation or a documented post-flip boundary. Because regimes tile
time, per-regime paths with a 600s post-terminal overlap would duplicate ~90M rows
on top of a 61.5M-row base.

**Decision.** Store exactly one row per 1s bar, keyed to its owning regime. Serve
hold-through by reading successor regimes via `regime_sequence_number`.

**Why.** Strictly dominant: unbounded hold-through (not a fixed 600s window) at
~40% of the storage, with no duplicated bars to keep consistent. The only cost is
that `seconds_from_regime_start` is owner-relative, so a query holding past the
terminal boundary recomputes it against its own anchor — a cheap, explicit
operation.

**Consequence.** Path table ≈ 61,543,945 rows (~2.5 GB) rather than ~152M (~6 GB).
Entry-dependent columns remain forbidden in this table.

---

## DECISION-5 — Feature snapshots stay inline

**Date:** 2026-07-27 · **Authority:** implementer (reversible) · **Spec:** §5.5

**Context.** The request preferred a separate feature-snapshot table, optionally
long-format, and asked that storage efficiency not silently reduce provenance.

**Decision.** Keep the accepted inline wide layout: 25 feature values plus an
`__is_null` mask per model per checkpoint, already present in the observations
artifact (179 columns, 344 B/row).

**Why.** A long-format table would be ~608M rows for identical information. The
inline columns plus the existing `bullish_feature_vector_sha256` /
`bearish_feature_vector_sha256` already prove the exact vector that was scored, so
provenance is unchanged. Tradeoff documented rather than silent.

---

## DECISION-6 — `RegimeEngine` is pinned; `RegimeStateEngine` is not used

**Date:** 2026-07-27 · **Authority:** implementer · **Spec:** §2

**Context.** The study request named `RegimeStateEngine` in its preferred
implementation stack. That class
(`collectors/collector_v2/regime_engine.py:28`) is an independent implementation
with identical math but a registry/aggregator-driven multi-timeframe interface. The
accepted 5,836-trade population was produced by
`studies/fable5_pre_flip_d10_reversal_entry/strategy.py::RegimeEngine`, which is
also used by Phase A, Phase B, the live-parity harness, the NT POC, and the
short-RTH Policy A strategy.

**Decision.** Pin `RegimeEngine`. Any use of `RegimeStateEngine` requires its own
parity proof against `RegimeEngine` first.

**Why.** Substituting a second implementation into the collector that must reproduce
5,836 trades exactly puts backward parity — the central acceptance gate — at risk for
no benefit. `regime_engine_version` (SHA-256 of the engine source) is baked into
`regime_id`, so a silent engine swap changes every ID and is immediately detectable.

---

## DECISION-7 — In-domain requires RTH explicitly

**Date:** 2026-07-27 · **Authority:** implementer (defect correction) · **Spec:** §5.2.3

**Context.** The inherited predicate is:

```python
bullish_in_domain = (direction == 1 and established_regime_gate)
bearish_in_domain = (direction == -1 and established_regime_gate)
```

It never tested session, because the Phase B collector only ever dispatched
inside RTH — the session conjunct was implicit in the emission gate. Widening to
the full session (DECISION-1) made that assumption false. The 2025-03-03 smoke
produced **2,682 ETH rows marked in-domain**: 1,578 bullish and 1,104 bearish.

Both frozen model contracts specify `session: [08:30:00,15:00:00) America/Chicago`
as part of the model domain, so a mature ETH regime is out of domain by
definition, however established it is.

**Decision.** Re-derive in-domain in the augmentation as the inherited predicate
**and** RTH. ETH rows additionally carry
`bullish_out_of_domain_reason` / `bearish_out_of_domain_reason` =
`OUT_OF_FROZEN_SESSION_CONTRACT`.

**Why in the augmentation rather than the parent.** RTH rows already satisfy the
session conjunct, so the correction is a no-op for them — which is what keeps the
RTH byte-identity gate meaningful. Editing the parent would change the accepted
collector.

**Consequence.** Out-of-domain suppresses *eligibility*, never *retention*: the
ETH rows, their regimes, and their paths are all still stored. Guarded by
`test_no_eth_row_can_ever_be_in_domain` and
`test_established_eth_regimes_are_retained_despite_being_out_of_domain`, plus a
store-wide check in `validate_pilot.py`.

---

## DECISION-8 — Dispatch gaps reconciled against the window grid, not detected incrementally

**Date:** 2026-07-27 · **Authority:** implementer (defect correction) · **Spec:** §5.2.4

**Context.** The inherited collector detected a dispatch gap by comparing each
observed 5s boundary against the previous one. That only emits a gap once a
*later* boundary arrives, so a gap running to the end of the collection window is
never emitted at all. The 2025-03 pilot came up **2 slots short** of the expected
535,680 — the final two, 23:59:50 and 23:59:55 — and this would recur at every one
of the 60 partition boundaries.

**Decision.** Remove the incremental detector. The runner, which knows the window
bounds, computes `missing = full 5s window grid − scored keys`.

**Why.** `scores + missing == expected slots` then holds *by construction* rather
than as a property that happens to be true when the stream cooperates. Full count
reconciliation with no silently dropped slots is an acceptance criterion, so it
should not depend on where the data happens to stop.

**Consequence.** Gaps are still a separate artifact and are never imputed into the
score table. `validate_pilot.py` asserts the identity exactly.

---

## DECISION-9 — Schema and artifact-name deviations from the frozen SPEC

**Date:** 2026-07-27 · **Authority:** implementer (contract-checker Pass 1 finding)
· **Spec:** §5.1, §5.3, §11

**Context.** `contract-checker` Pass 1 returned BLOCKED on four discrepancies
between the frozen SPEC and the built artifacts. All four were verified directly
against the Parquet schemas rather than taken on report:

```text
REGIMES  missing vs SPEC: source_file_id
REGIMES  extra   vs SPEC: contract_version
PATHS    missing vs SPEC: (none)
PATHS    extra   vs SPEC: contract_version, regime_established_decision_ns,
                          regime_sequence_number
```

**Decision.**

1. **`source_file_id` is added**, not waived. It is attached during
   consolidation from the partition manifest's dataset hash, because a collector
   subprocess cannot know the hash of the file it is still writing. This required
   re-consolidation only — no recollection.

2. **The four additive columns are adopted into the contract**, and the SPEC
   field lists in §5.1 and §5.3 are amended to include them:
   - `contract_version` — pins the store contract on every row, the same role
     `collector_version` plays for code.
   - `regime_sequence_number` on paths — **required** by DECISION-4. Successor
     regime lookup is the storage-saving mechanism, so the path table must carry
     the key it joins on.
   - `regime_established_decision_ns` on paths — the anchor that
     `established_state` and `seconds_from_established` are derived from;
     retaining it lets a query recompute those against its own anchor without
     joining back to the regime table.

   None is entry-dependent, so none violates the §5.3 prohibition.

3. **`backward_parity_report.json` and `partition_manifest.parquet` are now
   emitted under the names the study request used.** Their contents already
   existed inside `population_coverage_summary.json` and
   `canonical_collection_manifest.json`; equivalent content under a different
   filename is not compliance with a named deliverable, so both are written
   directly rather than argued as satisfied.

**Why amend rather than waive.** A frozen SPEC whose schema does not match the
artifact is the repeat-offender `C4`/`D1` category the split audit gate exists to
catch. Leaving a documented column absent, or extra columns unlisted, means the
next reader cannot tell a deviation from a defect.

---

## DECISION-10 — Three SPEC negative tests were asserted from architecture, now exercised

**Date:** 2026-07-27 · **Authority:** implementer (contract-checker Pass 1 finding)
· **Spec:** §10.2

**Context.** Three negative properties the SPEC lists as required tests had no
implementation. Their correctness rested on absence of mechanism — "the collector
has no exit concept, so an exit cannot truncate a path" — which is a design claim,
not evidence, and would not survive a refactor that introduced one:

```text
a selected-trade exit cannot terminate a regime path
a Top-2.5% filter cannot remove low-score regimes
a future bar cannot alter a prior score row
```

**Decision.** Implemented in `tests/test_negative_collection.py`, each driving
the behavior rather than inspecting structure: a long candidate whose stop is
breached mid-regime (path must continue 400s to the regime boundary); a regime
whose every checkpoint scores below the lowest frozen threshold (regime, 12 score
rows, and 120 path rows all retained); and a byte-comparison of every score row
before and after 300 further seconds and two later checkpoints.

Two further immutability tests were added while writing these: establishment must
not backfill an offset onto earlier checkpoints, and a path row's carried-forward
score must never reference a future checkpoint.

**Why.** A required test that was never written is `NOT VERIFIED`, not `PASS`.
The distinction matters most for exactly these properties, since each is the kind
of thing a later optimization silently breaks.
