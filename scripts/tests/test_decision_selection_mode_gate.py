"""Feature-selection-mode fidelity gate (contract audit pass 01, WARNING).

`scripts/check_research_decision_fidelity.py` compared the study's selection mode against
the decision contract's **only** when the decision declared ``mode: "none"``. A contract
declaring ``train_only`` or ``pre_frozen`` cross-checked nothing at all, so the gate
silently passed for two of its three modes.

The rule is a permissiveness ordering rather than equality: a study may be narrower than
its decision contract authorizes, never broader. Equality would false-positive the common
and legitimate case of a study naming an explicit ``feature_list`` (selection mode defaults
to ``none``) under a contract whose baseline was selected ``train_only``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

DECISION = """
research_question: "probe"
baseline:
  short: "f"
  long: "f"
baseline_feature_selection:
  mode: "{decision_mode}"
model_arms:
  A: "a"
variable_being_tested:
  - "f"
prohibited_changes: []
allowed_changes: []
chronology:
  train: [2024]
  dev: []
  prohibited: [2025, 2026]
primary_comparison: "p"
terminal_question: "q"
"""

STUDY = {
    "study": {"id": "sel_mode_probe", "type": "flip_prediction", "risk_tier": 2,
              "description": "probe"},
    "operation": {"kind": "train_evaluate", "target_metric": "roc_auc"},
    "instrument": {"symbol": "ES", "venue": "XCME"},
    "population": {"type": "regime_state", "prevailing_regime": "both", "session": "RTH"},
    "target": {"type": "flip", "event": "prevailing_1m_regime_transition",
               "direction": "both", "horizon_seconds": 300},
    "features": {"source": "explicit_feature_list",
                 "feature_list": ["latest_1m_wick_imbalance"], "timing_contract": "verified"},
    "model": {"mode": "scoring", "family": "HistGradientBoostingClassifier"},
    "chronology": {"train": [2024], "dev": [], "prohibited": [2025, 2026]},
    "execution": {"runtime": "nautilustrader", "progress_seconds": 60, "bounded": True},
}


def _mk_study(tmp_path: Path, decision_mode: str, study_sel_mode=None) -> Path:
    d = tmp_path / "sel_mode_probe"
    d.mkdir(parents=True, exist_ok=True)

    study = {k: (dict(v) if isinstance(v, dict) else v) for k, v in STUDY.items()}
    study["features"] = dict(study["features"])
    if study_sel_mode is not None:
        study["features"]["selection"] = {"mode": study_sel_mode}
    (d / "study.yaml").write_text(yaml.dump(study, sort_keys=False), encoding="utf-8")
    (d / "research_decision.yaml").write_text(
        DECISION.format(decision_mode=decision_mode), encoding="utf-8"
    )
    (d / "SPEC.md").write_text("# SPEC: sel_mode_probe\n", encoding="utf-8")
    return d


def _check(study_dir: Path):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_research_decision_fidelity.py"),
         "--study", str(study_dir)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )


@pytest.mark.parametrize("decision_mode", ["none", "pre_frozen", "train_only"])
def test_study_broader_than_its_contract_is_refused(tmp_path, decision_mode):
    """The gap: only `none` used to be checked, so `pre_frozen` was a free pass."""
    if decision_mode == "train_only":
        pytest.skip("train_only is the most permissive mode; nothing can exceed it")
    d = _mk_study(tmp_path, decision_mode, study_sel_mode="train_only")
    res = _check(d)
    assert res.returncode != 0, (
        f"study declaring train_only under a '{decision_mode}' contract was not refused:\n"
        f"{res.stdout}"
    )
    assert "UNAUTHORIZED_FEATURE_DISCOVERY" in res.stdout


@pytest.mark.parametrize("decision_mode", ["none", "pre_frozen", "train_only"])
def test_study_narrower_than_its_contract_is_permitted(tmp_path, decision_mode):
    """An explicit feature_list performs no selection; that is narrower, not a violation."""
    d = _mk_study(tmp_path, decision_mode, study_sel_mode=None)
    res = _check(d)
    assert "UNAUTHORIZED_FEATURE_DISCOVERY" not in res.stdout, res.stdout


def test_matching_modes_are_permitted(tmp_path):
    d = _mk_study(tmp_path, "train_only", study_sel_mode="train_only")
    res = _check(d)
    assert "UNAUTHORIZED_FEATURE_DISCOVERY" not in res.stdout, res.stdout


def test_unknown_selection_mode_fails_closed(tmp_path):
    """An unrecognised mode must not be silently treated as harmless."""
    d = _mk_study(tmp_path, "none", study_sel_mode="freestyle")
    res = _check(d)
    assert res.returncode != 0
    assert "UNKNOWN_SELECTION_MODE" in res.stdout or "UNAUTHORIZED_FEATURE_DISCOVERY" in res.stdout


def test_real_studies_still_pass_the_tightened_gate():
    """The tightening must not retro-block existing compliant studies."""
    for name in (
        "es_wick_imbalance_acceptance_v2",
        "Gemini_clean_maturity_flip_rolling_5m_productivity",
        "Codex_clean_maturity_flip_rolling_5m_productivity",
    ):
        d = REPO_ROOT / "studies" / name
        if not (d / "research_decision.yaml").exists():
            continue
        res = _check(d)
        assert res.returncode == 0, f"{name} now fails the fidelity gate:\n{res.stdout}"
