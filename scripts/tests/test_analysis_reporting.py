"""A4 tests: standard tables, context packet, report completeness.

Includes one end-to-end pass over the real Fixture A collection — loader through
tables and context — with no model fitted on real data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.analysis import reporting as R  # noqa: E402
from research.analysis import slices as S  # noqa: E402
from research.analysis.loader import (  # noqa: E402
    get_features_targets_metadata, load_collection, validate_collection, write_dataset_identity,
)
from research.analysis.spec import parse_analysis_spec  # noqa: E402
from scripts.tests.analysis_fixtures import (  # noqa: E402
    FIXTURE_A_RUN, resolve_real_runs_root, resolve_real_studies_root,
)

RUNS_ROOT = resolve_real_runs_root()
real_fixture = pytest.mark.skipif(RUNS_ROOT is None, reason="real A0 fixture parquet unavailable")

DS = "d" * 64
SPEC = "s" * 64


def demo_frame(n=200, seed=5):
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2023-06-15 12:00", periods=n, freq="3min", tz="UTC")
    meta = pd.DataFrame({
        "observation_ts": ts.astype("int64"),
        "regime_direction": rng.choice([-1, 1], size=n),
        "regime_age_seconds": rng.uniform(10, 900, size=n),
        "_year": ts.year,
        "_partition": ["train"] * n,
    })
    scores = rng.random(n)
    y = pd.Series((rng.random(n) < scores).astype(int))
    return y, meta, scores


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def test_slice_table_carries_identity_filters_definitions_and_n():
    y, meta, scores = demo_frame()
    t = R.build_slice_table(y, S.slice_direction(meta), scores=pd.Series(scores),
                            dataset_identity_sha256=DS, analysis_spec_sha256=SPEC)
    d = t.to_dict()
    for key in R.REQUIRED_TABLE_KEYS:
        assert key in d, key
    assert d["dataset_identity_sha256"] == DS
    assert d["analysis_spec_sha256"] == SPEC
    assert d["filters"]["slice"] == "direction"
    assert d["filters"]["slice_definition"]
    assert d["metric_definitions"]
    assert d["total_sample_count"] == len(y)
    assert {r["group"] for r in d["rows"]} == {"long", "short"}


def test_table_rows_report_metric_status_for_uncomputable_groups():
    """A single-class group must say why, not print a number."""
    meta = pd.DataFrame({"regime_direction": [1] * 10 + [-1] * 10})
    y = pd.Series([1] * 10 + [0] * 10)          # each group is single-class
    scores = pd.Series(np.linspace(0, 1, 20))
    t = R.build_slice_table(y, S.slice_direction(meta), scores=scores, dataset_identity_sha256=DS)
    for row in t.rows:
        assert row["roc_auc"] is None
        assert row["roc_auc_status"] == "not_computable"
        assert "single-class" in row["roc_auc_reason"]


def test_degenerate_slice_produces_a_caveat():
    meta = pd.DataFrame({"regime_direction": [1] * 20})
    y = pd.Series(np.random.default_rng(1).integers(0, 2, 20))
    t = R.build_slice_table(y, S.slice_direction(meta), dataset_identity_sha256=DS)
    assert any("not a comparison" in c for c in t.caveats)


def test_small_group_caveat_emitted():
    meta = pd.DataFrame({"regime_direction": [1] * 5 + [-1] * 5})
    y = pd.Series([0, 1] * 5)
    t = R.build_slice_table(y, S.slice_direction(meta), dataset_identity_sha256=DS)
    assert any("n<30" in c for c in t.caveats)


def test_non_derivable_slice_is_reported_not_fatal():
    y = pd.Series([0, 1, 0])
    t = R.build_slice_table(y, S.slice_direction(pd.DataFrame({"x": [1, 2, 3]})),
                            dataset_identity_sha256=DS)
    assert t.rows == []
    assert any("not derivable" in c for c in t.caveats)


def test_arm_table_reports_each_arm_on_identical_rows():
    y, meta, scores = demo_frame()
    rng = np.random.default_rng(2)
    arm_scores = {"A": rng.random(len(y)), "B": rng.random(len(y)), "C": scores}
    prov = {"A": {"n_features": 1, "seed": 42, "estimator": "logistic_regression",
                  "fit_identity_sha256": "a" * 64}}
    t = R.build_arm_table(y, arm_scores, dataset_identity_sha256=DS, arm_provenance=prov)
    assert {r["arm"] for r in t.rows} == {"A", "B", "C"}
    assert all(r["n"] == len(y) for r in t.rows)
    assert t.rows[0]["fit_identity_sha256"] == "a" * 64
    assert any("identical evaluation rows" in c for c in t.caveats)


def test_decile_table_has_ten_buckets_and_records_n_buckets():
    y, meta, scores = demo_frame(n=300)
    t = R.build_decile_table(y, scores, dataset_identity_sha256=DS)
    assert len(t.rows) == 10
    assert t.filters["n_buckets"] == 10
    assert t.total_n == len(y)


def test_standard_table_set_contains_the_required_views():
    y, meta, scores = demo_frame()
    arm_scores = {"A": scores, "B": scores}
    tables = R.build_standard_tables(y, meta, scores=scores, arm_scores=arm_scores,
                                     dataset_identity_sha256=DS, analysis_spec_sha256=SPEC)
    for required in ("by_arm", "by_direction", "by_year", "by_maturity", "by_decile"):
        assert required in tables, required


def test_tables_write_csv_and_json(tmp_path):
    y, meta, scores = demo_frame()
    t = R.build_slice_table(y, S.slice_direction(meta), scores=pd.Series(scores),
                            dataset_identity_sha256=DS)
    paths = t.write(tmp_path)
    assert Path(paths["csv"]).is_file() and Path(paths["json"]).is_file()
    reloaded = json.loads(Path(paths["json"]).read_text())
    assert reloaded["dataset_identity_sha256"] == DS
    assert len(pd.read_csv(paths["csv"])) == len(t.rows)


# ---------------------------------------------------------------------------
# Context packet + completeness
# ---------------------------------------------------------------------------


def build_context(tmp_path, tables):
    dataset_identity = {
        "collection_identity_sha256": DS,
        "identity": {"run_id": "r1", "study_id": "s1", "stage": "day",
                     "start_date": "2023-06-15", "end_date": "2023-06-15"},
        "sealed": True,
    }
    validation = {"passed": True, "checks": [{"check": "x", "passed": True}],
                  "partition_row_counts": {"train": 200}, "join_key": ["observation_ts"],
                  "metadata_source": "declared"}
    paths = {name: t.write(tmp_path / "tables") for name, t in tables.items()}
    return R.build_analysis_context(
        analysis_id="demo", question="Does X predict Y?",
        dataset_identity=dataset_identity, analysis_spec_sha256=SPEC,
        validation=validation, tables=tables, table_paths=paths,
        headline_metrics={"roc_auc": 0.61},
    )


def test_context_packet_is_complete_and_compact(tmp_path):
    y, meta, scores = demo_frame()
    tables = R.build_standard_tables(y, meta, scores=scores, dataset_identity_sha256=DS,
                                     analysis_spec_sha256=SPEC)
    ctx = build_context(tmp_path, tables)

    assert ctx["identity"]["collection_identity_sha256"] == DS
    assert ctx["identity"]["analysis_spec_sha256"] == SPEC
    assert ctx["validation"]["passed"] is True
    assert ctx["headline_metrics"]["roc_auc"] == 0.61
    assert ctx["metric_definitions"]
    assert "data_access_note" in ctx
    for name in tables:
        assert name in ctx["tables"]
        assert ctx["tables"][name]["paths"]["csv"]

    # Compact: references artifacts, does not embed row-level data.
    blob = json.dumps(ctx)
    assert "rows" not in ctx["tables"]["by_direction"]
    assert len(blob) < 60_000


def test_report_completeness_passes_on_a_full_report(tmp_path):
    y, meta, scores = demo_frame()
    tables = R.build_standard_tables(y, meta, scores=scores, dataset_identity_sha256=DS,
                                     analysis_spec_sha256=SPEC)
    ctx = build_context(tmp_path, tables)
    assert R.check_report_completeness(ctx, tables) == []


def test_report_completeness_flags_missing_identity(tmp_path):
    y, meta, scores = demo_frame()
    tables = R.build_standard_tables(y, meta, scores=scores)   # no identity supplied
    ctx = build_context(tmp_path, tables)
    problems = R.check_report_completeness(ctx, tables)
    assert any("does not carry a dataset identity" in p for p in problems)


def test_context_writes_to_disk(tmp_path):
    y, meta, scores = demo_frame()
    tables = R.build_standard_tables(y, meta, scores=scores, dataset_identity_sha256=DS)
    ctx = build_context(tmp_path, tables)
    out = R.write_analysis_context(ctx, tmp_path / "analysis_context.json")
    assert out.is_file()
    assert json.loads(out.read_text())["analysis_id"] == "demo"


def test_caveats_are_propagated_from_tables_into_the_context(tmp_path):
    meta = pd.DataFrame({"regime_direction": [1] * 10, "_year": [2023] * 10,
                         "observation_ts": pd.date_range("2023-06-15", periods=10, freq="min",
                                                          tz="UTC").astype("int64"),
                         "regime_age_seconds": [100.0] * 10, "_partition": ["train"] * 10})
    y = pd.Series([0, 1] * 5)
    tables = R.build_standard_tables(y, meta, dataset_identity_sha256=DS)
    ctx = build_context(tmp_path, tables)
    assert any("[by_direction]" in c for c in ctx["caveats"])


# ---------------------------------------------------------------------------
# End-to-end on the real Fixture A (no model fitted on real data)
# ---------------------------------------------------------------------------


@real_fixture
def test_end_to_end_real_fixture_a_produces_tables_and_context(tmp_path):
    spec = parse_analysis_spec({
        "analysis_id": "fixture_a_smoke",
        "collection": {"run_id": FIXTURE_A_RUN},
        "partitions": ["train"], "seed": 20260816,
    })
    col = load_collection(FIXTURE_A_RUN, runs_root=RUNS_ROOT,
                          studies_root=resolve_real_studies_root())
    report = validate_collection(col, spec)
    assert report.passed, [c.to_dict() for c in report.failures]

    X, y, meta = get_features_targets_metadata(col, spec, report)
    assert len(X) == 2002 and list(X.columns) == col.declared_features
    assert set(y.unique()) <= {0, 1}

    ident = write_dataset_identity(col, report, tmp_path / "dataset_identity.json", spec)

    # Tables built WITHOUT any model: label-only metrics on real data are descriptive,
    # not a research conclusion, and no threshold is derived.
    tables = R.build_standard_tables(
        y, meta, dataset_identity_sha256=ident["collection_identity_sha256"],
        analysis_spec_sha256=spec.analysis_spec_sha256,
    )
    assert {"by_direction", "by_year", "by_maturity", "by_partition", "by_session"} <= set(tables)

    by_dir = tables["by_direction"]
    assert by_dir.total_n == 2002
    assert {r["group"] for r in by_dir.rows} == {"long", "short"}
    # No scores were supplied, so score-based metrics are omitted entirely rather
    # than emitted as nulls — an absent column is honest, a null column invites
    # being read as "measured and undefined".
    assert all("roc_auc" not in r for r in by_dir.rows)
    assert all("positive_rate" in r and r["n"] > 0 for r in by_dir.rows)

    paths = {n: t.write(tmp_path / "tables") for n, t in tables.items()}
    ctx = R.build_analysis_context(
        analysis_id=spec.analysis_id, question="Structural smoke of the A0 fixture.",
        dataset_identity=ident, analysis_spec_sha256=spec.analysis_spec_sha256,
        validation=report.to_dict(), tables=tables, table_paths=paths,
    )
    assert R.check_report_completeness(ctx, tables) == []
    assert ctx["validation"]["partition_row_counts"]["train"] == 2002
    assert ctx["identity"]["sealed"] is True
