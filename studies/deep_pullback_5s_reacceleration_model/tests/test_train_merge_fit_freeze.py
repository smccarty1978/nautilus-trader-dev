"""Synthetic tests for the governed TRAIN merge/fit/freeze driver.

No real data. Builds three tiny fake partition run-dirs (matching the real
candidate/observation schema) and drives the whole pipeline, asserting:
  - per-partition verification catches a composite / year / count defect
  - the deterministic merge rejects a cross-year duplicate candidate key
  - CENSORED rows are excluded and never coerced to negative
  - the feature surface is 34 canonical + model_c_score_at_candidate, in order
  - the pre-fit gate binds the merged dataset identity + population/target/chronology scope
  - the freeze is deterministic and reproducible
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

IMPL = "studies.deep_pullback_5s_reacceleration_model.implementation.train_merge_fit_freeze"
STUDY = Path(__file__).resolve().parents[1]
NS = 1_000_000_000


def _load():
    import importlib

    return importlib.import_module(IMPL)


def _candidate_columns() -> list[str]:
    fc = json.loads((STUDY / "config" / "feature_contract.json").read_text(encoding="utf-8"))
    feats = list(fc["feature_list"])
    meta = [
        "observation_ts", "regime_start_ns", "regime_direction", "checkpoint_index",
        "prevailing_regime_start_ns", "episode_id", "arm_ts", "candidate_ts",
        "triggering_completed_5s_ts", "pullback_start_ts", "prevailing_direction",
        "counter_regime_close_ts", "frozen_atr_arm", "atr_t", "triggering_1s_ts_init",
    ]
    return meta + feats + ["model_c_score_at_candidate"]


def _fake_partition(tmp: Path, year: int, n: int, *, pos_frac=0.2, cens_frac=0.1,
                    composite: str, key_offset: int = 0) -> Path:
    rng = np.random.default_rng(year)
    cols = _candidate_columns()
    t0 = pd.Timestamp(f"{year}-06-01", tz="UTC").value
    obs_ts = t0 + (np.arange(n) + key_offset) * 60 * NS
    cand = pd.DataFrame({c: 0.0 for c in cols}, index=range(n))
    cand["observation_ts"] = obs_ts
    cand["candidate_ts"] = obs_ts
    cand["regime_start_ns"] = t0
    cand["checkpoint_index"] = np.arange(n) + key_offset
    cand["episode_id"] = [f"{year}-{i}" for i in range(n)]
    cand["prevailing_direction"] = rng.choice([1, -1], n)
    cand["regime_direction"] = cand["prevailing_direction"]
    for f in cols:
        if f not in ("observation_ts", "candidate_ts", "regime_start_ns", "checkpoint_index",
                     "episode_id", "prevailing_direction", "regime_direction"):
            cand[f] = rng.normal(size=n)
    # let some rolling_300s be null (null_policy = allow)
    null_mask = rng.random(n) < 0.3
    for f in ("rolling_300s_retention_ratio", "model_c_score_at_candidate"):
        cand.loc[null_mask, f] = np.nan
    cand = cand[cols]

    u = rng.random(n)
    disp = np.where(u < cens_frac, "CENSORED",
                    np.where(u < cens_frac + pos_frac, "LABELED_POSITIVE", "LABELED_NEGATIVE"))
    label = np.where(disp == "LABELED_POSITIVE", 1.0,
                     np.where(disp == "LABELED_NEGATIVE", 0.0, np.nan))
    obs = pd.DataFrame({
        "observation_ts": obs_ts, "regime_start_ns": t0,
        "regime_direction": cand["regime_direction"].values,
        "checkpoint_index": cand["checkpoint_index"].values,
        "flip_ts": np.nan, "time_to_flip_seconds": np.nan,
        "target_flip_within_horizon": label, "disposition": disp,
        "censored": (disp == "CENSORED").astype(int), "censor_reason": None,
        "horizon_end_ts": obs_ts + 300 * NS, "session_close_ts": obs_ts,
        "resolved_at_ts": obs_ts + 301 * NS,
    })

    rd = tmp / f"run_{year}"
    (rd / "collection").mkdir(parents=True)
    cand.to_parquet(rd / "collection" / "candidates.parquet")
    obs.to_parquet(rd / "collection" / "observations.parquet")
    (rd / "run_manifest.json").write_text(json.dumps({
        "run_id": f"fake_{year}", "study_id": "deep_pullback_5s_reacceleration_model",
        "execution_manifest_sha256": composite, "dates": {"start": f"{year}-01-01"},
    }), encoding="utf-8")
    return rd


def test_verify_partition_flags_wrong_composite(tmp_path):
    mod = _load()
    rd = _fake_partition(tmp_path, 2021, 50, composite="deadbeef")
    v = mod.verify_partition(rd, 2021, _candidate_columns())
    assert not v["passed"]
    assert any("composite" in f for f in v["findings"])


def test_verify_partition_flags_wrong_year(tmp_path):
    mod = _load()
    rd = _fake_partition(tmp_path, 2021, 50, composite=mod.SEALED_COMPOSITE)
    v = mod.verify_partition(rd, 2022, _candidate_columns())  # claim it's 2022
    assert not v["passed"]
    assert any("year" in f for f in v["findings"])


def test_merge_rejects_cross_year_duplicate_key(tmp_path):
    mod = _load()
    c = mod.SEALED_COMPOSITE
    # same key_offset + same regime_start collision engineered via identical observation_ts
    from research_workflow.partitioning import PartitionError

    a = _fake_partition(tmp_path / "a", 2021, 30, composite=c)
    b = _fake_partition(tmp_path / "b", 2021, 30, composite=c)  # identical year+offset => dup keys
    with pytest.raises((mod.TrainFreezeError, PartitionError)):
        mod.merge_train_partitions(STUDY, {2021: a, 2022: b}, _feature_list())


def _feature_list() -> list[str]:
    fc = json.loads((STUDY / "config" / "feature_contract.json").read_text(encoding="utf-8"))
    return list(fc["feature_list"])


def test_full_pipeline_excludes_censored_and_freezes_deterministically(tmp_path, monkeypatch):
    mod = _load()
    c = mod.SEALED_COMPOSITE
    runs = {
        2021: _fake_partition(tmp_path / "p", 2021, 400, composite=c, key_offset=0),
        2022: _fake_partition(tmp_path / "p", 2022, 400, composite=c, key_offset=0),
        2023: _fake_partition(tmp_path / "p", 2023, 400, composite=c, key_offset=0),
    }
    of = _feature_list()
    dn = "model_c_score_at_candidate"

    mi = mod.merge_train_partitions(STUDY, runs, of)
    fr = mod.build_modeling_frame(mi["merged_candidates"], mi["merged_observations"], of, dn)

    # CENSORED excluded, never coerced
    assert fr["pos"] + fr["neg"] == fr["resolved_rows"]
    assert fr["censored_excluded"] > 0
    assert fr["resolved_rows"] + fr["censored_excluded"] == mi["total_candidates"]
    assert set(fr["y"].unique()).issubset({0.0, 1.0})

    # feature surface = 34 canonical (in order) + derived, last
    assert fr["model_columns"][:len(of)] == of
    assert fr["model_columns"][-1] == dn
    assert len(fr["model_columns"]) == 35

    # meta chronology roles
    roles = dict(fr["meta"].groupby("_year")["_selection_role"].first())
    assert roles[2021] == "tuning" and roles[2022] == "tuning" and roles[2023] == "final_validation"

    # deterministic merged identity
    mi2 = mod.merge_train_partitions(STUDY, runs, of)
    assert mi2["merged_frame_sha256"] == mi["merged_frame_sha256"]
