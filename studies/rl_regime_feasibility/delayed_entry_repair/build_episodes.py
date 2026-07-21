"""
Delayed Entry Repair — build_episodes.py  (Phases 1–3)

Fixes from delayed_health study:
  1. KNN merge performed ONCE; no double-merge that produces _x/_y suffixes.
  2. Periods re-assigned from flip_time so test spans two distinct windows.
  3. Uses seconds_since_flip (not step_index) for delay targeting.
  4. Saves knn_manifest.json asserting the five required KNN fields exist.

Outputs → studies/rl_regime_feasibility/delayed_entry_repair/results/
  study_features.parquet    all observations with features + KNN + labels
  episode_meta.parquet      per-episode metadata (direction, boundaries, stop_px)
  knn_manifest.json         KNN column presence assertion
"""

from pathlib import Path
import json
import numpy as np
import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────────
STUDY_DIR   = Path("studies/rl_regime_feasibility")
SNAP_FILE   = STUDY_DIR / "results/feature_snapshots.parquet"
LABEL_FILE  = STUDY_DIR / "results/forward_labels.parquet"
EP_FILE     = STUDY_DIR / "results/episode_summary.parquet"
KNN_FILE    = STUDY_DIR / "delayed_health/results/causal_knn_health.parquet"
OUT_DIR     = STUDY_DIR / "delayed_entry_repair/results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Split boundaries (UTC ns) ──────────────────────────────────────────────────
# train       Jan 2024 – Jun 2024  (6 months)
# val         Jul 2024 – Oct 2024  (4 months; delay selection + threshold tuning)
# test_2024q4 Nov 2024 – Dec 2024  (2 months)
# test_2025h1 Jan 2025 – May 2025  (5 months)
def _ns(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").value)

CUTS = {
    "train":       (_ns("2024-01-01"), _ns("2024-07-01")),
    "val":         (_ns("2024-07-01"), _ns("2024-11-01")),
    "test_2024q4": (_ns("2024-11-01"), _ns("2025-01-01")),
    "test_2025h1": (_ns("2025-01-01"), _ns("2025-06-01")),
}

def assign_period(flip_time_ns: pd.Series) -> pd.Series:
    period = pd.Series("unknown", index=flip_time_ns.index)
    for name, (lo, hi) in CUTS.items():
        mask = (flip_time_ns >= lo) & (flip_time_ns < hi)
        period[mask] = name
    return period

# ── Required KNN columns ───────────────────────────────────────────────────────
# These are the 5 fields the manifest MUST contain after model training.
REQUIRED_KNN = ["knn_hA", "knn_hB", "knn_hC", "knn_mean_dist", "knn_n_eff"]
# Full KNN column set available from causal_knn_health.parquet
KNN_COLS = ["knn_hA", "knn_hB", "knn_hC", "knn_composite",
            "knn_mean_dist", "knn_n_eff", "knn_unique_eps", "knn_neighbor_agreement"]

# ── Label columns we need ──────────────────────────────────────────────────────
LABEL_COLS = [
    "observation_time",
    "entry_ts", "entry_px", "stop_px",
    "base__pnl_300s",   "base__stopped_300s",
    "base__pnl_regime", "base__exit_type_regime",
    "base_plus_1t__pnl_300s", "base_plus_1t__pnl_regime",
    "base_plus_2t__pnl_300s", "base_plus_2t__pnl_regime",
]


def main() -> None:
    print("=" * 70)
    print("Delayed Entry Repair — Phase 1-3: Build Episodes")
    print("=" * 70)

    # ── Phase 1: Load data ──────────────────────────────────────────────────
    print("\nPhase 1: Loading data ...")
    snap = pd.read_parquet(SNAP_FILE)
    print(f"  snap: {snap.shape}")

    labels = pd.read_parquet(LABEL_FILE, columns=LABEL_COLS)
    print(f"  labels: {labels.shape}")

    ep = pd.read_parquet(EP_FILE)
    print(f"  episodes: {ep.shape}")

    knn = pd.read_parquet(KNN_FILE)
    print(f"  knn: {knn.shape}")

    # ── Phase 2: Re-assign periods from flip_time ───────────────────────────
    print("\nPhase 2: Assigning multi-year periods ...")
    snap["period"] = assign_period(snap["flip_time"])
    coverage = snap["period"].value_counts().sort_index()
    print(f"  Observation counts by period:\n{coverage.to_string()}")

    ep["period"] = assign_period(ep["flip_time"])
    ep_counts = ep["period"].value_counts().sort_index()
    print(f"  Episode counts by period:\n{ep_counts.to_string()}")

    # ── Phase 3: Single clean KNN merge ────────────────────────────────────
    print("\nPhase 3: Merging KNN scores (single pass) ...")

    # Verify KNN columns are NOT already in snap (guard against double-merge bug)
    already_in = [c for c in KNN_COLS if c in snap.columns]
    if already_in:
        print(f"  WARNING: dropping pre-existing KNN cols from snap: {already_in}")
        snap = snap.drop(columns=already_in)

    knn_clean = (
        knn[["observation_time"] + KNN_COLS]
        .drop_duplicates("observation_time")
    )
    print(f"  KNN rows to merge: {len(knn_clean):,}")

    # Merge KNN into snap — left join (KNN only covers bar-4+ observations)
    snap = snap.merge(knn_clean, on="observation_time", how="left")

    knn_coverage = snap["knn_hA"].notna().mean()
    print(f"  KNN coverage after merge: {knn_coverage:.1%}")

    # ── Verify no suffix conflicts ──────────────────────────────────────────
    for col in KNN_COLS:
        assert col in snap.columns, f"KNN column {col} missing after merge!"
        assert f"{col}_x" not in snap.columns, f"Suffix conflict: {col}_x present!"
        assert f"{col}_y" not in snap.columns, f"Suffix conflict: {col}_y present!"
    print("  Suffix conflict check: PASS")

    # ── Phase 3b: Merge labels ──────────────────────────────────────────────
    print("\nPhase 3b: Merging forward labels ...")
    snap = snap.merge(labels, on="observation_time", how="left")
    print(f"  After label merge: {snap.shape}")

    # ── Phase 4: Build episode_meta ─────────────────────────────────────────
    print("\nPhase 4: Building episode metadata ...")
    # stop_px from the immediate entry label (step_index=0 for each episode)
    imm = snap[snap["step_index"] == 0][
        ["episode_id", "flip_time", "flip_close", "atr_at_flip", "direction",
         "episode_end_time", "termination_reason", "period", "stop_px"]
    ].copy()
    # Some episodes don't have step_index=0; fall back to min step
    missing_imm = set(snap["episode_id"].unique()) - set(imm["episode_id"].unique())
    if missing_imm:
        fallback = snap[snap["episode_id"].isin(missing_imm)].sort_values(
            ["episode_id", "step_index"]
        ).groupby("episode_id").first().reset_index()[
            ["episode_id", "flip_time", "flip_close", "atr_at_flip", "direction",
             "episode_end_time", "termination_reason", "period", "stop_px"]
        ]
        imm = pd.concat([imm, fallback], ignore_index=True)
    imm = imm.drop_duplicates("episode_id")
    print(f"  Episode metadata: {len(imm):,} episodes")

    # ── Verify KNN manifest ─────────────────────────────────────────────────
    print("\nVerifying KNN manifest fields ...")
    knn_manifest = {
        "status": "PASS",
        "fields_present": [],
        "fields_missing": [],
        "coverage_pct": float(f"{knn_coverage:.4f}"),
    }
    for col in REQUIRED_KNN:
        present = col in snap.columns and snap[col].notna().any()
        if present:
            knn_manifest["fields_present"].append(col)
        else:
            knn_manifest["fields_missing"].append(col)
            knn_manifest["status"] = "FAIL"

    if knn_manifest["status"] == "FAIL":
        raise AssertionError(
            f"KNN manifest FAIL — missing: {knn_manifest['fields_missing']}"
        )
    print(f"  KNN manifest: {knn_manifest['status']}")
    print(f"  Fields verified: {knn_manifest['fields_present']}")

    with open(OUT_DIR / "knn_manifest.json", "w") as f:
        json.dump(knn_manifest, f, indent=2)

    # ── Save outputs ────────────────────────────────────────────────────────
    print("\nSaving outputs ...")
    snap.to_parquet(OUT_DIR / "study_features.parquet", index=False)
    print(f"  study_features.parquet: {snap.shape}")

    imm.to_parquet(OUT_DIR / "episode_meta.parquet", index=False)
    print(f"  episode_meta.parquet: {len(imm):,} rows")

    print("\nPhase 1-3 complete.")


if __name__ == "__main__":
    main()
