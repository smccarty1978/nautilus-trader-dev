"""Data Plan Resolver for NautilusTrader Execution.
==================================================
Standardizes catalog resolution, bar types, and timestamp contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from backtests.nt_runtime.compiled_study_loader import CompiledStudyData


class UnauthorizedExecutionDomainError(ValueError):
    """Raised when execution date domain violates study chronology rules."""
    pass


def resolve_authorized_dates(compiled_data) -> Optional[List[str]]:
    """Reads a study's exact authorized calendar dates, if it declares any.

    Declared under ``execution.data_requirements.authorized_dates`` as ``YYYY-MM-DD``
    strings. That location is deliberate: ``data_requirements`` is an existing free-form
    field on ``ExecutionSpec``, so a study that sets it changes only *its own*
    ``spec_sha256``. Adding a new top-level schema field would instead alter
    ``StudySpec.compute_sha256`` for every study in the repository -- because
    ``compute_sha256`` hashes ``model_dump(exclude_none=False)``, an unset optional field
    still appears -- marking every existing ``compiled_study.json`` stale and
    invalidating seals and audits far outside the scope of a date-bounding change.

    Returns ``None`` when the study declares no exact dates, in which case the
    pre-existing year-level chronology gates remain the only date authority.
    """
    reqs = getattr(compiled_data.spec.execution, "data_requirements", None) or {}
    dates = reqs.get("authorized_dates")
    if not dates:
        return None
    if not isinstance(dates, list) or not all(isinstance(d, str) for d in dates):
        raise UnauthorizedExecutionDomainError(
            "MALFORMED_AUTHORIZED_DATES: execution.data_requirements.authorized_dates must be "
            "a list of 'YYYY-MM-DD' strings"
        )
    for d in dates:
        try:
            pd.Timestamp(d)
        except Exception as err:
            raise UnauthorizedExecutionDomainError(
                f"MALFORMED_AUTHORIZED_DATES: {d!r} is not a valid date ({err})"
            )
    return sorted(dates)


def enforce_authorized_dates(
    compiled_data,
    start_date: str,
    end_date: str,
) -> Optional[List[str]]:
    """Refuses any run window containing a date the study did not explicitly authorize.

    Year-level chronology cannot express "these three September days". The acceptance
    request intended 2024-09-03/04/05 while ``train: [2024]`` authorized all of 2024, and
    a reviewer reading the contract had no way to tell the intended scope from the
    permitted one. This closes that gap: when exact dates are declared, every calendar day
    in the requested window must appear among them.
    """
    authorized = resolve_authorized_dates(compiled_data)
    if authorized is None:
        return None

    requested = pd.date_range(start=start_date, end=end_date, freq="D")
    requested_strs = [d.strftime("%Y-%m-%d") for d in requested]
    unauthorized = [d for d in requested_strs if d not in set(authorized)]
    if unauthorized:
        raise UnauthorizedExecutionDomainError(
            f"UNAUTHORIZED_EXECUTION_DATE: requested window [{start_date} to {end_date}] "
            f"includes {unauthorized}, which this study does not authorize. "
            f"Authorized dates: {authorized}"
        )
    return authorized


PRODUCT_CATALOGS: Dict[str, Dict[str, Any]] = {
    "NQ": {
        "symbol": "NQ",
        "venue": "XCME",
        "instrument_id": "NQ.XCME",
        "multiplier": "20.0",
        "price_increment": "0.25",
        "catalog_rel_path": "data/catalog/NQ_v0_2020_2026",
        "bar_type_1s": "NQ.XCME-1-SECOND-LAST-EXTERNAL",
        "bar_type_1m": "NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        "raw_timestamp_semantic": "OPEN_STAMPED",
        "ts_init_delta_1s_ns": 1_000_000_000,
        "ts_init_delta_1m_ns": 60_000_000_000,
    },
    "ES": {
        "symbol": "ES",
        "venue": "XCME",
        "instrument_id": "ES.XCME",
        "multiplier": "50.0",
        "price_increment": "0.25",
        "catalog_rel_path": "data/catalog/ES_v0_2020_2026",
        "bar_type_1s": "ES.XCME-1-SECOND-LAST-EXTERNAL",
        "bar_type_1m": "ES.XCME-1-MINUTE-LAST-EXTERNAL",
        "raw_timestamp_semantic": "OPEN_STAMPED",
        "ts_init_delta_1s_ns": 1_000_000_000,
        "ts_init_delta_1m_ns": 60_000_000_000,
    },
    "YM": {
        "symbol": "YM",
        "venue": "XCBT",
        "instrument_id": "YM.XCBT",
        "multiplier": "5.0",
        "price_increment": "1",
        "catalog_rel_path": "data/catalog/YM_v0_2024",
        "bar_type_1s": "YM.XCBT-1-SECOND-LAST-EXTERNAL",
        "bar_type_1m": "YM.XCBT-1-MINUTE-LAST-EXTERNAL",
        "raw_timestamp_semantic": "OPEN_STAMPED",
        "ts_init_delta_1s_ns": 1_000_000_000,
        "ts_init_delta_1m_ns": 60_000_000_000,
    },
}


@dataclass(frozen=True)
class DataPlan:
    symbol: str
    venue: str
    instrument_id: str
    multiplier: str
    price_increment: str
    catalog_path: Path
    bar_type_1s: str
    bar_type_1m: str
    start_dt: pd.Timestamp
    end_dt: pd.Timestamp
    warmup_days: int
    warmup_start_dt: pd.Timestamp
    raw_timestamp_semantic: str
    ts_init_delta_1s_ns: int
    ts_init_delta_1m_ns: int


def resolve_catalog_plan(
    symbol: str,
    start_date: str,
    end_date: str,
    warmup_days: int = 5,
    repo_root: Optional[Path] = None,
) -> DataPlan:
    """Resolves the **generic** half of a data plan: catalog, instrument, bar types, warmup.

    This function is deliberately free of study governance. It performs no
    chronology, prohibited-year, authorized-domain, or OOS/DEV partition checks,
    because those rules belong to the study contract that declares them and must
    not leak into an unrelated backtest. Use :func:`resolve_data_plan` when a
    compiled study contract governs the run.

    Parameters
    ----------
    symbol : str
        Product symbol (e.g. ``"NQ"``). Case-insensitive.
    start_date, end_date : str
        Inclusive ``YYYY-MM-DD`` run window bounds.
    warmup_days : int
        Calendar days of lead-in data loaded before ``start_date``.
    repo_root : Path, optional
        Repository root used to resolve the catalog path.

    Returns
    -------
    DataPlan
        The same frozen structure consumed by ``build_engine``.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]

    symbol = symbol.upper()
    if symbol not in PRODUCT_CATALOGS:
        raise ValueError(f"Unsupported product '{symbol}'. Supported: {list(PRODUCT_CATALOGS.keys())}")

    prod = PRODUCT_CATALOGS[symbol]
    catalog_path = (repo_root / prod["catalog_rel_path"]).resolve()
    if not catalog_path.exists():
        # Fallback to local directory if relative
        catalog_path = Path(prod["catalog_rel_path"]).resolve()

    start_dt = pd.Timestamp(f"{start_date} 00:00:00", tz="UTC")
    end_dt = pd.Timestamp(f"{end_date} 23:59:59.999999999", tz="UTC")
    if start_dt > end_dt:
        raise ValueError(f"start_date ({start_date}) cannot be after end_date ({end_date})")

    warmup_start_dt = start_dt - pd.Timedelta(days=warmup_days)

    return DataPlan(
        symbol=symbol,
        venue=prod["venue"],
        instrument_id=prod["instrument_id"],
        multiplier=prod["multiplier"],
        price_increment=prod["price_increment"],
        catalog_path=catalog_path,
        bar_type_1s=prod["bar_type_1s"],
        bar_type_1m=prod["bar_type_1m"],
        start_dt=start_dt,
        end_dt=end_dt,
        warmup_days=warmup_days,
        warmup_start_dt=warmup_start_dt,
        raw_timestamp_semantic=prod["raw_timestamp_semantic"],
        ts_init_delta_1s_ns=prod["ts_init_delta_1s_ns"],
        ts_init_delta_1m_ns=prod["ts_init_delta_1m_ns"],
    )


