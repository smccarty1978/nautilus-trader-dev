# Pre-execution audit: authorized OHLC full policy matrix (final)

Date: 2026-07-11  
Gate status: **PASS — AUTHORIZED OHLC MATRIX MAY RESUME**

**CRITICAL: 0**  
**WARNING: 0**

This pass authorizes the user-selected `EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT` primary matrix and `CLOSE_DETECTED_NEXT_NT_FILL_SENSITIVITY` appendix only. It does not convert either contract into NT-native executable validation.

## Final edge verification

The last remaining issue is fixed. Confirmation/wait price contributes to realized pre-flip MAE only when `reached_confirmation` is true:

```python
if confirm_i is not None and reached_confirmation:
    pre_mae = max(pre_mae, adverse_distance_to_wait_px)
```

A trade stopped before confirmation therefore uses only causally realized pre-terminal bars under its contract plus the actual/assumed stop fill adverse point. The later hypothetical wait-for-flip price remains available solely in separately labeled front-run fields and cannot contaminate realized MAE.

## Passed invariants

- W4 training and absolute D10 threshold are chronologically frozen; no test rank or 2026 parameter selection is used.
- Within-regime crossing state is computed on the full chronological sequence before evaluation filtering; score availability is observation plus one second.
- Pre-flip entries require score availability strictly before confirmation; flip update wins equality.
- Primary entries use explicit next-open OHLC labels; Contract 3 uses fixture-authorized prior-close/next-event conventions.
- Stop grid is exactly 0.50/1.00/1.50 ATR; entry-bar activation, worse-open gap, stop-tie, and contract-specific release rules are frozen.
- Position overlap, entry timing/gap class, reset identity, exit completeness, output schemas/cells, and required placebo-pair cells fail fast.
- Primary entry-bar stop MAE permits an empty prior-bar path and adds only assumed stop-fill adverse distance; Contract 3 retains its completed detection-bar semantics.
- Confirmation bar post-open extremes do not enter primary pre-flip MAE.
- Natural-exit counterfactual uses the same fixed stop and records its actual contract-specific terminal timestamp/price/reason or censorship.
- Post-D10 path diagnostics stop at the earlier counterfactual terminal event and exclude post-exit OHLC, adding terminal price only.
- D10/flip equality, stop/logical equality, valid-never-D10, score unavailable, stopped-before-D10, D10 improvement/reduction, and fallback states are retained and reported.
- Regime coverage uses causal availability, validated F1 ends, evaluation-only population, explicit score-unavailable missing regimes, and a right-censor causal availability bound.
- Placebos are official-period, outcome-blind, no-self/no-reuse, past-only, validation-bucketed, calipered, and paired with fixed-seed sign-randomization plus design/executed balance and attrition.
- Maximum drawdown includes initial zero; zero-exit months, direction/session/exit breakdowns, decomposition, runner/tail diagnostics, confirmed-trade availability, final headers, limitations, and required output manifest are implemented.
- Reports explicitly state OHLC research assumptions, unknown intrabar order, and no NT-native executable claim.

## Required completion audit

After execution, reinvoke the lookahead auditor on generated trades, audits, summaries, and final report. Reconcile causal event timestamps, entry/exit/stop prices, PnL components, overlap, cell completeness, placebo pairs, and report claims before declaring the study complete.

## Targeted placebo re-audit after fail-fast repair

The repaired treated population now requires membership in coverage `ever_reached_D10`, whose definition uses causal availability no later than completed regime end/data bound. This correctly removes raw crossings that were not causally available while the regime was eligible. Donors remain disjoint never-treated, non-censored regimes; self-match, treated-donor overlap, and donor reuse assertions remain present. Donor checkpoints are constrained to `observation_time <= treated observation_time`, so checkpoint state matching itself is past-only.

### CRITICAL — Donors are not official-window filtered and CT match keys cross UTC evaluation boundaries

File: `build_placebos.py`

Treated events are filtered using UTC causal availability windows. Donor candidates are not. Their `year` and `month` match keys are derived in `America/Chicago`. Consequently:

- an early March 2025 UTC treated event is still February CT and can match a February calibration-period donor;
- an early January 2026 UTC treated event is December 2025 CT and can match a prior-year donor;
- output year summaries use CT year rather than the configured evaluation year.

