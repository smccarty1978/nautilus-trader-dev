# Regime-Complete Canonical Store — Frozen Specification

**Study:** `regime_complete_canonical_store_v1`
**Status:** Phase 0 complete. Contract frozen 2026-07-27.
**Supersedes for future research:** the policy-specific `full_trade_path_builder`
canonical trade population (which remains immutable and is the backward-parity
reference, not a dependency).

---

## 0. Governing principle

The collection layer records observable state. The analysis layer creates trades.

No threshold, entry rule, stop, exit, confirmation requirement, re-entry policy,
or trade-selection predicate may determine what rows are retained. Every such
policy is a query against this store.

---

## 1. What already exists (Phase 0 discovery)

| Requested dataset | Existing asset | Gap |
|---|---|---|
| Scores + feature snapshots | `full_trade_path_builder/consolidated/canonical_observations_all.parquet` — 5,665,103 true 5s checkpoints, both models, domain flags, and all 25 feature values inlined per model | RTH-only and confirmed-regime-only; no `score_observation_id`; no per-model availability timestamps |
| Regimes | `_work/phase_a_monthly/*/flips.parquet` — 137,881 unique confirmed flips 2021–2025, full 24h | No regime table; no IDs; no path bounds; no established-gate milestone |
| Paths | `canonical_trade_paths/` — 6,589,582 rows for 5,836 **selected trades** only | 99.996% of regime time has no stored path |
| Threshold contracts | `thresholds.json` (bullish), `metrics_2025.json` (bearish) | **CLOSED in Phase 0** — see §7 |

The score artifact is far more complete than a policy-specific collector would
suggest: it was already built globally and threshold-free. This store extends it
rather than replacing it.

---

## 2. Frozen regime engine

**Canonical implementation:** `studies/fable5_pre_flip_d10_reversal_entry/strategy.py::RegimeEngine`
(an exact port of `studies/regime_sequence_chop_context/reproduce_regimes.py`).

```python
new = self.regime                                   # sticky default
if   c > ema3_h and c > ema9_h:  new =  1
elif c < ema3_l and c < ema9_l:  new = -1
if new != 0 and new != self.regime:
    self.regime = new
```

- EMA3 (α=0.5) and EMA9 (α=0.2) of the **high** and of the **low**, separately.
- Wilder ATR(14). Updated once per completed 1m bar, stamped at `ts_init` (bar close).
- `regime` starts at 0, becomes ±1 on the first firing bar, and thereafter only swaps sign.

**Do not substitute `collectors/collector_v2/regime_engine.py::RegimeStateEngine`.**
It is an independent implementation with identical math but a different interface,
and it did not produce the accepted 5,836-trade population. Any use of it requires
its own parity proof against `RegimeEngine` first.

### 2.1 Structural invariants (verified over 2021–2025)

| Invariant | Evidence |
|---|---|
| Regimes **tile** time — no gaps, no neutral segments after warmup | no exit condition exists in the rule |
| Regimes **strictly alternate** | 7 consecutive same-direction pairs out of 137,880 (0.005%), all month-partition boundary artifacts — must be reconciled to 0 in Phase 3 |
| `next_opposing_flip == regime_end == next regime start` | identity, not coincidence |
| Minimum regime duration is one 1m bar | observed min 60s; median 540s; mean 1,146s; max 342,240s |

### 2.2 Flip vs confirmation — resolved

This engine has **no raw-flip/confirmation split**. The sticky flip *is* the
confirmation. The four events named in the study request are **regime-sequence
positions**, not sub-events within a regime. For a fade candidate in regime `R`:

| Requested event | This store |
|---|---|
| raw regime flip | `regime_start(R)` |
| intended-direction confirmation | `regime_start(R+1)` — the existing `confirm_flip_ns` |
| opposing flip / regime exit | `regime_start(R+2)` — the existing `fallback_exit_flip_ns` |

All four are recoverable by `regime_sequence_number` arithmetic. The regime table
therefore does **not** carry redundant confirmation-pointer columns.

The only genuine within-regime milestone is the **established gate**, and that is
what `regime_established_*` records (DECISION-2):

```python
established = (age >= 120 and favorable_extreme >= 1.0
               and progress_count >= 2 and retained >= 0.5)
```

