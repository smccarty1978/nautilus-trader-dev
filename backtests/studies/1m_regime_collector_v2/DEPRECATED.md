# DEPRECATED — Legacy collector v2

**As of 2026-04-27**, this directory is **legacy**. The active
NT-native MTF collector lives at:

    collectors/collector_v2/

The new architecture enforces:
- All MTF state lives in a `CompletedBarRegistry` updated only on
  bar close
- Fail-fast provenance audit on every snapshot
- No pandas reconstruction of state
- 1-week NT-vs-NT parity gate before any full run

See `CAUSALITY.md` at repo root for the hard rules.

This legacy directory is preserved for read-only reference (existing
strategies that subclass `CollectorV2` from here continue to work
until migrated).

**New work must use `collectors/collector_v2/`.**
