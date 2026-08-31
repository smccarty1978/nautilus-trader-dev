"""Direction-qualified model-selection winner binding in freeze_train_artifacts.

A two-phase study freezes one tuned model per direction and aggregates them into a
single canonical ``train_experiment_freeze.json`` (the OOS gate reads only that
filename).  The aggregate arm keys become ``LONG_C`` / ``SHORT_C`` while each
direction's selection manifest still keys its winner ``C``.  These tests prove the
aggregate freeze keeps the same winner-binding guarantees as the per-direction
freezes: renaming ``C`` -> ``LONG_C`` cannot skip the check, and a mismatched
directional hyperparameter set fails closed.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from research_workflow.modeling import (
    ModelSelectionBindingMismatch,
    ModelSelectionFinalValidationFailed,
    _resolve_selection_bindings,
    _selection_manifest_sha_field,
    freeze_train_artifacts,
)

ARM_C = [
    "arrival_velocity", "arrival_acceleration", "ema_slope",
    "prior_1m_regime_efficiency", "prior_1m_regime_mfe_atr", "prior_1m_regime_range_atr",
    "prior_5m_regime_efficiency", "prior_5m_regime_mfe_atr", "prior_5m_regime_range_atr",
    "rolling_300s_retention_ratio", "rolling_300s_current_progress_atr",
    "rolling_300s_max_progress_atr", "rolling_300s_giveback_atr",
]
LONG_HP = {"learning_rate": 0.03944, "max_depth": 5, "n_estimators": 100, "num_leaves": 4, "verbosity": -1}
SHORT_HP = {"learning_rate": 0.02886, "max_depth": 5, "n_estimators": 200, "num_leaves": 4, "verbosity": -1}


def _manifest(winner_hp: dict, *, seed: int = 42, status: str = "PASS", sha: str = "deadbeef") -> dict:
    return {
        "random_seed": seed,
        "winner": {"C": {"family": "lightgbm", "hyperparameters": winner_hp}},
        "final_validation_policy": "gated",
        "final_validation_status": status,
        "final_validation_reasons": [],
        "manifest_sha256": sha,
    }


def _write(tmp: Path, name: str, payload: dict) -> Path:
    p = tmp / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _selection_spec() -> SimpleNamespace:
    return SimpleNamespace(
        model=SimpleNamespace(selection=SimpleNamespace(search_method="random")),
        required_gates=None,
    )


def _call_freeze(tmp: Path, *, models_manifest: dict, manifest_map: dict):
    """Drive freeze_train_artifacts far enough to exercise the binding loop.

    The binding checks raise before any filesystem-heavy step, so a bare tmp dir is
    enough for the negative cases.
    """
    return freeze_train_artifacts(
        tmp,
        feature_sets={"LONG_C": list(ARM_C), "SHORT_C": list(ARM_C)},
        models_manifest=models_manifest,
        preprocessing_hash="p",
        score_arrays={"LONG_C": [], "SHORT_C": []},
        meta=pd.DataFrame({"_partition": ["train", "train"]}),
        thresholds={"LONG_C": {}, "SHORT_C": {}},
        deciles={"LONG_C": {}, "SHORT_C": {}},
        study_spec=_selection_spec(),
        model_selection_manifest_path=manifest_map,
    )


def _mm(long_hp: dict, short_hp: dict) -> dict:
    return {"arms": {
        "LONG_C": {"hyperparameters": long_hp, "seed": 42, "fit_identity_sha256": "L"},
        "SHORT_C": {"hyperparameters": short_hp, "seed": 42, "fit_identity_sha256": "S"},
    }}


# --------------------------------------------------------------------------- #
# _resolve_selection_bindings
# --------------------------------------------------------------------------- #

def test_shared_manifest_binds_every_arm_by_exact_key(tmp_path):
    m = _write(tmp_path, "sel.json", {
        "random_seed": 42,
        "winner": {"A": {"hyperparameters": {"x": 1}}, "C": {"hyperparameters": LONG_HP}},
        "manifest_sha256": "z",
    })
    out = _resolve_selection_bindings(str(m), {"A": [], "C": []})
    assert out["C"][1]["hyperparameters"] == LONG_HP
    assert out["A"][1]["hyperparameters"] == {"x": 1}


def test_per_arm_mapping_binds_direction_qualified_arm_to_sole_winner(tmp_path):
    ml = _write(tmp_path, "long.json", _manifest(LONG_HP, sha="lsha"))
    ms = _write(tmp_path, "short.json", _manifest(SHORT_HP, sha="ssha"))
    out = _resolve_selection_bindings(
        {"LONG_C": str(ml), "SHORT_C": str(ms)},
        {"LONG_C": ARM_C, "SHORT_C": ARM_C},
    )
    assert out["LONG_C"][1]["hyperparameters"] == LONG_HP
    assert out["SHORT_C"][1]["hyperparameters"] == SHORT_HP
    assert _selection_manifest_sha_field(out) == {"LONG_C": "lsha", "SHORT_C": "ssha"}


def test_ambiguous_manifest_yields_no_winner(tmp_path):
    ambiguous = {
        "random_seed": 42,
        "winner": {"C1": {"hyperparameters": LONG_HP}, "C2": {"hyperparameters": SHORT_HP}},
        "manifest_sha256": "z",
    }
    m = _write(tmp_path, "amb.json", ambiguous)
    out = _resolve_selection_bindings({"LONG_C": str(m)}, {"LONG_C": ARM_C})
    assert out["LONG_C"][1] is None  # caller fails closed


def test_sha_field_collapses_to_string_when_shared(tmp_path):
    m = _write(tmp_path, "sel.json", _manifest(LONG_HP, sha="one"))
    out = _resolve_selection_bindings(str(m), {"LONG_C": [], "SHORT_C": []})
    assert _selection_manifest_sha_field(out) == "one"


# --------------------------------------------------------------------------- #
# freeze_train_artifacts binding loop
# --------------------------------------------------------------------------- #

def test_direction_qualified_binding_accepts_matching_hyperparameters(tmp_path):
    ml = _write(tmp_path, "long.json", _manifest(LONG_HP))
    ms = _write(tmp_path, "short.json", _manifest(SHORT_HP))
    # Matching HP -> binding loop passes; the call then fails LATER (bare tmp dir has
    # no study.yaml / compiled_study.json). Anything other than a binding error means
    # the winner binding was satisfied.
    with pytest.raises(Exception) as exc:
        _call_freeze(tmp_path, models_manifest=_mm(LONG_HP, SHORT_HP),
                     manifest_map={"LONG_C": str(ml), "SHORT_C": str(ms)})
    assert not isinstance(exc.value, (ModelSelectionBindingMismatch, ModelSelectionFinalValidationFailed))


def test_rename_to_direction_qualified_arm_cannot_bypass_winner_binding(tmp_path):
    # Aggregate arm LONG_C, manifest sole winner keyed "C" with LONG_HP, but the
    # frozen record carries SHORT_HP. Renaming must NOT skip the check.
    ml = _write(tmp_path, "long.json", _manifest(LONG_HP))
    ms = _write(tmp_path, "short.json", _manifest(SHORT_HP))
    with pytest.raises(ModelSelectionBindingMismatch):
        _call_freeze(tmp_path, models_manifest=_mm(SHORT_HP, SHORT_HP),
                     manifest_map={"LONG_C": str(ml), "SHORT_C": str(ms)})


def test_mismatched_directional_hyperparameters_fail_closed(tmp_path):
    ml = _write(tmp_path, "long.json", _manifest(LONG_HP))
    ms = _write(tmp_path, "short.json", _manifest(SHORT_HP))
    # SHORT frozen record perturbed.
    bad_short = dict(SHORT_HP, learning_rate=0.099)
    with pytest.raises(ModelSelectionBindingMismatch):
        _call_freeze(tmp_path, models_manifest=_mm(LONG_HP, bad_short),
                     manifest_map={"LONG_C": str(ml), "SHORT_C": str(ms)})


def test_seed_mismatch_fails_closed(tmp_path):
    ml = _write(tmp_path, "long.json", _manifest(LONG_HP, seed=7))
    ms = _write(tmp_path, "short.json", _manifest(SHORT_HP))
    with pytest.raises(ModelSelectionBindingMismatch):
        _call_freeze(tmp_path, models_manifest=_mm(LONG_HP, SHORT_HP),
                     manifest_map={"LONG_C": str(ml), "SHORT_C": str(ms)})


def test_gated_final_validation_failure_refuses(tmp_path):
    ml = _write(tmp_path, "long.json", _manifest(LONG_HP, status="FAIL"))
    ms = _write(tmp_path, "short.json", _manifest(SHORT_HP))
    with pytest.raises(ModelSelectionFinalValidationFailed):
        _call_freeze(tmp_path, models_manifest=_mm(LONG_HP, SHORT_HP),
                     manifest_map={"LONG_C": str(ml), "SHORT_C": str(ms)})


# --------------------------------------------------------------------------- #
# integration: the aggregate freeze satisfies the real OOS gate
# --------------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parents[2]
S180 = REPO_ROOT / "studies" / "clean_maturity_flip_model_180s_horizon"


@pytest.mark.skipif(
    not (S180 / "artifacts" / "train_experiment_freeze.json").is_file(),
    reason="180s horizon study has no aggregate TRAIN freeze in this checkout",
)
def test_aggregate_freeze_opens_the_real_oos_gate():
    from research_workflow.experiment import assert_oos_open

    freeze = assert_oos_open(str(S180))  # read-only; does not touch OOS data
    assert freeze["partition"] == "train"
    assert set(freeze["model_hashes"]) == {"LONG_C", "SHORT_C"}
    # direction-qualified selection-manifest bindings preserved, one per direction
    assert isinstance(freeze["model_selection_manifest_sha256"], dict)
    assert set(freeze["model_selection_manifest_sha256"]) == {"LONG_C", "SHORT_C"}
    comp = freeze["aggregate_of"]["components"]
    assert comp["LONG_C"]["model_id"] == "139fb532d28ee6c1020cdf300ac1bb1b1673d528475aef3a66f7e41976f04389"
    assert comp["SHORT_C"]["model_id"] == "4d62250a6b8af62aac86de4a92e0924704ff3e774670e208de3af285472a1cb4"
