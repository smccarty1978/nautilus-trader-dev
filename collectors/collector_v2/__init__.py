"""Collector V2 — NT-native MTF feature/state.

The single rule:

    source_bar_close_ts <= decision_ts

Enforced by CompletedBarRegistry.audit_provenance() on every
snapshot. Halts (raises) on violation.

# Timing convention (CRITICAL — reproduced from CAUSALITY.md)

Databento timestamps bars at OPEN. The catalog has been built with
the correct ts_init_delta so that inside NT:

  - bar.ts_event = bar OPEN time
  - bar.ts_init  = bar CLOSE time = the moment NT delivers the bar
                   to the strategy

Inside Collector V2:

  - **Bucket assignment** uses bar.ts_event. A 1s bar with
    ts_event=09:04:59 belongs to the 5m bucket [09:00, 09:05).
  - **Feature availability** is governed by bar.ts_init. The
    aggregator closes a bucket only when the FIRST bar of the
    NEXT bucket arrives, and that bar arrives at ts_init = its
    ts_event + 1s.
  - **decision_ts is always bar.ts_init.** Never use ts_event for
    decisions; you don't have the bar at ts_event yet.
  - **close_ts = calendar close.** A 5m bucket [09:00, 09:05) has
    close_ts = 09:05:00. NT receives the trigger 1s bar at
    ts_init = 09:05:01. So decision_ts >= close_ts is naturally
    satisfied by ~1s margin — that 1s IS the causality buffer.

# Audit invariant

    close_ts <= decision_ts

for every state stored in CompletedBarRegistry. Violation raises
CausalityViolation immediately.

# Public surface

    - CompletedBarRegistry
    - CompletedBarState
    - RegimeStateEngine
    - TimeframeAggregator
    - FeatureSnapshotBuilder
    - CollectorV2Strategy + CollectorV2Config (Mode 1 / Mode 2)
"""
