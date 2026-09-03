"""Red-team regression: packet E (research_workflow/tuning.py).

E1 -- a PRUNED Optuna trial's last-reported (partial, single/few-fold) value can never be
selected as the tuning winner; only COMPLETE trials whose recomputed aggregate spans every
declared fold are eligible.
E2 -- the Optuna resume identity binds the full tuning contract (plan, execution closure,
population, target/feature/preprocessing contracts, chronology, objective, search space,
sampler seed) and fails closed on a field-level mismatch under a colliding study name.
E3 -- validation.random_seed governs sampler randomness only; the estimator seed is untouched;
absence falls back to the model seed with a disclosed source.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from research_workflow import tuning as tuning_mod
from research_workflow.tuning import TuningError, tune


def _frame(seed: int, n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({"f1": rng.normal(size=n), "f2": rng.normal(size=n), "_year": np.repeat([2021, 2022, 2023], n // 3)})
    frame["y"] = ((frame["f1"] + 0.4 * frame["f2"] + rng.normal(scale=0.6, size=n)) > 0).astype(int)
    return frame


BASE_IDENTITIES = {"plan_sha256": "plan-a", "execution_closure_composite": "closure-a", "population_identity": "pop-a",
                    "target_contract_sha256": "target-a", "feature_contract_sha256": "feat-a", "preprocessing_contract_sha256": "identity"}


# ---------------------------------------------------------------------------------------------
# E1(a) -- optuna: a PRUNED trial's lucky partial value cannot win selection
# ---------------------------------------------------------------------------------------------
def test_e1a_pruned_trial_with_lucky_partial_value_cannot_be_selected(tmp_path, monkeypatch):
    optuna = pytest.importorskip("optuna")
    frame = _frame(5)
    validation = {"protocol": "validation.model_selection.optuna", "tuning_years": [2021, 2022, 2023], "max_trials": 4,
                  "random_seed": 7, "primary_metric": "roc_auc"}
    space = {"C": {"choices": [1.0]}}  # fixed param: isolates the selection defect from sampler variance

    call = {"n": 0}
    script = [0.60, 0.62, 0.61, 0.63, 0.99]  # trial0 fold0/fold1, trial1 fold0/fold1, trial2 fold0 (lucky)
    def fake_score(metric, y_true, y_score):
        v = script[call["n"]] if call["n"] < len(script) else 0.5
        call["n"] += 1
        return v
    monkeypatch.setattr(tuning_mod, "_score", fake_score)

    prune_count = {"n": 0}
    def fake_should_prune(self):
        prune_count["n"] += 1
        return prune_count["n"] == 5  # right after trial2's lucky fold-0 report; never reaches fold 1
    monkeypatch.setattr(optuna.trial.Trial, "should_prune", fake_should_prune)

    out = tune(study_id="attack", frame=frame, features=["f1", "f2"], label="y", family="logistic_regression", base_params={}, seed=7,
               search_space=space, validation=validation, artifacts_dir=tmp_path, identities=BASE_IDENTITIES)
    ledger = json.loads((tmp_path / "tuning_trials.json").read_text())

    pruned = [t for t in ledger["trials"] if t["state"] == "PRUNED"]
    assert len(pruned) == 1, "attack setup did not produce exactly one PRUNED trial"
    p = pruned[0]
    assert p["eligible"] is False
    assert p["ineligible_reason"] in ("NO_FOLD_SCORES", "INCOMPLETE_FOLDS", "NULL_FOLD_SCORE")

    complete = [t for t in ledger["trials"] if t["state"] == "COMPLETE"]
    assert complete, "attack setup produced no COMPLETE trial to compare against"
    true_best = max(t["aggregate"] for t in complete)
    assert p["optuna_value"] is not None and p["optuna_value"] >= 0.99 - 1e-9
    assert p["optuna_value"] > true_best, "attack precondition: the pruned trial's lucky partial value must beat every true multi-fold aggregate"

    # pre-fix reproduction: the OLD code selected max(t.value) over any trial whose value was not
    # None -- it would have picked this pruned trial purely on its lucky partial score.
    old_selection = max((t for t in ledger["trials"] if t.get("optuna_value") is not None), key=lambda t: t["optuna_value"])
    assert old_selection["number"] == p["number"]

    # fixed behavior: only a COMPLETE, fully-fold-covered trial can be selected.
    sel = next(t for t in ledger["trials"] if t["number"] == ledger["selected"]["number"])
    assert sel["state"] == "COMPLETE" and sel["eligible"] is True
    assert ledger["selected"]["aggregate"] == true_best
    assert out["selected"]["number"] != p["number"]


# ---------------------------------------------------------------------------------------------
# E1(b) -- random sampler: a None fold score makes a trial ineligible, never wins
# ---------------------------------------------------------------------------------------------
def test_e1b_random_sampler_none_fold_score_is_ineligible(tmp_path, monkeypatch):
    frame = _frame(9)
    validation = {"protocol": "validation.model_selection.random", "tuning_years": [2021, 2022, 2023], "max_trials": 3,
                  "random_seed": 3, "primary_metric": "roc_auc"}
    space = {"C": {"choices": [0.5, 1.0, 2.0]}}
    real_score = tuning_mod._score
    call = {"n": 0}
    def flaky_score(metric, y_true, y_score):
        call["n"] += 1
        if call["n"] == 4:  # second trial's second fold
            return None
        return real_score(metric, y_true, y_score)
    monkeypatch.setattr(tuning_mod, "_score", flaky_score)

    out = tune(study_id="s", frame=frame, features=["f1", "f2"], label="y", family="logistic_regression", base_params={}, seed=3,
               search_space=space, validation=validation, artifacts_dir=tmp_path, identities=BASE_IDENTITIES)
    ledger = json.loads((tmp_path / "tuning_trials.json").read_text())

    flawed = next(t for t in ledger["trials"] if t["number"] == 1)
    assert flawed["eligible"] is False and flawed["ineligible_reason"] == "NULL_FOLD_SCORE" and flawed["aggregate"] is None
    assert all(t["eligible"] for t in ledger["trials"] if t["number"] != 1)
    assert ledger["selected"]["number"] != 1
    assert out["selected"]["aggregate"] == max(t["aggregate"] for t in ledger["trials"] if t["eligible"])


# ---------------------------------------------------------------------------------------------
# E1(e) -- adjacent bypass: a short fold_scores list is ineligible even if labeled COMPLETE
# ---------------------------------------------------------------------------------------------
def test_e1e_short_or_null_fold_scores_never_eligible():
    from research_workflow.tuning import _recompute_aggregate
    assert _recompute_aggregate(None, 2) == (None, False, "NO_FOLD_SCORES")
    assert _recompute_aggregate([0.5], 2) == (None, False, "INCOMPLETE_FOLDS")
    assert _recompute_aggregate([0.5, None], 2) == (None, False, "NULL_FOLD_SCORE")
    agg, eligible, reason = _recompute_aggregate([0.5, 0.6], 2)
    assert eligible is True and reason is None and abs(agg - 0.55) < 1e-9


# ---------------------------------------------------------------------------------------------
# E2 -- resume identity: identical config resumes; a field change under a colliding study name
# fails closed with a named-field TuningError, never a silent mixed-history resume.
# ---------------------------------------------------------------------------------------------
def _kwargs(frame, **overrides):
    base = dict(study_id="resume-study", frame=frame, features=["f1", "f2"], label="y", family="logistic_regression",
                base_params={}, seed=11, search_space={"C": {"choices": [0.5, 1.0]}},
                validation={"protocol": "validation.model_selection.optuna", "tuning_years": [2021, 2022, 2023], "max_trials": 2,
                            "random_seed": 11, "primary_metric": "roc_auc"},
                identities=dict(BASE_IDENTITIES))
    base.update(overrides)
    return base


def test_e2_identical_identity_resumes_without_error(tmp_path):
    pytest.importorskip("optuna")
    frame = _frame(21)
    out1 = tune(artifacts_dir=tmp_path, **_kwargs(frame))
    ledger1 = json.loads((tmp_path / "tuning_trials.json").read_text())
    out2 = tune(artifacts_dir=tmp_path, **_kwargs(frame))
    ledger2 = json.loads((tmp_path / "tuning_trials.json").read_text())
    assert out2["n_trials"] == out1["n_trials"]  # remaining==0 -> no re-optimize, same trial count
    assert ledger2["selected"]["params"] == ledger1["selected"]["params"]


@pytest.mark.parametrize("field,mutate", [
    ("search_space", lambda kw: kw.update(search_space={"C": {"choices": [0.5, 1.0, 2.0]}})),
    ("folds", lambda kw: kw.update(validation={**kw["validation"], "tuning_years": [2021, 2022]})),
    ("objective", lambda kw: kw.update(validation={**kw["validation"], "primary_metric": "pr_auc"})),
])
def test_e2_field_mismatch_under_a_colliding_study_name_fails_closed(tmp_path, field, mutate):
    optuna = pytest.importorskip("optuna")
    frame = _frame(21)
    kw_a = _kwargs(frame)
    folds_a = tuning_mod.walk_forward_folds(kw_a["validation"]["tuning_years"])
    ident_a, payload_a = tuning_mod._tuning_identity(study_id=kw_a["study_id"], identities=kw_a["identities"], features=kw_a["features"],
                                                       folds=folds_a, metric=kw_a["validation"]["primary_metric"], maximize=True,
                                                       search_space=kw_a["search_space"], sampler_seed=11, sampler_seed_source="validation.random_seed",
                                                       family=kw_a["family"], base_params=kw_a["base_params"])

    kw_b = _kwargs(frame)
    mutate(kw_b)
    folds_b = tuning_mod.walk_forward_folds(kw_b["validation"]["tuning_years"])
    maximize_b = kw_b["validation"]["primary_metric"] != "brier"
    ident_b, payload_b = tuning_mod._tuning_identity(study_id=kw_b["study_id"], identities=kw_b["identities"], features=kw_b["features"],
                                                       folds=folds_b, metric=kw_b["validation"]["primary_metric"], maximize=maximize_b,
                                                       search_space=kw_b["search_space"], sampler_seed=11, sampler_seed_source="validation.random_seed",
                                                       family=kw_b["family"], base_params=kw_b["base_params"])
    assert ident_a != ident_b

    # Plant a study under the SAME name config B will compute, carrying config A's identity
    # fields -- simulating a truncated-hash collision / tampered db entry.
    artifacts_dir = tmp_path / field
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    storage = f"sqlite:///{(artifacts_dir / 'tuning_optuna.db').resolve().as_posix()}"
    planted = optuna.create_study(study_name=f"{kw_b['study_id']}:{ident_b[:16]}", storage=storage,
                                   direction="maximize" if maximize_b else "minimize")
    planted.set_user_attr("tuning_identity", ident_a)
    planted.set_user_attr("tuning_identity_fields", payload_a)

    with pytest.raises(TuningError, match="TUNING_RESUME_IDENTITY_MISMATCH"):
        tune(artifacts_dir=artifacts_dir, **kw_b)


# ---------------------------------------------------------------------------------------------
# E3 -- validation.random_seed governs the sampler only; source disclosed in the ledger.
# ---------------------------------------------------------------------------------------------
def test_e3_random_seed_governs_sampler_not_estimator(tmp_path):
    frame = _frame(31)
    space = {"C": {"low": 0.05, "high": 5.0, "log": True, "int": False}}

    def run(artifacts_dir, random_seed):
        validation = {"protocol": "validation.model_selection.random", "tuning_years": [2021, 2022, 2023], "max_trials": 3,
                      "primary_metric": "roc_auc"}
        if random_seed is not None:
            validation["random_seed"] = random_seed
        return tune(study_id="seed-study", frame=frame, features=["f1", "f2"], label="y", family="logistic_regression",
                    base_params={}, seed=42, search_space=space, validation=validation, artifacts_dir=artifacts_dir, identities=BASE_IDENTITIES)

    out_100 = run(tmp_path / "s100", 100)
    ledger_100 = json.loads((tmp_path / "s100" / "tuning_trials.json").read_text())
    out_100b = run(tmp_path / "s100b", 100)
    ledger_100b = json.loads((tmp_path / "s100b" / "tuning_trials.json").read_text())
    out_200 = run(tmp_path / "s200", 200)
    ledger_200 = json.loads((tmp_path / "s200" / "tuning_trials.json").read_text())
    out_none = run(tmp_path / "snone", None)
    ledger_none = json.loads((tmp_path / "snone" / "tuning_trials.json").read_text())

    assert [t["params"] for t in ledger_100["trials"]] == [t["params"] for t in ledger_100b["trials"]]
    assert [t["params"] for t in ledger_100["trials"]] != [t["params"] for t in ledger_200["trials"]]
    assert ledger_100["sampler_seed"] == 100 and ledger_100["sampler_seed_source"] == "validation.random_seed"
    assert ledger_none["sampler_seed"] == 42 and ledger_none["sampler_seed_source"] == "model.params.random_state"
