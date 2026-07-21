# Regime Flip Truth Collector — Look-Ahead Audit Record

Auditor: `lookahead-auditor` subagent. Scope: `collector.py`, `indicators.py`,
`run_collector.py`, `SPEC.md`, and the additive 5s extension to
`collectors/collector_v2/{aggregator,registry}.py`.

## Round 1
- **CRITICAL: 0.** WARNING: 2. Note: 3.
- W1 — VWAP updated with the triggering 1s bar before the entry snapshot
  (sub-tick look-ahead into `dist_from_vwap_atr` / `vwap_z` at entry).
- W2 — checkpoint trigger keyed on `ts_event` fired the named offset ("+30s",
  "Bar2", …) one second late; recorded `ts` was 1s past the landmark.
- Verified clean: Population A/B entry at 1m boundary with no first-minute MFE/MAE
  blind spot; feature engine `update()` before snapshot; MTF context via registry
  with `audit_provenance` air-gap; terminating event excludes the new regime's
  first 1s bar while the new event includes it; prior-regime context taken from
  the just-ended (finalized) regime; safe catalog; no double `ts_init_delta`;
  `NQ.v.0` (roll-safe); temporal split.

## Fixes applied
- **W1**: `SessionVWAP.update_1s(...)` moved to AFTER `_on_1m_close` (entry
  snapshots now read VWAP as-of `entry_ts`, excluding the triggering bar; path
  checkpoints read VWAP including the current closed bar). Each 1s bar updates
  VWAP exactly once (verified — no double-count/drop).
- **W2**: checkpoint trigger changed to `decision_ts >= entry_ts + off` so each
  landmark fires on the bar closing exactly at `entry_ts+off`, with running
  state folded in before the snapshot.

## Round 2 (re-audit of fixes)
- **CRITICAL: 0. WARNING: 0 (unresolved).** Note: 1 (benign duplication of
  `dist_from_vwap_atr` between feature snapshot and entry checkpoint — numerically
  identical, no causality impact).
- Both fixes verified correct and complete; no new look-ahead introduced; all
  round-1 clean items re-confirmed.

**Gate status: PASSED** — cleared for production research runs. A 1-week
causality smoke (zero `CausalityViolation`) is run before the full collection.
