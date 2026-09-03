"""Thin governed hyperparameter tuning for Platform-v2 studies.

Chronology is structural: folds are walk-forward over ``validation.tuning_years`` only (fit on
every earlier tuning year, validate on the next); dev/OOS and prohibited years never enter
(the compiler already refuses tuning years outside TRAIN). The search is bounded by
``validation.max_trials``; the sampler is ``model_selection.random`` (deterministic from
``random_seed``) or ``model_selection.optuna`` (TPE with the same seed, median pruning across
folds, resumable from ``artifacts/tuning_optuna.db``). Every trial is persisted to the ledger
``artifacts/tuning_trials.json`` with the identities the selected configuration is bound to.
"""
from __future__ import annotations

import json
import math
import platform
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

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

    def aggregate(scores: List[Optional[float]]) -> Optional[float]:
        vals = [v for v in scores if v is not None]
        return float(np.mean(vals)) if vals else None

    trials: List[Dict[str, Any]] = []
    if sampler == "random":
        rng = random.Random(int(seed))
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
            trials.append({"number": len(trials), "params": params, "fold_scores": scores, "aggregate": aggregate(scores), "state": "COMPLETE"})
    else:
        try:
            import optuna
        except ImportError as exc:
            raise TuningError("OPTUNA_NOT_INSTALLED: validation.protocol model_selection.optuna needs the optuna package; use model_selection.random or install optuna") from exc
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        storage = f"sqlite:///{(Path(artifacts_dir) / 'tuning_optuna.db').resolve().as_posix()}"
        ostudy = optuna.create_study(study_name=f"{study_id}:{identities.get('plan_sha256', '')[:12]}", storage=storage, load_if_exists=True,
                                     direction="maximize" if maximize else "minimize", sampler=optuna.samplers.TPESampler(seed=int(seed)),
                                     pruner=optuna.pruners.MedianPruner(n_startup_trials=max(3, n_trials // 5)))

        def objective(trial):
            params = _suggest_optuna(trial, search_space)
            def report(value, step):
                if value is not None:
                    trial.report(value if maximize else -value, step)
                    if trial.should_prune():
                        raise optuna.TrialPruned()
            scores = evaluate(params, report)
            trial.set_user_attr("fold_scores", scores)
            agg = aggregate(scores)
            if agg is None:
                raise optuna.TrialPruned()
            return agg

        remaining = max(0, n_trials - len([t for t in ostudy.trials if t.state.is_finished()]))
        if remaining:
            ostudy.optimize(objective, n_trials=remaining, n_jobs=1)
        for t in ostudy.trials:
            trials.append({"number": t.number, "params": dict(t.params), "fold_scores": t.user_attrs.get("fold_scores"), "aggregate": (t.value if t.value is not None else None),
                           "state": str(t.state.name)})
    complete = [t for t in trials if t["aggregate"] is not None]
    if not complete:
        raise TuningError("TUNING_NO_COMPLETE_TRIAL")
    selected = (max if maximize else min)(complete, key=lambda t: t["aggregate"])
    ledger = {"schema_version": 1, "study_id": study_id, **dict(identities), "feature_order": list(features), "label_column": label, "family": family, "base_params": dict(base_params),
              "folds": folds, "sampler": sampler, "sampler_seed": int(seed), "search_space": dict(search_space), "objective": {"metric": metric, "aggregate": "mean_over_folds", "maximize": maximize},
              "n_trials": len(trials), "trials": trials, "selected": {"number": selected["number"], "params": selected["params"], "aggregate": selected["aggregate"]},
              "environment": _versions(), "generated_at_utc": datetime.now(timezone.utc).isoformat()}
    path = Path(artifacts_dir) / "tuning_trials.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2, default=str) + "\n", encoding="utf-8")
    return {"ledger": str(path), "sampler": sampler, "n_trials": len(trials), "selected": ledger["selected"], "folds": folds}


__all__ = ["tune", "walk_forward_folds", "TuningError", "SUPPORTED_METRICS"]
