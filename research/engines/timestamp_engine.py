"""Timestamp and Bar-Availability Contract Engine.
================================================
Measures and validates empirical Databento -> NautilusTrader timestamp contracts
from actual catalog parquet data files.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


class CatalogTimestampSemanticError(RuntimeError):
    """Raised when measured catalog timestamp semantics violate causal contracts."""
    pass


class PreservedTimestampEvidenceReuseError(CatalogTimestampSemanticError):
    """A sealed timestamp contract cannot safely be reused for this recompile."""


EXPECTED_TIMEFRAME_DELTAS_NS = {
    "1-SECOND": 1_000_000_000,
    "1-MINUTE": 60_000_000_000,
    "3-MINUTE": 180_000_000_000,
    "5-MINUTE": 300_000_000_000,
}


def measure_catalog_bar_semantics(
    catalog_path: Path,
    sample_rows: int = 1000,
) -> Dict[str, Any]:
    """Empirically samples catalog parquet files and verifies ts_init - ts_event == bar_duration_ns."""
    bar_dir = catalog_path / "data" / "bar" if (catalog_path / "data" / "bar").exists() else catalog_path
    if not bar_dir.exists():
        # Fallback to searching data/catalog
        cand_dirs = list(Path("data/catalog").glob(f"*{catalog_path.name}*/data/bar"))
        if cand_dirs:
            bar_dir = cand_dirs[0]

    measurements: Dict[str, Any] = {}

    if not bar_dir.exists():
        return {
            "status": "UNMEASURED_CATALOG_NOT_FOUND",
            "catalog_path": str(catalog_path),
            "measurements": {},
        }

    for type_dir in sorted(bar_dir.iterdir()):
        if not type_dir.is_dir():
            continue
        parquet_files = list(type_dir.glob("*.parquet"))
        if not parquet_files:
            continue

        sample_file = parquet_files[0]
        try:
            df = pd.read_parquet(sample_file, columns=["ts_event", "ts_init"])
            if len(df) > sample_rows:
                df = df.head(sample_rows)
            deltas = (df["ts_init"] - df["ts_event"]).unique().tolist()

            # Determine expected delta from directory name
            expected_delta = None
            for tf_key, exp_d in EXPECTED_TIMEFRAME_DELTAS_NS.items():
                if tf_key in type_dir.name.upper():
                    expected_delta = exp_d
                    break

            is_valid = (expected_delta is not None) and (deltas == [expected_delta])
            measurements[type_dir.name] = {
                "sample_count": len(df),
                "expected_delta_ns": expected_delta,
                "observed_deltas_ns": deltas,
                "pass": is_valid,
            }
            if not is_valid and expected_delta is not None:
                raise CatalogTimestampSemanticError(
                    f"CATALOG_TIMESTAMP_VIOLATION: {type_dir.name} observed deltas {deltas} != expected {expected_delta}"
                )
        except Exception as exc:
            if isinstance(exc, CatalogTimestampSemanticError):
                raise
            measurements[type_dir.name] = {"error": str(exc), "pass": False}

    return {
        "status": "MEASURED",
        "catalog_path": str(catalog_path),
        "measurements": measurements,
    }


def resolve_catalog_for_symbol(instrument_symbol: str) -> str:
    """Resolves a product symbol to its catalog, using the runtime's own registry.

    ``PRODUCT_CATALOGS`` in ``backtests/nt_runtime/data_plan.py`` is what actually decides
    which catalog a run loads. Compiling the timestamp contract from a *different* source
    of truth is how an ES study came to carry NQ measurements: the previous signature
    accepted ``instrument_symbol`` and then ignored it, defaulting the catalog path to
    ``data/catalog/NQ_v0_2020_2026`` for every instrument.
    """
    from backtests.nt_runtime.data_plan import PRODUCT_CATALOGS

    sym = (instrument_symbol or "").strip().upper()
    if sym not in PRODUCT_CATALOGS:
        raise CatalogTimestampSemanticError(
            f"UNSUPPORTED_INSTRUMENT: no catalog registered for {instrument_symbol!r}. "
            f"Known products: {sorted(PRODUCT_CATALOGS)}. A timestamp contract must be "
            f"measured on the instrument's own catalog, never on another product's."
        )
    return PRODUCT_CATALOGS[sym]["catalog_rel_path"]


def compile_timestamp_contract(
    instrument_symbol: str = "NQ",
    catalog_path: Optional[str] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Compiles the authoritative timestamp and availability contract backed by empirical measurements.

    The catalog is resolved *from the instrument* unless one is passed explicitly.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]

    if catalog_path is None:
        catalog_path = resolve_catalog_for_symbol(instrument_symbol)

    cat_p = (repo_root / catalog_path).resolve()
    measurements = measure_catalog_bar_semantics(cat_p)

    # An instrument contract must carry its own instrument's evidence. Measuring the
    # right catalog is not enough if the measurement came back empty -- that would leave
    # the contract asserting a timestamp invariant nothing had checked.
    measured_types = [k for k in measurements.get("measurements", {})]
    sym = (instrument_symbol or "").strip().upper()
    foreign = [k for k in measured_types if not k.upper().startswith(f"{sym}.")]
    if foreign:
        raise CatalogTimestampSemanticError(
            f"FOREIGN_INSTRUMENT_EVIDENCE: timestamp contract for {sym} would record "
            f"measurements for {foreign}. Evidence must come from the study's own instrument."
        )
    if measurements.get("status") != "MEASURED" or not measured_types:
        raise CatalogTimestampSemanticError(
            f"TIMESTAMP_EVIDENCE_UNMEASURED: no bar-timestamp measurements could be taken for "
            f"{sym} at {cat_p} (status={measurements.get('status')}). A contract may not assert "
            f"an availability invariant it never measured."
        )

    contract = {
        "source": "databento_glbx_mdp3",
        "instrument_symbol": sym,
        "measured_catalog_rel_path": catalog_path,
        "raw_timestamp_semantic": "OPEN_STAMPED",
        "raw_index_field": "ts_event",
        "timezone": "UTC",
        "offline_research_aggregation": {
            "pandas_rule": "resample(rule, label='right', closed='left')",
            "semantic": "CLOSE_STAMPED",
        },
        "nautilus_catalog": {
            "ts_event_semantic": "OPEN_STAMPED",
            "ts_init_semantic": "CLOSE_STAMPED",
            "causal_dispatch_field": "ts_init",
            "availability_invariant": "if nt_ts_event_semantic == 'OPEN_STAMPED': ts_init - ts_event == bar_duration_ns",
            "timeframe_deltas_ns": EXPECTED_TIMEFRAME_DELTAS_NS,
            "empirical_measurement": measurements,
        },
        "causal_rule": "FULL_BAR_OHLCV_AVAILABLE_ONLY_AT_INTERVAL_CLOSE",
    }
    return contract


def preserved_timestamp_contract_for_modeling_recompile(
    study_dir: Path,
    new_spec: Any,
) -> Dict[str, Any]:
    """Authenticate a sealed timestamp contract when an isolated worktree lacks data.

    This is intentionally not a general ``catalog unavailable`` fallback.  It is only
    available to an existing sealed study whose current edit is limited to Phase-D
    modeling declarations.  Collection/data/instrument/timestamp edits, a missing
    or altered sealed predecessor, and every new study still require a live empirical
    measurement through :func:`compile_timestamp_contract`.
    """
    study = Path(study_dir).resolve()
    compiled_path = study / "compiled_study.json"
    frozen_path = study / "audit" / "frozen_execution_manifest.json"
    seal_path = study / "artifacts" / "preexec_audit_seal.json"
    timestamp_path = study / "config" / "timestamp_contract.json"
    required = (compiled_path, frozen_path, seal_path, timestamp_path)
    if not all(path.is_file() for path in required):
        raise PreservedTimestampEvidenceReuseError("PRESERVED_TIMESTAMP_REUSE_EVIDENCE_MISSING")
    compiled_bytes = compiled_path.read_bytes()
    compiled_sha = hashlib.sha256(compiled_bytes).hexdigest()
    try:
        compiled = json.loads(compiled_bytes)
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        prior = json.loads(timestamp_path.read_text(encoding="utf-8"))
        from research.schemas.study_spec import StudySpec
        old_spec = StudySpec.model_validate(compiled["spec"])
    except Exception as exc:
        raise PreservedTimestampEvidenceReuseError("PRESERVED_TIMESTAMP_REUSE_EVIDENCE_MALFORMED") from exc
    if old_spec.compute_sha256() != compiled.get("spec_sha256"):
        raise PreservedTimestampEvidenceReuseError("PRESERVED_TIMESTAMP_REUSE_PRIOR_SPEC_HASH_INVALID")

    # Idempotent-recompile path.  The first authenticated modeling-only transition writes
    # ``evidence_provenance`` into ``config/timestamp_contract.json`` and leaves
    # ``compiled_study.json`` as an already-transitioned Phase-D descendant of the sealed
    # predecessor.  Every subsequent compile in the same lifecycle (PREPARE re-compiles,
    # readiness re-compiles) then re-enters this function with a compiled_study.json that
    # no longer byte-matches the frozen/sealed predecessor, and with a frozen manifest that
    # PREPARE has legitimately re-written.  Re-authenticate transitively against the still
    # sealed predecessor recorded in ``preexec_audit_seal.json`` (immutable until the
    # causal-audit acceptance re-seals), and require that study.yaml has not drifted past
    # the spec that the first transition authenticated.
    _prov = (prior.get("evidence_provenance") or {}) if isinstance(prior, dict) else {}
    _sealed_compiled_sha = (seal.get("file_hashes") or {}).get("study:compiled_study.json")
    idempotent_recompile = (
        _prov.get("mode") == "PRESERVED_SEALED_MODELING_ONLY_REUSE"
        and _prov.get("prior_compiled_study_sha256") == _sealed_compiled_sha
        and _prov.get("sealed_execution_composite_sha256") == seal.get("composite_seal_hash")
        and (compiled.get("spec") or {}).get("operation", {}).get("kind") == "phase_d_modeling"
        and new_spec.compute_sha256() == compiled.get("spec_sha256")
    )

    if not idempotent_recompile:
        if frozen.get("compiled_study_sha256") != compiled_sha:
            raise PreservedTimestampEvidenceReuseError("PRESERVED_TIMESTAMP_REUSE_FROZEN_COMPILED_BINDING_MISMATCH")
        if seal.get("composite_seal_hash") != frozen.get("frozen_execution_composite_sha256"):
            raise PreservedTimestampEvidenceReuseError("PRESERVED_TIMESTAMP_REUSE_SEAL_COMPOSITE_MISMATCH")
        if _sealed_compiled_sha != compiled_sha:
            raise PreservedTimestampEvidenceReuseError("PRESERVED_TIMESTAMP_REUSE_SEAL_COMPILED_BINDING_MISMATCH")

    old = old_spec.model_dump(mode="json")
    new = new_spec.model_dump(mode="json")
    # Only model declarations and the corresponding declared study-local driver may
    # change.  The rest of the executable/collection authority compares exactly.
    old_model, new_model = old.pop("model", None), new.pop("model", None)
    if old_model is None or new_model is None:
        raise PreservedTimestampEvidenceReuseError("PRESERVED_TIMESTAMP_REUSE_MODEL_DECLARATION_MISSING")
    old_execution, new_execution = old.get("execution") or {}, new.get("execution") or {}
    old_drivers = set(old_execution.pop("modeling_driver_relpaths", []) or [])
    new_drivers = set(new_execution.pop("modeling_driver_relpaths", []) or [])
    if not new_drivers or not old_drivers <= new_drivers:
        raise PreservedTimestampEvidenceReuseError("PRESERVED_TIMESTAMP_REUSE_DRIVER_DECLARATION_INVALID")
    old_bespoke, new_bespoke = old.get("bespoke") or {}, new.get("bespoke") or {}
    old_scope = set(old_bespoke.pop("custom_scope", []) or [])
    new_scope = set(new_bespoke.pop("custom_scope", []) or [])
    if not old_scope <= new_scope or not (new_scope - old_scope) <= new_drivers:
        raise PreservedTimestampEvidenceReuseError("PRESERVED_TIMESTAMP_REUSE_CUSTOM_SCOPE_CHANGED")
    old_operation, new_operation = old.get("operation") or {}, new.get("operation") or {}
    exact_phase_d_transition = (
        old_operation.get("kind") == "train_evaluate"
        and new_operation.get("kind") == "phase_d_modeling"
        and {k: v for k, v in old_operation.items() if k != "kind"}
        == {k: v for k, v in new_operation.items() if k != "kind"}
    )
    if exact_phase_d_transition:
        # The only allowed non-modeling declaration delta is the existing study's
        # Phase-D mode transition, needed to compile its literal modeling outputs.
        old["operation"] = new_operation
    elif old_operation != new_operation:
        raise PreservedTimestampEvidenceReuseError("PRESERVED_TIMESTAMP_REUSE_OPERATION_CHANGED")
    if old != new:
        raise PreservedTimestampEvidenceReuseError("PRESERVED_TIMESTAMP_REUSE_NONMODELING_CONTRACT_CHANGED")

    symbol = new_spec.instrument.symbol.upper()
    if prior.get("instrument_symbol") != symbol:
        raise PreservedTimestampEvidenceReuseError("PRESERVED_TIMESTAMP_REUSE_INSTRUMENT_MISMATCH")
    expected_catalog = resolve_catalog_for_symbol(symbol)
    if prior.get("measured_catalog_rel_path") != expected_catalog:
        raise PreservedTimestampEvidenceReuseError("PRESERVED_TIMESTAMP_REUSE_CATALOG_AUTHORITY_MISMATCH")
    nt = prior.get("nautilus_catalog") or {}
    measurement = nt.get("empirical_measurement") or {}
    measurements = measurement.get("measurements") or {}
    if (measurement.get("status") != "MEASURED" or not measurements
            or any(not record.get("pass") for record in measurements.values())
            or any(not str(name).upper().startswith(symbol + ".") for name in measurements)):
        raise PreservedTimestampEvidenceReuseError("PRESERVED_TIMESTAMP_REUSE_MEASUREMENT_INVALID")
    semantic = (prior.get("raw_timestamp_semantic"), prior.get("raw_index_field"),
                nt.get("ts_event_semantic"), nt.get("ts_init_semantic"), nt.get("causal_dispatch_field"),
                prior.get("causal_rule"))
    if semantic != ("OPEN_STAMPED", "ts_event", "OPEN_STAMPED", "CLOSE_STAMPED", "ts_init", "FULL_BAR_OHLCV_AVAILABLE_ONLY_AT_INTERVAL_CLOSE"):
        raise PreservedTimestampEvidenceReuseError("PRESERVED_TIMESTAMP_REUSE_SEMANTICS_INVALID")

    reused = copy.deepcopy(prior)
    reused["evidence_provenance"] = {
        "mode": "PRESERVED_SEALED_MODELING_ONLY_REUSE",
        "newly_measured": False,
        # Anchored to the sealed predecessor (immutable until the causal-audit re-seal),
        # never to the live compiled bytes -- otherwise an idempotent recompile would
        # rewrite its own anchor and break the next recompile's re-authentication.
        "prior_compiled_study_sha256": _sealed_compiled_sha,
        "prior_spec_sha256": _prov.get("prior_spec_sha256") if idempotent_recompile else compiled["spec_sha256"],
        "frozen_execution_composite_sha256": frozen.get("frozen_execution_composite_sha256"),
        "sealed_execution_composite_sha256": seal["composite_seal_hash"],
        "idempotent_recompile": bool(idempotent_recompile),
    }
    return reused


def compile_with_timestamp_evidence_adapter(compiler: Any, spec: Any, study_dir: Path) -> Any:
    """Compile normally, then apply the sole authenticated missing-catalog fallback.

    Both the study factory and the lifecycle compiler call this one adapter.  Keeping
    it here prevents the two entrypoints from diverging into subtly different
    timestamp-evidence policies.
    """
    try:
        return compiler.compile(spec)
    except CatalogTimestampSemanticError:
        # Flip studies have no bespoke modeling-only escape hatch.  A timestamp
        # failure for them remains the original failure, not a reuse opportunity.
        if getattr(getattr(spec, "study", None), "type", None) != "bespoke":
            raise
        preserved = preserved_timestamp_contract_for_modeling_recompile(study_dir, spec)
        return compiler.compile(spec, timestamp_contract_override=preserved)
