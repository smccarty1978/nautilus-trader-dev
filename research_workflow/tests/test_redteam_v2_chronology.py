"""Red-team packet A / A1 -- requested execution years must be a non-empty subset of the
authorized chronology ROLE for the stage, never broader (``research_workflow.lifecycle_v2.
authorized_years``). TRAIN stages (collection/reconcile/merge/fit) may only touch
``plan.chronology.train``; OOS stages (oos/analyze) may only touch ``plan.chronology.dev``
(``"dev"`` is an alias period name for "oos"); a prohibited year is never executable under
either role; an omitted ``--years`` resolves to exactly the role's years.

Pure-function tests: no bars, no catalog, no controller run.
"""
from __future__ import annotations

import pytest

from research_workflow.lifecycle_v2 import LifecycleV2Error, authorized_years

PLAN = {"chronology": {"train": [2021, 2022, 2023], "dev": [2024], "prohibited": [2025]}}


# ---------------------------------------------------------------------------
# core role-boundary rejections
# ---------------------------------------------------------------------------

def test_train_request_for_an_undeclared_year_rejects():
    with pytest.raises(LifecycleV2Error, match="YEARS_NOT_AUTHORIZED"):
        authorized_years(PLAN, "train", [2024])  # 2024 belongs to dev, not train


def test_oos_request_for_a_train_year_rejects():
    with pytest.raises(LifecycleV2Error, match="YEARS_NOT_AUTHORIZED"):
        authorized_years(PLAN, "oos", [2022])  # 2022 belongs to train, not dev


def test_prohibited_year_rejects_for_train():
    with pytest.raises(LifecycleV2Error, match="YEARS_NOT_AUTHORIZED"):
        authorized_years(PLAN, "train", [2025])


def test_prohibited_year_rejects_for_oos():
    plan = {"chronology": {"train": [2021], "dev": [2024, 2025], "prohibited": [2025]}}
    with pytest.raises(LifecycleV2Error, match="YEARS_NOT_AUTHORIZED"):
        authorized_years(plan, "oos", [2025])


def test_prohibited_year_mixed_with_a_valid_year_still_rejects_the_whole_request():
    plan = {"chronology": {"train": [2021, 2022], "dev": [], "prohibited": [2022]}}
    with pytest.raises(LifecycleV2Error, match="YEARS_NOT_AUTHORIZED"):
        authorized_years(plan, "train", [2021, 2022])


# ---------------------------------------------------------------------------
# narrowing is fine, expansion never is
# ---------------------------------------------------------------------------

def test_valid_subset_passes_and_returns_exactly_the_subset_sorted():
    assert authorized_years(PLAN, "train", [2023, 2021]) == [2021, 2023]


def test_omitted_years_equals_role_years_exactly():
    assert authorized_years(PLAN, "train", None) == [2021, 2022, 2023]
    assert authorized_years(PLAN, "oos", None) == [2024]
    assert authorized_years(PLAN, "dev", None) == [2024]   # dev is an alias period name


def test_empty_requested_list_rejects():
    with pytest.raises(LifecycleV2Error, match="YEARS_NOT_AUTHORIZED"):
        authorized_years(PLAN, "train", [])


# ---------------------------------------------------------------------------
# adjacent bypass: dup / str-typed years cannot expand the request
# ---------------------------------------------------------------------------

def test_duplicate_and_str_years_normalize_and_still_cannot_expand():
    assert authorized_years(PLAN, "train", ["2023", 2023, "2021"]) == [2021, 2023]
    with pytest.raises(LifecycleV2Error, match="YEARS_NOT_AUTHORIZED"):
        authorized_years(PLAN, "train", ["2023", "2025"])  # 2025 is prohibited even as a string


# ---------------------------------------------------------------------------
# stale experiment_authorization.json artifact
# ---------------------------------------------------------------------------

def test_stale_authorization_artifact_rejects_even_a_valid_request():
    authorization = {"train_years": [2021, 2022], "oos_years": [2024], "prohibited_years": [2025]}  # missing 2023
    with pytest.raises(LifecycleV2Error, match="YEARS_NOT_AUTHORIZED"):
        authorized_years(PLAN, "train", [2021], authorization=authorization)


def test_stale_authorization_prohibited_mismatch_rejects():
    authorization = {"train_years": [2021, 2022, 2023], "oos_years": [2024], "prohibited_years": []}
    with pytest.raises(LifecycleV2Error, match="YEARS_NOT_AUTHORIZED"):
        authorized_years(PLAN, "train", [2021], authorization=authorization)


def test_matching_authorization_artifact_passes():
    authorization = {"train_years": [2021, 2022, 2023], "oos_years": [2024], "prohibited_years": [2025]}
    assert authorized_years(PLAN, "train", [2022], authorization=authorization) == [2022]
    assert authorized_years(PLAN, "oos", None, authorization=authorization) == [2024]


def test_unknown_period_rejects():
    with pytest.raises(LifecycleV2Error, match="YEARS_NOT_AUTHORIZED"):
        authorized_years(PLAN, "bogus", None)
