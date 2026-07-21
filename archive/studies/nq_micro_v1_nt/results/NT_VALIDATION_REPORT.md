# V_A + flip2conf_dir_efficiency >= 0.30 — NT Runtime Validation

Filter implemented inside Collector V2 strategy via `require_flip2conf_efficiency=0.30`. Bit-perfect construction by construction: the runtime gate reads the same `flip2conf_dir_efficiency` value computed by `_compute_micro_window` that's emitted to `micro_pre.parquet`. This means parity is structural, not empirical — but we verify anyway.

## 1. Parity vs offline study

Verifies runtime trade selection == {baseline RTH trades} ∩ {flip2conf >= 0.30}.

- **NQ 2020**: expected=392, runtime=392, matched=392, only_expected=0, only_runtime=0, parity_ok=True
  - runtime min flip2conf at signal = 0.3000 (must be >= 0.3); n below = 0
  - matched-trade PnL agreement: max abs diff = $0.00, n_diff > $0.01 = 0
- **NQ 2021**: expected=433, runtime=433, matched=433, only_expected=0, only_runtime=0, parity_ok=True
  - runtime min flip2conf at signal = 0.3000 (must be >= 0.3); n below = 0
  - matched-trade PnL agreement: max abs diff = $0.00, n_diff > $0.01 = 0
- **NQ 2022**: expected=289, runtime=289, matched=289, only_expected=0, only_runtime=0, parity_ok=True
  - runtime min flip2conf at signal = 0.3000 (must be >= 0.3); n below = 0
  - matched-trade PnL agreement: max abs diff = $0.00, n_diff > $0.01 = 0
- **NQ 2023**: expected=289, runtime=289, matched=289, only_expected=0, only_runtime=0, parity_ok=True
  - runtime min flip2conf at signal = 0.3000 (must be >= 0.3); n below = 0
  - matched-trade PnL agreement: max abs diff = $0.00, n_diff > $0.01 = 0
- **NQ 2024**: expected=287, runtime=287, matched=287, only_expected=0, only_runtime=0, parity_ok=True
  - runtime min flip2conf at signal = 0.3000 (must be >= 0.3); n below = 0
  - matched-trade PnL agreement: max abs diff = $0.00, n_diff > $0.01 = 0
- **NQ 2025**: expected=329, runtime=329, matched=329, only_expected=0, only_runtime=0, parity_ok=True
  - runtime min flip2conf at signal = 0.3000 (must be >= 0.3); n below = 0
  - matched-trade PnL agreement: max abs diff = $0.00, n_diff > $0.01 = 0
- **NQ 2026**: expected=124, runtime=124, matched=124, only_expected=0, only_runtime=0, parity_ok=True
  - runtime min flip2conf at signal = 0.3030 (must be >= 0.3); n below = 0
  - matched-trade PnL agreement: max abs diff = $0.00, n_diff > $0.01 = 0

## 2. Provenance and lookahead

Collector V2 `_compute_micro_window` filters to `start_ts < ts_init <= end_ts`. `_recent_1s_bars` is appended in `_on_1s_bar` only when bar.ts_init arrives. Since `decision_ts = bar.ts_init` of the 1s bar that triggers the bar+1 1m bucket close, every buffered bar's ts_init satisfies ts_init <= decision_ts. By inspection of the code path: no lookahead possible.

- Halts across all 7 cells: 0
- (Halts would be raised by registry.audit_provenance violation; 0 = clean.)

## 3. Baseline vs filtered economics — NQ RTH

### Baseline (no filter)

| Year | n | %kept | WR | Mean $ | PF | Total $ | Max DD | Avg Win | Avg Loss | Med Hold s |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 2020 | 3,571 | 100.0% | 35.7% | $-9.57 | 0.94 | $-34,170 | $-54,310 | $436.69 | $-259.87 | 631.0 |
| 2021 | 3,548 | 100.0% | 33.2% | $-22.02 | 0.86 | $-78,130 | $-105,865 | $413.79 | $-241.60 | 631.0 |
| 2022 | 3,465 | 100.0% | 34.2% | $-15.82 | 0.94 | $-54,805 | $-69,695 | $674.51 | $-376.79 | 631.0 |
| 2023 | 3,448 | 100.0% | 34.3% | $-13.28 | 0.92 | $-45,780 | $-55,830 | $427.54 | $-244.81 | 631.0 |
| 2024 | 3,343 | 100.0% | 35.2% | $6.35 | 1.03 | $21,220 | $-42,045 | $569.33 | $-302.21 | 631.0 |
| 2025 | 3,310 | 100.0% | 34.2% | $18.04 | 1.07 | $59,720 | $-46,270 | $787.99 | $-384.60 | 631.0 |
| 2026 | 1,006 | 100.0% | 35.1% | $-17.23 | 0.94 | $-17,335 | $-28,790 | $795.16 | $-457.09 | 631.0 |
| **7yr total** | **21,691** | — | — | — | — | **$-149,280** | — | — | — | — |

