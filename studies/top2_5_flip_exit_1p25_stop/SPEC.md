# Top-2.5% First-Signal, 1.25 ATR Stop / Confirmed-Flip Exit

## Decision

Measure independent per-signal path economics for the canonical first Top-2.5%
checkpoint population under a descriptive 1.25 checkpoint-ATR loss cap and a
confirmed-flip-close exit. This is not an executable portfolio backtest.

## Frozen population and inputs

- Input: `canonical_checkpoint_population.parquet` with frozen SHA-256
  `d6e5b71e6244cd7ed19161862211e1c3f8bc668c1c7db7cd7fe81b5d25de8121`.
- Include exactly `is_first_top_2_5 == True` and `to_flip_path_available == True`.
- Report Bullish Fade, Bearish Fade, and combined; also retain year detail.
- Do not access 2026 or raw bars.

## Economics

The checkpoint price is the descriptive entry reference and
`atr_at_checkpoint` is the sole ATR denominator.

For a genuine resting stop, touching the boundary triggers it:

```text
survives_stop = mae_to_flip_atr < 1.25
pnl_atr = checkpoint_to_flip_close_atr, if survives_stop
          -1.25, otherwise
pnl_points = pnl_atr * atr_at_checkpoint
pnl_nq_dollars = pnl_points * 20
```

The flip exit is `flip_close_price`. This study does not assert executable entry
or exit fills, resolve portfolio overlap, apply costs/slippage, or model order
latency. It is a policy-conditioned path estimate, not a NautilusTrader backtest.

The Top-2.5% threshold was calculated retrospectively by direction over the
combined 2024-2025 population. It is not a walk-forward threshold; consequently
the 2024 year detail is conditioned on the later 2025 score distribution.

## Outputs

- `results/trades.parquet`
- `results/summary.csv`
- `report.md`
- `audit/audit.md`

## Acceptance

Exact input hash, exact population flag, complete required fields, formula
reconciliation, no duplicate checkpoint keys, and mandatory causal audit with
zero CRITICAL and zero WARNING.
