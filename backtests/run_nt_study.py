#!/usr/bin/env python
"""NautilusTrader Generic Study Runner CLI.
===========================================
Executes declarative NautilusTrader studies from compiled_study.json contracts.

Usage:
    python backtests/run_nt_study.py --study studies/<name> --mode collect --stage day
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtests.nt_runtime.modes.collect import run_collect_mode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute declarative NautilusTrader study contracts."
    )
    parser.add_argument(
        "--study",
        "-s",
        type=str,
        required=True,
        help="Path to study directory containing study.yaml and compiled_study.json",
    )
    parser.add_argument(
        "--mode",
        "-m",
        type=str,
        default="collect",
        choices=["collect", "parity", "backtest"],
        help="Execution mode (Phase 1 supports 'collect' only)",
    )
    parser.add_argument(
        "--stage",
        type=str,
        default="day",
        choices=["fixture", "day", "week", "month", "full"],
        help="Bounded execution stage (default: day)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Explicit date within authorized study chronology (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Custom base output directory for runs (default: runs/)",
    )
    parser.add_argument(
        "--reference",
        "-r",
        type=str,
        default=None,
        help="Optional path to trusted reference candidates.parquet for automatic equivalence validation",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="ERROR",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="NautilusTrader logging verbosity",
    )

    args = parser.parse_args()

    if args.mode != "collect":
        print(
            f"[ERROR] Mode '{args.mode}' is deferred to Phase 2/3. Phase 1 supports 'collect' only.",
            file=sys.stderr,
        )
        return 1

    try:
        status_data = run_collect_mode(
            study_path=args.study,
            stage=args.stage,
            date_override=args.date,
            output_dir=args.output_dir,
            log_level=args.log_level,
        )

        if args.reference:
            from scripts.check_collect_equivalence import check_collect_equivalence, load_parquet_safe
            cand_parquet = status_data["output_artifacts"]["candidates_parquet"]
            ref_df = load_parquet_safe(args.reference)
            cand_df = load_parquet_safe(cand_parquet)
            is_eq, report = check_collect_equivalence(ref_df, cand_df)
            if is_eq:
                print("\n[VALIDATION] GENERIC_RUNNER_EQUIVALENT against reference.")
            else:
                print(f"\n[VALIDATION FAILED] GENERIC_RUNNER_DIVERGED: {report.get('divergence')}", file=sys.stderr)
                return 1

        return 0
    except Exception as e:
        print(f"[ERROR] NT Execution failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
