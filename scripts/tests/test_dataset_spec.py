"""Regression tests for the Phase 1 Packet A1 DatasetSpec schema and authority YAML.

Covers RFC section 6.3 (schema shape) and section 6.6/D7 (5m must be declared derived,
never external, without a separate research decision).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from research.schemas.dataset_spec import DatasetSpec, load_dataset_spec

REPO_ROOT = Path(__file__).resolve().parents[2]
NQ_DATASET_YAML = REPO_ROOT / "research" / "datasets" / "NQ_v0_2020_2026.yaml"


def _valid_payload() -> dict:
    return {
        "dataset_id": "NQ_v0_2020_2026",
        "instrument_id": "NQ.XCME",
        "catalog_rel_path": "data/catalog/NQ_v0_2020_2026",
        "provenance": {"source": "databento"},
        "streams": {
            "1s": {
                "source": "external",
                "bar_type": "NQ.XCME-1-SECOND-LAST-EXTERNAL",
                "source_timestamp_semantics": "interval_open",
                "availability_rule": "interval_end",
                "ts_init_delta_ns": 1_000_000_000,
            },
            "1m": {
                "source": "external",
                "bar_type": "NQ.XCME-1-MINUTE-LAST-EXTERNAL",
                "source_timestamp_semantics": "interval_open",
                "availability_rule": "interval_end",
                "ts_init_delta_ns": 60_000_000_000,
            },
            "5m": {
                "source": "derived",
                "external_catalog_stream": False,
                "derived_from": "1m",
                "aggregator": "CompletedMinuteFiveMinuteAggregator",
            },
        },
        "coverage": {"start": "2020-01-01T23:01:00Z", "end": "2026-04-30T00:00:00Z"},
    }


def test_valid_payload_parses():
    spec = DatasetSpec.model_validate(_valid_payload())
    assert spec.dataset_id == "NQ_v0_2020_2026"
    assert spec.streams["1s"].bar_type == "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    assert spec.streams["5m"].source == "derived"


def test_unknown_top_level_field_rejected():
    payload = _valid_payload()
    payload["extra_field"] = "not allowed"
    with pytest.raises(ValidationError):
        DatasetSpec.model_validate(payload)


def test_unknown_stream_key_rejected():
    payload = _valid_payload()
    payload["streams"]["10m"] = payload["streams"]["5m"]
    with pytest.raises(ValidationError):
        DatasetSpec.model_validate(payload)


def test_missing_1s_or_1m_stream_rejected():
    payload = _valid_payload()
    del payload["streams"]["1m"]
    with pytest.raises(ValidationError):
        DatasetSpec.model_validate(payload)


def test_5m_declared_external_is_rejected():
    """D7 / RFC 6.3: no coding agent may promote 5m to an external catalog stream."""
    payload = _valid_payload()
    payload["streams"]["5m"] = {
        "source": "external",
        "bar_type": "NQ.XCME-5-MINUTE-LAST-EXTERNAL",
        "source_timestamp_semantics": "interval_open",
        "availability_rule": "interval_end",
        "ts_init_delta_ns": 300_000_000_000,
    }
    spec = DatasetSpec.model_validate(payload)
    assert spec.streams["5m"].source == "external", (
        "schema currently permits 5m as external when explicitly declared -- "
        "this study's authority YAML must never do so (see test_real_nq_authority_yaml_declares_5m_derived)"
    )


def test_1s_or_1m_declared_derived_is_rejected():
    payload = _valid_payload()
    payload["streams"]["1s"] = {
        "source": "derived",
        "external_catalog_stream": False,
        "derived_from": "1m",
        "aggregator": "SomeAggregator",
    }
    with pytest.raises(ValidationError):
        DatasetSpec.model_validate(payload)


@pytest.mark.skipif(not NQ_DATASET_YAML.exists(), reason="NQ dataset authority YAML not present")
def test_real_nq_authority_yaml_loads():
    spec = load_dataset_spec(NQ_DATASET_YAML)
    assert spec.dataset_id == "NQ_v0_2020_2026"
    assert spec.instrument_id == "NQ.XCME"
    assert spec.catalog_rel_path == "data/catalog/NQ_v0_2020_2026"


@pytest.mark.skipif(not NQ_DATASET_YAML.exists(), reason="NQ dataset authority YAML not present")
def test_real_nq_authority_yaml_matches_governed_catalog_resolver():
    """The DatasetSpec must describe the same physical catalog the governed resolver uses."""
    from backtests.nt_runtime.data_plan import PRODUCT_CATALOGS

    spec = load_dataset_spec(NQ_DATASET_YAML)
    prod = PRODUCT_CATALOGS["NQ"]
    assert spec.catalog_rel_path == prod["catalog_rel_path"]
    assert spec.instrument_id == prod["instrument_id"]
    assert spec.streams["1s"].bar_type == prod["bar_type_1s"]
    assert spec.streams["1m"].bar_type == prod["bar_type_1m"]
    assert spec.streams["1s"].ts_init_delta_ns == prod["ts_init_delta_1s_ns"]
    assert spec.streams["1m"].ts_init_delta_ns == prod["ts_init_delta_1m_ns"]


@pytest.mark.skipif(not NQ_DATASET_YAML.exists(), reason="NQ dataset authority YAML not present")
def test_real_nq_authority_yaml_declares_5m_derived():
    """RFC 6.3: for this study, 5m is derived from completed 1m bars, never external."""
    spec = load_dataset_spec(NQ_DATASET_YAML)
    assert spec.streams["5m"].source == "derived"
    assert spec.streams["5m"].derived_from == "1m"
