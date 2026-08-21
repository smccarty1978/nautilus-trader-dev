"""Generic raw-parquet -> NautilusTrader catalog materializer CLI.

Thin CLI over backtests.nt_runtime.catalog_materializer, driven by the
product registry in backtests.nt_runtime.data_plan.PRODUCT_CATALOGS. Do not
copy this into a product-specific script -- register the product in
PRODUCT_CATALOGS and pass its symbol here instead.

Usage:
    python scripts/build_v0_catalog.py --product YM --years 2024 --streams 1s,1m
    python scripts/build_v0_catalog.py --product YM --years 2024 --streams 1s,1m --plan-only
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from backtests.nt_runtime.catalog_materializer import build_catalog, plan_materialization


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", required=True, help="Product symbol registered in PRODUCT_CATALOGS, e.g. YM")
    parser.add_argument("--years", required=True, help="Comma-separated years/year-tokens, e.g. 2024 or 2024,2025,2026_ytd")
    parser.add_argument("--streams", required=True, help="Comma-separated streams, e.g. 1s,1m")
    parser.add_argument("--plan-only", action="store_true", help="Report the materialization plan; write nothing")
    args = parser.parse_args()

    years = [y.strip() for y in args.years.split(",") if y.strip()]
    streams = [s.strip() for s in args.streams.split(",") if s.strip()]

    plan = plan_materialization(args.product, years, streams)
    print(f"status: {plan.status}")
    print(f"product: {plan.product}")
    print(f"catalog_path: {plan.catalog_path}")
    print(f"detail: {plan.detail}")

    if args.plan_only:
        return 0

    if plan.status == "READY":
        print("Already materialized; nothing to build.")
        return 0
    if plan.status in ("UNSUPPORTED_PRODUCT", "RAW_DATA_MISSING"):
        print(f"[abort] cannot build: {plan.status}")
        return 1

    manifest = build_catalog(args.product, years, streams)
    print("Build complete.")
    for stream, info in manifest["streams"].items():
        print(f"  {stream}: {info['row_count']:,} bars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