This is the identical predicate that already defines `bullish_in_domain` /
`bearish_in_domain`. 2.0% of regimes are shorter than 120s and can never establish.

---

## 3. Population and scope

| Dimension | Contract |
|---|---|
| Instrument | `NQ.XCME` only. `*.v.0` volume-continuous catalog: `data/catalog/NQ_v0_2020_2026`. No silent expansion. |
| Years | 2021–2025 inclusive, America/Chicago calendar year. **2026 is forbidden** — reserved for runtime OOS. Sealed boundary `2026-01-01T00:00:00Z`. |
| Sessions | RTH **and** ETH retained for regimes, paths, and score rows. RTH = `[08:30:00, 15:00:00)` America/Chicago, classified by decision timestamp via `is_rth_decision`. |
| Warmup | 4 days, per `config/phase_b.yaml`. Regimes whose start precedes ATR initialization are excluded and counted. |
| Regime exclusions | Only: insufficient warmup, missing source data, corrupt ordering, contract gaps, unresolvable terminal censoring. Each counted and classified. Never excluded for lacking a score, a threshold crossing, a confirmation, or a trade. |

### 3.1 Measured scale

| Quantity | Exact value |
|---|---|
| 1s bars 2021–2025 | **61,543,945** |
| 5s dispatch checkpoints, full session | **12,156,904** |
| 5s dispatch checkpoints, RTH only (today) | 5,665,103 |
| Net new ETH score rows | **+6,491,801** |
| Unique confirmed flips (regimes) | **137,881** — to be reconciled against the 137,961 in `BUILD_REPORT.md` |

---

## 4. Architecture

```text
data/canonical/regime_complete_v1/
  canonical_regimes_all.parquet                 ~137,881 rows      ~30 MB
  canonical_regime_scores_all.parquet          ~12,156,904 rows   ~4.0 GB
  canonical_regime_paths_all.parquet           ~61,543,945 rows   ~2.5 GB
  canonical_model_threshold_contracts.parquet          12 rows     built ✔
  canonical_collection_manifest.json
```

Development writes to `regime_complete_v1/`. The accepted
`full_trade_path_builder/` artifacts are **never overwritten**.

### 4.1 Path table: one row per second, not one path per regime

Because regimes tile time, "the full 1s path for each regime" and "the complete
1s bar stream" are the same set of rows. The path table therefore stores **exactly
one row per 1s bar**, keyed to its owning regime.

Holding through the opposing flip — or through the opposing confirmation, or any
number of subsequent regimes — is served by reading the **successor regimes' rows**
via `regime_sequence_number`. This gives unbounded hold-through capability at zero
storage cost, versus ~90M duplicated rows for a 600s per-regime overlap.

Consequences the analysis layer owns:
- `seconds_from_regime_start` is relative to the **owning** regime; a query holding
  past the terminal boundary recomputes it against its own anchor.
- Entry-dependent quantities (MFE/MAE from a selected entry, trade return, stop hit,
  target hit) are **forbidden** in this table. They are analysis outputs.

---

## 5. Dataset schemas

### 5.1 `canonical_regimes_all.parquet` — one row per regime

Primary key: `regime_id`. Partition: `entry_year`.

```text
instrument_id  contract_id  regime_id  regime_sequence_number
regime_direction
regime_start_decision_ns   regime_start_event_ns   regime_start_price
regime_end_decision_ns     regime_end_event_ns     regime_end_price  regime_end_reason
regime_established_decision_ns   established_reached          # DECISION-2
atr_at_regime_start  atr_at_established  atr_at_regime_end
entry_year  session_at_start  session_at_established  session_at_end
path_start_ns  path_end_ns  path_row_count  path_is_complete  path_censor_reason
duration_seconds  duration_bars_1m
source_partition  source_file_id  collector_version  regime_engine_version
```

Nulls where an event does not occur. Censored regimes never receive invented
terminal values. `regime_end_reason ∈ {opposing_flip, sealed_boundary_censored,
data_gap_censored}`.

`regime_sequence_number` is a dense, gap-free, globally monotonic integer over the
instrument's regime stream. It is the mechanism by which successor-regime lookups
(§2.2) are exact.

#### `regime_id` construction — frozen

