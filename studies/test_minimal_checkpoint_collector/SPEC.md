# SPEC: Minimal 15s Checkpoint Collector Test (test_minimal_checkpoint_collector)

## 1. Research Overview
Minimal 15-second checkpoint collector test fixture for multi-collector framework genericity verification.

## 2. Chronology & Partitioning
- Train: [2023]
- Dev: [2024] (Locked)
- Prohibited: [2025, 2026]

## 3. Features & Data Streams
- Streams: 1s, 1m
- Features (3 total):
  1. `bar_close_delta_1m`
  2. `bar_volume_1m`
  3. `bar_hl_spread_1m`
- SHA-256: `782955f9ee097aab1559727eb841faa369325302e3ddf0a8ba3a4f5c20076074`

## 4. Execution Runtime
- Runtime: `NautilusTrader`
- Strategy Class: `strategies.minimal_checkpoint_collector.MinimalCheckpointCollector`
- Cadence: 15 seconds
- Exact grid timing: `triggering_1s_ts_init == observation_ts == T`
