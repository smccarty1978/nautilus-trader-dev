# CODEX 5.X W4 Policy A Residual-Loss Attribution

## Scope

Descriptive attribution of the already-audited Policy A outcomes on the exact repaired 4,383-entry W4 fade set. Policy A remains fixed at a 1.25 ATR pre-flip stop plus a 300-second confirmation timeout. No policy is changed or tested.

This is post-policy analysis under one-second OHLC research semantics, not NT-native executable validation.

## Frozen buckets

- Align time: `no_flip_before_exit`, `0-60s`, `60-120s`, `120-300s`, `>300s`. Boundaries are `[0,60]`, `(60,120]`, `(120,300]`, and `>300`. A late flip during a pending timeout order can occupy `>300s` even though Policy A did not treat it as confirmation.
- Entry regime age: `<15m`, `15-30m`, `30-60m`, `60-120m`, `>=120m`. The upstream `regime_age_s` is measured at the W4 decision/checkpoint, so exact entry age is `regime_age_s + (entry_fill_ts - decision_ts)` and both values are exported.
- W4 score: `<0.70`, `0.70-0.75`, `0.75-0.80`, `>=0.80`.
- MFE at timeout: `not_alive_at_timeout`, `<0.25`, `0.25-0.50`, `0.50-0.75`, `0.75-1.00`, `>=1.00` ATR.
- PnL at timeout: `not_alive_at_timeout`, `<-1.00`, `-1.00--0.50`, `-0.50-0.00`, `0.00-0.50`, `0.50-1.00`, `>=1.00` ATR.

Timeout state uses only completed raw bars with `ts_event < entry + 300s`. PnL uses the latest completed bar close. A stop whose containing bar is labeled exactly at timeout occurs after the timeout-open decision and is considered alive at that instant; an opposing-flip market fill at the timeout open is not.

## Summary dimensions

Year, direction, session, year-direction-session interaction, original baseline outcome, Policy A exit reason, align-time bucket, regime-age bucket, W4 bucket, timeout MFE bucket, timeout PnL bucket, residual loss mode, and a late-aligning baseline-winner timeout diagnostic.

Classifications are descriptive and are not candidate filters.

## Drawdown

Bucket drawdown is peak-to-trough drawdown of bucket-only cumulative Policy A net PnL in original entry-time order. It is non-additive and is not a marked-to-market portfolio drawdown.