The policy runner later applies UTC period filtering to placebo events, so these selected donors are dropped only after design/balance artifacts are produced. This can distort match rates, balance, attrition, and required pair-cell availability.

Required fix: compute `available_time = observation_time + 1s` for both treated and donor candidates; assign an explicit `evaluation_year` from the configured UTC windows; exclude all candidates outside those windows before grouping; and include `evaluation_year` as a required matching/summarization key. CT month/session may remain additional covariates. Assert every emitted donor and its paired treated event share the same evaluation year and lie inside that year's official UTC window.

### WARNING — Donor comment incorrectly denies future treatment-path conditioning

File: `build_placebos.py`

The code comment says donor selection never conditions on later D10 status or flip time, but the design intentionally requires `ever_reached_D10=False` and `right_censored=False`, both determined using the completed regime path. This is not economic-outcome leakage and was explicitly chosen as a never-treated/non-censored retrospective control definition, but it is future treatment/follow-up conditioning and must not be described as checkpoint-only eligibility.

Required fix: document the control as retrospective never-treated/non-censored matching, distinguish treatment-path eligibility from PnL/stop outcomes, and avoid online/causal risk-set claims.

### Targeted repair verification

The targeted findings are resolved:

- both treated and donor score rows now receive `available_time = observation_time + 1s`;
- an explicit `evaluation_year` is assigned only inside the exact configured UTC 2025/2026 windows;
- both treated and candidates are filtered to valid evaluation years before grouping;
- `evaluation_year` is a required match key, while Chicago month/session remain secondary covariates;
- emitted `year` and summaries use evaluation year rather than Chicago calendar year;
- past-only matching remains enforced (`donor observation_time <= treated observation_time`, equivalent under the shared +1s availability rule);
- reached and never-treated/non-censored sets are disjoint by causal coverage definition;
- self-match, treated-donor overlap, donor reuse, and both-year coverage assertions remain active;
- documentation now accurately identifies retrospective conditioning on later D10 treatment status and noncensoring, while excluding PnL, stop, and economic outcomes.

Targeted gate: **PASS**. Placebo generation and the previously authorized OHLC matrix may resume. Completion audit remains mandatory.

## Targeted F1 direction-reconstruction audit

The reconstruction concept is causally acceptable: direction alternates structurally across verified consecutive flip events, and scored-regime direction rows serve only as identity/parity anchors. Using anchors later in the chain to validate/backfill parity does not use prices, PnL, stop outcomes, or future economic information. All available anchors must agree, and reconstructed regime IDs retain exact flip timestamps. This is an offline provenance correction, not a trading signal.

However, three implementation issues prevent continuation.

### CRITICAL 1 — Interior missing opposing flips are accepted as a valid chain

Files: `build_frozen_events.py`, `run_ohlc_contracts.py`

Both checks define continuity as:

```python
opposing_flip_time.isna() OR next_observation.isna() OR opposing_flip_time == next_observation
```

Thus an interior row with missing `opposing_flip_time` passes even though it has a following flip. The stated invariant—every observation maps to the next flip—is not enforced, and parity can be propagated across an unknown/missing transition.

Required fix: for every nonterminal row in each reconstruction segment, require a non-null opposing flip exactly equal to the next observation. Only the segment terminal row may lack an in-segment next row; if it has an opposing flip outside the segment, preserve it as a boundary/censor fact without using it to infer an unobserved row.

### CRITICAL 2 — Cached stale `regime` still participates in duplicate conflict failure

File: `run_ohlc_contracts.py`

The new direction logic says it ignores cached `regime`, but duplicate conflict detection still calculates uniqueness across `opposing_flip_time`, `regime`, and `atr`. Duplicate rows that agree on event identity/end but disagree only in the known-stale cached regime can halt before reconstruction.

Required fix: remove cached `regime` from duplicate conflict/identity checks. Reconstruct direction solely from structural order plus scored anchors. Continue to fail on conflicting observation/end mappings and any other field explicitly required as causal input (such as ATR, if duplicate disagreement cannot be resolved).

### WARNING — Coverage year breakdown is overwritten with Chicago calendar year

File: `build_frozen_events.py`

