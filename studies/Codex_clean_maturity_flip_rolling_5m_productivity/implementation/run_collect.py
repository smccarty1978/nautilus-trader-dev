"""QUARANTINED (Phase 1 Packet A3) -- this script no longer executes.

Historical context: this was a one-time, user-authorized exploratory diagnostic (see
../EXPLORATORY_CONTRACT_WAIVER.md, authorized 2026-08-14) that opened
data/catalog/NQ_v0_2020_2026 directly, built its own BacktestEngine and instrument, and
wrote parquet output directly -- bypassing resolve_catalog_plan, authorized_dates /
chronology enforcement, frozen identity + preexec seal verification, and OutputManager.
Referenced historically in ../audit/pass_06.md, ../audit/pass_07.md, ../audit/pass_17.md,
and ../audit/contract_pass_19.md.

That bypass is retired. Verified at quarantine time (2026-08-21): zero import
dependents and zero test dependents anywhere in the repo (nothing imports
`studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.run_collect`).

The one governed execution path for this study is:

    python backtests/run_nt_study.py \\
        --study studies/Codex_clean_maturity_flip_rolling_5m_productivity \\
        --mode collect --stage <day|full>

which flows through backtests/nt_runtime/data_plan.py:resolve_data_plan (fail-closed
catalog resolution, A2), frozen identity + preexec seal verification, the existing
backtests/nt_runtime/modes/collect.py collect mode, and backtests/nt_runtime/output_manager.py.

This file is kept, rather than deleted, only so a reader following the audit trail above
finds an explicit refusal here instead of a silently vanished file. It intentionally
contains no catalog construction, no engine construction, and no hardcoded catalog path,
so it carries nothing for the Packet A3 static guard
(scripts/scan_alternate_catalog_openers.py) to find.
"""

from __future__ import annotations


def main() -> None:
    raise RuntimeError(
        "QUARANTINED_ENTRYPOINT: this script directly opened a hardcoded catalog and "
        "bypassed governed execution; it is permanently disabled (Phase 1 Packet A3). "
        "Use the governed collector entrypoint instead: "
        "python backtests/run_nt_study.py "
        "--study studies/Codex_clean_maturity_flip_rolling_5m_productivity "
        "--mode collect --stage <day|full>"
    )


if __name__ == "__main__":
    main()
