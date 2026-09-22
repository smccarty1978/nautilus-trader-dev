# Capability report — `entry_observation_and_atlas_ops`

Chore branch `chore/entry_observation_and_atlas_ops` from main `677687f2`. Requested by
`studies/nq_mtf_regime_structural_geometry_atlas/CAPABILITY_REQUEST_entry_observation_and_atlas_analysis_ops.md`.
No data was collected, no 2023/2024 outcome was read, and the frozen atlas design was not modified.

## A. Causal executable-entry observation (`outcome.entry_observation: true`)

**What changed.** `research_workflow/host/outcomes.py` adds `ENTRY_OBSERVATION_COLUMNS` =
`executable_entry_ts`, `executable_entry_price` and `executable_entry_unavailable_reason`.

- The columns are declared from one list by both the kernel and the compiler. They come after the C1 terminal block and before `observed_seconds`, which stays last (A5).
- `OutcomeSpec.entry_observation` is opt-in, and so is the contract flag. A plan that does not request it compiles and replays unchanged: no key, no column, and a byte-identical row dict (tested).
- `terminal_entry_*` is untouched, and so is its historical C1 contract (published only beside an executable exit).

**Semantics.** `_entry_observation()` is a function of four inputs only: T, the first execution bar with `ts_init > T`, T's session close, and `max_gap`.

- `executable_entry_price` = that bar's OPEN.
- `executable_entry_ts` = that bar's open instant (`ts_event`). This is the same convention as `terminal_entry_ts` and as the arms' `resolution_seconds` anchor. On a contiguous 1s tape it equals T, and the price is first traded after T. **Note:** the chore brief's `decision_ts < entry_ts` holds for the bar's close instant (`ts_init`), not for this timestamp. The timestamp was kept equal to the kernel's entry anchor so that `entry_ts + fp_k_resolution_seconds` stays exact.

When the entry is unavailable, both value columns are NULL and a reason is published. Nothing is fabricated.

| reason | condition |
|---|---|
| `SESSION_END` | the first bar after T closes past T's session close. Same bound and same SESSION_END > GAP precedence as the C1 exit. |
| `GAP` | that bar opens more than `max_gap` after T (N-3 stale reference) |
| `DATA_END` | no bar after T in the run |

- Only the barrier and composite kernels read the execution stream.
- `kernel: flip` + `entry_observation` is refused at two levels: the compiler raises `INVALID_PARAMETERIZATION`, and the kernel raises `ENTRY_OBSERVATION_REQUIRES_EXECUTION_BARS`.

**Proofs (`research_workflow/tests/test_entry_observation.py`, 32 tests, production kernel/compiler/host).**

- **Next-bar OPEN:** open, high, low and close of the entry bar all differ from each other and from the decision bar.
- **Future independence:** one shared history through the entry bar, four different futures:
  - normal flip + exit;
  - never flips (SESSION_END terminal);
  - flip on the last bar (no exit bar, DATA_END);
  - flip at the close (exit SESSION_END).

  The entry is bit-identical across all four; their terminals differ, and `terminal_entry_*` is NULL in three of them.
- **Other cases:** exit-GAP, DATA_END without a flip, censored terminal, and censored/unresolved milestone arms.
- **Gaps:** a short tape hole resolves to the next existing bar; an entry exactly at `max_gap` is published; one past `max_gap` gives `GAP`.
- **Session and data end:** no bar before the close gives `SESSION_END`; an entry bar closing exactly at the close is published; no bar at all gives `DATA_END`.
- **Kernel coverage:** short direction and the barrier kernel both work; the flip kernel is refused.
- **Compatibility and replay:** deterministic replay; with the flag off, rows equal the flag-on rows minus the new columns (all four futures); column order checked; every emitted key is declared.
- **Golden fixture end to end:** compile → `run_plan_on_bars`. Every published entry is the open of the first 1s bar after `observation_ts`, and equals `terminal_entry_*` wherever both exist. Without the flag the frame is identical minus the three columns. The persisted-schema assertion (`lifecycle_v2` merge) covers the new columns through the plan's `observation_columns`.

