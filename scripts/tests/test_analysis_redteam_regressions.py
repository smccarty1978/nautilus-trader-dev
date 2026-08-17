"""Regression tests for the independent Red Team probes (2026-08-16).

Each test reproduces the *exact* call sequence a probe used and asserts the harness
now refuses. The probe id is named in each test so a future reviewer can map a
failure back to the finding it protects.

    H1  P1c   run_id path traversal escapes runs_root
    H2  P2    a spec-less ValidationReport authorises a DEV extraction
        P2b   an unsealed collection passes spec-less validation
    H3  P3    a 4-column declared join key silently degrades to 3
    H4  P4    a slice table drops 30 of 100 rows and reports "complete"
    M6  P5    non-finite metrics report status ok / crash the table build
    M2  P6    two fits on different populations share a fit identity
    M3  P7    a fit without partition provenance proceeds silently
    M4  P8    a threshold freezes with an empty or false derivation population
    M5  P9    completeness returns [] for a failed, unsealed validation
    M7  P11   the cross-study pooling guard is unexported

These are *negative* tests by design: every one of them passed before the fix.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import research.analysis as PKG  # noqa: E402
from research.analysis import errors as E  # noqa: E402
from research.analysis import metrics as M  # noqa: E402
from research.analysis import modeling as MOD  # noqa: E402
from research.analysis import reporting as R  # noqa: E402
from research.analysis import slices as S  # noqa: E402
from research.analysis.loader import (  # noqa: E402
    get_features_targets_metadata, load_collection, validate_collection,
    write_dataset_identity,
)
from research.analysis.spec import parse_analysis_spec  # noqa: E402
from scripts.tests.analysis_fixtures import (  # noqa: E402
    load_synthetic, make_synthetic_collection,
)


def spec_for(bundle, **over):
    payload = {
        "analysis_id": "rt", "schema_version": 1,
        "collection": {"run_id": bundle["run_id"], **over.pop("collection", {})},
        "partitions": over.pop("partitions", ["train"]),
        "seed": 1,
    }
    payload.update(over)
    return parse_analysis_spec(payload)


# ---------------------------------------------------------------------------
# H1 / P1c — run_id path traversal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [
    "../secret_runs/20230101_000000_synthetic_study_day",
    "..\\secret_runs\\20230101_000000_synthetic_study_day",
    "..",
    ".",
    "sub/dir",
    "sub\\dir",
    "run.with.dots",
    "C:evil",
])
def test_p1c_run_id_containing_path_syntax_is_rejected(bad, tmp_path):
    """P1c: `run_id='../secret_runs/<run>'` loaded a run outside runs_root and the
    recorded identity kept only the basename, erasing the traversal."""
    (tmp_path / "runs").mkdir()
    with pytest.raises(E.InvalidRunId) as err:
        load_collection(bad, runs_root=tmp_path / "runs", studies_root=tmp_path / "studies")
    assert err.value.code == "INVALID_RUN_ID"


def test_p1c_existing_collection_outside_runs_root_is_not_loadable(tmp_path):
    """The exact probe: a real, complete collection sitting outside runs_root."""
    outside = make_synthetic_collection(tmp_path / "secret")
    empty_runs = tmp_path / "main" / "runs"
    empty_runs.mkdir(parents=True)

    traversal = f"../../secret/runs/{outside['run_id']}"
    # Sanity: the target really is there, so a pass would be a genuine escape.
    assert (tmp_path / "secret" / "runs" / outside["run_id"]).is_dir()

    with pytest.raises(E.InvalidRunId):
        load_collection(traversal, runs_root=empty_runs, studies_root=outside["studies_root"])


def test_p1c_traversal_rejection_does_not_break_legitimate_runs(tmp_path):
    """The guard must reject paths, not ordinary run ids."""
    a = make_synthetic_collection(tmp_path / "a")
    col = load_synthetic(a)
    assert col.identity.run_id == a["run_id"]
    assert col.paths.resolved_run_dir == (a["runs_root"] / a["run_id"]).resolve()


def test_p1c_resolved_run_dir_is_recorded_in_dataset_identity(tmp_path):
    """The artifact must say which directory it actually read, not only a basename."""
    a = make_synthetic_collection(tmp_path / "a")
    col = load_synthetic(a)
    report = validate_collection(col, spec_for(a))
    payload = write_dataset_identity(col, report, tmp_path / "id.json", spec_for(a))
    assert payload["resolved_run_dir"].endswith(a["run_id"])
    assert Path(payload["resolved_run_dir"]).is_absolute()
    # ...and it is NOT hashed into the collection identity, which must stay portable.
    assert "resolved_run_dir" not in payload["identity"]


# ---------------------------------------------------------------------------
# H2 / P2, P2b — report is not bound to the spec
# ---------------------------------------------------------------------------


def test_p2_specless_report_cannot_authorize_a_dev_extraction(tmp_path):
    """P2: validate_collection(c) -> passed; extraction with a DEV spec returned 60
    DEV rows and OOS_LOCKED never fired."""
    a = make_synthetic_collection(tmp_path / "a", years=(2023, 2024),
                                  train=(2023,), dev=(2024,), prohibited=(2025, 2026))
    col = load_synthetic(a)

    report = validate_collection(col)                       # no spec
    assert report.passed                                    # unchanged: still passes
    assert report.spec_supplied is False
    assert "oos_unlocked" in report.skipped_checks
    assert {c.check for c in report.checks}.isdisjoint(report.skipped_checks)

    dev_spec = spec_for(a, partitions=["dev"])
    with pytest.raises(E.ValidationNotRun, match="does not authorise"):
        get_features_targets_metadata(col, dev_spec, report)


def test_p2_dev_extraction_still_blocked_when_validated_with_the_dev_spec(tmp_path):
    """Closing the bypass must not quietly open the front door: the DEV spec, properly
    validated, still fails OOS_LOCKED."""
    a = make_synthetic_collection(tmp_path / "a", years=(2023, 2024),
                                  train=(2023,), dev=(2024,), prohibited=(2025, 2026))
    col = load_synthetic(a)
    dev_spec = spec_for(a, partitions=["dev"])
    report = validate_collection(col, dev_spec)
    assert any(c.failure_code == E.OOSLocked.code for c in report.failures)
    with pytest.raises(E.OOSLocked):
        get_features_targets_metadata(col, dev_spec, report)


def test_p2_report_from_a_different_spec_is_refused(tmp_path):
    """Two specs that differ in any material field are not interchangeable."""
    a = make_synthetic_collection(tmp_path / "a")
    col = load_synthetic(a)
    report = validate_collection(col, spec_for(a, seed=1))
    other = parse_analysis_spec({
        "analysis_id": "rt", "schema_version": 1,
        "collection": {"run_id": a["run_id"]}, "partitions": ["train"], "seed": 999,
    })
    with pytest.raises(E.ValidationNotRun):
        get_features_targets_metadata(col, other, report)


def test_p2b_unsealed_collection_cannot_be_laundered_through_a_specless_report(tmp_path):
    """P2b: an unsealed collection passed spec-less validation and
    write_dataset_identity then recorded validation_passed: true for it."""
    a = make_synthetic_collection(tmp_path / "a", sealed=False)
    col = load_synthetic(a)
    report = validate_collection(col)
    payload = write_dataset_identity(col, report, tmp_path / "id.json")

    # The artifact must disclose that the seal check never ran.
    assert payload["sealed"] is False
    assert payload["validation_spec_supplied"] is False
    assert "seal_policy" in payload["validation_skipped_checks"]

    with pytest.raises(E.ValidationNotRun):
        get_features_targets_metadata(col, spec_for(a), report)


# ---------------------------------------------------------------------------
# H3 / P3 — the declared join key must be asserted, not derived
# ---------------------------------------------------------------------------


def _drop_observation_column(bundle, column: str, *, refresh_manifest_columns: bool):
    """Reproduces the probe: drop a key column from observations and refresh the
    manifest hash/count so no other check fires first."""
    coll = bundle["runs_root"] / bundle["run_id"] / "collection"
    obs = pd.read_parquet(coll / "observations.parquet").drop(columns=[column])
    obs.to_parquet(coll / "observations.parquet", index=False)

    mpath = coll / "collection_manifest.json"
    manifest = json.loads(mpath.read_text())
    manifest["observations_sha256"] = hashlib.sha256(
        (coll / "observations.parquet").read_bytes()
    ).hexdigest()
    manifest["observations_count"] = len(obs)
    if refresh_manifest_columns:
        manifest["columns"]["observations"] = list(obs.columns)
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def test_p3_shortened_join_key_is_blocked(tmp_path):
    """P3: dropping regime_direction from a 4-key collection shortened the key to 3
    and validation passed with zero failures."""
    a = make_synthetic_collection(tmp_path / "a")
    assert len(load_synthetic(a).join_key()) == 4

    _drop_observation_column(a, "regime_direction", refresh_manifest_columns=False)
    col = load_synthetic(a)

    # The key of record is still 4 columns...
    assert col.join_key() == ["observation_ts", "regime_start_ns", "regime_direction",
                              "checkpoint_index"]
    report = validate_collection(col, spec_for(a))
    assert not report.passed
    fail = next(c for c in report.failures if c.failure_code == E.JoinKeyMissing.code)
    assert fail.measured["missing_from_observations"] == ["regime_direction"]


def test_p3_shortened_join_key_is_blocked_even_when_the_manifest_is_rewritten(tmp_path):
    """The stronger form of the probe: the manifest's own column list is refreshed too,
    so the collection is internally self-consistent. An analysis that pins the key it
    expects still refuses."""
    a = make_synthetic_collection(tmp_path / "a")
    _drop_observation_column(a, "regime_direction", refresh_manifest_columns=True)
    col = load_synthetic(a)

    pinned = spec_for(a, collection={"expected_join_key": [
        "observation_ts", "regime_start_ns", "regime_direction", "checkpoint_index"]})
    report = validate_collection(col, pinned)
    assert not report.passed
    fail = next(c for c in report.failures if c.failure_code == E.JoinKeyMissing.code)
    assert fail.measured["source"] == "analysis_spec.collection.expected_join_key"
    assert fail.measured["missing_from_observations"] == ["regime_direction"]


def test_p3_rewriting_the_manifest_moves_the_collection_identity(tmp_path):
    """Defence in depth for the self-consistent variant: the manifest is part of the
    collection identity, so a spec that pins the identity detects the rewrite."""
    a = make_synthetic_collection(tmp_path / "a")
    before = load_synthetic(a).identity.collection_identity_sha256
    _drop_observation_column(a, "regime_direction", refresh_manifest_columns=True)
    after = load_synthetic(a).identity.collection_identity_sha256
    assert before != after

    report = validate_collection(
        load_synthetic(a), spec_for(a, collection={"collection_identity_sha256": before})
    )
    assert any(c.failure_code == E.IdentityMismatch.code for c in report.failures)


def test_p3_join_key_is_not_read_from_the_observation_frame(tmp_path):
    """The defect was structural: the key was *defined* as an intersection with the
    observation columns, so JOIN_KEY_MISSING could only fire on an empty key."""
    a = make_synthetic_collection(tmp_path / "a")
    _drop_observation_column(a, "regime_direction", refresh_manifest_columns=False)
    col = load_synthetic(a)
    _, source = col.declared_join_key()
    assert "observations.columns" not in source
    assert source == "collection_manifest.columns.observations"


def test_p3_short_key_study_is_not_wrongly_rejected(tmp_path):
    """Preserved behaviour: a study that legitimately declares a 3-column key still
    validates. Hardcoding a 4-column key would break exactly this case."""
    meta = ["observation_ts", "regime_start_ns", "checkpoint_index", "regime_age_seconds"]
    a = make_synthetic_collection(tmp_path / "a", metadata_columns=meta,
                                  join_key=["observation_ts", "regime_start_ns",
                                            "checkpoint_index"])
    col = load_synthetic(a)
    assert len(col.join_key()) == 3
    assert validate_collection(col, spec_for(a)).passed


# ---------------------------------------------------------------------------
# H4 / P4 — slice tables must account for every row
# ---------------------------------------------------------------------------


def _p4_frame(n=100, n_below=30):
    """100 rows, 30 of them below the MATURITY_EDGES floor of 0.0."""
    rng = np.random.default_rng(4)
    ages = np.concatenate([np.full(n_below, -5.0), rng.uniform(10, 900, n - n_below)])
    meta = pd.DataFrame({"regime_age_seconds": ages})
    y = pd.Series(rng.integers(0, 2, n))
    return y, meta


def test_p4_rows_outside_every_bin_are_reported_not_dropped():
    """P4: total_sample_count was 70 against len(y)==100 and the 30 lost rows appeared
    in no caveat."""
    y, meta = _p4_frame()
    t = R.build_slice_table(y, S.slice_maturity(meta), dataset_identity_sha256="d" * 64)

    assert t.n_input_rows == 100
    assert t.total_n == 100, "every input row must be accounted for"
    unassigned = [r for r in t.rows if r["group"] == R.UNASSIGNED_GROUP]
    assert len(unassigned) == 1 and unassigned[0]["n"] == 30
    assert any("in no group" in c for c in t.caveats)
    assert t.unassigned_rows == 0


def test_p4_completeness_check_reconciles_row_counts(tmp_path):
    """check_report_completeness returned [] ("complete") for the 70-of-100 table."""
    y, meta = _p4_frame()
    t = R.build_slice_table(y, S.slice_maturity(meta), dataset_identity_sha256="d" * 64)
    # Hand-forge the pre-fix table shape: drop the unassigned row, keep the total.
    t.rows = [r for r in t.rows if r["group"] != R.UNASSIGNED_GROUP]
    assert t.total_n == 70

    ctx = R.build_analysis_context(
        analysis_id="p4", question="q",
        dataset_identity={"collection_identity_sha256": "d" * 64, "identity": {}, "sealed": True},
        analysis_spec_sha256="s" * 64,
        validation={"passed": True, "checks": []}, tables={"by_maturity": t},
    )
    problems = R.check_report_completeness(ctx, {"by_maturity": t})
    assert any("does not account for every input row" in p for p in problems)


def test_p4_nan_labels_are_also_reconciled():
    """A NaT timestamp or a NaN score is enough to reproduce the defect."""
    scores = [0.1, 0.2, np.nan, 0.4, 0.5, 0.6, np.nan, 0.8]
    y = pd.Series([0, 1, 0, 1, 0, 1, 0, 1])
    t = R.build_decile_table(y, scores, n_buckets=3, dataset_identity_sha256="d" * 64)
    assert t.total_n == len(y)
    assert any(r["group"] == R.UNASSIGNED_GROUP and r["n"] == 2 for r in t.rows)


def test_p4_clean_slice_emits_no_unassigned_row():
    """Preserved behaviour: a table that already reconciles is left alone."""
    y, meta = _p4_frame(n_below=0)
    t = R.build_slice_table(y, S.slice_maturity(meta), dataset_identity_sha256="d" * 64)
    assert all(r["group"] != R.UNASSIGNED_GROUP for r in t.rows)
    assert t.total_n == t.n_input_rows == 100


# ---------------------------------------------------------------------------
# M6 / P5 — non-finite metrics
# ---------------------------------------------------------------------------


def test_p5a_non_finite_metric_values_are_not_computable():
    """P5a: brier([0,1],[inf,0.5]) returned {'status':'ok','value':None} — on the wire
    indistinguishable from a metric that was never computed."""
    res = M.brier([0, 1], [np.inf, 0.5])
    assert res.computable is False
    assert res.to_dict()["status"] == M.NOT_COMPUTABLE
    assert res.to_dict()["value"] is None
    assert res.to_dict()["reason"]


def test_p5a_non_finite_values_in_extras_are_caught_too():
    """excursion([1.0, inf]) emitted extra={'q50': None, 'q90': None} under status ok."""
    res = M.excursion([1.0, np.inf], kind="mfe")
    assert res.computable is False and res.reason

    ev = M.expected_value([1.0, np.inf])
    assert ev.computable is False


def test_p5b_infinite_scores_do_not_raise_from_auc():
    """P5b: roc_auc with an inf score raised an uncaught sklearn ValueError."""
    for fn in (M.roc_auc, M.pr_auc):
        res = fn([0, 1, 0, 1], [0.1, np.inf, 0.3, 0.9])
        assert res.computable is False
        assert "non-finite" in res.reason


def test_p5c_one_infinite_score_does_not_abort_the_whole_table_build():
    """P5c: build_standard_tables aborted the entire table set on a single inf."""
    rng = np.random.default_rng(9)
    n = 120
    ts = pd.date_range("2023-06-15 14:00", periods=n, freq="min", tz="UTC")
    meta = pd.DataFrame({
        "observation_ts": ts.astype("int64"),
        "regime_direction": rng.choice([-1, 1], size=n),
        "regime_age_seconds": rng.uniform(10, 900, size=n),
        "_year": ts.year, "_partition": ["train"] * n,
    })
    y = pd.Series(rng.integers(0, 2, n))
    scores = rng.random(n)
    scores[3] = np.inf

    tables = R.build_standard_tables(y, meta, scores=scores, dataset_identity_sha256="d" * 64)
    assert {"by_direction", "by_year", "by_maturity", "by_decile"} <= set(tables)

    rows = [r for t in tables.values() for r in t.rows]
    flagged = [r for r in rows if r.get("roc_auc_status") == M.NOT_COMPUTABLE]
    assert flagged, "the affected groups must say why, not vanish"
    # A refused metric never carries a value.
    assert all(r.get("roc_auc") is None for r in flagged)


def test_p5_finite_metrics_are_unchanged():
    """Preserved behaviour: ordinary values still report status ok."""
    res = M.roc_auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9])
    assert res.computable and res.to_dict()["status"] == "ok"
    assert res.value == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# M2 / P6 — fit identity must bind the training data
# ---------------------------------------------------------------------------


def _xy(n, seed, shift=0.0, partition="train"):
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(rng.normal(shift, 1.0, size=(n, 3)), columns=["f0", "f1", "f2"])
    y = pd.Series(rng.integers(0, 2, n))
    meta = pd.DataFrame({"_partition": [partition] * n})
    return X, y, meta


def test_p6_different_populations_get_different_fit_identities():
    """P6: fits on n=200 and n=80 from different distributions produced the identical
    fit_identity_sha256 because only the *asserted* dataset identity was hashed."""
    X1, y1, m1 = _xy(200, seed=1)
    X2, y2, m2 = _xy(80, seed=2, shift=3.0)
    a = MOD.fit_model(X1, y1, arm="A", seed=1, dataset_identity_sha256="DECLARED", meta=m1)
    b = MOD.fit_model(X2, y2, arm="A", seed=1, dataset_identity_sha256="DECLARED", meta=m2)
    assert a.provenance.fit_identity_sha256 != b.provenance.fit_identity_sha256
    assert a.provenance.n_rows == 200 and b.provenance.n_rows == 80


def test_p6_same_row_count_but_different_values_changes_identity():
    """n_rows alone is not enough — the values must be bound."""
    X1, y1, m1 = _xy(150, seed=5)
    X2, y2, m2 = _xy(150, seed=6)
    a = MOD.fit_model(X1, y1, arm="A", seed=1, dataset_identity_sha256="D", meta=m1)
    b = MOD.fit_model(X2, y2, arm="A", seed=1, dataset_identity_sha256="D", meta=m2)
    assert a.provenance.fit_identity_sha256 != b.provenance.fit_identity_sha256


def test_p6_changing_only_the_target_changes_identity():
    X, y, meta = _xy(150, seed=7)
    a = MOD.fit_model(X, y, arm="A", seed=1, meta=meta)
    b = MOD.fit_model(X, 1 - y, arm="A", seed=1, meta=meta)
    assert a.provenance.fit_identity_sha256 != b.provenance.fit_identity_sha256


def test_p6_library_version_change_changes_identity():
    """P6: mutating provenance.library_versions left the identity UNCHANGED, although
    the versions were recorded."""
    X, y, meta = _xy(120, seed=3)
    m = MOD.fit_model(X, y, arm="A", seed=1, meta=meta)
    before = m.provenance.fit_identity_sha256
    m.provenance.library_versions = {**m.provenance.library_versions, "sklearn": "999.0"}
    assert m.provenance.fit_identity_sha256 != before


def test_p6_identical_experiments_still_reproduce_one_identity():
    """Preserved behaviour: the identity must remain stable for the same experiment."""
    X, y, meta = _xy(150, seed=8)
    a = MOD.fit_model(X, y, arm="A", seed=4, dataset_identity_sha256="D", meta=meta)
    b = MOD.fit_model(X, y, arm="A", seed=4, dataset_identity_sha256="D", meta=meta)
    assert a.provenance.fit_identity_sha256 == b.provenance.fit_identity_sha256


# ---------------------------------------------------------------------------
# M3 / P7 — partition provenance is mandatory
# ---------------------------------------------------------------------------


def test_p7_fit_without_partition_provenance_is_blocked():
    """P7: without `meta` a 50-train/50-dev frame fit cleanly, and the provenance
    recorded split_policy 'no partition metadata supplied' — an innocent explanation
    asserted for its own blind spot."""
    X, y, _ = _xy(100, seed=2)
    with pytest.raises(E.PartitionProvenanceMissing) as err:
        MOD.fit_model(X, y, arm="A", seed=1)
    assert err.value.code == "PARTITION_PROVENANCE_MISSING"


def test_p7_mixed_partitions_are_still_blocked_when_meta_is_present():
    X, y, _ = _xy(100, seed=2)
    meta = pd.DataFrame({"_partition": ["train"] * 50 + ["dev"] * 50})
    with pytest.raises(E.PartitionMixing):
        MOD.fit_model(X, y, arm="A", meta=meta)


def test_p7_meta_that_does_not_describe_these_rows_is_rejected():
    X, y, _ = _xy(100, seed=2)
    meta = pd.DataFrame({"_partition": ["train"] * 40})
    with pytest.raises(E.SchemaMissing, match="does not describe these rows"):
        MOD.fit_model(X, y, arm="A", meta=meta)


def test_p7_explicit_opt_out_is_allowed_and_recorded():
    """The opt-out exists, but it must be stated and it must appear on the artifact."""
    X, y, _ = _xy(100, seed=2)
    policy = MOD.SplitPolicy(kind="none", description="synthetic data, no partitions exist")
    m = MOD.fit_model(X, y, arm="A", seed=1, split_policy=policy)
    assert m.provenance.partition_provenance == "explicit_opt_out"
    assert m.provenance.split_policy["description"] == "synthetic data, no partitions exist"
    # The opt-out is material: it is bound into the fit identity.
    with_meta = MOD.fit_model(X, y, arm="A", seed=1,
                              meta=pd.DataFrame({"_partition": ["train"] * 100}))
    assert with_meta.provenance.fit_identity_sha256 != m.provenance.fit_identity_sha256


# ---------------------------------------------------------------------------
# M4 / P8 — threshold derivation population
# ---------------------------------------------------------------------------


def _scores_y(n: int = 60):
    scores = np.linspace(0, 1, n)
    return scores, (scores > 0.5).astype(int)


def test_p8_threshold_without_a_population_is_blocked():
    """P8: freeze_threshold(scores, y) emitted derivation_population='' with a
    well-formed threshold_freeze_sha256."""
    scores, y = _scores_y(100)
    with pytest.raises(E.PartitionProvenanceMissing):
        MOD.freeze_threshold(scores, y)
    with pytest.raises(E.PartitionProvenanceMissing):
        MOD.freeze_threshold(scores, y, population="   ")


def test_freeze_threshold_requires_partition_meta():
    """M4-A, the residual exploit: DEV rows + population='train' + meta omitted.

    The caller-declared route is gone entirely. Omitting provenance was the whole
    bypass: it cost one keyword argument and produced an artifact that recorded
    `derivation_population='train'` over DEV scores.
    """
    dev_scores, y = _scores_y(60)
    with pytest.raises(E.PartitionProvenanceMissing) as err:
        MOD.freeze_threshold(dev_scores, y, population="train", meta=None)
    assert err.value.code == "PARTITION_PROVENANCE_MISSING"

    # And there is no positional back door either.
    with pytest.raises(E.PartitionProvenanceMissing):
        MOD.freeze_threshold(dev_scores, y)


def test_freeze_threshold_rejects_missing_partition_column():
    scores, y = _scores_y(60)
    meta = pd.DataFrame({"_year": [2023] * 60})       # metadata, but not provenance
    with pytest.raises(E.PartitionProvenanceMissing, match="no '_partition' column"):
        MOD.freeze_threshold(scores, y, meta=meta)


def test_freeze_threshold_rejects_all_null_partition_column():
    scores, y = _scores_y(60)
    meta = pd.DataFrame({"_partition": [None] * 60})
    with pytest.raises(E.PartitionProvenanceMissing, match="entirely null"):
        MOD.freeze_threshold(scores, y, meta=meta)


def test_freeze_threshold_rejects_mixed_train_dev():
    """M4-B: a threshold is a fitted parameter; 50 train + 50 dev was recorded as
    `derivation_population='dev+train'`, which names the contamination instead of
    refusing it."""
    scores, y = _scores_y(100)
    meta = pd.DataFrame({"_partition": ["train"] * 50 + ["dev"] * 50})
    with pytest.raises(E.PartitionMixing) as err:
        MOD.freeze_threshold(scores, y, meta=meta)
    assert err.value.code == "PARTITION_MIXING"


def test_freeze_threshold_derives_train_population():
    """M4-C: all-TRAIN meta passes and the population is derived, not declared."""
    scores, y = _scores_y(60)
    rec = MOD.freeze_threshold(scores, y, meta=pd.DataFrame({"_partition": ["train"] * 60}))
    assert rec["derivation_population"] == "train"
    assert rec["derivation_population_source"] == "derived_from_meta_partition"
    assert rec["derivation_n"] == 60
    # Identity binds population, source and row count.
    for key in ("derivation_population", "derivation_population_source", "derivation_n"):
        assert key in rec
    assert len(rec["threshold_freeze_sha256"]) == 64


def test_freeze_threshold_derives_dev_population_mechanically():
    """All-DEV is derivable here; whether such a freeze is authorised is spec/seal
    policy, which this function deliberately does not own."""
    scores, y = _scores_y(60)
    rec = MOD.freeze_threshold(scores, y, meta=pd.DataFrame({"_partition": ["dev"] * 60}))
    assert rec["derivation_population"] == "dev"
    assert rec["derivation_population_source"] == "derived_from_meta_partition"


def test_freeze_threshold_rejects_declared_population_disagreement():
    """M4-D: derived train, caller says dev -> BLOCK. The declaration is a
    cross-check; it is never the source."""
    scores, y = _scores_y(60)
    train_meta = pd.DataFrame({"_partition": ["train"] * 60})
    with pytest.raises(E.InvalidAnalysisSpec, match="contradicts the scored rows"):
        MOD.freeze_threshold(scores, y, population="dev", meta=train_meta)


def test_p8_dev_derived_threshold_cannot_be_labelled_train():
    """The finding in one line: a DEV-derived threshold labelled population='train'
    was byte-indistinguishable from a real TRAIN freeze."""
    scores, y = _scores_y(60)
    dev_meta = pd.DataFrame({"_partition": ["dev"] * 60})
    with pytest.raises(E.InvalidAnalysisSpec, match="contradicts the scored rows"):
        MOD.freeze_threshold(scores, y, population="train", meta=dev_meta)

    # The honest DEV freeze and the mislabelled one are no longer the same artifact
    # because the mislabelled one cannot be produced at all.
    honest = MOD.freeze_threshold(scores, y, meta=dev_meta)
    train_freeze = MOD.freeze_threshold(
        scores, y, meta=pd.DataFrame({"_partition": ["train"] * 60}))
    assert honest["threshold_freeze_sha256"] != train_freeze["threshold_freeze_sha256"]


def test_p8_meta_of_the_wrong_length_is_rejected():
    scores, y = _scores_y(60)
    with pytest.raises(E.SchemaMissing, match="does not describe these rows"):
        MOD.freeze_threshold(scores, y, meta=pd.DataFrame({"_partition": ["train"] * 10}))


def test_p8_declared_population_still_works_when_it_agrees():
    """Preserved behaviour: an explicit, honest label is accepted."""
    scores, y = _scores_y(60)
    meta = pd.DataFrame({"_partition": ["train"] * 60})
    rec = MOD.freeze_threshold(scores, y, population="TRAIN", meta=meta)
    assert rec["derivation_population"] == "train"
    assert rec["derivation_population_source"] == "derived_from_meta_partition"


# ---------------------------------------------------------------------------
# M5 / P9 — completeness must read the verdict
# ---------------------------------------------------------------------------


def _context_with(validation, sealed, **over):
    return R.build_analysis_context(
        analysis_id="p9", question="q",
        dataset_identity={"collection_identity_sha256": "d" * 64, "identity": {},
                          "sealed": sealed},
        analysis_spec_sha256="s" * 64, validation=validation, tables={}, **over,
    )


def test_p9_failed_validation_is_not_complete():
    """P9: a context with validation.passed False and sealed False returned []."""
    ctx = _context_with(
        {"passed": False,
         "checks": [{"check": "candidates_hash_matches_manifest", "passed": False}]},
        sealed=False,
    )
    problems = R.check_report_completeness(ctx, {})
    assert any("validation did not pass" in p for p in problems)
    assert any("unsealed" in p for p in problems)


def test_p9_unsealed_is_complete_only_with_recorded_authorization():
    passing = {"passed": True, "checks": []}
    assert any("unsealed" in p for p in R.check_report_completeness(
        _context_with(passing, sealed=False), {}))
    assert R.check_report_completeness(
        _context_with(passing, sealed=False, allow_unsealed_collection=True), {}) == []


def test_p9_specless_validation_is_flagged_in_the_packet():
    ctx = _context_with({"passed": True, "checks": [], "spec_supplied": False,
                         "skipped_checks": ["seal_policy", "oos_unlocked"]}, sealed=True)
    problems = R.check_report_completeness(ctx, {})
    assert any("without an analysis spec" in p for p in problems)


def test_p9_a_clean_report_is_still_complete():
    """Preserved behaviour: the gate must not become unsatisfiable.

    Note this packet declares no tables, so `{}` IS its exact table set — the N1
    binding below is satisfied here, not bypassed.
    """
    ctx = _context_with({"passed": True, "checks": [], "spec_supplied": True,
                         "skipped_checks": []}, sealed=True)
    assert R.check_report_completeness(ctx, {}) == []


# ---------------------------------------------------------------------------
# N1 — completeness must be bound to the packet's own table set
# ---------------------------------------------------------------------------


def _table_frame(n, *, seed=5, year=2023):
    rng = np.random.default_rng(seed)
    ts = pd.date_range(f"{year}-06-15 12:00", periods=n, freq="3min", tz="UTC")
    meta = pd.DataFrame({
        "observation_ts": ts.astype("int64"),
        "regime_direction": rng.choice([-1, 1], size=n),
        "regime_age_seconds": rng.uniform(10, 900, size=n),
        "_year": ts.year,
        "_partition": ["train"] * n,
    })
    y = pd.Series((rng.random(n) < 0.4).astype(int))
    return y, meta


def _packet_over(n, *, seed=5, year=2023):
    """A real packet built from real tables, exactly as the probe built it."""
    y, meta = _table_frame(n, seed=seed, year=year)
    tables = R.build_standard_tables(y, meta, dataset_identity_sha256="d" * 64,
                                     analysis_spec_sha256="s" * 64)
    ctx = R.build_analysis_context(
        analysis_id="n1", question="q",
        dataset_identity={"collection_identity_sha256": "d" * 64, "identity": {}, "sealed": True},
        analysis_spec_sha256="s" * 64,
        validation={"passed": True, "checks": [], "spec_supplied": True, "skipped_checks": []},
        tables=tables,
    )
    return ctx, tables


def test_completeness_accepts_exact_context_table_set():
    """N1-C: the gate must still pass when the packet and the tables agree."""
    ctx, tables = _packet_over(120)
    assert len(tables) >= 5
    assert R.check_report_completeness(ctx, tables) == []


def test_completeness_rejects_empty_supplied_table_set():
    """N1-A, the probe: a context built from six tables over 120 rows was reported
    complete when handed `{}`. The checker derived its scope from its argument."""
    ctx, tables = _packet_over(120)
    problems = R.check_report_completeness(ctx, {})
    assert problems, "a packet describing tables cannot be complete with no tables supplied"
    for name in tables:
        assert any(f"context declares table {name!r}" in p for p in problems)


def test_completeness_rejects_missing_table():
    ctx, tables = _packet_over(120)
    dropped = "by_direction"
    partial = {k: v for k, v in tables.items() if k != dropped}
    problems = R.check_report_completeness(ctx, partial)
    assert any(f"context declares table {dropped!r}" in p for p in problems)


def test_completeness_rejects_unexpected_table():
    ctx, tables = _packet_over(120)
    y, meta = _table_frame(120)
    extra = dict(tables)
    extra["by_smuggled"] = R.build_slice_table(
        y, S.slice_direction(meta), name="by_smuggled", dataset_identity_sha256="d" * 64)
    problems = R.check_report_completeness(ctx, extra)
    assert any("'by_smuggled' was supplied but the context packet does not declare it" in p
               for p in problems)


def test_completeness_rejects_table_count_mismatch():
    """N1-B: same table NAMES, different tables — the packet describes 120 rows and
    the supplied tables cover 30. Name identity alone is not table identity."""
    ctx, _ = _packet_over(120)
    _, small_tables = _packet_over(30, seed=9)
    assert set(small_tables) == set(ctx["tables"]), "the exploit needs identical names"

    problems = R.check_report_completeness(ctx, small_tables)
    assert any("does not match the context packet" in p and "total_sample_count" in p
               for p in problems)


def test_completeness_rejects_a_swapped_table_object_under_the_same_name():
    """The narrower version of the same defect: one table replaced, same name."""
    ctx, tables = _packet_over(120)
    y_small, meta_small = _table_frame(30, seed=11)
    swapped = dict(tables)
    swapped["by_direction"] = R.build_slice_table(
        y_small, S.slice_direction(meta_small), dataset_identity_sha256="d" * 64)
    problems = R.check_report_completeness(ctx, swapped)
    assert any("table by_direction does not match the context packet" in p for p in problems)


def test_completeness_flags_a_packet_with_no_tables_summary():
    ctx, tables = _packet_over(120)
    ctx.pop("tables")
    problems = R.check_report_completeness(ctx, tables)
    assert any("missing the tables summary" in p for p in problems)


# ---------------------------------------------------------------------------
# M7 / P11 — the pooling guard must be reachable
# ---------------------------------------------------------------------------


def test_p11_pooling_guard_is_exported_from_the_package():
    """P11: 'assert_single_study' in research.analysis.__all__ -> False."""
    assert "assert_single_study" in PKG.__all__
    assert callable(PKG.assert_single_study)


def test_p11_pooling_guard_still_refuses_two_studies(tmp_path):
    a = make_synthetic_collection(tmp_path / "a", study_id="study_a")
    b = make_synthetic_collection(tmp_path / "b", study_id="study_b",
                                  run_id="20230101_000000_study_b_day")
    with pytest.raises(E.CrossStudyPooling):
        PKG.assert_single_study([load_synthetic(a), load_synthetic(b)])


def test_p11_caller_obligation_is_documented():
    assert "assert_single_study" in (PKG.__doc__ or "")


# ---------------------------------------------------------------------------
# M1 / L8 — identity and artifacts must not depend on line endings
# ---------------------------------------------------------------------------


def test_m1_collection_identity_survives_crlf_normalization(tmp_path):
    """M1: collection_manifest_sha256 was a raw byte hash of a git-tracked JSON file,
    so a Windows checkout and a Linux checkout produced different collection
    identities for byte-identical collection DATA."""
    a = make_synthetic_collection(tmp_path / "a")
    mpath = a["runs_root"] / a["run_id"] / "collection" / "collection_manifest.json"
    before = load_synthetic(a).identity.collection_identity_sha256

    lf = mpath.read_text(encoding="utf-8")
    mpath.write_bytes(lf.replace("\n", "\r\n").encode("utf-8"))
    assert mpath.read_bytes().count(b"\r") > 0
    assert load_synthetic(a).identity.collection_identity_sha256 == before

    # ...but a changed VALUE must still move the identity.
    doc = json.loads(mpath.read_text(encoding="utf-8"))
    doc["candidates_count"] = doc["candidates_count"] + 1
    mpath.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    assert load_synthetic(a).identity.collection_identity_sha256 != before


def test_m1_parquet_identity_is_still_a_raw_byte_hash(tmp_path):
    """Generated binary data keeps raw-byte hashing — no normalisation, ever."""
    a = make_synthetic_collection(tmp_path / "a", corrupt_candidates_hash=True)
    report = validate_collection(load_synthetic(a))
    assert any(c.failure_code == E.ArtifactHashMismatch.code for c in report.failures)


def test_l8_written_artifacts_use_lf_on_every_platform(tmp_path):
    a = make_synthetic_collection(tmp_path / "a")
    col = load_synthetic(a)
    report = validate_collection(col, spec_for(a))
    out = tmp_path / "dataset_identity.json"
    write_dataset_identity(col, report, out, spec_for(a))
    assert b"\r\n" not in out.read_bytes()

    y, meta = _p4_frame()
    t = R.build_slice_table(y, S.slice_maturity(meta), dataset_identity_sha256="d" * 64)
    paths = t.write(tmp_path / "tables")
    assert b"\r\n" not in Path(paths["json"]).read_bytes()
    assert b"\r\n" not in Path(paths["csv"]).read_bytes()

    ctx = R.build_analysis_context(
        analysis_id="lf", question="q",
        dataset_identity={"collection_identity_sha256": "d" * 64, "identity": {}, "sealed": True},
        analysis_spec_sha256="s" * 64, validation={"passed": True, "checks": []},
        tables={"by_maturity": t},
    )
    ctx_path = R.write_analysis_context(ctx, tmp_path / "analysis_context.json")
    assert b"\r\n" not in ctx_path.read_bytes()


# ---------------------------------------------------------------------------
# L2 — an absent feature contract must not pass vacuously
# ---------------------------------------------------------------------------


def test_l2_absent_feature_contract_fails_schema_missing(tmp_path):
    """L2: with the study directory absent, declared=[] made feature_order_preserved
    and feature_list_hash_matches both pass (`None in {None, None}`)."""
    a = make_synthetic_collection(tmp_path / "a")
    col = load_collection(a["run_id"], runs_root=a["runs_root"],
                          studies_root=tmp_path / "no_such_studies")
    assert col.declared_features == []
    report = validate_collection(col)
    codes = {c.failure_code for c in report.failures}
    assert E.SchemaMissing.code in codes
    assert not next(c for c in report.checks if c.check == "feature_order_preserved").passed
    assert not next(c for c in report.checks if c.check == "feature_list_hash_matches").passed
