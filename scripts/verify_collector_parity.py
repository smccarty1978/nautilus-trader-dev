"""Diagnostic parity check: run the full collector and compare every persisted
value against a trusted reference run directory.

Seal verification is bypassed because this is a benchmark/diagnostic comparison,
not a governed artifact.  It never issues acceptance; it only answers
"did this change alter any output value?".
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtests.nt_runtime.modes import collect
import scripts.resolve_execution_manifest as execution_manifest

STUDY = ROOT / "studies/clean_maturity_flip_model_rolling_productivity"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", required=True)
    ap.add_argument("--date", default="2023-10-02")
    ap.add_argument("--output-dir", default="runs/parity_check")
    args = ap.parse_args()

    collect.verify_preexec_audit_seal = lambda *a, **k: True
    execution_manifest.verify_frozen_execution_identity = lambda *a, **k: None

    started = time.perf_counter()
    result = collect.run_collect_mode(
        study_path=STUDY, stage="day", date_override=args.date,
        output_dir=ROOT / args.output_dir, log_level="ERROR")
    wall = time.perf_counter() - started

    run_dir = Path(result["run_directory"]) if "run_directory" in result else None
    art = result.get("output_artifacts", {})
    new_c = Path(art["candidates_parquet"])
    new_o = Path(art.get("observations_parquet", new_c.parent / "observations.parquet"))
    ref = Path(args.reference)
    ref_c, ref_o = ref / "candidates.parquet", ref / "observations.parquet"

    ok = True
    for label, a, b in (("candidates", new_c, ref_c), ("observations", new_o, ref_o)):
        da, db = pd.read_parquet(a), pd.read_parquet(b)
        same_shape = da.shape == db.shape
        same_cols = list(da.columns) == list(db.columns)
        print(f"{label}: new={da.shape} ref={db.shape} shape_match={same_shape} cols_match={same_cols}")
        if not (same_shape and same_cols):
            ok = False
            continue
        # Exact equality including NaN positions and dtypes.
        try:
            pd.testing.assert_frame_equal(da, db, check_exact=True, check_dtype=True)
            print(f"  {label}: EXACT MATCH on all {len(da)} rows x {len(da.columns)} cols")
        except AssertionError as exc:
            ok = False
            print(f"  {label}: MISMATCH\n{exc}")

    o = pd.read_parquet(new_o)
    if "target_flip_within_horizon" in o.columns:
        vc = o["target_flip_within_horizon"].value_counts(dropna=False).to_dict()
        print("labels:", vc)
    print(f"wall_seconds={wall:.2f} run_dir={run_dir}")
    print("EXACT_PARITY:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