Existing C1 / truncate / oracle-parity suites pass unchanged (46 tests).

## B. Three registered analysis operations

| op | module |
|---|---|
| `analysis.derive.columns` | `research/analysis/derive_ops.py` + grammar `research/analysis/expressions.py` |
| `analysis.contrast.nominate` | `research/analysis/contrast_ops.py` |
| `analysis.replication.scorecard` | `research/analysis/contrast_ops.py` (needs_context) |

Registered in `research_workflow/capabilities_index.d/analysis_ops.yaml`; `research cap generate` reports 14 ops, 0 broken.
Helpers shared with `diagnostic_ops` are behavioural copies in `research/analysis/frame_common.py`.

- Why copies: the boundary forbids one implementation module statically importing another.
- `diagnostic_ops.py` is untouched, so no sealed study's analysis closure moves.
- A parity test proves the session-day cluster is identical in both modules.

**derive.columns.** A bounded grammar, tokenised and parsed by hand into a canonical JSON AST.

- It never calls `eval`, `exec` or `pandas.eval`. `__import__(...)`, attribute access, `**`, chained comparisons and indexing are all refused.
- Supported: `+ - * /`, comparisons, Kleene `and/or/not`, and a closed function set: `abs sign sqrt min max is_null not_null where coalesce concat cut`.
- NULL propagates. `a/0` is NULL by default (`div_zero: null`), or refused under `div_zero: error`.
- Integer columns stay exact, so nanosecond timestamp differences are exact.
- `each:` templates expand over declared values in deterministic order. `keep:` filters rows, and dropped rows are counted.
- It never overwrites a column. Each column's `definition_sha256` is recorded in the payload.
- **Compiler:** `_analysis_column_proof` refuses any expression that references a column the plan does not provide. The plan's columns are identity + metadata + features + observation + `_year`, plus earlier derived columns.
  - Output schemas of `describe.grouped`, `clustered_mean` and `classify.precedence` are propagated, which is how a Wilson interval over a summary becomes provable.
  - A derive over an op with no static schema is refused.
  - Ops that already existed get no new checks.

**contrast.nominate.** For each parent, child value and metric it computes child minus rest-of-parent, using the `clustered_mean` difference estimator (CR1, G−1 df). A test shows the estimate, SE, CI and cluster count match `analysis.uncertainty.clustered_mean` `differences`.

- **Support gates:** `min_child_n`, `min_parent_n`, `min_nominate_n` on basis `metric` or `rows`.
- **Multiple comparisons:** Benjamini-Hochberg over the whole tested family. `contrasts: [{parent_by, dimensions}, ...]` puts L1 (state vs pooled) and L2 (bucket vs state) in one family.
- **Materiality:** `min_abs_difference` and `min_relative_difference` (child vs whole parent), CI excludes 0 (child vs rest), and `max_bh_q`.
- No number is hard-coded. Output is in key order and never ranked.
- The payload is the claim file: specification, gates, replication rules and claims, frozen together with a `specification_sha256`.
- `mode: precomputed` gates an existing statistics frame instead of computing one.
- BH is tested for textbook values, ties, 200 permutations of order invariance, both null-p policies (`count_as_one` default / `exclude`), all-pass, none-pass and the q = threshold boundary.

**replication.scorecard.** Reads `claims_path`, which must be relative to the study directory and stay inside it. It refuses to run if the file's sha256 differs from the pinned `claims_sha256`.

- It re-measures every claim with the file's own contrast specification and each claim's own `parent_by`.
- It classifies with the file's own ordered rules. Each rule is `{class, requires: [predicates]}`; the first match wins, and anything unmatched gets the fallback class and is kept.
- The op takes no threshold parameters (tested: TypeError).
- It cannot drop or add a claim: every claim yields exactly one row, in file order, including claims whose parent has no replication rows (UNDERPOWERED, support 0).
- Output columns: claim_id, discovery_value/CI, replication_value/CI, expected_direction, support, classification, reason, and every predicate.

