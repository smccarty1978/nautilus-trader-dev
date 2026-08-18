"""Shared fixtures for the analysis-harness tests.

Two sources of truth:

* **Synthetic collections** built on a tmp path — used for every negative case, so a
  malformed collection never has to exist in the repository.
* **The real A0 fixtures** — resolved from the owning repository's `runs/`. The
  parquet files are gitignored, so they are absent from a worktree checkout; the
  resolver walks up from `.claude/worktrees/<name>` to find them and tests skip with
  an explicit message when they are unavailable.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.schemas.study_spec import StudySpec  # noqa: E402

# The two A0 fixtures, by run id.
FIXTURE_A_RUN = "20260815_213139_Gemini_clean_maturity_flip_rolling_5m_productivity_day"
FIXTURE_B_RUN = "20260814_232113_reconstructed_long_rth_strict_retrain_day"
FIXTURE_N_RUN = "20260815_003408_Gemini_clean_maturity_flip_rolling_5m_productivity_day"


def resolve_real_runs_root() -> Optional[Path]:
    """Finds a `runs/` directory that actually contains fixture parquet.

    Order: explicit env var, then this checkout, then the owning repository when this
    checkout is a worktree under `.claude/worktrees/`.
    """
    candidates: List[Path] = []
    env = os.environ.get("ANALYSIS_FIXTURE_RUNS_ROOT")
    if env:
        candidates.append(Path(env))
    candidates.append(REPO_ROOT / "runs")
    parts = REPO_ROOT.parts
    if ".claude" in parts:
        owner = Path(*parts[: parts.index(".claude")])
        candidates.append(owner / "runs")

    for root in candidates:
        probe = root / FIXTURE_A_RUN / "collection" / "candidates.parquet"
        if probe.is_file():
            return root
    return None


def resolve_real_studies_root() -> Path:
    root = resolve_real_runs_root()
    if root is not None:
        return root.parent / "studies"
    return REPO_ROOT / "studies"


# ---------------------------------------------------------------------------
# Synthetic collection builder
# ---------------------------------------------------------------------------

NS_PER_S = 1_000_000_000


def _ts_for_year(year: int, offset_s: int = 0) -> int:
    return int(pd.Timestamp(f"{year}-06-15 14:00:00", tz="UTC").value) + offset_s * NS_PER_S


def make_study_yaml(
    study_id: str,
    features: Sequence[str],
    *,
    metadata_columns: Optional[Sequence[str]] = None,
    train: Sequence[int] = (2023,),
    dev: Sequence[int] = (2024,),
    prohibited: Sequence[int] = (2025, 2026),
    horizon_seconds: int = 300,
) -> Dict[str, Any]:
    doc: Dict[str, Any] = {
        "study": {"id": study_id, "type": "flip_prediction", "risk_tier": 2,
                  "description": "synthetic fixture"},
        "instrument": {"symbol": "NQ", "venue": "XCME"},
        "population": {"type": "regime_state", "prevailing_regime": "both", "session": "RTH"},
        "target": {"type": "flip", "event": "confirmed_flip", "direction": "both",
                   "horizon_seconds": horizon_seconds},
        "features": {
            "feature_list": list(features),
            "feature_list_sha256": hashlib.sha256(
                json.dumps(list(features)).encode("utf-8")
            ).hexdigest(),
        },
        "chronology": {"train": list(train), "dev": list(dev), "prohibited": list(prohibited)},
    }
    if metadata_columns is not None:
        doc["features"]["metadata_columns"] = list(metadata_columns)
    return doc


DEFAULT_SYNTHETIC_METADATA = [
    "observation_ts", "regime_start_ns", "regime_direction", "checkpoint_index",
    "regime_age_seconds",
]


def make_synthetic_collection(
    tmp_path: Path,
    *,
    study_id: str = "synthetic_study",
    run_id: str = "20230101_000000_synthetic_study_day",
    n_rows: int = 120,
    features: Sequence[str] = ("f_alpha", "f_beta", "f_gamma"),
    metadata_columns: Optional[Sequence[str]] = None,
    join_key: Optional[Sequence[str]] = None,
    years: Sequence[int] = (2023,),
    train: Sequence[int] = (2023,),
    dev: Sequence[int] = (2024,),
    prohibited: Sequence[int] = (2025, 2026),
    sealed: bool = True,
    target_column: str = "target_flip_within_horizon",
    include_target: bool = True,
    empty_observations: bool = False,
    duplicate_keys: bool = False,
    drop_observation_rows: int = 0,
    feature_order_shuffled: bool = False,
    surplus_column: bool = False,
    corrupt_candidates_hash: bool = False,
    stale_compiled_study: bool = False,
    spec_drift: bool = False,
    status: str = "SUCCESS",
    positive_rate: float = 0.35,
    seed: int = 7,
    nan_feature: Optional[str] = None,
) -> Dict[str, Any]:
    """Writes a complete, self-consistent (or deliberately broken) collection to disk.

    Returns a dict with `runs_root`, `studies_root`, `run_id`, `study_id`.
    """
    rng = np.random.default_rng(seed)
    runs_root = tmp_path / "runs"
    studies_root = tmp_path / "studies"
    run_dir = runs_root / run_id
    coll_dir = run_dir / "collection"
    study_dir = studies_root / study_id
    coll_dir.mkdir(parents=True, exist_ok=True)
    study_dir.mkdir(parents=True, exist_ok=True)

    meta_cols = list(metadata_columns) if metadata_columns is not None else list(DEFAULT_SYNTHETIC_METADATA)
    keys = list(join_key) if join_key is not None else [c for c in meta_cols if c != "regime_age_seconds"]

    # --- study contract --------------------------------------------------
    study_doc = make_study_yaml(
        study_id, features,
        metadata_columns=None if metadata_columns is None else meta_cols,
        train=train, dev=dev, prohibited=prohibited,
    )
    import yaml

    (study_dir / "study.yaml").write_text(yaml.safe_dump(study_doc, sort_keys=False), encoding="utf-8")
    spec_hash = StudySpec.model_validate(study_doc).compute_sha256()

    compiled_hash = spec_hash
    if stale_compiled_study:
        compiled_hash = "0" * 64  # study.yaml has moved on since compilation
    (study_dir / "compiled_study.json").write_text(
        json.dumps({"spec_sha256": compiled_hash,
                    "contracts": {"execution_contract": {"runtime": "nautilustrader"}}}, indent=2),
        encoding="utf-8",
    )

    # --- frames ----------------------------------------------------------
    per_year = max(1, n_rows // len(years))
    ts: List[int] = []
    for y in years:
        ts.extend(_ts_for_year(y, i * 5) for i in range(per_year))
    ts = ts[:n_rows] if len(ts) >= n_rows else ts + [ts[-1] + NS_PER_S] * (n_rows - len(ts))
    n = len(ts)

    cand = pd.DataFrame({
        "observation_ts": np.array(ts, dtype="int64"),
        "regime_start_ns": np.array(ts, dtype="int64") - 600 * NS_PER_S,
        "regime_direction": rng.choice([-1, 1], size=n),
        "checkpoint_index": np.arange(n, dtype="int64"),
        "regime_age_seconds": rng.uniform(30, 900, size=n),
    })
    cand = cand[[c for c in cand.columns if c in meta_cols]]
    for i, f in enumerate(features):
        cand[f] = rng.normal(i, 1.0, size=n)
    if nan_feature and nan_feature in cand.columns:
        idx = rng.choice(n, size=max(1, n // 10), replace=False)
        cand.loc[idx, nan_feature] = np.nan
    if surplus_column:
        cand["undeclared_extra"] = 1.0
    if feature_order_shuffled and len(features) > 1:
        cols = [c for c in cand.columns if c not in features]
        shuffled = list(features)[::-1]
        cand = cand[cols + shuffled]
    if duplicate_keys and n > 1:
        cand.iloc[1, cand.columns.get_loc("checkpoint_index")] = cand.iloc[0]["checkpoint_index"]
        cand.iloc[1, cand.columns.get_loc("observation_ts")] = cand.iloc[0]["observation_ts"]
        cand.iloc[1, cand.columns.get_loc("regime_start_ns")] = cand.iloc[0]["regime_start_ns"]
        if "regime_direction" in cand.columns:
            cand.iloc[1, cand.columns.get_loc("regime_direction")] = cand.iloc[0]["regime_direction"]

    if empty_observations:
        obs = pd.DataFrame()
    else:
        obs = cand[[k for k in keys if k in cand.columns]].copy()
        obs["flip_ts"] = cand["observation_ts"] + 60 * NS_PER_S
        obs["time_to_flip_seconds"] = 60.0
        if include_target:
            obs[target_column] = (rng.random(n) < positive_rate).astype("int64")
        if drop_observation_rows:
            obs = obs.iloc[:-drop_observation_rows].copy()

    cand.to_parquet(coll_dir / "candidates.parquet", index=False)
    obs.to_parquet(coll_dir / "observations.parquet", index=False)

    def _sha(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()

    cand_sha = _sha(coll_dir / "candidates.parquet")
    obs_sha = _sha(coll_dir / "observations.parquet")
    if corrupt_candidates_hash:
        cand_sha = "f" * 64

    (coll_dir / "collection_manifest.json").write_text(json.dumps({
        "run_id": run_id, "study_id": study_id,
        "candidates_count": len(cand), "observations_count": len(obs),
        "candidates_sha256": cand_sha, "observations_sha256": obs_sha,
        "columns": {"candidates": list(cand.columns), "observations": list(obs.columns)},
    }, indent=2), encoding="utf-8")

    run_spec_hash = spec_hash if not spec_drift else "1" * 64
    lo = min(years)
    hi = max(years)
    (run_dir / "run_manifest.json").write_text(json.dumps({
        "run_id": run_id, "study_id": study_id, "stage": "day",
        "spec_sha256": run_spec_hash,
        "composite_seal_hash": ("a" * 64) if sealed else None,
        "dates": {"start": f"{lo}-01-01", "end": f"{hi}-12-31",
                  "warmup_start": f"{lo}-01-01T00:00:00+00:00"},
        "timestamp_contract": {"raw_timestamp_semantic": "OPEN_STAMPED"},
    }, indent=2), encoding="utf-8")
    (run_dir / "status.json").write_text(json.dumps({"status": status}, indent=2), encoding="utf-8")

    return {"runs_root": runs_root, "studies_root": studies_root,
            "run_id": run_id, "study_id": study_id,
            "candidates": cand, "observations": obs}


def load_synthetic(bundle: Dict[str, Any]):
    from research.analysis.loader import load_collection

    return load_collection(bundle["run_id"], runs_root=bundle["runs_root"],
                           studies_root=bundle["studies_root"])
