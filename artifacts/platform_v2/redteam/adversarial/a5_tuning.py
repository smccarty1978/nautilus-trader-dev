"""A5 (CRIT-4 / WARN optuna resume): tuning winner selection and resume identity.
Constructs a search in which a PRUNED trial holds the best partial (Optuna) value."""
from __future__ import annotations
import json, sys, tempfile
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
import optuna  # noqa
from research_workflow.tuning import tune, TuningError, _tuning_identity, walk_forward_folds  # noqa

res = []


def rec(case, outcome, verdict):
    res.append({"case": case, "outcome": str(outcome)[:400], "verdict": verdict})


# ---- data: fold 0 (validate 2030) is easy, fold 1 (validate 2031) is near-random ----
rng = np.random.default_rng(3)
rows = []
for year, sep in ((2029, 2.0), (2030, 2.0), (2031, 0.02)):
    n = 700
    lab = rng.integers(0, 2, size=n)
    rows.append(pd.DataFrame({"_year": year, "f_a": rng.normal(size=n) + sep * lab,
                              "f_b": rng.normal(size=n), "f_c": rng.normal(size=n), "y": lab}))
frame = pd.concat(rows, ignore_index=True)
FEATS = ["f_a", "f_b", "f_c"]
SPACE = {"learning_rate": {"low": 0.01, "high": 0.4},
         "num_leaves": {"int": True, "low": 2, "high": 16}}
VALID = {"protocol": "model_selection.optuna", "tuning_years": [2029, 2030, 2031],
         "primary_metric": "roc_auc", "max_trials": 10, "random_seed": 5}
IDENT = {"plan_sha256": "p" * 64, "population_identity": "q" * 64, "execution_closure_composite": "c" * 64,
         "target_contract_sha256": "t" * 64, "feature_contract_sha256": "f" * 64,
         "preprocessing_contract_sha256": "identity"}
BASE = {"n_estimators": 25, "max_depth": 3, "verbosity": -1}


class HighValuePruner(optuna.pruners.BasePruner):
    """Prunes exactly the trials with the HIGHEST partial value, so a PRUNED trial always
    holds the best Optuna `trial.value` in the study."""

    def prune(self, study, trial):
        # prune every ODD trial as soon as it reports fold 0 (its best, ~0.95); even trials
        # run to completion and aggregate to ~0.72 across the easy + hard fold.
        vals = trial.intermediate_values
        return bool(vals) and (trial.number % 2 == 1)


_real_median = optuna.pruners.MedianPruner
optuna.pruners.MedianPruner = lambda **kw: HighValuePruner()

TD = Path(tempfile.mkdtemp())
art = TD / "e1"
art.mkdir(parents=True)
report = tune(study_id="adv_tune", frame=frame, features=FEATS, label="y", family="lightgbm",
              base_params=BASE, seed=42, search_space=SPACE, validation=VALID,
              artifacts_dir=art, identities=IDENT)
ledger = json.loads((art / "tuning_trials.json").read_text())
states = {}
for t in ledger["trials"]:
    states.setdefault(t["state"], []).append(t)
pruned = states.get("PRUNED", [])
sel = ledger["selected"]
sel_trial = next(t for t in ledger["trials"] if t["number"] == sel["number"])
best_pruned_value = max([t["optuna_value"] for t in pruned if t["optuna_value"] is not None], default=None)
print("states:", {k: len(v) for k, v in states.items()})
print("selected:", json.dumps(sel))
print("selected state:", sel_trial["state"], "fold_scores:", sel_trial["fold_scores"])
print("best PRUNED optuna_value:", best_pruned_value)
ok = (sel_trial["state"] == "COMPLETE" and sel_trial["eligible"]
      and best_pruned_value is not None and best_pruned_value > sel["aggregate"])
rec("E1 a PRUNED trial holds the best Optuna partial value; winner must still be COMPLETE",
    "selected=#%s state=%s aggregate=%.6f ; best PRUNED optuna_value=%s ; n_pruned=%d"
    % (sel["number"], sel_trial["state"], sel["aggregate"], best_pruned_value, len(pruned)),
    "BLOCKED" if ok else ("BYPASSED" if sel_trial["state"] != "COMPLETE" else "INCONCLUSIVE"))
# selected aggregate must equal mean(fold_scores), never optuna's own value
recomputed = float(np.mean(sel_trial["fold_scores"]))
rec("E1b selected aggregate is recomputed from fold_scores (not trial.value)",
    "aggregate=%r mean(fold_scores)=%r optuna_value=%r" % (sel["aggregate"], recomputed, sel_trial["optuna_value"]),
    "BLOCKED" if abs(sel["aggregate"] - recomputed) < 1e-12 else "BYPASSED")
# every pruned trial must be ineligible
bad = [t["number"] for t in pruned if t["eligible"]]
rec("E1c no PRUNED trial is eligible", "eligible_pruned=%s" % bad, "BLOCKED" if not bad else "BYPASSED")

optuna.pruners.MedianPruner = _real_median

# ---- adjacent: a COMPLETE trial with a MISSING / SHORT fold_scores user_attr ----
folds = walk_forward_folds(VALID["tuning_years"])
tid, payload = _tuning_identity(study_id="adv_tune", identities=IDENT, features=FEATS, folds=folds,
                                metric="roc_auc", maximize=True, search_space=SPACE, sampler_seed=5,
                                sampler_seed_source="validation.random_seed", family="lightgbm", base_params=BASE)
