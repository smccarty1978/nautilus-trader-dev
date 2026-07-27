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
