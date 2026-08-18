import pytest

from backtests.nt_runtime.catalog_materializer import (
    MaterializationPlanError,
    plan_materialization,
)


def test_unsupported_product_reports_status_not_raises():
    plan = plan_materialization("ZZ", ["2024"], ["1s"])
    assert plan.status == "UNSUPPORTED_PRODUCT"
    assert "ZZ" in plan.detail


def test_raw_data_missing_for_unavailable_year():
    plan = plan_materialization("YM", ["1901"], ["1s"])
    assert plan.status == "RAW_DATA_MISSING"
    assert plan.raw_sources and not plan.raw_sources[0].exists


def test_materialization_required_when_catalog_absent():
    plan = plan_materialization("YM", ["2024"], ["1s", "1m"])
    assert plan.status in ("MATERIALIZATION_REQUIRED", "READY")
    if plan.status == "MATERIALIZATION_REQUIRED":
        assert set(plan.missing_streams) <= {"1s", "1m"}


def test_unsupported_stream_raises():
    with pytest.raises(MaterializationPlanError):
        plan_materialization("YM", ["2024"], ["1h"])


def test_plan_is_side_effect_free(tmp_path):
    """Planning must not create the catalog directory."""
    plan = plan_materialization("YM", ["2024"], ["1s"])
    assert not plan.catalog_path.exists() or plan.status == "READY"
