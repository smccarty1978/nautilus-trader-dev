"""
Databento ES Data Adapter & Indicator Pipeline (scripts/databento_es_adapter.py)
Reusable CLI script for ingesting Databento ES 1m Parquet files and generating
feature-enriched RTH Parquet caches for NautilusTrader.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.noise_vp_study.databento_es_adapter import DatabentoESAdapter

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Databento ES Data Adapter & Indicator Pipeline")
    parser.add_argument("--input", type=str, required=True, help="Path to raw Databento parquet")
    parser.add_argument("--output", type=str, default="research/noise_vp_study/es_rth_cache.parquet", help="Path to output cache")
    parser.add_argument("--multiplier", type=float, default=1.0, help="Noise band multiplier")
    args = parser.parse_args()

    adapter = DatabentoESAdapter(
        input_parquet_path=args.input,
        output_cache_path=args.output,
        band_multiplier=args.multiplier,
    )
    adapter.process()
