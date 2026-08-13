# Canonical Research Parquet Consolidation — Contract Gate

**Date:** 2026-07-26  
**Reviewer:** Main-session contract fallback, explicitly authorized by user  
**Scope:** C4, D, E, and `CONSOLIDATION_SPEC.md` deliverables only  
**Verdict:** **PASS**

## Status

- Critical: 0
- Warning: 0
- Note: 0

The named `contract_checker` role was invoked twice and failed before review
because its configured model is unavailable on this Codex account. The user
explicitly authorized this one-time main-session contract-only fallback.

## Compliance

| Contract area | Status | Evidence |
|---|---|---|
| C4 promotion/seal checks | PASS | Only complete artifacts matching accepted adjacent manifests and hashes are eligible. Exact expected source counts are enforced. |
| D1 offline/live parity | N/A | No feature recomputation or serving occurs; accepted NT-produced values are copied unchanged. |
| D2 post-filter population | N/A | No training or filter fitting occurs. |
| D3 model export identity | N/A | No model export occurs. |
| D4 ordering/null/schema determinism | PASS | Strict Arrow column order, type, nullability, and metadata equality is required within each grain; no schema union/coercion is allowed. |
| E1–E5 backtest configuration | N/A | No backtest or order simulation occurs. |
| Source inventory | PASS | Exact observation, summary, and path source roots are frozen; inventory records year, month, direction/model, schema hash, collector hash, rows, file hash, and manifest hash. |
| Row-grain separation | PASS | Observations, summaries, and one-second paths are written independently. |
| Direction/model mapping | PASS | Summary model is the accepted `entry_model_id`; path model is joined by immutable `trade_id` and direction equality is enforced. Dual-model observations are not artificially duplicated. |
| Duplicate handling | PASS | Exact and conflicting duplicates are classified independently; any semantic-key duplicate stops consolidation without deletion. |
| Reconciliation | PASS | Global fingerprints, all-column null counts, immutable-key hash sums, selected numeric aggregates, and exact year/month/model/direction counts must match before/after. |
| Coverage | PASS | Missing months, sides/models, empty files, overlaps, timestamp-gap assessment, timestamp ranges, and unique regime/trade counts are reported. |
| Source preservation | PASS | Every source hash is recorded before writing and rechecked afterward. |
| Deterministic output | PASS | Frozen grain-specific sort keys and Zstandard settings are configuration-bound. |
| Lazy loader | PASS | Grain-aware required-column validation and pushdown-compatible date/model/direction filters return a Polars `LazyFrame`. |
| Tests | PASS | Synthetic tests cover schema mismatch, count/null/fingerprint reconciliation, metadata preservation, duplicate classification, deterministic ordering, source immutability, and loader filtering. |

## Deliverables manifest

| Deliverable | Reachable |
|---|---|
| `consolidated/canonical_observations_all.parquet` | Yes |
| `consolidated/canonical_trade_summaries_all.parquet` | Yes |
| `consolidated/canonical_trade_paths_all.parquet` | Yes |
| `consolidated/SOURCE_INVENTORY.json` | Yes |
| `consolidated/RECONCILIATION_REPORT.json` | Yes |
| Consolidation implementation | Yes |
| Lazy loader with usage example | Yes |
| Bounded synthetic tests | Yes |

Annual convenience files are intentionally omitted because the lazy loader
provides annual filtering without substantially duplicating the primary
artifacts.

---

*The contract-only pre-execution gate is satisfied.*
