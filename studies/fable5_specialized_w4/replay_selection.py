"""Causal candidate-selection replay for the frozen specialized W4 models.

At each candidate (time order): score with the frozen model, accept iff the
score passes the frozen retention cutoff for the candidate's segment, enter
at the candidate's immediate causal fill, manage with Policy A (labels were
replayed independently in build_dataset). Two accountings: independent
candidate economics and one-position streaming economics.
"""
from __future__ import annotations

import argparse
import json
import pickle

import numpy as np
import pandas as pd

import fable5_common as C
from train_models import (calibration_rows, decile_rows, metric_rows,
                          score_structure, segment_masks)

BAND_LABELS = [f"top_{int(b * 100)}" for b in C.RETENTION_BANDS]


def assign_cutoff(structure: str, cutoffs: dict, band: str,
                  d: pd.DataFrame) -> np.ndarray:
    out = np.full(len(d), np.nan)
    positions = pd.Series(np.arange(len(d)), index=d.index)
    for name, mask in segment_masks(structure, d).items():
        if not mask.any():
            continue
        out[positions[mask.to_numpy()].to_numpy()] = cutoffs[name][band]
    if np.isnan(out).any():
        raise RuntimeError("candidate without retention cutoff")
    return out


def split_specs(frame: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    interaction = (frame.direction.str.replace("_fade", "", regex=False)
                   + "_" + frame.session)
    return [("combined", pd.Series("ALL", index=frame.index)),
            ("direction", frame.direction), ("session", frame.session),
            ("direction_session", interaction)]


def summarize(policy_id: str, window: str, accounting: str,
              considered: pd.DataFrame, executed_mask: pd.Series,
              skipped_position: pd.Series) -> list[dict]:
    rows = []
    for split_type, labels in split_specs(considered):
        for value, g in considered.assign(_s=labels).groupby("_s", sort=False):
            ex = g[executed_mask.reindex(g.index, fill_value=False)]
            pnl = ex.net_pnl_usd.astype(float)
            booked = pd.Series(0.0, index=g.index)
            booked.loc[ex.index] = pnl
            order = (ex.sort_values("exit_fill_ts") if accounting == "streaming"
                     else ex.sort_values("candidate_time"))
            rows.append({
                "policy_id": policy_id, "window": window,
                "accounting": accounting, "split_type": split_type,
                "split_value": str(value), "candidates": len(g),
                "executed": len(ex),
                "skipped_by_score": int((~executed_mask.reindex(
                    g.index, fill_value=False)
                    & ~skipped_position.reindex(g.index, fill_value=False)).sum()),
                "skipped_position_open": int(skipped_position.reindex(
                    g.index, fill_value=False).sum()),
                "retention_rate": len(ex) / len(g) if len(g) else np.nan,
                "total_net_pnl_usd": float(pnl.sum()),
                "mean_pnl_per_candidate_usd": float(booked.mean()) if len(g) else np.nan,
                "mean_pnl_per_trade_usd": float(pnl.mean()) if len(ex) else np.nan,
                "profit_factor": C.profit_factor(pnl),
                "win_rate": float((pnl > 0).mean()) if len(ex) else np.nan,
                "stop_rate": float(ex.exit_reason.str.contains("stop").mean())
                if len(ex) else np.nan,
                "prestop_rate": float(
                    (ex.exit_reason == "preflip_policy_stop").mean())
                if len(ex) else np.nan,
                "timeout_rate": float(
                    (ex.exit_reason == "confirmation_timeout_exit").mean())
                if len(ex) else np.nan,
                "average_winner_usd": float(pnl[pnl > 0].mean())
                if (pnl > 0).any() else np.nan,
                "average_loser_usd": float(pnl[pnl < 0].mean())
                if (pnl < 0).any() else np.nan,
                "max_closed_trade_drawdown_usd": C.drawdown(
                    order.net_pnl_usd.astype(float)) if len(ex) else 0.0,
                "cost_total_usd": float(len(ex) * C.COST)})
    return rows


def streaming_execution(accepted: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """One-position accounting over accepted, replayable candidates."""
    executed = pd.Series(False, index=accepted.index)
    skipped_position = pd.Series(False, index=accepted.index)
    busy_until = -1
    ordered = accepted.sort_values(["candidate_fill_time", "candidate_seq"])
    for idx, c in ordered.iterrows():
        entry_ts = int(c.candidate_fill_time)
        if entry_ts < busy_until:
            skipped_position.loc[idx] = True
            continue
        executed.loc[idx] = True
        exit_ts = int(c.exit_fill_ts)
        busy_until = exit_ts + C.NS if "stop" in c.exit_reason else exit_ts
    return executed, skipped_position


def policy_arms(bundle: dict, d: pd.DataFrame) -> dict[str, dict]:
    arms = {}
    scores = {}
    for structure, entry in bundle["structures"].items():
        scores[structure] = score_structure(structure, entry["fitted"], d)
        for band in BAND_LABELS:
            cutoff = assign_cutoff(structure, entry["cutoffs"], band, d)
            arms[f"{structure}_{band}"] = {
                "structure": structure,
                "accept": pd.Series(scores[structure] >= cutoff, index=d.index)}
    arms["take_all"] = {"structure": None,
                        "accept": pd.Series(True, index=d.index)}
    frozen_regimes = set()
    for year in sorted(d.year.unique()):
        frozen = pd.read_parquet(C.frozen_trade_path(int(year)),
                                 columns=["regime_start_ns"])
        frozen_regimes |= set(frozen.regime_start_ns.astype(np.int64))
    arms["policy_a_frozen"] = {
        "structure": None,
        "accept": (d.candidate_seq.eq(1)
                   & d.regime_start_ns.isin(frozen_regimes))}
    return arms, scores


def run_window(bundle: dict, window_name: str, d: pd.DataFrame
               ) -> tuple[list[dict], pd.DataFrame]:
    arms, scores = policy_arms(bundle, d)
    replayable = d[d.replayable].copy()
    results = []
    diff = d[["candidate_id", "opportunity_id", "candidate_seq", "year",
              "candidate_time", "candidate_fill_time", "direction", "session",
              "w4_score", "score_margin", "replayable", "net_pnl_usd",
              "exit_reason", "label_net_positive"]].copy()
    diff["window"] = window_name
    lo, hi = bundle["quintile_edges"]
    diff["label_top_quintile_pnl"] = np.where(
        d.replayable, (d.net_pnl_usd >= hi).astype(float), np.nan)
    diff["label_bottom_quintile_pnl"] = np.where(
        d.replayable, (d.net_pnl_usd <= lo).astype(float), np.nan)
    for structure, s in scores.items():
        diff[f"score_{structure}"] = s
    for policy_id, arm in arms.items():
        accept = arm["accept"] & d.replayable
        accepted = replayable[accept.reindex(replayable.index, fill_value=False)]
        diff[f"accept_{policy_id}"] = accept
        none = pd.Series(False, index=replayable.index)
        independent_exec = accept.reindex(replayable.index, fill_value=False)
        results += summarize(policy_id, window_name, "independent",
                             replayable, independent_exec, none)
        stream_exec, stream_skip = streaming_execution(accepted)
        results += summarize(policy_id, window_name, "streaming", replayable,
                             stream_exec.reindex(replayable.index,
                                                 fill_value=False),
                             stream_skip.reindex(replayable.index,
                                                 fill_value=False))
    return results, diff


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, choices=(2025, 2026), required=True)
    args = parser.parse_args()
    C.ensure_dirs()
    C.require_authorization()
    C.freeze_inputs_or_verify()
    manifest = json.loads(C.MODEL_MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("bundle_sha256") != C.sha256_file(C.BUNDLE_PATH):
        raise RuntimeError("bundle hash mismatch against frozen manifest")
    with C.BUNDLE_PATH.open("rb") as f:
        bundle = pickle.load(f)
    if args.year == 2026:
        C.require_2026_open_allowed("replay 2026 selection policies")
    d = pd.read_parquet(C.dataset_path(args.year))
    all_results, all_diffs = [], []
    windows = ([("2025_H1_train_insample", d[d.window == "2025_H1_train"]),
                ("2025_H2_dev", d[d.window == "2025_H2_dev"])]
               if args.year == 2025 else [("2026_test", d)])
    diagnostics = {"metrics": [], "deciles": [], "calibration": []}
    for window_name, frame in windows:
        frame = frame.copy()
        results, diff = run_window(bundle, window_name, frame)
        all_results += results
        all_diffs.append(diff)
        if window_name == "2026_test":
            labeled = frame[frame.replayable].copy()
            for structure, entry in bundle["structures"].items():
                s = score_structure(structure, entry["fitted"], labeled)
                rows = metric_rows(structure, entry["config"], labeled, s, True)
                for r in rows:
                    r["window"] = "2026_test"
                diagnostics["metrics"] += rows
                rows = decile_rows(structure, labeled, s)
                for r in rows:
                    r["window"] = "2026_test"
                diagnostics["deciles"] += rows
                rows = calibration_rows(structure, labeled, s)
                for r in rows:
                    r["window"] = "2026_test"
                diagnostics["calibration"] += rows
    pd.DataFrame(all_results).to_parquet(
        C.WORK / f"policy_results_{args.year}.parquet", index=False)
    pd.concat(all_diffs, ignore_index=True).to_parquet(
        C.WORK / f"trade_diffs_{args.year}.parquet", index=False)
    if args.year == 2026:
        for key, name in (("metrics", "model_metrics_2026"),
                          ("deciles", "decile_lift_2026"),
                          ("calibration", "calibration_2026")):
            pd.DataFrame(diagnostics[key]).to_parquet(
                C.WORK / f"{name}.parquet", index=False)
        combine_results()
    print(f"replayed {args.year}: "
          f"{len(pd.DataFrame(all_results)):,} policy split rows")


def combine_results() -> None:
    policy = pd.concat([pd.read_parquet(C.WORK / f"policy_results_{y}.parquet")
                        for y in (2025, 2026)], ignore_index=True)
    diffs = pd.concat([pd.read_parquet(C.WORK / f"trade_diffs_{y}.parquet")
                       for y in (2025, 2026)], ignore_index=True)
    audit = pd.concat([pd.read_parquet(C.WORK / f"dataset_audit_{y}.parquet")
                       for y in (2025, 2026)], ignore_index=True)
    metrics = pd.concat([pd.read_parquet(C.WORK / "model_metrics_dev.parquet"),
                         pd.read_parquet(C.WORK / "model_metrics_2026.parquet")],
                        ignore_index=True)
    deciles = pd.concat([pd.read_parquet(C.WORK / "decile_lift_dev.parquet"),
                         pd.read_parquet(C.WORK / "decile_lift_2026.parquet")],
                        ignore_index=True)
    calibration = pd.concat([pd.read_parquet(C.WORK / "calibration_dev.parquet"),
                             pd.read_parquet(C.WORK / "calibration_2026.parquet")],
                            ignore_index=True)
    importance = pd.read_parquet(C.WORK / "feature_importance.parquet")
    outputs = {
        "specialized_w4_dataset_audit.parquet": audit,
        "specialized_w4_model_metrics.parquet": metrics,
        "specialized_w4_decile_lift.parquet": deciles,
        "specialized_w4_policy_results.parquet": policy,
        "specialized_w4_trade_diffs.parquet": diffs,
        "specialized_w4_feature_importance.parquet": importance,
        "specialized_w4_calibration.parquet": calibration,
    }
    for name, frame in outputs.items():
        frame.to_parquet(C.RESULTS / name, index=False)
    manifest = {
        "status": "OUTPUTS_COMPLETE_PENDING_REPORT_AND_COMPLETION_AUDIT",
        "selection_manifest_sha256": C.sha256_file(C.MODEL_MANIFEST_PATH),
        "bundle_sha256": C.sha256_file(C.BUNDLE_PATH),
        "input_freeze_sha256": C.sha256_file(C.FREEZE_PATH),
        "output_sha256": {name: C.sha256_file(C.RESULTS / name)
                          for name in outputs},
    }
    C.MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
