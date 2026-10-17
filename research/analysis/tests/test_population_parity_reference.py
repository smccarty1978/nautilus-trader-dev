"""gate.population_parity against ANOTHER study's sealed merged frame (``reference_frame``).

The reference is a sealed ``merged/{candidates,observations}.parquet`` pair pinned by sha256;
the population is built by the V2 lifecycle's own analysis-frame builder from a candidate
study's partitions that carry EXTRA feature columns (as a feature-enriched replication does).
Every substantive difference must surface as a typed PARITY_FAIL with full counts and bounded
examples; row order alone must never fail.
"""
from __future__ import annotations

import hashlib
import itertools
import json

import numpy as np
import pandas as pd
import pytest

from research.analysis.diagnostic_ops import FRAME_JOIN_KEY, PARITY_EXAMPLES, population_parity_gate
from research.analysis.ops import AnalysisOpError, run_op

NS = 10 ** 9
_RUN = itertools.count()
YEARS = (2029, 2030)
MEMBERSHIP = ["displacement_signal", "bos_signal", "is_displacement", "is_bos"]
TIMING = ["horizon_end_ts", "resolved_at_ts", "tp38_sl25_resolution_seconds"]
OUTCOME = ["regime_direction", "disposition", "tp38_sl25_label", "tp38_sl25_disposition"]
CENSORING = ["censored", "censor_reason", "tp38_sl25_censor_reason"]
COMPARE = {"timing": TIMING, "membership": MEMBERSHIP, "outcome": OUTCOME, "censoring": CENSORING,
           "context": ["distance_to_level"]}


def _halves(n_per_year: int = 30):
    """Candidates/observations halves in the V2 schema (completed-bar population: the regime and
    checkpoint key columns are null, exactly as in the FPR frame)."""
    cands, obs = [], []
    for y in YEARS:
        t0 = int(pd.Timestamp(f"{y}-01-02 14:31", tz="UTC").value)
        for i in range(n_per_year):
            T = t0 + i * 60 * NS
            censored = int(i % 7 == 0)
            label = np.nan if censored else float(i % 2)
            cands.append({"observation_ts": T, "regime_start_ns": np.nan, "checkpoint_index": np.nan,
                          "is_displacement": int(i % 3 == 0), "displacement_signal": int(i % 3 == 0),
                          "is_bos": int(i % 4 == 0), "bos_signal": int(i % 4 == 0),
                          "distance_to_level": float(i) - 10.0})
            obs.append({"observation_ts": T, "regime_start_ns": np.nan, "regime_direction": 1 if i % 2 else -1,
                        "checkpoint_index": np.nan, "disposition": "CENSORED" if censored else "LABELED",
                        "censored": censored, "censor_reason": "SESSION_END" if censored else None,
                        "horizon_end_ts": T + 5400 * NS, "resolved_at_ts": T + (60 + i) * NS,
                        "tp38_sl25_label": label, "tp38_sl25_disposition": "CENSORED" if censored else ("POSITIVE" if i % 2 else "NEGATIVE"),
                        "tp38_sl25_censor_reason": "SESSION_END" if censored else None,
                        "tp38_sl25_resolution_seconds": np.nan if censored else float(60 + i)})
    return pd.DataFrame(cands), pd.DataFrame(obs)


def _sealed_reference(tmp_path, c=None, o=None):
    c0, o0 = _halves()
    c, o = (c0 if c is None else c), (o0 if o is None else o)
    d = tmp_path / "studies" / "reference_study" / "_work" / "controller" / "merged"
    d.mkdir(parents=True, exist_ok=True)
    c.to_parquet(d / "candidates.parquet", index=False)
    o.to_parquet(d / "observations.parquet", index=False)
    sha = {n: hashlib.sha256((d / f"{n}.parquet").read_bytes()).hexdigest() for n in ("candidates", "observations")}
    return {"dir": "reference_study/_work/controller/merged",
            "candidates_sha256": sha["candidates"], "observations_sha256": sha["observations"]}


def _population(tmp_path, mutate=None):
    """The candidate study's frame, built by V2Lifecycle._train_frame_all_labels from per-year
    partitions that also carry new feature columns."""
    from research_workflow.lifecycle_v2 import V2Lifecycle
    c, o = _halves()
    c["price_change_atr_300s"] = np.linspace(-1, 1, len(c))       # added features: irrelevant to parity
    c["range_points_900s"] = np.linspace(5, 50, len(c))
    if mutate:
        c, o = mutate(c.copy(), o.copy())
    base = tmp_path / f"candidate_partitions_{next(_RUN)}"
    for y in YEARS:
        part = base / str(y)
        part.mkdir(parents=True)
        yc = c[pd.to_datetime(c["observation_ts"], unit="ns", utc=True).dt.year == y]
        yo = o[pd.to_datetime(o["observation_ts"], unit="ns", utc=True).dt.year == y]
        yc.to_parquet(part / "candidates.parquet", index=False)
        yo.to_parquet(part / "observations.parquet", index=False)
    lc = V2Lifecycle.__new__(V2Lifecycle)
    return lc._train_frame_all_labels({}, base, list(YEARS))


