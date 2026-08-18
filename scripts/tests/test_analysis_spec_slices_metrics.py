"""A2 tests: analysis-spec schema, recurring slices, metric edge cases."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.analysis import errors as E  # noqa: E402
from research.analysis import metrics as M  # noqa: E402
from research.analysis import slices as S  # noqa: E402
from research.analysis.spec import load_analysis_spec, parse_analysis_spec  # noqa: E402

MINIMAL = {"analysis_id": "a", "collection": {"run_id": "r1"}}


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


def test_minimal_spec_parses_with_documented_defaults():
    s = parse_analysis_spec(MINIMAL)
    assert s.run_id == "r1"
    assert s.partitions == ("train",)
    assert s.missing_values == "report_only"
    assert s.feature_set == "declared"


@pytest.mark.parametrize("run_id", ["latest", "LATEST", "newest", "*", "last"])
def test_spec_rejects_latest_style_run_ids(run_id):
    with pytest.raises(E.InvalidAnalysisSpec, match="explicit run identity"):
        parse_analysis_spec({"analysis_id": "a", "collection": {"run_id": run_id}})


def test_spec_requires_run_id():
    with pytest.raises(E.InvalidAnalysisSpec, match="run_id"):
        parse_analysis_spec({"analysis_id": "a", "collection": {}})


def test_spec_requires_analysis_id():
    with pytest.raises(E.InvalidAnalysisSpec, match="analysis_id"):
        parse_analysis_spec({"collection": {"run_id": "r"}})


def test_spec_rejects_unknown_top_level_key():
    """A misspelled key must not silently leave a default in place."""
    with pytest.raises(E.InvalidAnalysisSpec, match="unknown key"):
        parse_analysis_spec({**MINIMAL, "partiton": ["dev"]})


def test_spec_rejects_unknown_nested_key():
    with pytest.raises(E.InvalidAnalysisSpec, match="unknown key"):
        parse_analysis_spec({**MINIMAL, "collection": {"run_id": "r", "run_di": "x"}})


def test_spec_rejects_unknown_partition():
    with pytest.raises(E.InvalidAnalysisSpec, match="unknown partition"):
        parse_analysis_spec({**MINIMAL, "partitions": ["oos"]})


def test_spec_rejects_imputation_policy():
    with pytest.raises(E.InvalidAnalysisSpec, match="never imputes"):
        parse_analysis_spec({**MINIMAL, "missing_values": "median"})


def test_spec_rejects_subset_without_members():
    with pytest.raises(E.InvalidAnalysisSpec, match="requires a non-empty"):
        parse_analysis_spec({**MINIMAL, "features": {"set": "subset:x"}})


def test_spec_rejects_bad_seed_type():
    with pytest.raises(E.InvalidAnalysisSpec, match="seed"):
        parse_analysis_spec({**MINIMAL, "seed": "7"})


def test_spec_rejects_duplicate_arm_features_and_names():
    with pytest.raises(E.InvalidAnalysisSpec, match="duplicate feature"):
        parse_analysis_spec({**MINIMAL, "model_arms": [{"name": "A", "features": ["f", "f"]}]})
    with pytest.raises(E.InvalidAnalysisSpec, match="unique"):
        parse_analysis_spec({**MINIMAL, "model_arms": [
            {"name": "A", "features": ["f"]}, {"name": "A", "features": ["g"]}]})


def test_spec_hash_changes_with_every_material_field():
    base = parse_analysis_spec({**MINIMAL, "seed": 1})
    variants = {
        "seed": {**MINIMAL, "seed": 2},
        "partitions": {**MINIMAL, "seed": 1, "partitions": ["dev"]},
        "target": {**MINIMAL, "seed": 1, "target": {"column": "other"}},
        "features": {**MINIMAL, "seed": 1,
                     "features": {"set": "subset:s", "subset": ["a"]}},
        "run_id": {"analysis_id": "a", "seed": 1, "collection": {"run_id": "r2"}},
    }
    for label, payload in variants.items():
        assert parse_analysis_spec(payload).analysis_spec_sha256 != base.analysis_spec_sha256, label


def test_spec_hash_is_stable_across_equal_specs():
    assert (parse_analysis_spec({**MINIMAL, "seed": 5}).analysis_spec_sha256
            == parse_analysis_spec({**MINIMAL, "seed": 5}).analysis_spec_sha256)


def test_spec_loads_from_yaml(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text("analysis_id: y\ncollection:\n  run_id: r9\nseed: 3\n", encoding="utf-8")
    assert load_analysis_spec(p).run_id == "r9"


def test_spec_yaml_missing_file():
    with pytest.raises(E.InvalidAnalysisSpec, match="not found"):
        load_analysis_spec(Path("does_not_exist.yaml"))


# ---------------------------------------------------------------------------
# Slices
# ---------------------------------------------------------------------------


def meta_frame(n=60, direction_values=(-1, 1)):
    rng = np.random.default_rng(3)
    ts = pd.date_range("2023-06-15 12:00", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({
        "observation_ts": ts.astype("int64"),
        "regime_direction": rng.choice(list(direction_values), size=n),
        "regime_age_seconds": rng.uniform(10, 900, size=n),
        "_year": ts.year,
        "_partition": ["train"] * n,
    })


def test_all_registry_slices_derive_on_a_normal_frame():
    out = S.build_slices(meta_frame())
    assert set(out) == set(S.SLICE_REGISTRY)
    for name, res in out.items():
        assert res.derivable, f"{name}: {res.reason}"
        assert res.definition, f"{name} has no definition"


def test_direction_slice_labels_and_degeneracy():
    both = S.slice_direction(meta_frame())
    assert set(both.groups) == {"long", "short"} and not both.degenerate

    one = S.slice_direction(meta_frame(direction_values=(-1,)))
    assert one.derivable and one.degenerate
    assert "not a comparison" in one.reason


def test_missing_column_slice_is_reported_not_raised():
    res = S.slice_direction(pd.DataFrame({"x": [1, 2]}))
    assert not res.derivable and "regime_direction" in res.reason


def test_maturity_buckets_are_boundary_correct():
    meta = pd.DataFrame({"regime_age_seconds": [0, 119.9, 120, 299.9, 300, 599.9, 600, 5000]})
    res = S.slice_maturity(meta)
    assert list(res.labels) == ["young", "young", "establishing", "establishing",
                                "mature", "mature", "old", "old"]


def test_session_slice_splits_rth_and_eth():
    ts = pd.to_datetime(["2023-06-15 13:29", "2023-06-15 13:30",
                         "2023-06-15 19:59", "2023-06-15 20:00"], utc=True)
    res = S.slice_session(pd.DataFrame({"observation_ts": ts.astype("int64")}))
    assert list(res.labels) == ["ETH", "RTH", "RTH", "ETH"]


def test_decile_slice_and_constant_score():
    ok = S.slice_decile(np.linspace(0, 1, 100))
    assert ok.derivable and len(ok.groups) == 10

    const = S.slice_decile([0.5] * 50)
    assert const.degenerate and "constant" in const.reason

    empty = S.slice_decile([np.nan] * 5)
    assert not empty.derivable


def test_unknown_slice_name_is_reported():
    out = S.build_slices(meta_frame(), ["nope"])
    assert not out["nope"].derivable and "unknown slice" in out["nope"].reason


# ---------------------------------------------------------------------------
# Metrics — edge cases are the point
# ---------------------------------------------------------------------------


def test_empty_slice_is_not_computable_for_every_metric():
    empty: list = []
    for res in (M.positive_rate(empty), M.win_rate(empty), M.expected_value(empty),
                M.drawdown(empty), M.quantiles(empty),
                M.excursion(empty, kind="mfe"), M.roc_auc(empty, empty),
                M.pr_auc(empty, empty), M.brier(empty, empty)):
        assert not res.computable, res.name
        assert res.reason
        assert res.to_dict()["value"] is None
        assert res.to_dict()["status"] == M.NOT_COMPUTABLE


@pytest.mark.parametrize("label", [0, 1])
def test_one_class_slice_refuses_auc_rather_than_returning_a_number(label):
    y = [label] * 20
    s = np.linspace(0, 1, 20)
    for res in (M.roc_auc(y, s), M.pr_auc(y, s)):
        assert not res.computable
        assert "single-class" in res.reason
        assert res.to_dict()["value"] is None


def test_one_class_slice_still_reports_base_rate_and_brier():
    y = [1] * 10
    assert M.positive_rate(y).value == 1.0
    assert M.brier(y, [0.9] * 10).computable


def test_nan_handling_counts_rather_than_silently_dropping():
    y = [0, 1, np.nan, 1]
    res = M.positive_rate(y)
    assert res.n == 3 and res.n_missing == 1
    assert res.value == pytest.approx(2 / 3)


def test_nan_in_scores_is_excluded_pairwise_and_counted():
    res = M.roc_auc([0, 1, 0, 1], [0.1, 0.9, np.nan, 0.8])
    assert res.computable and res.n == 3 and res.n_missing == 1


def test_length_mismatch_is_not_computable():
    assert not M.roc_auc([0, 1], [0.5]).computable
    assert not M.brier([0, 1], [0.5]).computable


def test_perfect_separation_gives_auc_one():
    res = M.roc_auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9])
    assert res.computable and res.value == pytest.approx(1.0)


def test_economic_metrics_on_known_series():
    r = [1.0, -0.5, 2.0, -1.0]
    assert M.win_rate(r).value == pytest.approx(0.5)
    assert M.expected_value(r).value == pytest.approx(0.375)
    # cumulative: 1.0, 0.5, 2.5, 1.5 -> worst peak-to-trough is -1.0
    assert M.drawdown(r).value == pytest.approx(-1.0)


def test_excursion_reports_mean_and_quantiles():
    res = M.excursion([1, 2, 3, 4], kind="mfe", quantiles=(0.5, 0.9))
    assert res.value == pytest.approx(2.5)
    assert "q50" in res.extra and "q90" in res.extra


def test_every_metric_carries_its_definition():
    for res in (M.positive_rate([1, 0]), M.win_rate([1.0]), M.drawdown([1.0]),
                M.roc_auc([0, 1], [0.1, 0.9])):
        assert res.to_dict()["definition"], res.name


def test_bundles_are_json_safe():
    import json

    y = [0, 1, 0, 1]
    payload = {
        **M.classification_bundle(y, [0.2, 0.7, 0.3, 0.9]),
        **M.economic_bundle(returns=[1.0, -1.0, 2.0, 0.5], mfe=[1, 2, 3, 4], mae=[0, 1, 0, 1]),
    }
    json.dumps(payload)  # must not raise on numpy/NaN types
    assert payload["roc_auc"]["status"] == "ok"


def test_classification_bundle_without_scores_omits_score_metrics():
    out = M.classification_bundle([0, 1, 1])
    assert set(out) == {"sample_count", "positive_rate"}