```python
regime_id = "RGM_" + sha256(
    b"regime_complete_v1\x00"
    + instrument_id.encode("utf-8") + b"\x00"
    + struct.pack("<q", regime_start_decision_ns) + b"\x00"
    + struct.pack("<b", regime_direction) + b"\x00"
    + regime_engine_version.encode("utf-8")
).hexdigest()[:24]
```

Deterministic, globally unique, stable across reruns, independent of row order,
and derived only from immutable fields. `regime_engine_version` is the SHA-256 of
the `RegimeEngine` source text, pinning the hash to the exact rule that produced it.

### 5.2 `canonical_regime_scores_all.parquet` — one row per true scoring event

Primary key: `score_observation_id`. Semantic key `(instrument_id, score_decision_ns)`.
Partition: `entry_year`, `study_month`.

Carries forward every column of the accepted observations artifact (including the
50 inline feature columns — see §6), plus:

```text
score_observation_id           # SCR_ + sha256(instrument_id, score_decision_ns, contract_version)[:24]
regime_id                      # exact link, never fuzzy
score_sequence_in_regime       # dense from 0
score_decision_ns  score_event_ns  score_available_ns
bullish_score_available_ns  bearish_score_available_ns    # §5.2.1
bullish_score_is_new  bearish_score_is_new                # always true; see §5.2.2
seconds_from_regime_start  seconds_from_established
session  session_contract_status                          # §5.2.3
feature_snapshot_id  feature_contract_version
```

#### 5.2.1 No implied simultaneity

Both models are dispatched inside one `_emit()` at the same `decision_ns` from one
`SourceProvenance`, so today they are genuinely simultaneous. The per-model
`*_score_available_ns` columns are still materialized explicitly so that a future
cadence split does not silently change the meaning of existing rows.

#### 5.2.2 Carry-forward is never a score event

One canonical score row = one true scoring event. The 5s dispatch fires only on
`ts_init % 5s == 0`. One-second carry-forward onto path rows is a **path-table**
concern and carries `score_source_ns`, `score_age_seconds`, `is_carried_forward`
there. A carried value may never appear as a row in this table. `*_score_is_new`
is therefore `true` on every row by construction, and a negative test asserts it.

#### 5.2.3 ETH scores are computed and flagged (DECISION-1)

Four of the 25 frozen features (`rth_elapsed_seconds`, `rth_vol_cum`,
`rth_abs_delta_cum`, `opening_range_30m_*`) are RTH accumulators reset at RTH open
and closed at RTH end. Outside RTH they are past their reset boundary.

Per DECISION-1, ETH checkpoints are **scored anyway** and flagged:

```text
session                  = "ETH"
session_contract_status  = "OUT_OF_FROZEN_SESSION_CONTRACT"
bullish_in_domain        = false        # unchanged predicate
bearish_in_domain        = false
```

An ETH probability is a computed number outside its frozen session contract. It is
retained for inspection and may **never** qualify an entry. A negative test asserts
that no in-domain row carries `session != "RTH"`.

#### 5.2.4 Missing dispatch

The existing `missing_dispatch` grid (2,880,577 RTH rows) is preserved and extended
to the full session as a **separate** artifact. Gaps are never imputed into the
score table.

### 5.3 `canonical_regime_paths_all.parquet` — one row per 1s bar

Primary key: `(regime_id, path_event_ns)`. Partition: `entry_year`, `study_month`.

```text
instrument_id  contract_id  regime_id  path_sequence_in_regime
path_event_ns  path_init_ns  path_decision_ns
open  high  low  close  volume
atr_current  atr_at_regime_start
regime_state  established_state
seconds_from_regime_start  seconds_from_established
session  entry_year
is_regime_start_row  is_established_row  is_opposing_flip_row  is_terminal_row
last_score_decision_ns  last_bullish_probability  last_bearish_probability
score_age_seconds  is_carried_forward
source_partition  collector_version
```

`is_opposing_confirmation_row` is **omitted**: it is identically
`is_opposing_flip_row` under §2.2 and would be a duplicate column.

Forbidden in this table: `mfe_from_entry`, `mae_from_entry`, `trade_return`,
`stop_hit`, `target_hit`, or any field whose value depends on a selected entry.

### 5.4 `canonical_model_threshold_contracts.parquet` — **BUILT**

See §7.

### 5.5 Feature snapshots

**Decision: inline, not a separate table.** The accepted observations artifact
already stores all 25 feature values plus an `__is_null` mask per model, per
checkpoint (179 columns, 344 B/row). A long-format snapshot table would produce
~608M rows for the same information.

