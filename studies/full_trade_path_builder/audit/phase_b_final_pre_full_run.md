# Phase B Final Pre-Full-Run Re-Audit

**Date:** 2026-07-24  
**Scope:** hardened monthly runner, global finalizer, current collector/config, boundary and runtime-parity evidence, and Phase B contract tests  
**Scope hash:** `cc32eeee1bd7e12d27d7f09e2c7562e3021e68a62182677dda23801f57eff357`  
**Auditor:** lookahead-auditor v1  
**Verdict:** **PASS — full Phase B launch authorized**

## Summary

- Critical: 0
- Warning: 0
- Note: 0

## Critical findings

None.

## Warnings

None.

## Clean checks

### Fresh monthly execution

- The runner explicitly passes `--warmup-days 4`; it no longer depends on an implicit collector default.
- Month ownership remains deterministic and disjoint through ordinal modulo sharding.
- CT calendar boundaries are converted explicitly to UTC.
- Each assigned month runs in its own subprocess and writes to a unique year/month path.

### Resume validation

Before accepting an existing partition, the runner now requires:

- an accepted provisional or finalized status;
- the exact expected month interval;
- canonical four-day warmup;
- the current `phase_b.yaml` hash;
- the exact current runtime identity;
- valid hashes for score, flip, and missing-dispatch artifacts.

Old three-day, stale-config, mixed-code, corrupt, or wrong-window partitions fail loudly and cannot enter a resumed build.

### Global finalization

The finalizer requires:

- exactly 60 partitions covering 2021–2025;
- provisional status for every partition;
- `warmup_days == 4`;
- the current config hash from the correct repository path;
- one exact current runtime identity across all partitions;
- exact CT-calendar UTC intervals;
- valid hashes for all three monthly artifacts.

Only after validation does the finalizer deduplicate and hash the global flip ledger, recompute cross-partition next-flip labels, atomically rewrite each score partition, update its score hash, promote status to `complete`, and record global provenance hashes.

### Causal and parity evidence

- March runtime parity is exact for Bullish and Bearish vectors, null masks, feature hashes, raw scores, and probabilities.
- Missing Bear reference keys are fully reconciled to exact missing-dispatch timestamps.
- Four-day versus 30-day boundary continuity passes on 18,237 rows and 174 columns with exact equality.
- Year, spring-DST, summer, and fall-DST cases have zero mismatches.
- All 60 production prefixes observe a confirmed flip before output begins.
- The four-day prefix is consistently frozen throughout the execution stack.
- The 2026 sealed boundary remains enforced.
- Eleven Phase B contract tests pass.

### Launch sequencing

Authorized sequence:

1. Launch two bounded shards with `shard-count=2`, indices 0 and 1, and distinct progress files.
2. Each shard processes its 30 disjoint months sequentially.
3. Require both status cards to report `score_shard_complete` with 30 months.
4. Run the global finalizer exactly once from the root process.
5. Do not permit either shard worker to finalize.

## Compliance matrix

| Rule | Status |
|---|---|
| A1–A5 | PASS |
| B1–B7 | PASS |
| C1–C3 | PASS |
| D1–D4 | PASS/N/A |
| E1–E2 | PASS |
| E3–E5 | N/A |
| F1–F4 | PASS |
| G1–G4 | PASS |
| H1–H4 | N/A |

*Read-only audit. Authorization applies to the exact source/config state identified by the scope hash above and the bounded two-shard execution plan described here.*
