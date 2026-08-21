"""Reusable analysis harness (phases A1–A4).

Built to the contract in `ANALYSIS_HARNESS_A0_CONTRACT.md`. Deliberately independent
of the backtest harness and the collector runtime: this package imports neither, so
it cannot perturb the collector's sealed execution closure.

    A1  loader.py    validated, identity-bound collection loading
    A2  spec.py      analysis specification schema and identity
        slices.py    recurring slices
        metrics.py   canonical metrics with safe empty/one-class/NaN behaviour
    A3  modeling.py  reproducible model wrappers with full provenance
    A4  reporting.py standard tables and the compact analysis_context.json

Caller obligations that the package cannot enforce for you
----------------------------------------------------------
* **`assert_single_study(collections)` before pooling.** Cross-study pooling is
  prohibited (A0 §5) because two studies' chronologies may disagree — one study's
  locked DEV year can be another's TRAIN. There is no multi-collection entry point
  yet, so any code that loads more than one `Collection` must call this itself,
  before the frames are concatenated.
* **`validate_collection(collection, spec)` with the spec you intend to use.**
  `get_features_targets_metadata` refuses a report produced under a different spec
  (or under none), because a spec-less report never ran the seal, OOS-unlock,
  partition-mixing or identity checks.
"""

from research.analysis.errors import ALL_FAILURE_CODES, AnalysisError  # noqa: F401
from research.analysis.identity import CollectionIdentity, canonical_sha256  # noqa: F401
from research.analysis.loader import (  # noqa: F401
    Collection,
    ValidationReport,
    assert_single_study,
    get_features_targets_metadata,
    load_collection,
    validate_collection,
    write_dataset_identity,
)
from research.analysis.spec import AnalysisSpec, load_analysis_spec, parse_analysis_spec  # noqa: F401

__all__ = [
    "ALL_FAILURE_CODES", "AnalysisError", "CollectionIdentity", "canonical_sha256",
    "Collection", "ValidationReport", "load_collection", "validate_collection",
    "get_features_targets_metadata", "write_dataset_identity", "assert_single_study",
    "AnalysisSpec", "load_analysis_spec", "parse_analysis_spec",
]
