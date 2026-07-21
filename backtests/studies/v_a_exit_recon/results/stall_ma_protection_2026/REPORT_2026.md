# V_A Stall-to-MA Protection — 2026 OOS Test (S5_SMA21)

Run: 2026-04-29T21:13:04.806673+00:00

Tests the best H1-2025 variant (`S5_SMA21`) on the 2026 regime where baseline regime-exit was negative. Question: does the protective stop save 2026?

## Configuration

- Span: NQ RTH 2025-12-29 to 2026-04-15
- Population: 1,006 V_A trades
- Cost: $10 RT
- Framework: `utils/safe_replay`
- Variant: `S5_SMA21` (stall_bars=5, MA=SMA(21), 1m granularity)
- Mode: conservative_ohlc / at_or_worse_close / market_exit_now

## Audit verdict

- **PASS** — 0 impossible fills

## Headline

| Variant | n | Total | vs Base | Mean | Median | PF | WR | DD | %cat | %ma | %reg | %inv@entry |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `BASELINE_regime` | 1,006 | $-17,335 | (base) | $-17.23 | $-177.50 | 0.94 | 35.1% | $-28,790 | 0.0% | 0.0% | 100.0% | 0.0% |
| `BASELINE_cat_only` | 1,006 | $-19,495 | $-2,160 | $-19.38 | $-177.50 | 0.93 | 30.4% | $-39,420 | 41.0% | 0.0% | 59.0% | 2.0% |
| `S5_SMA21` | 1,006 | $-10,170 | +$7,165 | $-10.11 | $-167.50 | 0.96 | 30.8% | $-33,595 | 37.9% | 17.0% | 39.1% | 2.0% |

## Comparison vs H1 2025 result

| Variant | H1 2025 total | 2026 total | H1 2025 vs base | 2026 vs base |
|---|--:|--:|--:|--:|
| `BASELINE_regime` | $53,050 | $-17,335 | (base) | (base) |
| `BASELINE_cat_only` | $23,385 | $-19,495 | $-29,665 | $-2,160 |
| `S5_SMA21` | $16,050 | $-10,170 | $-37,000 | +$7,165 |

## Conclusion

- **S5_SMA21 BEATS baseline regime exit on 2026 by $7,165.** Despite underperforming H1 2025, the rule specifically helps in the 2026 regime where baseline is negative.
- Recommend full IS/OOS expansion for robustness validation.
