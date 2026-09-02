"""Strict Machine-Readable DatasetSpec Schema.
==============================================
Binding layer over the existing governed catalog resolver
(``backtests/nt_runtime/data_plan.py:resolve_catalog_plan``). A DatasetSpec YAML under
``research/datasets/`` is the authority a study references by id
(``execution.data_requirements.dataset_id``); it does not replace the resolver or
introduce a parallel data-plan system.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Dict, Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DatasetProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Optional[str] = Field(None, description="Origin of the raw data, e.g. databento")
    manifest_path: Optional[str] = Field(None, description="Path to a source manifest, if one exists")
    expected_hash: Optional[str] = Field(None, description="Pinned provenance hash, if verified")


class ExternalStreamSpec(BaseModel):
    """A bar stream physically present in the catalog."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["external"] = "external"
    bar_type: str = Field(..., description="NautilusTrader BarType string, e.g. NQ.XCME-1-MINUTE-LAST-EXTERNAL")
    source_timestamp_semantics: Literal["interval_open"] = Field(
        "interval_open", description="Raw source bars are OPEN-stamped"
    )
    availability_rule: Literal["interval_end"] = Field(
        "interval_end", description="A bar is available at its interval close, not its open"
    )
    ts_init_delta_ns: int = Field(..., description="ts_init - ts_event in nanoseconds, e.g. 60_000_000_000 for 1m")


class DerivedStreamSpec(BaseModel):
    """A stream computed at runtime from a lower-timeframe external stream, not stored in the catalog."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["derived"] = "derived"
    external_catalog_stream: Literal[False] = Field(
        False, description="Always False for a derived stream; it is never opened from the catalog directly"
    )
    derived_from: str = Field(..., description="Stream key this is aggregated from, e.g. '1m'")
    aggregator: str = Field(..., description="Aggregator class name, e.g. CompletedMinuteFiveMinuteAggregator")


StreamSpec = Annotated[Union[ExternalStreamSpec, DerivedStreamSpec], Field(discriminator="source")]

_ALLOWED_STREAM_KEYS = frozenset({"1s", "1m", "5m"})
_REQUIRED_EXTERNAL_STREAM_KEYS = frozenset({"1s", "1m"})


class DatasetCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str = Field(..., description="Earliest timestamp physically present in the catalog")
    end: str = Field(..., description="Latest timestamp physically present in the catalog")


class DatasetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(..., description="Identifier a study references via execution.data_requirements.dataset_id")
    instrument_id: str = Field(..., description="NautilusTrader instrument id, e.g. NQ.XCME")
    catalog_rel_path: str = Field(..., description="Repo-relative path to the physical ParquetDataCatalog (legacy/transitional resolution only; ignored once catalog_roots are configured)")
    logical_digest: Optional[str] = Field(
        None,
        description="Content digest of the immutable catalog (research_workflow.roots.compute_catalog_digest). "
                    "This is the dataset's scientific identity; machine-local roots are matched against it.",
    )
    digest_method: Optional[str] = Field(None, description="How logical_digest was computed (research_workflow.roots.DIGEST_METHOD)")
    provenance: DatasetProvenance = Field(default_factory=DatasetProvenance)
    streams: Dict[str, StreamSpec] = Field(..., description="Per-timeframe stream contracts, keyed '1s'/'1m'/'5m'")
    coverage: DatasetCoverage

    @field_validator("streams")
    @classmethod
    def validate_stream_keys(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        unknown = set(v.keys()) - _ALLOWED_STREAM_KEYS
        if unknown:
            raise ValueError(
                f"Unknown stream key(s) {sorted(unknown)}; allowed keys are {sorted(_ALLOWED_STREAM_KEYS)}"
            )
        missing = _REQUIRED_EXTERNAL_STREAM_KEYS - set(v.keys())
        if missing:
            raise ValueError(f"streams is missing required key(s) {sorted(missing)}")
        for key in _REQUIRED_EXTERNAL_STREAM_KEYS:
            if v[key].source != "external":
                raise ValueError(f"stream '{key}' must be source: external")
        return v


def load_dataset_spec(path: Path) -> DatasetSpec:
    """Parses and validates a DatasetSpec authority YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return DatasetSpec.model_validate(raw)
