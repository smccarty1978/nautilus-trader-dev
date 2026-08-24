"""Run Plan & Stage Resolver for NautilusTrader Execution.
==========================================================
Manages bounded execution stages and prevents automated stage expansion.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional, Tuple, Union

import pandas as pd

from backtests.nt_runtime.compiled_study_loader import CompiledStudyData


class RunStage(str, enum.Enum):
    FIXTURE = "fixture"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    FULL = "full"


@dataclass(frozen=True)
class RunPlan:
    stage: RunStage
    start_date: str
    end_date: str
    is_bounded: bool = True
    auto_expand: bool = False


def resolve_run_plan(
    compiled_data: CompiledStudyData,
    stage: Union[str, RunStage],
    reference_date: Optional[str] = None,
    authorized_dates: Optional[list[str]] = None,
) -> RunPlan:
    """Resolves bounded date ranges for a requested execution stage."""
    if isinstance(stage, str):
        stage_enum = RunStage(stage.lower())
    else:
        stage_enum = stage

    chrono = compiled_data.spec.chronology
    train_years = sorted(chrono.train or [])
    auth_years = sorted((chrono.train or []) + (chrono.dev or []))
    default_year = train_years[-1] if train_years else (auth_years[-1] if auth_years else 2023)

    # When a study declares exact authorized dates, they are the default reference too.
    # Otherwise a bounded study would still default to `<year>-03-03` and be refused
    # downstream for a date the caller never chose.
    from backtests.nt_runtime.data_plan import resolve_authorized_dates

    authorized_dates = authorized_dates or resolve_authorized_dates(compiled_data)

    if reference_date is None:
        if authorized_dates:
            ref_dt = pd.Timestamp(authorized_dates[0], tz="UTC")
        else:
            ref_dt = pd.Timestamp(f"{default_year}-03-03", tz="UTC")
    else:
        ref_dt = pd.Timestamp(reference_date, tz="UTC")

    if stage_enum == RunStage.FIXTURE:
        # Single day bounded window
        start_date = ref_dt.strftime("%Y-%m-%d")
        end_date = ref_dt.strftime("%Y-%m-%d")
    elif stage_enum == RunStage.DAY:
        start_date = ref_dt.strftime("%Y-%m-%d")
        end_date = ref_dt.strftime("%Y-%m-%d")
    elif stage_enum == RunStage.WEEK:
        start_date = ref_dt.strftime("%Y-%m-%d")
        end_date = (ref_dt + pd.Timedelta(days=4)).strftime("%Y-%m-%d")
    elif stage_enum == RunStage.MONTH:
        start_date = ref_dt.replace(day=1).strftime("%Y-%m-%d")
        # End of month
        end_date = (ref_dt.replace(day=1) + pd.offsets.MonthEnd(1)).strftime("%Y-%m-%d")
    elif stage_enum == RunStage.FULL:
        if authorized_dates:
            # 'full' for a date-bounded study means its authorized dates, not its years.
            # Expanding to a whole calendar year would silently exceed the authorization.
            start_date = authorized_dates[0]
            end_date = authorized_dates[-1]
        elif train_years:
            start_date = f"{train_years[0]}-01-01"
            end_date = f"{train_years[-1]}-12-31"
        elif auth_years:
            start_date = f"{auth_years[0]}-01-01"
            end_date = f"{auth_years[-1]}-12-31"
        else:
            start_date = f"{default_year}-01-01"
            end_date = f"{default_year}-12-31"
    else:
        raise ValueError(f"Unknown run stage: {stage}")

    return RunPlan(
        stage=stage_enum,
        start_date=start_date,
        end_date=end_date,
        is_bounded=True,
        auto_expand=False,
    )
