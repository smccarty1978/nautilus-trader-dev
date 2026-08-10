# Phase D Frozen Task Packet — Full One-Second Trade Paths

## Inputs

- Accepted Phase C selections: 5,836 exact first Top-2.5% trades.
- Accepted Phase B score partitions and confirmed-flip ledger.
- Frozen NQ one-second NautilusTrader catalog.
- The explicit 2025 threshold-reference overlap waiver and disclosure.

## Endpoint facts

- Confirmation is the first accepted flip into the trade direction after the
  selected checkpoint, already attached by Phase C.
- Fallback exit is the next accepted confirmed flip opposite the trade
  direction, strictly after confirmation.
- These future facts define descriptive path endpoints only. They never affect
  trade selection or any feature/model value.
- A fallback boundary is released only at its own timestamp during NT replay.
- If no fallback is observable before the sealed boundary, the path is
  right-censored at the final observed one-second bar.

## Path timing

- First path bar: first completed one-second bar with
  `bar.ts_event >= checkpoint_decision_ns`.
- `timestamp_open_ns = bar.ts_event`; `timestamp_close_ns = bar.ts_init`.
- Include the fallback bar through `timestamp_close_ns == fallback_exit_flip_ns`.
- Store, but do not include, the first bar open after the fallback boundary.
- Accepted flip state for a row ending at `T` uses flips strictly before `T`;
  a flip at `T` becomes prevailing for the next one-second row.
- Five-second scores available at `T` may be attached to the completed row
  ending at `T`. Older valid scores are explicitly carried with source/age.

## Economics and extrema

- Anchor: checkpoint reference price.
- ATR: immutable ATR at entry.
- Running MFE is nonnegative.
- Path `adverse_intrabar_extreme_atr` and `running_mae_atr` are signed,
  normally nonpositive.
- Summary `full_trade_mae_points` and `full_trade_mae_atr` are positive stop
  distances equal to the magnitude of the most adverse signed path value.
- Intrabar extremum timestamps use the completed one-second bar close
  timestamp; sub-second high/low time is unknowable.
- Same-bar entry revisit plus new favorable extreme is labeled
  `ordering_ambiguous_same_bar`.

## Execution and output

- All path attachment and running-state updates occur in NautilusTrader
  one-second callbacks.
- Process one entry month at a time with atomic Parquet and manifest writes.
- Monthly aggregate outputs are finalized into the exact canonical
  direction/prefix partition layout after all monthly runs pass.
- Every summary must pass exact recomputation from its path.
- Deterministic samples from every entry month must match raw catalog OHLC.