Tests: `research/analysis/tests/test_derive_ops.py` (32) and `test_contrast_ops.py` (31).
`research_workflow/tests/test_analysis_derive_contrast_compile.py` (7) covers:

- compiler refusals;
- closure seeding of all three new modules;
- a real pipeline run on the golden frame: derive → nominate → pinned scorecard.

## C. Integration with the requesting atlas (`atlas_compile_proof.py`, `atlas_compile_proof.json`)

What the proof did:

- Took the study's own `study.yaml` (sha `3639cf1a…`, read-only).
- Applied two overlays: `entry_observation: true` and the analysis block in `atlas_analysis_proof.yaml`.
- Compiled it with this chore's compiler.
- Ran the production pipeline over a synthetic frame with the compiled plan's exact schema. No collection, no outcomes.

Results:

- **Compile ok:** plan `65171f14…`. `terminal_outcome` and `entry_observation` are both true. `observed_seconds` is still the last column. The closure contains all three new modules.
- **Distances:** 277 derived atlas columns, including all **84 distances** (42 HTF-own-ATR A, 42 trade-ATR B).
- **Other derived columns:**
  - current and prior levels with the direction-dependent MFE/MAE choice;
  - `cur_pos` (ZERO_SPAN → NULL) and `cur_span`;
  - the exact 16-cell `mtf_state` and the relative code;
  - exclusions;
  - **45 L2 fixed-edge bucket dimensions** plus absolute buckets;
  - terminal classes;
  - strict before-flip reach for 16 rungs;
  - orderings with TIE and NEITHER;
  - runner preservation;
  - rung ladder and shapes.
- **Execution:**
  - All three null categories (NO_PRIOR, NO_ATR, ZERO_SPAN) appeared.
  - Wilson intervals were computed over the summary.
  - One BH family: 33,264 contrasts, 26,850 tested.
  - The 2024 step compiled (`3e4dabc2…`), and the pinned scorecard retained every claim.
  - A tampered claim file was refused with `HASH_MISMATCH`.
  - An unknown column was refused at compile with `DERIVE_COLUMN_UNKNOWN`.

## D. Findings the study session must act on (not decided here)

1. **RESIDUAL ANALYSIS_HARNESS_GAP: two items of `per_cell_report` are not expressible through registered ops.**
   - `profit_factor` = Σ(g|g>0)/|Σ(g|g<0)| within a cell. `describe.grouped` output is long format (one row per value column), and a row-wise derive cannot combine two rows.
   - `trades_per_day` = cell N ÷ partition RTH sessions. This needs a partition-level constant joined into each cell row.

   Both need a cross-row combine: a long→wide pivot of summary output, or a scalar join. This was **not** built here: it is outside the request, and building it would be improvising. The request should be raised as its own capability (for example `analysis.reshape.pivot_wide` plus a constant join) or resolved by a decision about the design. Everything else in `per_cell_report` is expressible, including Wilson intervals, duration quantiles, rung distributions, reach, orderings and preservation.
2. **The frozen replication classes overlap.** Examples:
   - same sign, CI includes 0, ratio < 0.5 matches both DIRECTIONALLY_CONSISTENT and NOT_REPLICATED;
   - opposite sign, CI excludes 0, ratio < 0.5 matches both CONTRADICTED and NOT_REPLICATED.

   The op resolves overlaps by the declared rule order. The proof order is `UNDERPOWERED, REPLICATED, CONTRADICTED, DIRECTIONALLY_CONSISTENT, NOT_REPLICATED×2`, marked DECISION. The study must freeze an order before sealing.
3. **Other choices marked DECISION in `atlas_analysis_proof.yaml`:**
   - support basis `n_basis: rows` ("child trades");
   - DATA_END terminals have no before-flip bound;
   - null categories are tested as their own children.
4. **Two-phase chronology.** The scorecard needs the committed 2023 claim file's sha256 pinned in `study.yaml`. The replication configuration is therefore a post-2023 plan change, which means a reseal. It cannot run in the same analyze pass as discovery.

## E. Tests

Test results are in `test_gate.json` and in the merge commit message.
