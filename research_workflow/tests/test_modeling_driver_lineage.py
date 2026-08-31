"""RT-01 -- study-local modeling drivers must enter MODELING_EXECUTION_CLOSURE.

A study-local ``implementation/*.py`` that composes governed modeling APIs can change
governed model outputs (chronology roles, binary population, seed, arm construction, the
fit / freeze call). Before this fix ``ExecutionSpec`` had no legal
``modeling_driver_relpaths`` field, so such a driver sat outside the modeling closure and
a modeling-only edit did not stale the TRAIN freeze.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from research.schemas.study_spec import ExecutionSpec, StudySpec
from research_workflow.modeling_closure import resolve_modeling_closure
from research_workflow.modeling_drivers import (
    UndeclaredModelingDriverError,
    assert_declared_modeling_drivers,
    find_participating_modeling_modules,
)

REPO = Path(__file__).resolve().parents[2]

_REPRESENTATIVE = [
    "deep_pullback_5s_reacceleration_model",
    "workflow_canary_ordered_barrier_v1",
    "clean_maturity_flip_model_180s_horizon",
    "ym_prev5_range_position",
    "es_wick_imbalance_acceptance_v2",
]


# --------------------------------------------------------------------------- #
# hash neutrality
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("study_id", _REPRESENTATIVE)
def test_absent_field_keeps_existing_spec_hash_byte_identical(study_id):
    study = REPO / "studies" / study_id
    if not (study / "study.yaml").is_file() or not (study / "compiled_study.json").is_file():
        pytest.skip(f"{study_id} not present")
    spec = StudySpec.model_validate(yaml.safe_load((study / "study.yaml").read_text()))
    compiled = json.loads((study / "compiled_study.json").read_text())
    assert spec.compute_sha256() == compiled["spec_sha256"], (
        f"{study_id}: adding ExecutionSpec.modeling_driver_relpaths changed the spec hash"
    )


def test_null_and_empty_canonicalize_identically_to_absent():
    absent = ExecutionSpec().model_dump(exclude_none=False)
    null = ExecutionSpec(modeling_driver_relpaths=None).model_dump(exclude_none=False)
    empty = ExecutionSpec(modeling_driver_relpaths=[]).model_dump(exclude_none=False)
    assert "modeling_driver_relpaths" not in absent
    assert absent == null == empty
    declared = ExecutionSpec(modeling_driver_relpaths=["implementation/d.py"]).model_dump()
    assert declared["modeling_driver_relpaths"] == ["implementation/d.py"]


def test_declared_field_still_hash_neutral_when_empty_in_full_study_spec(tmp_path):
    base = {
        "study": {"id": "s", "type": "flip_prediction", "description": "d"},
        "instrument": {"symbol": "NQ", "venue": "XCME"},
        "population": {"type": "regime_state"},
        "target": {"type": "flip", "horizon_seconds": 300},
        "features": {"source": "canonical_verified_definition_universe"},
        "chronology": {"train": [2021], "dev": [2022], "prohibited": [2025, 2026]},
        "execution": {"runtime": "nautilustrader"},
    }
    without = StudySpec.model_validate(base).compute_sha256()
    with_null = {**base, "execution": {**base["execution"], "modeling_driver_relpaths": None}}
    with_empty = {**base, "execution": {**base["execution"], "modeling_driver_relpaths": []}}
    assert StudySpec.model_validate(with_null).compute_sha256() == without
    assert StudySpec.model_validate(with_empty).compute_sha256() == without
    with_real = {**base, "execution": {**base["execution"], "modeling_driver_relpaths": ["implementation/d.py"]}}
    assert StudySpec.model_validate(with_real).compute_sha256() != without


# --------------------------------------------------------------------------- #
# undeclared-driver detection
# --------------------------------------------------------------------------- #
def _mk_study(tmp_path: Path, *, impl_files: dict[str, str], declared: list[str] | None):
    s = tmp_path / "s"
    (s / "implementation").mkdir(parents=True)
    for name, body in impl_files.items():
        (s / "implementation" / name).write_text(body, encoding="utf-8")
    spec = {"execution": {"runtime": "nautilustrader"}}
    if declared is not None:
        spec["execution"]["modeling_driver_relpaths"] = declared
    (s / "compiled_study.json").write_text(json.dumps({"spec": spec}))
    return s


_GOVERNED_DRIVER = "from research_workflow.modeling import fit_models, freeze_train_artifacts\n"
_SELECTION_HELPER = "from research_workflow.model_selection import run_model_selection\n"
_DIAGNOSTIC_ONLY = "from research.analysis.modeling import SplitPolicy, fit_model\n"


def test_undeclared_participating_driver_fails_closed(tmp_path):
    s = _mk_study(tmp_path, impl_files={"driver.py": _GOVERNED_DRIVER}, declared=[])
    with pytest.raises(UndeclaredModelingDriverError, match="MODELING_DRIVER_UNDECLARED"):
        assert_declared_modeling_drivers(s, [])


def test_declared_driver_passes(tmp_path):
    s = _mk_study(tmp_path, impl_files={"driver.py": _GOVERNED_DRIVER},
                  declared=["implementation/driver.py"])
    assert assert_declared_modeling_drivers(s, ["implementation/driver.py"]) == [
        "implementation/driver.py"
    ]


def test_diagnostic_only_module_does_not_trigger(tmp_path):
    s = _mk_study(tmp_path, impl_files={"feasibility.py": _DIAGNOSTIC_ONLY}, declared=[])
    assert find_participating_modeling_modules(s) == []
    assert_declared_modeling_drivers(s, [])  # no raise


def test_selection_helper_also_counts_as_participant(tmp_path):
    s = _mk_study(
        tmp_path,
        impl_files={"driver.py": _GOVERNED_DRIVER, "two_phase.py": _SELECTION_HELPER},
        declared=["implementation/driver.py"],
    )
    with pytest.raises(UndeclaredModelingDriverError, match="two_phase.py"):
        assert_declared_modeling_drivers(s, ["implementation/driver.py"])


def test_real_studies_participants_are_exactly_the_freeze_drivers():
    dp = find_participating_modeling_modules(REPO / "studies" / "deep_pullback_5s_reacceleration_model")
    assert dp == ["implementation/train_merge_fit_freeze.py"]
    h = find_participating_modeling_modules(REPO / "studies" / "clean_maturity_flip_model_180s_horizon")
    assert set(h) == {
        "implementation/final_train_freeze.py",
        "implementation/two_phase_selection.py",
    }


# --------------------------------------------------------------------------- #
# modeling closure folds the declared driver; order independent
# --------------------------------------------------------------------------- #
def test_declared_driver_bytes_change_the_modeling_closure(tmp_path):
    s = tmp_path / "s"
    (s / "implementation").mkdir(parents=True)
    drv = s / "implementation" / "driver.py"
    drv.write_text("X = 1\n", encoding="utf-8")

    base = resolve_modeling_closure(s, driver_relpaths=[])["modeling_execution_composite_sha256"]
    with_drv = resolve_modeling_closure(s, driver_relpaths=["implementation/driver.py"])[
        "modeling_execution_composite_sha256"
    ]
    assert with_drv != base

    drv.write_text("X = 2\n", encoding="utf-8")
    edited = resolve_modeling_closure(s, driver_relpaths=["implementation/driver.py"])[
        "modeling_execution_composite_sha256"
    ]
    assert edited != with_drv


def test_modeling_closure_order_independent(tmp_path):
    s = tmp_path / "s"
    (s / "implementation").mkdir(parents=True)
    (s / "implementation" / "a.py").write_text("A = 1\n", encoding="utf-8")
    (s / "implementation" / "b.py").write_text("B = 1\n", encoding="utf-8")
    one = resolve_modeling_closure(s, driver_relpaths=["implementation/a.py", "implementation/b.py"])
    two = resolve_modeling_closure(s, driver_relpaths=["implementation/b.py", "implementation/a.py"])
    assert one["modeling_execution_composite_sha256"] == two["modeling_execution_composite_sha256"]


# --------------------------------------------------------------------------- #
# fit_models fails closed on an undeclared participant
# --------------------------------------------------------------------------- #
def test_fit_models_refuses_undeclared_driver(tmp_path):
    import pandas as pd
    from research_workflow.modeling import fit_models

    s = _mk_study(tmp_path, impl_files={"driver.py": _GOVERNED_DRIVER}, declared=[])
    (s / "artifacts").mkdir(exist_ok=True)
    X = pd.DataFrame({"f": [0.0, 1.0]})
    y = pd.Series([0, 1])
    meta = pd.DataFrame({"_partition": ["train", "train"]})
    with pytest.raises(UndeclaredModelingDriverError):
        fit_models(s, X, y, meta=meta, spec=object())