def _gate(tmp_path, rows, reference=None, **over):
    params = {"reference_frame": reference or _sealed_reference(tmp_path),
              "key": ["observation_ts"], "reference_key": ["observation_ts"],
              "expected_total": 60, "expected_by": {"_year": {2029: 30, 2030: 30}},
              "compare": COMPARE, "context": {"studies_root": str(tmp_path / "studies")}}
    params.update(over)
    return population_parity_gate(rows, **params)


def _fail(tmp_path, rows, **over):
    with pytest.raises(AnalysisOpError, match="ANALYSIS_POPULATION_PARITY_FAILED") as e:
        _gate(tmp_path, rows, **over)
    report = e.value.report
    assert report["verdict"] == "PARITY_FAIL" and report["status"] == "FAIL"
    assert json.loads(str(e.value).split(" | report=", 1)[1])["failure_codes"] == report["failure_codes"]
    return report


def test_the_reference_join_rule_is_the_analysis_frame_join_rule():
    from research_workflow.lifecycle_v2 import KEY
    assert tuple(FRAME_JOIN_KEY) == tuple(KEY)


def test_exact_population_passes_with_added_feature_columns(tmp_path):
    out = _gate(tmp_path, _population(tmp_path))
    p = out["payload"]
    assert p["verdict"] == "PARITY_PASS" and p["failure_codes"] == [] and p["failures"] == []
    assert p["population_rows"] == p["reference_rows"] == 60
    assert p["observed_by"]["_year"] == {"2029": 30, "2030": 30}
    assert set(p["compared"]) == set(COMPARE) and all(v["rows_changed"] == 0 for v in p["compared"].values())
    assert p["reference"]["candidates_sha256"] and p["reference"]["observations_sha256"]
    json.dumps(p)                                   # machine-readable as-is


def test_ordering_alone_never_fails(tmp_path):
    rows = _population(tmp_path).sample(frac=1.0, random_state=7).reset_index(drop=True)
    c, o = _halves()
    ref = _sealed_reference(tmp_path, c.iloc[::-1].reset_index(drop=True), o.sample(frac=1.0, random_state=3).reset_index(drop=True))
    assert _gate(tmp_path, rows, reference=ref)["payload"]["verdict"] == "PARITY_PASS"


def test_one_missing_candidate(tmp_path):
    rows = _population(tmp_path)
    gone = int(rows.loc[5, "observation_ts"])
    r = _fail(tmp_path, rows.drop(index=5))
    assert "PARITY_MISSING" in r["failure_codes"] and "PARITY_COUNT_MISMATCH" in r["failure_codes"]
    assert "PARITY_EXTRA" not in r["failure_codes"]
    assert r["missing_from_population"] == 1 and r["missing_examples"] == [[gone]]


def test_one_extra_candidate(tmp_path):
    def add(c, o):
        T = int(pd.Timestamp("2029-06-03 14:31", tz="UTC").value)
        c = pd.concat([c, c.iloc[[0]].assign(observation_ts=T)], ignore_index=True)
        o = pd.concat([o, o.iloc[[0]].assign(observation_ts=T)], ignore_index=True)
        return c, o
    r = _fail(tmp_path, _population(tmp_path, add))
    assert "PARITY_EXTRA" in r["failure_codes"] and r["extra_in_population"] == 1
    assert r["observed_by"]["_year"] == {"2029": 31, "2030": 30}


def test_duplicate_candidate(tmp_path):
    rows = _population(tmp_path)
    r = _fail(tmp_path, pd.concat([rows, rows.iloc[[3]]], ignore_index=True), expected_total=None, expected_by=None)
    assert r["failure_codes"] == ["PARITY_DUPLICATE_KEY"]           # key SETS still match: only the duplicate fails
    assert r["duplicate_keys"]["population"] == {"keys": 1, "rows": 2, "examples": [[int(rows.loc[3, "observation_ts"])]]}


