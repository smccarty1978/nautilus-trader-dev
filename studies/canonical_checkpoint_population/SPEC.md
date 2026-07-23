# Canonical Checkpoint Population

## Decision to inform

Build one reusable, policy-neutral checkpoint table for rapid descriptive
research into the frozen Bullish Fade Top25 V1 and Bearish Fade Top25 V2
artifacts. This study builds data only. It does not optimize, recommend, or
simulate an exit policy.

## Frozen scope

- NQ, Chicago RTH 08:30 through before 15:15, years 2024–2025 only.
- Bullish: `BULLISH_FADE_TO_BEARISH_FLIP_TOP25_GBT_V1` / frozen legacy artifact
  `short_bearish_flip_top25_current_reference`.
- Bearish: `BEARISH_FADE_TO_BULLISH_FLIP_TOP25_GBT_V2` / frozen artifact
  `LONG_STRICT_top25_gbt_v2`.
- Primary key: `(direction, regime_start_ns, observation_time)`.
- 2026 is sealed and forbidden.

The mandated Bullish artifact is provisional and carries a disclosed inherited
one-second feature look-ahead. The Bearish artifact is strict-causal. The table
preserves this provenance and is canonical for the named artifacts and pure
event/path contract; it does not make the Bullish artifact production-causal.

## Source populations and scoring

- Bullish corrected pure checkpoint files:
  `short_rth_pure_flip_prediction_enriched/_work/prepared_{year}.parquet`.
- Bearish strict model matrices:
  `long_rth_strict_symmetric_retrain/_work/monthly/{year}/*.parquet`, joined
  one-to-one to strict attached surfaces for identity, price, ATR, direction,
  and confirmed-flip provenance.
- Frozen feature orders and serialized models are loaded read-only. Thresholds
  and percentile ranks are computed separately by direction across the combined
  2024–2025 population. 2024 is in-sample and 2025 is development.
- Bullish 2025 reference predictions and Bearish frozen fixture predictions
  must reproduce bit-exactly.

## Pure event and normalization contracts

The event builder accepts only the primary key plus `confirm_flip_ns`:

```text
seconds_to_flip = (confirm_flip_ns - observation_time) / 1e9
flip_le_300 = 0 < seconds_to_flip <= 300
flip_le_600 = 0 < seconds_to_flip <= 600
```

Every economic metric is normalized by the row's frozen, finite, positive
`atr_at_checkpoint`. No future or rolling ATR is a denominator.

## Observed-bar endpoint contract

Raw files contain open-labelled observed one-second trade bars and are not gap
filled. A bar stamped `t` covers `[t,t+1s)` and completes at `t+1s`.

- Checkpoint→flip and fixed-horizon paths use bars opening strictly after the
  checkpoint and strictly before the endpoint.
- Flip open/close are the first observed open and last observed close in the
  confirming minute `[confirm_flip_ns-60s, confirm_flip_ns)`.
- Post-flip paths use `flip_close_price` as baseline and observed bars opening
  strictly after `confirm_flip_ns` and before the endpoint.
- Endpoint lags and gap counts are stored for provenance. An interval containing
  no observed trade bar is retained with `path_available = false` and null path
  economics; selected checkpoints are never silently dropped. Any interval
  truncated by raw-data coverage still stops the affected year.

Favorable/adverse orientation is always the hypothetical trade direction:
Bullish Fade is short (`-1`), Bearish Fade is long (`+1`).

## Confirmed-flip ATR and next flip

`atr_at_confirmed_flip` is Wilder ATR(14) emitted by the canonical one-minute
regime engine on the completed bar whose right-boundary `close_ts` is the
confirmed flip timestamp. Its source timestamp therefore equals
`confirm_flip_ns`; it uses the completed confirming bar and no later bar. This
field is provenance only and is never an economics denominator.

`next_opposing_confirm_flip_ns` comes from the complete canonical regime
timeline: it is the end of the newly confirmed opposing regime beginning at
`confirm_flip_ns`. A trailing censored next regime produces null next-flip path
fields and is reported as missing, never fabricated.

## Required table fields

Identity, frozen score/percentile/buckets/first-cross flags, pure events,
checkpoint/flip provenance, checkpoint→flip paths with extremum timestamps,
fixed 300/600-second paths, post-flip 60/300/600-second paths, next-flip paths,
direction and causal-provenance flags, and observed-bar boundary/gap diagnostics.

The output schema explicitly forbids policy, stop, target, execution, survival,
and simulated-trade fields.

Every build must pass an exhaustive synthetic range-query contract over all
intervals (including empty slices and tied extrema) and direct raw-array slice
parity samples for every path family and year. Any magnitude or earliest-index
disagreement stops the build before an artifact is written.

## Deliverables

- `SPEC.md`
- `config.yaml`
- `results/canonical_checkpoint_population.parquet`
- `results/canonical_checkpoint_population_schema.json`
- `canonical_checkpoint_population_quality_report.md`
- `audit/audit.md`

## Stop conditions

Any 2026 access, key defect, row loss, population-direction mismatch, event
dependency outside `confirm_flip_ns`, nonpositive ATR, artifact parity failure,
unexpected output field, raw-coverage-truncated non-censored path, or audit
CRITICAL stops acceptance. An interval wholly empty only because no trade bar was
observed inside otherwise complete raw coverage is permitted and explicitly
nullable. Completion requires zero CRITICAL and zero WARNING.

Execution is bounded to 3,600 seconds by the repository bounded-study runner.
Before allocation the builder computes a conservative peak-memory estimate and
refuses to proceed above 10,000 MB. It writes atomic per-year checkpoints before
the final combined artifact.
