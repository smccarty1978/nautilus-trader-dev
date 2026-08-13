# Phase A March 2025 Benchmark

**Status:** Passed bounded representative-run gate  
**Runtime:** 63.09 seconds  
**Peak memory:** 601 MB

## Output

- One-second bars: 1,228,521
- One-minute bars: 33,179
- Established Bullish RTH checkpoints: 15,552
- Complete 25-feature vectors: 14,383
- Score-suppressed warm-up vectors: 1,169
- Positive `flip_le_300` labels: 4,642
- Right-censored rows: 0
- Confirmed flip facts: 2,477
- Monthly missing-dispatch diagnostics: 66,786

## Causal checks

- `max_source_ts_event_1s >= decision`: 0
- `max_source_ts_init_1s > decision`: 0
- `max_source_ts_init_1m >= decision`: 0

The incomplete vectors are almost entirely checkpoints before the finalized
30-minute opening-range level exists. They are retained in diagnostics and
excluded from the in-domain model population per the frozen contract.

Checkpoint SHA-256:
`325d1f756f585b5e09695914ace243cd73e67a02900461ac423cc6cf2ae789d5`

Flip-fact SHA-256:
`618ce93e417d5623841ec44c38a72c484f591ff28b7af9ff03c08f221170c089`

Missing-dispatch SHA-256:
`7ddd4855aea0e44dcdc8bca09f8c51fdc56c3438988c4a3273e1cc2afb5257b5`

Code identity:
`d3cff47e75051919d5696a6b0e3a412a36bb0ebccd9d76770da137ea36b43f90`

Configuration SHA-256:
`3c6652892057fd0ad62f0017229e7c948c1335c4422bc9bfb146a908e006d414`

Trusted permitted-catalog manifest SHA-256:
`8ce13a6a5550aecc10dd2b136d053ddef13434a56bee03a03fee9a8197c3019a`
