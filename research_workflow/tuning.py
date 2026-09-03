"""Thin governed hyperparameter tuning for Platform-v2 studies.

Chronology is structural: folds are walk-forward over ``validation.tuning_years`` only (fit on
every earlier tuning year, validate on the next); dev/OOS and prohibited years never enter
(the compiler already refuses tuning years outside TRAIN). The search is bounded by
``validation.max_trials``; the sampler is ``model_selection.random`` (deterministic from the
sampler seed) or ``model_selection.optuna`` (TPE with the same seed, median pruning across
folds, resumable from ``artifacts/tuning_optuna.db``). Every trial is persisted to the ledger
``artifacts/tuning_trials.json`` with the identities the selected configuration is bound to.

Sampler seed: ``validation.random_seed`` governs sampler randomness (the random sampler's RNG
and the Optuna ``TPESampler`` seed) when present; otherwise the sampler falls back to the
estimator's own seed (``seed``, popped from ``model.params.random_state``/``seed``). The
estimator seed used to fit each fold's model is always ``seed`` — ``random_seed`` never changes
what the model itself does, only how the search explores. The ledger records
``sampler_seed_source`` as ``"validation.random_seed"`` or ``"model.params.random_state"``.

Winner selection: a trial is eligible only if it is COMPLETE (Optuna: ``TrialState.COMPLETE``;
random sampler: every fold evaluated) *and* has a fold_scores list of exactly
``len(folds)`` non-None values. The selected aggregate is always recomputed from those
per-fold scores (``mean_over_folds``) -- never taken from Optuna's own ``trial.value``, which
for a PRUNED trial is its last-reported intermediate (partial) value, not the final objective.
PRUNED / FAIL / RUNNING / WAITING trials, and any trial with a short or partially-None
fold_scores list, are recorded in the ledger with ``eligible: false`` and an
``ineligible_reason`` but can never be selected. If no trial is eligible, ``tune`` raises
``TuningError("TUNING_NO_COMPLETE_TRIAL")``.

Intermediate reporting to the Optuna pruner reports the *raw* per-fold score at every step,
unconditionally (no sign flip for ``brier``). Optuna's ``MedianPruner`` compares intermediate
values across trials at the same step *in the study's own configured direction*
(``direction="minimize"`` for brier, ``"maximize"`` otherwise), so pruning stays consistent
with the objective's polarity without the module manually negating the reported value.

Resume identity: the Optuna study name is derived from a ``tuning_identity`` sha256 computed
over the full set of fields two tuning runs must agree on to safely share trial history:
plan/study identity, the frozen execution closure composite, population identity, target and
feature contracts (including feature order), the preprocessing contract, the tuning chronology
(years + folds), the objective (metric/aggregate/direction), the search space, the sampler seed
and its source, and the model family + base params. On top of the name binding, the full
identity payload is stored as a ``tuning_identity_fields`` study user_attr the first time a
study is created and compared field-by-field on every subsequent load; a mismatch raises
``TuningError("TUNING_RESUME_IDENTITY_MISMATCH: <fields>")`` naming the differing fields rather
than silently resuming (or silently starting over) against incompatible history.
"""
from __future__ import annotations

import hashlib
import json
import math
import platform
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np

SUPPORTED_METRICS = ("roc_auc", "pr_auc", "brier")


class TuningError(RuntimeError):
    pass


def _versions() -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {"python": platform.python_version()}
    for mod in ("numpy", "pandas", "sklearn", "lightgbm", "optuna"):
        try:
            out[mod] = __import__(mod).__version__
        except Exception:
            out[mod] = None
    return out


def walk_forward_folds(tuning_years: List[int]) -> List[Dict[str, Any]]:
    ys = sorted(int(y) for y in tuning_years)
    return [{"fold": f"fold_{y}", "fit_years": [t for t in ys if t < y], "validation_year": y} for i, y in enumerate(ys) if i > 0]


