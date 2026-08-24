#!/usr/bin/env python3
"""Atomically activate the validated canonical Feature System V2 bundle."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from features.candidate_authority import activate_pipeline_candidate


def main() -> int:
    result = activate_pipeline_candidate(
        parity_matrix_path=ROOT / "scratch" / "feature_system_v2_full_legacy_parity_matrix.json"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