### Filtered (flip2conf_dir_efficiency >= 0.30)

| Year | n | %kept | WR | Mean $ | PF | Total $ | Max DD | Avg Win | Avg Loss | Med Hold s |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 2020 | 392 | 11.0% | 40.1% | $42.21 | 1.30 | $16,545 | $-5,205 | $454.11 | $-234.98 | 691.0 |
| 2021 | 433 | 12.2% | 38.6% | $16.36 | 1.12 | $7,085 | $-9,235 | $402.04 | $-227.48 | 751.0 |
| 2022 | 289 | 8.3% | 32.9% | $-39.53 | 0.87 | $-11,425 | $-23,825 | $790.68 | $-450.73 | 751.0 |
| 2023 | 289 | 8.4% | 42.6% | $13.84 | 1.09 | $4,000 | $-4,810 | $386.95 | $-264.21 | 811.0 |
| 2024 | 287 | 8.6% | 33.8% | $11.32 | 1.05 | $3,250 | $-8,060 | $662.94 | $-323.04 | 751.0 |
| 2025 | 329 | 9.9% | 34.0% | $93.80 | 1.35 | $30,860 | $-14,830 | $1,068 | $-414.88 | 751.0 |
| 2026 | 124 | 12.3% | 37.1% | $45.65 | 1.18 | $5,660 | $-5,180 | $816.74 | $-409.10 | 691.0 |
| **7yr total** | **2,143** | — | — | — | — | **$55,975** | — | — | — | — |

## 4. Comparison summary

| Metric | Baseline | Filtered | Δ |
|---|--:|--:|--:|
| 7yr trade count | 21,691 | 2,143 | 9.9% kept |
| 7yr total PnL | $-149,280 | $55,975 | $205,255 |
| Years +mean | 2/7 | 6/7 | +4 |
| 2026 mean $ | $-17.23 | $45.65 | $62.88 |

## 5. Cross-check vs offline study expectation

From `studies/nq_micro_v1/results/NQ_V_A_1S_MICROSTRUCTURE_REPORT.md`:

| Year | Study n | NT n | Study mean $ | NT mean $ | Δ mean | Study total $ | NT total $ | Δ total |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 2020 | 392 | 392 | $42.21 | $42.21 | $-0.00 | $16,545 | $16,545 | $0.00 |
| 2021 | 433 | 433 | $16.36 | $16.36 | $0.00 | $7,085 | $7,085 | $0.00 |
| 2022 | 289 | 289 | $-39.53 | $-39.53 | $-0.00 | $-11,425 | $-11,425 | $0.00 |
| 2023 | 289 | 289 | $13.84 | $13.84 | $0.00 | $4,000 | $4,000 | $0.00 |
| 2024 | 287 | 287 | $11.32 | $11.32 | $0.00 | $3,250 | $3,250 | $0.00 |
| 2025 | 329 | 329 | $93.80 | $93.80 | $-0.00 | $30,860 | $30,860 | $0.00 |
| 2026 | 124 | 124 | $45.65 | $45.65 | $-0.00 | $5,660 | $5,660 | $0.00 |

All cells match study within tolerance: **True**

## 6. Verdict

✅ **PASS** — all key questions answered yes:

- 6/7 years positive: **6/7** (target ≥ 6)
- 2026 stays positive: **$45.65/trade**
- Long-term PnL positive: **$55,975**
- NT runtime matches offline study: **bit-perfect**

This is the first NT-validated V_A variant with a positive cross-year track record. Concerns to address before live:
- Sample size is small (~300-450 trades/year)
- 2022 is the only loser (-$39/trade) — high-ATR regime may saturate the signal
- Single-threshold filter; no second-order robustness check (bootstrap CI per year, rolling-window stability, parameter sensitivity)

## Files

- Strategy gate: `collectors/collector_v2/strategy.py` — `require_flip2conf_efficiency` config field
- Runner: `collectors/collector_v2/run_filtered_validation.py`
- Per-year filtered: `collectors/collector_v2/results/filtered_f2c30/NQ_<year>/`
- Baseline: `collectors/collector_v2/results/portfolio/NQ_<year>/`
- Offline study: `studies/nq_micro_v1/results/NQ_V_A_1S_MICROSTRUCTURE_REPORT.md`