def resolve_data_plan(
    compiled_data: CompiledStudyData,
    start_date: str,
    end_date: str,
    warmup_days: int = 5,
    repo_root: Optional[Path] = None,
) -> DataPlan:
    """Resolves data plan and validates date domain against study chronology.

    Study-bound wrapper: delegates generic catalog/instrument/warmup resolution to
    :func:`resolve_catalog_plan`, then applies this study's governance gates
    (prohibited years, authorized domain, DEV/OOS partition locks, warmup domain).
    Behaviour is unchanged from the pre-split implementation.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]

    symbol = compiled_data.spec.instrument.symbol.upper()

    # Generic half (raises identically for unsupported product / inverted dates).
    plan = resolve_catalog_plan(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        warmup_days=warmup_days,
        repo_root=repo_root,
    )
    start_dt = plan.start_dt
    end_dt = plan.end_dt

    # Chronology validation
    chrono = compiled_data.spec.chronology
    prohibited_years = set(chrono.prohibited or [])
    authorized_years = set((chrono.train or []) + (chrono.dev or []) + (chrono.diagnostic or []))

    run_years = set(range(start_dt.year, end_dt.year + 1))

    # 1. Prohibited check
    overlap_prohib = run_years & prohibited_years
    if overlap_prohib:
        raise UnauthorizedExecutionDomainError(
            f"UNAUTHORIZED_EXECUTION_DOMAIN: Requested dates [{start_date} to {end_date}] "
            f"include prohibited years {sorted(overlap_prohib)}"
        )

    # 2. Authorized domain check
    if authorized_years:
        unauthorized = run_years - authorized_years
        if unauthorized:
            raise UnauthorizedExecutionDomainError(
                f"UNAUTHORIZED_EXECUTION_DOMAIN: Requested dates [{start_date} to {end_date}] "
                f"fall outside authorized study chronology (authorized: {sorted(authorized_years)}, "
                f"requested contains: {sorted(unauthorized)})"
            )

    # 2b. Exact authorized-date check. Runs after the year gates because a date outside
    # the authorized years should still be reported as a chronology violation first.
    enforce_authorized_dates(compiled_data, start_date, end_date)

    # 3. OOS / Dev Phase Lock check
    dev_years = set(chrono.dev or [])
    overlap_dev = run_years & dev_years
    if overlap_dev:
        study_dir = compiled_data.study_dir
        try:
            from scripts.generate_oos_unlock import verify_oos_unlock_token
            for yr in sorted(overlap_dev):
                if not verify_oos_unlock_token(study_dir, yr):
                    raise UnauthorizedExecutionDomainError(
                        f"OOS_LOCKED_UNTIL_FREEZE: Year {yr} is in dev/OOS partition. "
                        f"Access is locked until artifacts/oos_unlock.json is generated via verified dependency chain "
                        f"(phase0 -> train_collection -> frozen_feature_manifest -> preprocessing -> model_manifest)."
                    )
        except ImportError as err:
            raise UnauthorizedExecutionDomainError(
                f"OOS_AUTHORIZATION_DEPENDENCY_MISSING: Failed to import OOS verification module: {err}"
            )

    # 4. Warmup Domain Authorization & Validation
    warmup_start_dt = plan.warmup_start_dt
    warmup_years = set(range(warmup_start_dt.year, start_dt.year + 1))

    # Warmup prohibited check
    warmup_overlap_prohib = warmup_years & prohibited_years
    if warmup_overlap_prohib:
        raise UnauthorizedExecutionDomainError(
            f"UNAUTHORIZED_WARMUP_DOMAIN: Warmup start year {sorted(warmup_overlap_prohib)} falls in prohibited years {sorted(prohibited_years)}"
        )

    # Warmup DEV/OOS partition lock check
    warmup_overlap_dev = (warmup_years & dev_years) - overlap_dev
    if warmup_overlap_dev:
        study_dir = compiled_data.study_dir
        try:
            from scripts.generate_oos_unlock import verify_oos_unlock_token
            for yr in sorted(warmup_overlap_dev):
                if not verify_oos_unlock_token(study_dir, yr):
                    raise UnauthorizedExecutionDomainError(
                        f"UNAUTHORIZED_WARMUP_DOMAIN: Warmup window [{warmup_start_dt.strftime('%Y-%m-%d')} to {start_date}] "
                        f"enters locked DEV year {yr} without authorized OOS unlock token."
                    )
        except ImportError as err:
            raise UnauthorizedExecutionDomainError(
                f"OOS_AUTHORIZATION_DEPENDENCY_MISSING: Cannot verify warmup DEV access: {err}"
            )

    return plan
