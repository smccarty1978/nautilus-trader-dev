# Phase C Frozen Task Packet — First Top-2.5% Trade Selection

## Objective

Select exactly the first qualifying in-domain Top-2.5% checkpoint per
model-specific regime from the accepted Phase B global score population.
Selection is dispatched inside the NautilusTrader event loop at the original
five-second decision timestamp.

## Explicit threshold-reference amendment

The user explicitly authorized applying the already-frozen 2025 thresholds
across 2021–2025 despite the 2025 reference overlap. The binding waiver is
`THRESHOLD_OVERLAP_WAIVER.json`. Every manifest and report must disclose that
2025 is not threshold-out-of-sample.

Frozen thresholds:

- Bullish Fade / candidate SHORT: `0.5697449423968936`
- Bearish Fade / candidate LONG: `0.5641320087327389`
- Membership operator: `>=`

No threshold is recomputed from Phase B.

## Selection contract

- Bullish candidate: `bullish_in_domain`, score available, and probability at
  or above the Bullish threshold.
- Bearish candidate: `bearish_in_domain`, score available, and probability at
  or above the Bearish threshold.
- Select the earliest qualifying checkpoint for each
  `(instrument_id, entry_model_id, regime_start_ns)`.
- Regime selection state carries across month boundaries.
- Out-of-domain scores never select a trade.
- Future flip labels never participate in selection.
- Candidate direction is SHORT for Bullish Fade and LONG for Bearish Fade.
- Overlap is allowed; there is no portfolio lockout.

## Deterministic trade ID

SHA-256 of compact UTF-8 JSON:

```text
[instrument_id, entry_model_id, regime_start_ns, checkpoint_decision_ns, trade_direction]
```

with `separators=(",", ":")`, signed integer direction, and no whitespace.

## Output and validation

- Monthly `selected_trade_entries.parquet`.
- Per-month manifest binds Phase B input hash, threshold/waiver/config/code
  identities, prior selected-state hash, output hash, and resulting state hash.
- Exact offline parity may recompute the same deterministic first-qualifier
  rule from the accepted Phase B score artifact only as a validation of the
  NautilusTrader-generated selections.
- Zero missing, extra, duplicate-regime, timestamp, model, score, threshold,
  direction, or trade-ID mismatches.
