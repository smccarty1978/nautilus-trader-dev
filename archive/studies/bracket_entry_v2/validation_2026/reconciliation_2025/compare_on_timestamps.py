"""Fixed reconciliation — match on decision_ts_ns instead of event_id.

event_id is assigned sequentially per run, so it doesn't match across
a March-only live run and a full-year offline run. decision_ts_ns is
deterministic from the event's signal_time + checkpoint_s.
"""

from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

RECON = Path(
    "studies/bracket_entry_v2/validation_2026/reconciliation_2025")
LIVE_DUMP = RECON / "live_scored_march2025.parquet"
OFFLINE_PRED = Path(
    "studies/bracket_entry_v2/feature_reduction/"
    "predictions_2025_top_15.parquet")
EVENT_SUMMARY = Path(
    "studies/1m_regime_collector_v2/results/"
    "v2_event_summary_2025.parquet")
THRESHOLD_FILE = RECON / "score_threshold.json"

START = pd.Timestamp("2025-03-01", tz="UTC")
END = pd.Timestamp("2025-03-31 23:59:59", tz="UTC")


def main():
    live = pd.read_parquet(LIVE_DUMP)
    print(f"Live scored rows: {len(live):,}")

    # Restrict to March (already has decision_ts_ns)
    live = live[(live["decision_ts_ns"] >= START.value)
                 & (live["decision_ts_ns"] <= END.value)]
    live = live[live["checkpoint_s"] <= 600].copy()
    print(f"Live (March, T<=600): {len(live):,}")

    # Offline: attach signal_time via event_summary, compute decision_ts_ns
    offline = pd.read_parquet(OFFLINE_PRED)
    es = pd.read_parquet(EVENT_SUMMARY)[
        ["event_id", "signal_time", "signal_direction"]]
    offline = offline.merge(es, on="event_id", how="left",
                              suffixes=("", "_es"))
    if "signal_direction_es" in offline.columns:
        # Defensively drop duplicate
        offline = offline.drop(columns=["signal_direction_es"])
    offline["decision_ts_ns"] = (
        offline["signal_time"].astype("int64")
        + offline["checkpoint_s"].astype("int64") * 1_000_000_000)
    # March + T≤600
    offline = offline[
        (offline["decision_ts_ns"] >= START.value)
        & (offline["decision_ts_ns"] <= END.value)
        & (offline["checkpoint_s"] <= 600)].copy()
    print(f"Offline (March, T<=600, resolved): {len(offline):,}")

    # Merge on (decision_ts_ns, checkpoint_s)
    merged = live.merge(
        offline[["decision_ts_ns", "checkpoint_s", "score",
                 "signal_direction", "event_id"]].rename(
            columns={"score": "score_offline",
                      "signal_direction": "dir_offline",
                      "event_id": "event_id_offline"}),
        on=["decision_ts_ns", "checkpoint_s"],
        how="outer", indicator=True)
    print(f"\nMerge: {merged['_merge'].value_counts().to_dict()}")

    both = merged[merged["_merge"] == "both"].copy()
    live_only = merged[merged["_merge"] == "left_only"]
    ref_only = merged[merged["_merge"] == "right_only"]
    print(f"  both: {len(both):,}")
    print(f"  live only (scored but not in offline ref): "
           f"{len(live_only):,}")
    print(f"  offline only (in ref but live didn't score): "
           f"{len(ref_only):,}")

    # Direction parity on matched
    if len(both):
        # live signal_direction vs offline
        both["dir_match"] = (
            both["signal_direction"] == both["dir_offline"])
        print(f"\nDirection parity on matched: "
               f"{int(both['dir_match'].sum())} / {len(both)}")

        score_diff = (both["score"] - both["score_offline"]).abs()
        print(f"\nScore parity on matched rows:")
        print(f"  max abs diff:    {score_diff.max():.2e}")
        print(f"  mean abs diff:   {score_diff.mean():.2e}")
        print(f"  median abs diff: {score_diff.median():.2e}")
        print(f"  exact (diff==0):  "
               f"{int((score_diff == 0).sum()):>6} / {len(both)}")
        print(f"  within 1e-12:     "
               f"{int((score_diff < 1e-12).sum()):>6} / {len(both)}")
        print(f"  within 1e-9:      "
               f"{int((score_diff < 1e-9).sum()):>6} / {len(both)}")
        print(f"  within 1e-6:      "
               f"{int((score_diff < 1e-6).sum()):>6} / {len(both)}")
        print(f"  within 1e-3:      "
               f"{int((score_diff < 1e-3).sum()):>6} / {len(both)}")

        # Show largest mismatches
        if score_diff.max() > 1e-6:
            print(f"\nTop-10 score mismatches:")
            worst = both.assign(abs_diff=score_diff).nlargest(
                10, "abs_diff")
            cols = ["decision_ts_ns", "checkpoint_s",
                     "event_id", "event_id_offline",
                     "score", "score_offline", "abs_diff"]
            print(worst[cols].to_string(index=False))

    # Candidate parity
    with open(THRESHOLD_FILE) as f:
        thr = json.load(f)["threshold_top10"]
    live_cand = int((live["score"] >= thr).sum())
    off_cand = int((offline["score"] >= thr).sum())
    print(f"\nCandidate parity (score >= {thr:.4f}):")
    print(f"  Live:    {live_cand:,}")
    print(f"  Offline: {off_cand:,}")

    # Verdict
    print()
    if len(both) and score_diff.max() < 1e-9:
        verdict = ("PASS — runtime and collector paths produce "
                    "bit-identical scores on matched rows. "
                    "The 2026 result is NOT a pipeline artifact.")
    elif len(both) and score_diff.max() < 1e-4:
        verdict = ("PASS (tight) — small float-precision noise only. "
                    "Paths are effectively identical.")
    elif len(both) and score_diff.mean() < 1e-3:
        verdict = ("MARGINAL — small systematic drift. Worth "
                    "investigating but unlikely to be the 2026 cause.")
    else:
        verdict = ("FAIL — scores diverge meaningfully. Runtime "
                    "pipeline has a bug. Fix before trusting 2026.")
    print(f"VERDICT: {verdict}")

    # Dump report
    lines = []
    lines.append("# Runtime-vs-Collector Reconciliation — March 2025")
    lines.append("")
    lines.append("Match key: (decision_ts_ns, checkpoint_s). "
                  "event_id is NOT stable across runs.")
    lines.append("")
    lines.append("## Coverage")
    lines.append("")
    lines.append(f"- Live scored (Mar, T≤600): {len(live):,}")
    lines.append(f"- Offline ref (Mar, T≤600, resolved only): "
                  f"{len(offline):,}")
    lines.append(f"- Matched on (decision_ts_ns × checkpoint_s): "
                  f"{len(both):,}")
    lines.append(f"- Live-only (not in offline ref — mostly "
                  f"unresolved): {len(live_only):,}")
    lines.append(f"- Offline-only (in ref, not scored in live): "
                  f"{len(ref_only):,}")
    lines.append("")
    if len(both):
        lines.append("## Score parity (matched rows)")
        lines.append("")
        lines.append(f"- max abs diff: {score_diff.max():.2e}")
        lines.append(f"- mean abs diff: {score_diff.mean():.2e}")
        lines.append(f"- exact (diff == 0): "
                      f"{int((score_diff == 0).sum())} / {len(both)}")
        lines.append(f"- within 1e-9: "
                      f"{int((score_diff < 1e-9).sum())} / {len(both)}")
        lines.append(f"- within 1e-6: "
                      f"{int((score_diff < 1e-6).sum())} / {len(both)}")
        lines.append("")
        lines.append(f"- Direction parity: "
                      f"{int(both['dir_match'].sum())} / {len(both)}")
        lines.append("")
    lines.append("## Candidate-trade parity")
    lines.append("")
    lines.append(f"- Live candidates (score ≥ {thr:.4f}): {live_cand:,}")
    lines.append(f"- Offline candidates (score ≥ {thr:.4f}): {off_cand:,}")
    lines.append(f"- Delta: {live_cand - off_cand:+,}")
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    lines.append(f"**{verdict}**")

    out = RECON / "RECONCILIATION_REPORT.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()
