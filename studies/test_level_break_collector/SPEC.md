# SPEC: Level Break Test Collector (test_level_break_collector)

## 1. Research Overview
Level break 1m bar-close collector test fixture for multi-collector framework genericity verification.

## 2. Chronology & Partitioning
- Train: [2023]
- Dev: [2024] (Locked)
- Prohibited: [2025, 2026]

## 3. Features & Data Streams
- Streams: 1s, 1m
- Features (7 total):
  1. `arrival_vel_5s`
  2. `arrival_vel_10s`
  3. `arrival_vel_20s`
  4. `arrival_vel_30s`
  5. `arrival_accel_5s`
  6. `arrival_accel_10s`
  7. `arrival_jerk`
- SHA-256: `490150eda8485f43e63ad0572c8104f21eec135b3a1a6568ba47158c944779e9`

## 4. Execution Runtime
- Runtime: `NautilusTrader`
- Strategy Class: `strategies.level_break_test_collector.LevelBreakTestCollector`
- Observation: 1m bar close (`required_source_relation: "<="`)
