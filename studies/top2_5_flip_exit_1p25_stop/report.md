# INVALIDATED — Top-2.5% First-Signal: 1.25 ATR Stop / Confirmed-Flip Exit

**Do not use these results.** This study depended on path columns from canonical
artifact `d6e5b71e...`, whose vectorized range query was subsequently proven to
attach extrema outside individual checkpoint intervals. The repaired canonical
artifact has SHA-256 `97afa92a...`. This analysis must be rerun from that source
before any stop/PnL conclusion is used.

| scope        | year   | causal_status                  |   entries |   stopouts |   stopout_rate |   wins |   losses |   breakeven |   win_rate |   mean_pnl_atr |   median_pnl_atr |   total_pnl_points |   mean_pnl_nq_dollars |   median_pnl_nq_dollars |   total_pnl_nq_dollars |   profit_factor |
|:-------------|:-------|:-------------------------------|----------:|-----------:|---------------:|-------:|---------:|------------:|-----------:|---------------:|-----------------:|-------------------:|----------------------:|------------------------:|-----------------------:|----------------:|
| bearish_fade | all    | STRICT_CAUSAL                  |       785 |        755 |       0.961783 |     30 |      755 |           0 |  0.0382166 |       -1.15889 |            -1.25 |           -13008.3 |              -331.422 |                -300.943 |                -260166 |       0.0470319 |
| bullish_fade | all    | PROVISIONAL_KNOWN_1S_LOOKAHEAD |      1226 |       1160 |       0.946166 |     66 |     1160 |           0 |  0.0538336 |       -1.12779 |            -1.25 |           -17205.6 |              -280.678 |                -252.143 |                -344111 |       0.0542269 |
| combined     | all    | MIXED_INCLUDES_PROVISIONAL     |      2011 |       1915 |       0.952263 |     96 |     1915 |           0 |  0.0477374 |       -1.13993 |            -1.25 |           -30213.9 |              -300.486 |                -268.79  |                -604277 |       0.0511426 |

This is an independent per-signal, policy-conditioned path estimate using checkpoint price and confirmed-flip close. It is not an executable portfolio backtest and excludes commissions, slippage, latency, and overlap constraints. Bullish selection remains provisional with its disclosed inherited one-second feature look-ahead; therefore the combined scope is also provisional. Top-2.5 thresholds are retrospective combined-2024-2025 strata, not walk-forward thresholds, so 2024 detail uses the later 2025 score distribution.