def test_retimed_candidate_and_retimed_resolution(tmp_path):
    rows = _population(tmp_path)
    shifted = rows.copy()
    shifted.loc[4, "observation_ts"] += 30 * NS      # the checkpoint itself moved: a different candidate
    r = _fail(tmp_path, shifted)
    assert r["failure_codes"] == ["PARITY_MISSING", "PARITY_EXTRA"]  # counts still 60 / 30+30: only identity catches it
    assert r["missing_from_population"] == 1 and r["extra_in_population"] == 1
    late = rows.copy()
    late.loc[4, "resolved_at_ts"] += NS               # same candidate, resolved at a different instant
    r = _fail(tmp_path, late)
    assert r["failure_codes"] == ["PARITY_TIMING_CHANGED"]
    assert r["compared"]["timing"]["by_column"] == {"resolved_at_ts": 1}
    r = _fail(tmp_path, late, timestamp_column="resolved_at_ts", reference_timestamp_column="resolved_at_ts")
    assert "PARITY_RETIMED" in r["failure_codes"] and r["timestamp_mismatches"] == 1


def test_changed_a1_a2_membership(tmp_path):
    rows = _population(tmp_path)
    rows.loc[1, "displacement_signal"] = 1 - rows.loc[1, "displacement_signal"]
    rows.loc[2, "bos_signal"] = 1 - rows.loc[2, "bos_signal"]
    r = _fail(tmp_path, rows)
    assert r["failure_codes"] == ["PARITY_MEMBERSHIP_CHANGED"]
    m = r["compared"]["membership"]
    assert m["rows_changed"] == 2 and m["by_column"] == {"displacement_signal": 1, "bos_signal": 1}


def test_changed_outcome_classification(tmp_path):
    rows = _population(tmp_path)
    i = rows.index[rows["censored"] == 0][0]
    rows.loc[i, "tp38_sl25_label"] = 1.0 - rows.loc[i, "tp38_sl25_label"]
    r = _fail(tmp_path, rows)
    assert r["failure_codes"] == ["PARITY_OUTCOME_CHANGED"]
    assert r["compared"]["outcome"]["by_column"] == {"tp38_sl25_label": 1}


def test_changed_censoring_and_null_semantics(tmp_path):
    rows = _population(tmp_path)
    i = rows.index[rows["censored"] == 1][0]
    rows.loc[i, "tp38_sl25_censor_reason"] = "GAP"
    r = _fail(tmp_path, rows)
    assert r["failure_codes"] == ["PARITY_CENSORING_CHANGED"]
    # a censored (null) label against a resolved 0.0 is a change, never "equal after a bool cast"
    rows = _population(tmp_path)
    rows.loc[i, "tp38_sl25_label"] = 0.0
    r = _fail(tmp_path, rows)
    assert r["compared"]["outcome"]["by_column"] == {"tp38_sl25_label": 1}


def test_full_counts_with_bounded_examples(tmp_path):
    rows = _population(tmp_path)
    rows["resolved_at_ts"] += NS
    r = _fail(tmp_path, rows.iloc[25:], expected_total=None, expected_by=None)
    assert r["missing_from_population"] == 25 and len(r["missing_examples"]) == PARITY_EXAMPLES
    assert r["compared"]["timing"]["rows_changed"] == 35 and len(r["compared"]["timing"]["examples"]) == PARITY_EXAMPLES


def test_reference_bytes_and_shape_are_pinned(tmp_path):
    rows = _population(tmp_path)
    ref = _sealed_reference(tmp_path)
    with pytest.raises(AnalysisOpError, match="REFERENCE_SHA_MISMATCH"):
        _gate(tmp_path, rows, reference={**ref, "observations_sha256": "0" * 64})
    with pytest.raises(AnalysisOpError, match="REFERENCE_MISSING"):
        _gate(tmp_path, rows, reference={**ref, "dir": "nope"})
    with pytest.raises(AnalysisOpError, match="REFERENCE_FRAME_INCOMPLETE"):
        _gate(tmp_path, rows, reference={"dir": ref["dir"]})
    with pytest.raises(AnalysisOpError, match="REFERENCE_AMBIGUOUS"):
        _gate(tmp_path, rows, reference_path="x.parquet", reference_sha256="0" * 64)
    with pytest.raises(AnalysisOpError, match="COMPARE_CATEGORY_UNKNOWN"):
        _gate(tmp_path, rows, compare={"features": ["price_change_atr_300s"]})


def test_an_inconsistent_reference_is_refused_not_repaired(tmp_path):
    c, o = _halves()
    with pytest.raises(AnalysisOpError, match="REFERENCE_INCONSISTENT"):
        _gate(tmp_path, _population(tmp_path), reference=_sealed_reference(tmp_path, c, o.iloc[1:]))


def test_run_op_routes_the_reference_frame(tmp_path):
    ref = _sealed_reference(tmp_path)
    out = run_op("analysis.gate.population_parity", _population(tmp_path),
                 params={"reference_frame": ref, "key": ["observation_ts"], "reference_key": ["observation_ts"],
                         "expected_total": 60, "compare": COMPARE},
                 context={"studies_root": str(tmp_path / "studies")})
    assert out["payload"]["verdict"] == "PARITY_PASS"