def _sample_random(rng: random.Random, space: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, dom in space.items():
        if "choices" in dom:
            out[name] = rng.choice(list(dom["choices"]))
        elif dom.get("int"):
            out[name] = rng.randint(int(dom["low"]), int(dom["high"]))
        elif dom.get("log"):
            out[name] = math.exp(rng.uniform(math.log(float(dom["low"])), math.log(float(dom["high"]))))
        else:
            out[name] = rng.uniform(float(dom["low"]), float(dom["high"]))
    return out


def _suggest_optuna(trial: Any, space: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, dom in space.items():
        if "choices" in dom:
            out[name] = trial.suggest_categorical(name, list(dom["choices"]))
        elif dom.get("int"):
            out[name] = trial.suggest_int(name, int(dom["low"]), int(dom["high"]))
        else:
            out[name] = trial.suggest_float(name, float(dom["low"]), float(dom["high"]), log=bool(dom.get("log", False)))
    return out


def _score(metric: str, y_true, y_score) -> Optional[float]:
    from research.analysis.metrics import brier, pr_auc, roc_auc
    fn = {"roc_auc": roc_auc, "pr_auc": pr_auc, "brier": brier}[metric]
    return fn(y_true, y_score).to_dict().get("value")


def _recompute_aggregate(fold_scores: Optional[List[Optional[float]]], n_folds: int) -> Tuple[Optional[float], bool, Optional[str]]:
    """Recompute the governed objective from recorded per-fold scores. Eligible only when every
    declared fold reported a non-None score -- never from a sampler's own partial/intermediate value."""
    if fold_scores is None:
        return None, False, "NO_FOLD_SCORES"
    if len(fold_scores) != n_folds:
        return None, False, "INCOMPLETE_FOLDS"
    if any(v is None for v in fold_scores):
        return None, False, "NULL_FOLD_SCORE"
    return float(np.mean([float(v) for v in fold_scores])), True, None


def _tuning_identity(*, study_id: str, identities: Mapping[str, Any], features: List[str], folds: List[Dict[str, Any]],
                      metric: str, maximize: bool, search_space: Mapping[str, Any], sampler_seed: int, sampler_seed_source: str,
                      family: str, base_params: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
    payload = {
        "study_id": study_id,
        "plan_sha256": identities.get("plan_sha256"),
        "execution_closure_composite": identities.get("execution_closure_composite"),
        "population_identity": identities.get("population_identity"),
        "target_contract_sha256": identities.get("target_contract_sha256"),
        "feature_contract_sha256": identities.get("feature_contract_sha256"),
        "feature_order": list(features),
        "preprocessing_contract_sha256": identities.get("preprocessing_contract_sha256"),
        "folds": folds,
        "objective": {"metric": metric, "aggregate": "mean_over_folds", "maximize": maximize},
        "search_space": json.loads(json.dumps(search_space, sort_keys=True, default=str)),
        "sampler_seed": int(sampler_seed),
        "sampler_seed_source": sampler_seed_source,
        "family": family,
        "base_params": json.loads(json.dumps(base_params, sort_keys=True, default=str)),
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest(), payload


def tune(*, study_id: str, frame, features: List[str], label: str, family: str, base_params: Mapping[str, Any], seed: int,
         search_space: Mapping[str, Any], validation: Mapping[str, Any], artifacts_dir: Path, identities: Mapping[str, Any]) -> Dict[str, Any]:
    from research.analysis.modeling import _build_estimator
    protocol = str(validation.get("protocol") or "")
    sampler = "optuna" if protocol.endswith("optuna") else "random"
    metric = str(validation.get("primary_metric") or "roc_auc")
    if metric not in SUPPORTED_METRICS:
        raise TuningError(f"UNSUPPORTED_TUNING_METRIC: {metric}")
    maximize = metric != "brier"
    n_trials = int(validation.get("max_trials") or 20)
    folds = walk_forward_folds(validation.get("tuning_years") or [])
    if not folds:
        raise TuningError("TUNING_NEEDS_TWO_TUNING_YEARS")
    fold_frames = [(frame[frame["_year"].isin(f["fit_years"])], frame[frame["_year"] == f["validation_year"]]) for f in folds]
    for (fit_rows, val_rows), f in zip(fold_frames, folds):
        if fit_rows.empty or val_rows[label].nunique() < 2:
            raise TuningError(f"TUNING_FOLD_DEGENERATE: {f['fold']}")

    raw_seed = validation.get("random_seed")
    if raw_seed is None:
        sampler_seed = int(seed)
        sampler_seed_source = "model.params.random_state"
    else:
        sampler_seed = int(raw_seed)
        sampler_seed_source = "validation.random_seed"

    def evaluate(params: Mapping[str, Any], report=None) -> List[Optional[float]]:
        scores: List[Optional[float]] = []
        for step, (fit_rows, val_rows) in enumerate(fold_frames):
            est = _build_estimator(family, seed, {**dict(base_params), **dict(params)})
            est.fit(fit_rows[features], fit_rows[label].astype(int))
            s = est.predict_proba(val_rows[features])[:, 1]
            scores.append(_score(metric, val_rows[label], s))
            if report is not None:
                report(scores[-1], step)
        return scores

    n_folds = len(folds)
    trials: List[Dict[str, Any]] = []
    if sampler == "random":
        rng = random.Random(sampler_seed)
        seen = set()
        attempts = 0
        while len(trials) < n_trials and attempts < n_trials * 20:
            attempts += 1
            params = _sample_random(rng, search_space)
            key = json.dumps(params, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            scores = evaluate(params)
            agg, eligible, reason = _recompute_aggregate(scores, n_folds)
            trials.append({"number": len(trials), "params": params, "fold_scores": scores, "aggregate": agg, "state": "COMPLETE",
                           "eligible": eligible, "ineligible_reason": reason})
    else:
        try:
            import optuna
        except ImportError as exc:
            raise TuningError("OPTUNA_NOT_INSTALLED: validation.protocol model_selection.optuna needs the optuna package; use model_selection.random or install optuna") from exc
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        tuning_identity, identity_payload = _tuning_identity(study_id=study_id, identities=identities, features=features, folds=folds,
                                                               metric=metric, maximize=maximize, search_space=search_space,
                                                               sampler_seed=sampler_seed, sampler_seed_source=sampler_seed_source,
                                                               family=family, base_params=base_params)
        storage = f"sqlite:///{(Path(artifacts_dir) / 'tuning_optuna.db').resolve().as_posix()}"
        ostudy = optuna.create_study(study_name=f"{study_id}:{tuning_identity[:16]}", storage=storage, load_if_exists=True,
                                     direction="maximize" if maximize else "minimize", sampler=optuna.samplers.TPESampler(seed=sampler_seed),
                                     pruner=optuna.pruners.MedianPruner(n_startup_trials=max(3, n_trials // 5)))
        existing = ostudy.user_attrs.get("tuning_identity_fields")
        if existing is None:
            ostudy.set_user_attr("tuning_identity", tuning_identity)
            ostudy.set_user_attr("tuning_identity_fields", identity_payload)
        else:
            diffs = [k for k in identity_payload if json.dumps(identity_payload[k], sort_keys=True, default=str) != json.dumps(existing.get(k), sort_keys=True, default=str)]
            if diffs:
                raise TuningError(f"TUNING_RESUME_IDENTITY_MISMATCH: {', '.join(sorted(diffs))}")

        def objective(trial):
            params = _suggest_optuna(trial, search_space)
            def report(value, step):
                if value is not None:
                    trial.report(value, step)
                    if trial.should_prune():
                        raise optuna.TrialPruned()
            scores = evaluate(params, report)
            trial.set_user_attr("fold_scores", scores)
            agg, eligible, reason = _recompute_aggregate(scores, n_folds)
            if not eligible:
                trial.set_user_attr("ineligible_reason", reason)
                raise optuna.TrialPruned()
            return agg

        remaining = max(0, n_trials - len([t for t in ostudy.trials if t.state.is_finished()]))
        if remaining:
            ostudy.optimize(objective, n_trials=remaining, n_jobs=1)
        for t in ostudy.trials:
            fold_scores = t.user_attrs.get("fold_scores")
            agg, eligible, reason = _recompute_aggregate(fold_scores, n_folds)
            state = str(t.state.name)
            if state != "COMPLETE":
                eligible = False
                reason = t.user_attrs.get("ineligible_reason") or state
            trials.append({"number": t.number, "params": dict(t.params), "fold_scores": fold_scores, "optuna_value": t.value,
                           "aggregate": agg, "state": state, "eligible": eligible, "ineligible_reason": (None if eligible else reason)})
    eligible_trials = [t for t in trials if t.get("eligible")]
    if not eligible_trials:
        raise TuningError("TUNING_NO_COMPLETE_TRIAL")
    selected = (max if maximize else min)(eligible_trials, key=lambda t: t["aggregate"])
    ledger = {"schema_version": 2, "study_id": study_id, **dict(identities), "feature_order": list(features), "label_column": label, "family": family, "base_params": dict(base_params),
              "folds": folds, "sampler": sampler, "sampler_seed": int(sampler_seed), "sampler_seed_source": sampler_seed_source, "search_space": dict(search_space),
              "objective": {"metric": metric, "aggregate": "mean_over_folds", "maximize": maximize},
              "n_trials": len(trials), "n_eligible": len(eligible_trials), "trials": trials,
              "selected": {"number": selected["number"], "params": selected["params"], "aggregate": selected["aggregate"]},
              "environment": _versions(), "generated_at_utc": datetime.now(timezone.utc).isoformat()}
    path = Path(artifacts_dir) / "tuning_trials.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2, default=str) + "\n", encoding="utf-8")
    return {"ledger": str(path), "sampler": sampler, "n_trials": len(trials), "selected": ledger["selected"], "folds": folds}


__all__ = ["tune", "walk_forward_folds", "TuningError", "SUPPORTED_METRICS"]