Coverage correctly recomputes UTC year after adding missing rows and uses it for per-year reconstruction and causal bounds. Later it overwrites `cov["year"]` with the Chicago timestamp year. Early January UTC regimes can therefore be reported in the prior year, inconsistent with the configured UTC evaluation periods and policy runner year cells.

Required fix: preserve an explicit `evaluation_year`/UTC year for reconstruction, causal bounds, placebo joins, and requested year summaries. Store Chicago calendar year separately if desired; session remains Chicago-based.

### Targeted F1 repair verification

All targeted findings are resolved:

- every nonterminal row in each reconstruction segment must have a non-null `opposing_flip_time` exactly equal to the next `observation_time`;
- only the segment terminal row is exempt from an in-segment next-row equality check;
- run-time duplicate conflict checks ignore the known-stale cached `regime` field and validate only opposing-flip mapping and ATR;
- direction is reconstructed solely from structural alternation and all scored-regime anchors must agree;
- coverage reconstructs within UTC years, while the runner reconstructs within its requested year plus warmup segment;
- missing/unscored regime IDs use reconstructed direction plus exact flip timestamp;
- coverage preserves UTC/evaluation year in `year` for causal bounds and requested summaries, and stores Chicago calendar year separately as `ct_year`;
- no price, PnL, stop, economic outcome, or future market feature is used to assign direction.

Targeted F1 gate: **PASS**. The authorized OHLC matrix may resume. Completion audit remains mandatory.

## Targeted official-window F1 boundary audit

The latest boundary change also passes:

- `load_flips(year)` restricts the reconstructed F1 population to the exact official UTC evaluation window for that year;
- raw one-second bars independently retain seven days of price warmup, used only to make next-open/prior-close price lookup available and never to seed regime direction/state;
- the 2025 and 2026 flip chains are reconstructed independently, so no direction/regime state bridges the documented catalog-year gap;
- every nonterminal official-window flip still must map exactly to the next official flip;
- direction parity remains anchored to scored-regime rows inside the official chain and all anchors must agree;
- P0/P2 populations therefore begin only at an observed official-window flip;
- an official D10/placebo event whose originating regime began before the official window has no `fmap` row and is skipped before entry construction;
- a preperiod old regime is not silently relabeled as the first official regime, and no warmup flip can create a trade;
- last-window regimes whose opposing flip lies beyond loaded/evaluation data retain a forward end reference but become censored when no executable bar exists;
- the boundary restriction uses timestamps and structural adjacency only, with no future price, PnL, stop, or economic-outcome selection.

Targeted official-window boundary gate: **PASS**. Matrix execution may resume; completion audit remains mandatory.

## Targeted next-available-open gap audit

The revised execution contract is causally valid:

- sorted timestamp `searchsorted(..., side="left")` selects the first stored one-second bar at or after the decision, so no intervening stored bar can exist;
- negative decision-to-fill delay fails;
- primary fills at that first later bar's open;
- Contract 3 retains its fixture-authorized prior stored close price at the later event timestamp;
- stops begin under each contract only from the modeled fill/event onward;
- exact, short (`<=60s`), and extended (`>60s`) classes are persisted on every trade;
- weekend/holiday closures remain as explicit positive delays rather than being dropped or backfilled;
- config/spec remove the arbitrary maximum and clearly authorize first-next-available fills while disclaiming executable validation.

### WARNING — Summary does not separate the three frozen gap classes

File: `run_ohlc_contracts.py`

`entry_fill_gap_summary.parquet` currently groups only by contract/year and reports total `gap_count`, min/median/max. It does not report counts for exact, short, and extended classes. The per-trade audit retains the class, and maximum delay exposes that long gaps exist, but the named summary does not separately surface the known extended weekend/holiday population.

Required fix: group the summary by `entry_fill_gap_class` (or add one count column per class), with count and delay range per contract/year/class. This ensures extended gaps cannot be hidden inside a total nonzero-gap count.

### Gap summary repair verification

`entry_fill_gap_summary.parquet` now groups by `execution_contract`, `year`, and `entry_fill_gap_class`, with count plus minimum, median, and maximum delay. Exact, short, and extended closures are therefore separately visible in both per-trade and summary artifacts.

Targeted gap gate: **PASS**. The authorized matrix may resume; completion audit remains mandatory.
