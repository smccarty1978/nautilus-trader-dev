"""Compare a fresh Platform-v2 study's controller-produced partition frames with a frozen
historical reference (reference fixtures are read-only; nothing is written into them).

    python scripts/parity/compare_study_to_reference.py --study <dir> --shape a --partition train --year 2021
    python scripts/parity/compare_study_to_reference.py --study <dir> --shape c --partition oos --year 2022

Frames: <study>/_work/controller/partitions/<partition>/<year>/{candidates,observations}.parquet
(or the merged frames with --partition merged).  Report: <study>/artifacts/parity_<shape>_<partition>_<year>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.parity.compare_frames import compare_frames, summarize  # noqa: E402
from scripts.parity.run_shape import load_reference  # noqa: E402

KEY = ["observation_ts", "regime_start_ns", "checkpoint_index"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--study", required=True)
    ap.add_argument("--shape", required=True, choices=["a", "b", "c"])
    ap.add_argument("--partition", default="train", choices=["train", "oos", "merged"])
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--tolerance", type=float, default=1e-9)
    ns = ap.parse_args()
    study = Path(ns.study).resolve()
    base = study / "_work" / "controller" / ("merged" if ns.partition == "merged" else f"partitions/{ns.partition}/{ns.year}")
    cands = pd.read_parquet(base / "candidates.parquet")
    obs = pd.read_parquet(base / "observations.parquet")
    start_ns, end_ns = int(pd.Timestamp(f"{ns.year}-01-01", tz="UTC").value), int(pd.Timestamp(f"{ns.year + 1}-01-01", tz="UTC").value) - 1
    if ns.partition == "merged":
        m = cands["observation_ts"].between(start_ns, end_ns)
        cands, obs = cands[m].reset_index(drop=True), obs[obs["observation_ts"].between(start_ns, end_ns)].reset_index(drop=True)
    ref_c, ref_o = load_reference(ns.shape, start_ns, end_ns)
    cand_report = compare_frames(ref_c, cands, tolerance=ns.tolerance)
    if ns.shape == "c":
        obs_cols = ["regime_direction"] + [c for c in ref_o.columns if c.startswith("target_tp1_")]
    else:
        obs_cols = [c for c in ref_o.columns if c not in KEY]
    obs_report = compare_frames(ref_o, obs, tolerance=ns.tolerance, columns=obs_cols)
    report = {"study": study.name, "shape": ns.shape, "partition": ns.partition, "year": ns.year, "rows": {"runtime_candidates": int(len(cands)), "reference_candidates": int(len(ref_c)),
              "runtime_observations": int(len(obs)), "reference_observations": int(len(ref_o))}, "candidates": cand_report, "observations": obs_report,
              "passed": bool(cand_report["passed"] and obs_report["passed"]), "historical_study_modified": False}
    out = study / "artifacts" / f"parity_{ns.shape}_{ns.partition}_{ns.year}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"STATUS": "PASS" if report["passed"] else "FAIL", "report": str(out), "rows": report["rows"]}))
    print("CANDIDATES", summarize(cand_report))
    print("OBSERVATIONS", summarize(obs_report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
