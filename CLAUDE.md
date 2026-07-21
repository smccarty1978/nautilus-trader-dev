# NautilusTrader Development Framework

## CORE INVARIANTS (NEVER VIOLATE)
1. **NT is the ONLY execution environment.** NO pandas for signal detection, validation, or backtesting. Pandas is strictly for loading raw data and post-analysis of NT outputs.
2. **No Look-Ahead Bias.** Indicators compute on COMPLETED bars only.
3. **Timestamp Convention.** Databento timestamps at OPEN. You MUST apply `ts_init_delta` when wrangling (e.g., `60_000_000_000` for 1m bars). 1s bars need no adjustment.
4. **MFE/MAE Blind Spot.** 1s bars process before their parent 1m bar in NT. To avoid missing the first minute of price action, you MUST buffer recent 1s bars and replay them retroactively from fill time when a signal triggers.
5. **Mandatory Audit Gate.** You must invoke the `lookahead-auditor` and clear all CRITICAL findings before finalizing any strategy, feature engineering, or causal matching logic.

## DOCUMENTATION INDEX
Do not guess implementation details. Use your `Read` tool to read the relevant spec before writing code:

- **Catalog & Data:** `docs/DATA_CATALOG.md` (Wrangling, building, validation)
- **Backtest & Config:** `docs/BACKTEST_EXECUTION.md` (Runner setup, parameter sweeps, yaml configs)
- **Reporting & Tearsheets:** `docs/ANALYSIS_REPORTING.md` (NT built-in reports, TearsheetConfigs)
- **Studies & ML Data:** `docs/STUDY_METHODOLOGY.md` (Feature collection, MFE/MAE replay pattern)
- **Templates:** `docs/TEMPLATES.md` (Indicator and Strategy SPEC.md templates)
- **Optimization:** `docs/PERFORMANCE.md` (Profiling, ONNX ML inference)

<!-- BEGIN CENTRAL FEATURE SYSTEM -->
## Central Feature System

Before creating, modifying, or locally reimplementing a feature:

1. Read `features/FEATURE_REGISTRY_CONTRACT.md`.
2. Inspect `features/registry.py` for the canonical name, implementation,
   lifecycle, aliases, and verification status.
3. Reuse a verified registered feature when available.
4. Do not add a study-local duplicate without a documented exemption.
5. A central implementation defines how a feature is calculated; the
   study contract must still define when it is updated and snapped.
6. New or changed features require registry metadata, focused tests,
   provenance review, and parity evidence where applicable.
<!-- END CENTRAL FEATURE SYSTEM -->

