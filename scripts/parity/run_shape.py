#!/usr/bin/env python3
"""Three-shape real-data parity driver for the platform-v2 host.

    python scripts/parity/run_shape.py --shape a --start 2021-01-05 --end 2021-01-05
    python scripts/parity/run_shape.py --shape c --start 2021-01-05 --end 2021-01-05
    python scripts/parity/run_shape.py --shape b --start 2021-01-05 --end 2021-01-05

Runs the compiled parity plan over the catalog window (5-day warmup, primary interval =
the window), loads the sealed reference frames for the same window and compares
candidates and observations row-for-row (``compare_frames``).  Writes a JSON report
under ``artifacts/platform_v2_do_soon/parity/<shape>/``.  Never writes into a study.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
MAIN_REPO = ROOT.parent / "Nautilus Trader"
REGIME_WORKTREE = ROOT.parent / "Nautilus Trader-regime-transition-target"

from scripts.parity.compare_frames import compare_frames, summarize  # noqa: E402

NS = 1_000_000_000

SHAPES = {
    "a": {"spec": ROOT / "fixtures/parity/shape_a/study.yaml",
          "candidates": MAIN_REPO / "studies/clean_maturity_flip_model_180s_horizon/artifacts/train_candidates_merged.parquet",
          "observations": MAIN_REPO / "studies/clean_maturity_flip_model_180s_horizon/artifacts/train_observations_merged.parquet"},
    "c": {"spec": ROOT / "fixtures/parity/shape_c/study.yaml",
          "candidates": REGIME_WORKTREE / "studies/regime_transition_target_before_stop_v1/_work/train_merged_collection/candidates.parquet",
          "observations": REGIME_WORKTREE / "studies/regime_transition_target_before_stop_v1/_work/train_merged_collection/observations.parquet",
          "targets": REGIME_WORKTREE / "studies/regime_transition_target_before_stop_v1/_work/train_merged_collection/phase_c2_reconciled_targets.parquet"},
    "b": {"spec": ROOT / "fixtures/parity/shape_b/study.yaml",
          "runs": {2021: MAIN_REPO / "studies/deep_pullback_5s_reacceleration_model/runs/20260828_144743_deep_pullback_5s_reacceleration_model_full/collection",
                   2022: MAIN_REPO / "studies/deep_pullback_5s_reacceleration_model/runs/20260828_150235_deep_pullback_5s_reacceleration_model_full/collection",
                   2023: MAIN_REPO / "studies/deep_pullback_5s_reacceleration_model/runs/20260828_152004_deep_pullback_5s_reacceleration_model_full/collection"}},
}


def window_ns(start: str, end: str) -> tuple[int, int]:
    s = pd.Timestamp(f"{start} 00:00:00", tz="UTC").value
    e = pd.Timestamp(f"{end} 23:59:59.999999999", tz="UTC").value
    return int(s), int(e)


def load_reference(shape: str, start_ns: int, end_ns: int):
    cfg = SHAPES[shape]
    if shape == "b":
        years = sorted({pd.Timestamp(start_ns, tz="UTC").year, pd.Timestamp(end_ns, tz="UTC").year})
        cands = pd.concat([pd.read_parquet(cfg["runs"][y] / "candidates.parquet") for y in years], ignore_index=True)
        obs = pd.concat([pd.read_parquet(cfg["runs"][y] / "observations.parquet") for y in years], ignore_index=True)
    else:
        cands = pd.read_parquet(cfg["candidates"])
        obs = pd.read_parquet(cfg["observations"])
        if shape == "c":
            targets = pd.read_parquet(cfg["targets"])
            if len(targets) != len(cands):
                raise RuntimeError("SHAPE_C_TARGET_ROW_COUNT_MISMATCH")
            obs = obs.drop(columns=[c for c in targets.columns if c in obs.columns]).reset_index(drop=True)
            obs = pd.concat([obs, targets.reset_index(drop=True)], axis=1)
    m = (cands["observation_ts"] >= start_ns) & (cands["observation_ts"] <= end_ns)
    mo = (obs["observation_ts"] >= start_ns) & (obs["observation_ts"] <= end_ns)
    return cands.loc[m].reset_index(drop=True), obs.loc[mo].reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shape", required=True, choices=sorted(SHAPES))
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--warmup-days", type=int, default=5)
    ap.add_argument("--run-end", default=None, help="replay through this date (lookahead past the primary window), default = --end")
    ap.add_argument("--tolerance", type=float, default=1e-9)
    ap.add_argument("--tag", default="")
    ap.add_argument("--ledger", action="store_true")
    ap.add_argument("--save-frames", action="store_true")
    a = ap.parse_args()

    from research_workflow.grammar import compile_study, load_spec
    from research_workflow.host_runner import run_plan_on_catalog

    outcome = compile_study(load_spec(SHAPES[a.shape]["spec"]), repo_root=ROOT)
    if not outcome.ok:
        print(json.dumps(outcome.card(), indent=2))
        return 2
    plan = outcome.plan.to_dict()
    start_ns, end_ns = window_ns(a.start, a.end)
    out_dir = ROOT / "artifacts/platform_v2_do_soon/parity" / a.shape
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = a.tag or f"{a.start}_{a.end}"
    t0 = time.perf_counter()
    run = run_plan_on_catalog(plan, start_date=a.start, end_date=(a.run_end or a.end), repo_root=MAIN_REPO, primary_interval=(start_ns, end_ns),
                              warmup_days=a.warmup_days, progress_path=out_dir / f"{tag}.progress.json", ledger=a.ledger)
    elapsed = time.perf_counter() - t0
    cands, obs = run["candidates"], run["observations"]
    ref_c, ref_o = load_reference(a.shape, start_ns, end_ns)
    if a.save_frames:
        cands.to_parquet(out_dir / f"{tag}.candidates.parquet", index=False)
        obs.to_parquet(out_dir / f"{tag}.observations.parquet", index=False)
        if run.get("ledger") is not None:
            with open(out_dir / f"{tag}.ledger.jsonl", "w", encoding="utf-8") as fh:
                for row in run["ledger"]:
                    fh.write(json.dumps(row, default=str) + "\n")
    cand_report = compare_frames(ref_c, cands, tolerance=a.tolerance)
    if a.shape == "c":
        arm_cols = [c for c in ref_o.columns if c.startswith("target_tp1_")]
        obs_cols = ["regime_direction"] + arm_cols
    else:
        obs_cols = [c for c in ref_o.columns if c not in ("observation_ts", "regime_start_ns", "checkpoint_index")]
    obs_report = compare_frames(ref_o, obs, tolerance=a.tolerance, columns=obs_cols)
    report = {"shape": a.shape, "window": [a.start, a.end], "plan_sha256": outcome.plan.plan_sha256, "elapsed_s": round(elapsed, 2),
              "stats": run["stats"], "dataset": run["dataset"], "candidates": cand_report, "observations": obs_report,
              "passed": bool(cand_report["passed"] and obs_report["passed"]),
              "events_per_second": (run["stats"]["bars"] / run["elapsed_s"]) if run["elapsed_s"] else None}
    (out_dir / f"{tag}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"shape": a.shape, "window": report["window"], "passed": report["passed"], "elapsed_s": report["elapsed_s"],
                      "events_per_second": report["events_per_second"], "stats": run["stats"]}, default=str))
    print("CANDIDATES", summarize(cand_report))
    print("OBSERVATIONS", summarize(obs_report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