`feature_snapshot_id` links to the inline columns and to
`bullish_feature_vector_sha256` / `bearish_feature_vector_sha256`, which already
prove the exact scored vector. Storage tradeoff documented; provenance not reduced.

---

## 6. Time semantics — frozen

| Timestamp | Meaning |
|---|---|
| `*_event_ns` | source bar `ts_event`. Databento labels bars at **open**. |
| `*_init_ns` | source bar `ts_init` = bar **close** = availability. |
| `score_decision_ns` | right boundary of the completed 5s checkpoint; dispatch is exact `ts_init % 5s == 0`. |
| `score_available_ns` | equals `score_decision_ns` — features are complete at the boundary. |
| `path_decision_ns` | the 1s bar's `ts_init`. |

Enforced by `SourceProvenance.assert_admissible(decision_ns)` on every score, which
already records `max_source_ts_event_1s/1m` and `max_source_ts_init_1s/1m` per row.

`_on_1s` asserts `ts_event < ts_init` — no partial bars, no future bucket data.

**Joins.** Every link in the canonical build uses an exact key: score→regime and
path→regime by `regime_id`; score↔trade by `(instrument_id, score_decision_ns)`.
No `merge_asof`, no fuzzy matching. Carried-forward score values on path rows are
not a join: they are collector state, and they carry `score_source_ns` +
`score_age_seconds` so the carry is always visible.

---

## 7. Threshold contracts — CLOSED IN PHASE 0

Both frozen calibration populations were reconstructed exactly and rescored with
the frozen model binaries. **Every previously-frozen threshold reproduced
bit-exactly**; the builder aborts rather than emitting a derived value if any
reproduction fails.

| Model | Calibration population | Rows |
|---|---|---:|
| `BULLISH_STRICT_top25_gbt_v2` | 2025 feature-complete in-domain established bullish RTH checkpoints | 171,334 |
| `LONG_STRICT_top25_gbt_v2` | 2025 development population, LONG_STRICT symmetric retrain | 163,397 |

| Percentile | Bullish | Bearish | Status |
|---|---|---|---|
| Top 20% | 0.34374423771129053 | 0.3745119841718754 | reconstructed |
| Top 10% | **0.43167249785595935** ✔ | 0.44559149246408103 | frozen ✔ / reconstructed |
| Top 5% | **0.5067081427626979** ✔ | **0.5084619230529974** ✔ | frozen ✔ |
| Top 2.5% | **0.5697449423968936** ✔ | **0.5641320087327389** ✔ | frozen ✔ |
| Top 1% | 0.6412279079940403 | 0.6306416772425602 | reconstructed |
| Top 0.5% | 0.6886333180788179 | 0.6706161496105166 | reconstructed |

✔ = reproduced bit-exactly from the frozen artifact. Method `numpy.quantile(...,
method="linear")`, membership operator `>=`, per model — never shared.

The previously "unavailable" **bearish Top-10 is now materialized**.

**Disclosure carried on every row.** Both calibration populations are calendar-2025
and therefore overlap the 2021–2025 evaluation window. Per DECISION-3 this inherits
`full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`; every row carries
`overlaps_evaluation_window = true` and the disclosure text, and every report using
these thresholds must reproduce it. No threshold is derived from study outcomes,
and no interpolation between levels is permitted.

---

## 8. Collection mechanics

Reuse the causal streaming stack in-process, inside the NT event loop. No pandas
reimplementation of runtime logic (CORE INVARIANT 1).

```text
PhaseBCollector (extend)          scores + feature snapshots, both models
  RegimeEngine                    regime state + Wilder ATR
  PrevailingDomain                established gate, MFE/MAE, progress windows
  FrozenBullishAdapter / bearish  frozen ordered vectors
  SourceProvenance                causal admissibility assertion
```

Three changes to `phase_b_strategy.py`, all widening:

1. **Emit on the full-session grid.** `if is_rth_decision(ti) and atr is not None`
   becomes `if atr is not None`, with `session` and `session_contract_status` set
   per row. The RTH accumulator reset/end calls in `_on_1m` are unchanged, so RTH
   rows remain byte-identical to the accepted artifact — a parity test asserts this.