for tag, attrs in (("missing", {}), ("short", {"fold_scores": [0.999]}), ("null", {"fold_scores": [0.999, None]})):
    a = TD / ("e1x_" + tag)
    a.mkdir(parents=True)
    storage = "sqlite:///" + (a / "tuning_optuna.db").resolve().as_posix()
    st = optuna.create_study(study_name="adv_tune:" + tid[:16], storage=storage, direction="maximize")
    st.set_user_attr("tuning_identity", tid)
    st.set_user_attr("tuning_identity_fields", payload)
    st.add_trial(optuna.trial.create_trial(
        state=optuna.trial.TrialState.COMPLETE, value=0.999,
        params={"learning_rate": 0.2, "num_leaves": 8},
        distributions={"learning_rate": optuna.distributions.FloatDistribution(0.01, 0.4),
                       "num_leaves": optuna.distributions.IntDistribution(2, 16)},
        user_attrs=dict(attrs)))
    v = dict(VALID); v["max_trials"] = 3
    try:
        r = tune(study_id="adv_tune", frame=frame, features=FEATS, label="y", family="lightgbm",
                 base_params=BASE, seed=42, search_space=SPACE, validation=v, artifacts_dir=a, identities=IDENT)
        led = json.loads((a / "tuning_trials.json").read_text())
        planted = next((t for t in led["trials"] if t["number"] == 0), None)
        picked_planted = led["selected"]["number"] == 0
        rec("E1d ADJACENT: planted COMPLETE trial with %s fold_scores and value=0.999" % tag,
            "planted eligible=%r reason=%r ; selected=#%s aggregate=%r" % (
                planted and planted["eligible"], planted and planted["ineligible_reason"],
                led["selected"]["number"], led["selected"]["aggregate"]),
            "BYPASSED" if picked_planted else "BLOCKED")
    except Exception as exc:
        rec("E1d ADJACENT: planted COMPLETE trial with %s fold_scores and value=0.999" % tag,
            type(exc).__name__ + ": " + str(exc)[:200], "BLOCKED")

# ---- adjacent: resume identity ----
a = TD / "e2"
a.mkdir(parents=True)
v = dict(VALID); v["max_trials"] = 3
tune(study_id="adv_tune", frame=frame, features=FEATS, label="y", family="lightgbm", base_params=BASE,
     seed=42, search_space=SPACE, validation=v, artifacts_dir=a, identities=IDENT)
try:
    tune(study_id="adv_tune", frame=frame, features=FEATS, label="y", family="lightgbm", base_params=BASE,
         seed=42, search_space=SPACE, validation=v, artifacts_dir=a, identities=IDENT)
    rec("E2 resume with IDENTICAL identity", "resumed without error", "OK")
except Exception as exc:
    rec("E2 resume with IDENTICAL identity", type(exc).__name__ + ": " + str(exc)[:200], "UNEXPECTED_REJECT")

# perturb one identity field, but plant the perturbed study under the ORIGINAL study_name so the
# resume path (not a fresh study) is exercised -- exactly the truncated-name-collision shape.
for field, mutate in (("population_identity", lambda i: {**i, "population_identity": "z" * 64}),
                      ("feature_contract_sha256", lambda i: {**i, "feature_contract_sha256": "z" * 64}),
                      ("execution_closure_composite", lambda i: {**i, "execution_closure_composite": "z" * 64})):
    b = TD / ("e2_" + field)
    b.mkdir(parents=True)
    tune(study_id="adv_tune", frame=frame, features=FEATS, label="y", family="lightgbm", base_params=BASE,
         seed=42, search_space=SPACE, validation=v, artifacts_dir=b, identities=IDENT)
    try:
        tune(study_id="adv_tune", frame=frame, features=FEATS, label="y", family="lightgbm", base_params=BASE,
             seed=42, search_space=SPACE, validation=v, artifacts_dir=b, identities=mutate(IDENT))
        # a changed identity yields a NEW study_name -> a fresh study, which is also fail-safe,
        # but check whether it silently REUSED the old trials
        led = json.loads((b / "tuning_trials.json").read_text())
        rec("E2 resume against an existing db with %s changed" % field,
            "no error; n_trials=%d (fresh study under a new name means no cross-identity reuse)" % led["n_trials"],
            "BLOCKED" if led["n_trials"] <= v["max_trials"] else "BYPASSED")
    except TuningError as exc:
        rec("E2 resume against an existing db with %s changed" % field, str(exc)[:200], "BLOCKED")

# planted collision: same study_name, different recorded identity fields
c = TD / "e2_collide"
c.mkdir(parents=True)
storage = "sqlite:///" + (c / "tuning_optuna.db").resolve().as_posix()
st = optuna.create_study(study_name="adv_tune:" + tid[:16], storage=storage, direction="maximize")
st.set_user_attr("tuning_identity", tid)
st.set_user_attr("tuning_identity_fields", {**payload, "population_identity": "COLLIDED"})
try:
    tune(study_id="adv_tune", frame=frame, features=FEATS, label="y", family="lightgbm", base_params=BASE,
         seed=42, search_space=SPACE, validation=v, artifacts_dir=c, identities=IDENT)
    rec("E2b planted study_name collision with different identity fields", "RESUMED SILENTLY", "BYPASSED")
except TuningError as exc:
    rec("E2b planted study_name collision with different identity fields", str(exc)[:250], "BLOCKED")

print("\n" + json.dumps(res, indent=1))
Path(__file__).with_name("a5_results.json").write_text(json.dumps({"results": res, "tmp": str(TD)}, indent=1))
print("\nBYPASSED:", json.dumps([r for r in res if r["verdict"] in ("BYPASSED", "UNEXPECTED_REJECT", "INCONCLUSIVE")], indent=1))
