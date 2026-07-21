"""Phase 0 - build the frozen March-2025 OFFLINE reference for the long TOP25
runtime-parity study.

Pure slicing + verification. Nothing is recomputed, refit, or re-derived:
  * candidates/features come from the frozen prepared_long_2025.parquet
    (strict-causal, produced by long_rth_mirrored_surface_top100_training);
  * scores come from the frozen artifact's own score_reference_2025.parquet
    (freeze_reduced_flip_model_artifacts), which was itself parity-proven
    bit-identical to the source study's stored predictions.

Session boundaries are America/Chicago, NOT UTC calendar days (explicit brief
requirement). The exact loaded/sliced range is recorded in the manifest.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

STUDY = Path(__file__).resolve().parents[1]
ROOT = STUDY.parents[1]
RESULTS, WORK = STUDY / "results", STUDY / "_work"

FREEZE = ROOT / "studies" / "freeze_reduced_flip_model_artifacts" / "artifacts" / "long_bullish_flip_top25"
PREPARED = (ROOT / "studies" / "long_rth_mirrored_surface_top100_training" / "_work"
            / "prepared_long_2025.parquet")

TZ = "America/Chicago"
MARCH_START = pd.Timestamp("2025-03-01 00:00:00", tz=TZ)
MARCH_END = pd.Timestamp("2025-04-01 00:00:00", tz=TZ)

# Canonical project session rule.
RTH_START_MIN, RTH_END_MIN = 8 * 60 + 30, 15 * 60 + 15

TARGET = "bullish_regime_flip_within_300s"
KEY = ["regime_start_ns", "observation_time"]


def sha256_file(p: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while c := f.read(block):
            h.update(c)
    return h.hexdigest()


def git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def main() -> None:
    feats = pd.read_csv(FREEZE / "feature_order.csv")["feature_name"].tolist()
    assert len(feats) == 25, f"expected 25 features, got {len(feats)}"

    prep = pd.read_parquet(PREPARED)
    scores = pd.read_parquet(FREEZE / "score_reference_2025.parquet")

    # --- Chicago-session slicing (never UTC calendar days) ---
    obs_utc = pd.to_datetime(prep["observation_time"], unit="ns", utc=True)
    obs_chi = obs_utc.dt.tz_convert(TZ)
    mask = (obs_chi >= MARCH_START) & (obs_chi < MARCH_END)
    mar = prep[mask].copy().reset_index(drop=True)

    s_chi = pd.to_datetime(scores["observation_time"], unit="ns", utc=True).dt.tz_convert(TZ)
    smask = (s_chi >= MARCH_START) & (s_chi < MARCH_END)
    smar = scores[smask].copy().reset_index(drop=True)

    # Join frozen scores onto the frozen candidate rows (one-to-one on the key).
    if smar.duplicated(KEY).any() or mar.duplicated(KEY).any():
        raise SystemExit("duplicate (regime_start_ns, observation_time) keys - cannot join 1:1")
    ref = mar.merge(smar[KEY + ["score"]], on=KEY, how="left", validate="one_to_one")
    if ref["score"].isna().any():
        raise SystemExit(f"{int(ref['score'].isna().sum())} candidate rows lack a frozen score")

    # --- session / direction invariants ---
    mod = (obs_chi[mask].dt.hour * 60 + obs_chi[mask].dt.minute).to_numpy()
    ref["observation_minute_of_day_chicago"] = mod
    ref["decision_rth"] = (mod >= RTH_START_MIN) & (mod < RTH_END_MIN)
    if not ref["decision_rth"].all():
        raise SystemExit("offline reference contains non-RTH decision rows - unexpected")
    if not (ref["prevailing_direction"] == -1).all() or not (ref["entry_direction"] == 1).all():
        raise SystemExit("offline reference direction invariant violated")

    # --- checkpoint index, derived from the 5s grid off each regime flip ---
    ref["checkpoint_index"] = (
        (ref["observation_time"] - ref["regime_start_ns"]) // 5_000_000_000 - 1).astype(int)

    ref.to_parquet(WORK / "offline_reference_march_2025.parquet", index=False)

    # --- population waterfall (offline side) ---
    n_reg = int(ref["regime_start_ns"].nunique())
    waterfall = pd.DataFrame([
        {"stage": "eligible", "side": "offline", "rows": len(ref), "regimes": n_reg,
         "note": "frozen prepared_long_2025 sliced to March (Chicago). Upstream stages "
                 "(raw/established/decision_rth/fill_rth/valid_fill) are NOT recoverable "
                 "from the prepared artifact - it stores only surviving rows. The live "
                 "run must emit all stages; offline supplies the terminal count only."},
    ])
    waterfall.to_csv(RESULTS / "population_waterfall_offline.csv", index=False)

    per_regime = (ref.groupby("regime_start_ns")
                  .agg(n_rows=("observation_time", "size"),
                       first_obs=("observation_time", "min"),
                       last_obs=("observation_time", "max"),
                       first_cp=("checkpoint_index", "min"),
                       last_cp=("checkpoint_index", "max"),
                       atr_at_entry=("atr_at_entry", "first"),
                       n_flip=(TARGET, "sum")).reset_index())
    per_regime.to_csv(RESULTS / "offline_per_regime_march_2025.csv", index=False)

    manifest = {
        "study": "nt_long_top25_march2025_runtime_parity",
        "phase": "0_offline_reference",
        "git_commit": git_commit(),
        "model_id": "long_bullish_flip_top25",
        "model_artifact_sha256": sha256_file(FREEZE / "model.joblib"),
        "feature_order_sha256": hashlib.sha256(
            ("\n".join(feats) + "\n").encode()).hexdigest(),
        "coefficients_sha256": sha256_file(FREEZE / "coefficients.csv"),
        "intercept_sha256": sha256_file(FREEZE / "intercept.json"),
        "prepared_source": str(PREPARED.relative_to(ROOT)).replace("\\", "/"),
        "prepared_sha256": sha256_file(PREPARED),
        "score_reference_sha256": sha256_file(FREEZE / "score_reference_2025.parquet"),
        "session_timezone": TZ,
        "march_window_chicago": [str(MARCH_START), str(MARCH_END)],
        "march_window_utc": [str(MARCH_START.tz_convert("UTC")),
                             str(MARCH_END.tz_convert("UTC"))],
        "rth_rule_chicago": "08:30:00-15:15:00",
        "n_candidate_rows": len(ref),
        "n_regimes": n_reg,
        "rows_per_regime_min": int(per_regime["n_rows"].min()),
        "rows_per_regime_max": int(per_regime["n_rows"].max()),
        "rows_per_regime_median": float(per_regime["n_rows"].median()),
        "positive_rate": float(ref[TARGET].mean()),
        "score_min": float(ref["score"].min()), "score_max": float(ref["score"].max()),
        "score_mean": float(ref["score"].mean()),
        "n_features": len(feats),
        "feature_null_counts": {f: int(ref[f].isna().sum()) for f in feats
                                if int(ref[f].isna().sum()) > 0},
        "target": TARGET,
        "threshold_status": "NOT_SELECTED",
    }
    (RESULTS / "offline_reference_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps({k: v for k, v in manifest.items()
                      if k not in ("feature_null_counts",)}, indent=2))
    print("\nfeature nulls:", manifest["feature_null_counts"] or "none")


if __name__ == "__main__":
    main()