2. **Open a regime record at every flip**, not only where a trade would be selected;
   close it at the next flip; emit the regime row on close.
3. **Emit a path row for every completed 1s bar**, tagged with the open regime.

No threshold, score, or selection predicate may appear in any emission condition.

---

## 9. Partitioning and query design

| Dataset | Partition | Row group |
|---|---|---|
| regimes | `entry_year` | single, ~137,881 rows |
| scores | `entry_year` / `study_month` | 512 MB target, ~1M rows |
| paths | `entry_year` / `study_month` | 512 MB target, ~1M rows |

60 partitions per large dataset — not 5,307 as in the current path store, and not
millions of small files. Stable schema across every partition.

Supported lazy pushdown: `entry_year`, `study_month`, `regime_id`, `model_id`,
`score_decision_ns` / `path_event_ns` ranges, `session`. Access via an extension of
`full_trade_path_builder/implementation/canonical_research_loader.py`.

---

## 10. Validation and acceptance

### 10.1 Backward parity — the central gate

Regenerate, using **only** the new tables, the first in-domain Top-2.5% qualifying
signal per regime. Expected: **5,836** selections (1,147 / 1,206 / 1,187 / 1,149 /
1,147 by year; 2,507 long, 3,329 short).

Match on `instrument_id`, regime identity, `model_id`, direction, checkpoint
decision timestamp, reference price, entry ATR, domain status, model probability.
Report exact / missing / extra / duplicated / retimed / value-mismatched.

**Target: 0 unexplained mismatches.** Also reproduce the frozen 0.75 / 1.00 / 1.25
ATR stop studies; any divergence must be explained before acceptance.

### 10.2 Required tests

Positive: deterministic regime IDs · one row per regime · dense score and path
sequences · monotonic timestamps · no partial-bar scoring · no future feature
timestamps · both model outputs retained · domain flags retained · exact
score→regime and path→regime linkage · path continues after the first qualifying
score · path continues after a hypothetical stop · path reaches the terminal
boundary · threshold provenance · partition-resume idempotence · no duplicate
score-observation or path keys.

Negative — each must **fail** if the property is violated:
- a Top-2.5% filter cannot remove low-score regimes
- a first-signal flag cannot terminate collection
- a selected-trade exit cannot terminate a regime path
- a carried-forward score cannot appear as a score row
- a future bar cannot alter a prior score row
- no in-domain row may carry `session != "RTH"`
- no entry-dependent column may exist in the path table

### 10.3 Independent audit sample

Deterministic stratified sample, ≥25 regimes per year, covering both directions,
both sessions, established and never-established, threshold and no-threshold,
domain transitions. Independently recompute regime start, established onset, regime
end, score timestamps, feature availability, both scores, domain flags, path bounds.
**Target: 0 unexplained mismatches.** The auditor is not given the implementer's
correctness argument.

---

## 11. Phased execution

| Phase | Content | Gate |
|---|---|---|
| **0** ✔ | Discovery, this spec, threshold contracts built and tested | complete |
| 1 | Micro fixture: both directions, established and never-established, threshold hit and no hit, domain transitions, multiple checkpoints, opposing flip, censoring | exact row-level behavior |
| 2 | Bounded pilot, 2025-03 (the existing Phase B benchmark month) | schema stable · timestamps monotonic · no duplicate IDs · path coverage exact · both models scored · cadence preserved · pilot first-Top-2.5% reproducible · RTH rows byte-identical to accepted artifact · memory and disk within estimate |
| 3 | Full 2021–2025, resumable partitioned, checkpointed, hash-reconciled | no full restart on one failed partition |
| 4 | Backward parity §10.1 | 5,836 exact |
| 5 | `lookahead-auditor` + `contract-checker` + data-integrity audit | 0 CRITICAL |

Estimates: ~7 GB total on disk; peak memory < 10 GB (existing Phase B budget);
runtime ~12–20 h sharded monthly, versus the ~6 h RTH-only Phase B budget — driven
by 2.15× the checkpoints plus 61.5M path rows.

---

## 12. Non-goals

No threshold optimization, no economic ranking of percentiles, no policy selection,
no retraining, no feature changes, no regime or confirmation redefinition, no cost
assumptions, no broad exit study, no path duplicated per hypothetical trade, no
threshold derived from evaluation outcomes, no 2026 data, and no overwrite of
accepted canonical files.
