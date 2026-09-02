"""Bounded, TRAIN-only, executable model-selection / hyperparameter-search protocol.

Closes the model-selection governance gap as a real execution path, not a declaration
that is merely trusted. Three properties are structural, not assertions:

* **OOS/prohibited years cannot enter tuning.** Every row consumed here carries
  ``_selection_role`` and ``_year``; a row whose year does not belong to its declared
  role's year set raises ``SelectionPartitionMismatch`` against the *actual data*, not
  just the declared intent (``StudySpec``'s own compile-time validator already rejects a
  ``tuning_years``/``final_train_validation_years`` declaration overlapping
  ``chronology.dev``/``prohibited`` -- this is the second, data-level layer).
* **The search is bounded.** ``grid`` enumerates only ``choice`` domains and refuses to
  silently truncate a grid that exceeds ``max_trials``; ``random`` treats ``max_trials``
  as a count of UNIQUE configurations, de-duplicating deterministically from
  ``random_seed``, and stops cleanly (not an error) if the declared finite space is
  exhausted first.
* **Final TRAIN validation cannot re-select.** ``_evaluate_final_validation`` takes the
  already-selected winner as its only input and has no code path back into the
  candidate loop -- "no retuning after final validation" is a property of the call
  graph, not merely a recorded claim.
"""
from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from research.analysis.identity import canonical_sha256
from research.analysis.metrics import brier, pr_auc, roc_auc
from research.analysis.modeling import SplitPolicy, fit_model
from research.schemas.study_spec import ModelFamilySpec, ModelSelectionSpec

_METRIC_FNS = {"roc_auc": roc_auc, "pr_auc": pr_auc, "brier": brier}

# Consecutive duplicate random draws with no growth in the unique set before declaring
# the space exhausted (or, in the unreachable continuous-space case, stalled).
_RANDOM_SEARCH_RETRY_CAP = 200


class SelectionPartitionMismatch(RuntimeError):
    """A row's _selection_role/_year does not match its declared year set."""


class SearchSpaceExceedsMaxTrials(RuntimeError):
    """A grid search's full cartesian product exceeds max_trials; never silently truncated."""


class RandomSearchStalled(RuntimeError):
    """Defensive-only: the retry cap was hit against an undeclared (continuous) space size."""


class UnsupportedSelectionMetric(RuntimeError):
    """A declared primary/secondary metric name has no registered evaluator."""


def _metric_value(name: str, y_true: Sequence[float], y_score: Sequence[float]) -> Optional[float]:
    fn = _METRIC_FNS.get(name)
    if fn is None:
        raise UnsupportedSelectionMetric(
            f"UNSUPPORTED_SELECTION_METRIC: {name!r} has no registered evaluator "
            f"(supported: {sorted(_METRIC_FNS)})"
        )
    result = fn(y_true, y_score) if name != "brier" else fn(y_true, y_score)
    return result.value


def _assert_partition_and_years(meta: pd.DataFrame, selection: ModelSelectionSpec) -> None:
    if "_partition" not in meta.columns or set(meta["_partition"].dropna()) != {"train"}:
        raise SelectionPartitionMismatch(
            "model selection requires meta['_partition'] to be exclusively 'train'"
        )
    for col in ("_selection_role", "_year"):
        if col not in meta.columns:
            raise SelectionPartitionMismatch(f"model selection requires meta[{col!r}]")
    roles = set(meta["_selection_role"].dropna())
    if not roles <= {"tuning", "final_validation"}:
        raise SelectionPartitionMismatch(
            f"meta['_selection_role'] contains values outside {{tuning, final_validation}}: {roles}"
        )
    tuning_years = set(selection.tuning_years or [])
    final_years = set(selection.final_train_validation_years or [])
    tuning_rows = meta[meta["_selection_role"] == "tuning"]
    bad_tuning = set(tuning_rows["_year"].dropna()) - tuning_years
    if bad_tuning:
        raise SelectionPartitionMismatch(
            f"SELECTION_PARTITION_MISMATCH: tuning-role rows carry years {sorted(bad_tuning)} "
            f"outside declared tuning_years {sorted(tuning_years)}"
        )
    final_rows = meta[meta["_selection_role"] == "final_validation"]
    bad_final = set(final_rows["_year"].dropna()) - final_years
    if bad_final:
        raise SelectionPartitionMismatch(
            f"SELECTION_PARTITION_MISMATCH: final_validation-role rows carry years "
            f"{sorted(bad_final)} outside declared final_train_validation_years {sorted(final_years)}"
        )


@dataclass(frozen=True)
class Candidate:
    family: str
    hyperparameters: Tuple[Tuple[str, Any], ...]  # canonical, sorted

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.hyperparameters)


def _domain_size(h) -> Optional[int]:
    if h.kind == "choice":
        return len(h.values or [])
    if h.kind == "int_range":
        return int(h.high) - int(h.low) + 1
    return None  # float_range: uncountable


def _family_space_size(family: ModelFamilySpec) -> Optional[int]:
    domains = family.tunable_hyperparameters or []
    if not domains:
        return 1
    size = 1
    for h in domains:
        s = _domain_size(h)
        if s is None:
            return None
        size *= s
    return size


def _grid_candidates(families: Sequence[ModelFamilySpec]) -> List[Candidate]:
    out: List[Candidate] = []
    for family in families:
        domains = family.tunable_hyperparameters or []
        if not domains:
            out.append(Candidate(family.family, tuple(sorted((family.fixed_hyperparameters or {}).items()))))
            continue
        keys = [d.name for d in domains]
        for combo in itertools.product(*[d.values for d in domains]):
            cfg = dict(family.fixed_hyperparameters or {})
            cfg.update(zip(keys, combo))
            out.append(Candidate(family.family, tuple(sorted(cfg.items()))))
    return out


def _sample_one(rng: random.Random, family: ModelFamilySpec) -> Candidate:
    cfg = dict(family.fixed_hyperparameters or {})
    for h in family.tunable_hyperparameters or []:
        if h.kind == "choice":
            cfg[h.name] = rng.choice(h.values)
        elif h.kind == "int_range":
            if h.log_scale:
                v = math.exp(rng.uniform(math.log(h.low), math.log(h.high)))
                cfg[h.name] = int(round(v))
            else:
                cfg[h.name] = rng.randint(int(h.low), int(h.high))
        else:  # float_range
            if h.log_scale:
                cfg[h.name] = math.exp(rng.uniform(math.log(h.low), math.log(h.high)))
            else:
                cfg[h.name] = rng.uniform(h.low, h.high)
    return Candidate(family.family, tuple(sorted(cfg.items())))


def _enumerate_candidates(selection: ModelSelectionSpec) -> Tuple[List[Candidate], Dict[str, Any]]:
    """Returns (candidates, search_metadata). search_metadata always carries
    declared_search_space_size, attempted_draw_count, unique_evaluated_count,
    search_space_exhausted -- populated meaningfully only for random search."""
    meta: Dict[str, Any] = {
        "declared_search_space_size": None,
        "attempted_draw_count": 0,
        "unique_evaluated_count": 0,
        "search_space_exhausted": False,
    }
    if selection.search_method == "none":
        candidates = [
            Candidate(f.family, tuple(sorted((f.fixed_hyperparameters or {}).items())))
            for f in selection.allowed_families
        ]
        meta["declared_search_space_size"] = len(candidates)
        meta["unique_evaluated_count"] = len(candidates)
        return candidates, meta

    if selection.search_method == "grid":
        candidates = _grid_candidates(selection.allowed_families)
        space_size = sum(
            (_family_space_size(f) or 0) for f in selection.allowed_families
        )
        meta["declared_search_space_size"] = space_size
        if len(candidates) > selection.max_trials:
            raise SearchSpaceExceedsMaxTrials(
                f"SEARCH_SPACE_EXCEEDS_MAX_TRIALS: grid enumerates {len(candidates)} "
                f"configurations, exceeding max_trials={selection.max_trials}. No silent "
                f"truncation -- narrow the declared domains or raise max_trials."
            )
        meta["attempted_draw_count"] = len(candidates)
        meta["unique_evaluated_count"] = len(candidates)
        return candidates, meta

    # random
    sizes = [_family_space_size(f) for f in selection.allowed_families]
    declared_size = None if any(s is None for s in sizes) else sum(sizes)
    meta["declared_search_space_size"] = declared_size

    rng = random.Random(selection.random_seed)
    families = list(selection.allowed_families)
    seen: set = set()
    ordered: List[Candidate] = []
    draws = 0
    stall = 0
    while len(ordered) < selection.max_trials:
        family = families[draws % len(families)] if families else None
        if family is None:
            break
        draws += 1
        cand = _sample_one(rng, family)
        key = (cand.family, cand.hyperparameters)
        if key in seen:
            stall += 1
            if stall >= _RANDOM_SEARCH_RETRY_CAP:
                if declared_size is not None and len(ordered) >= declared_size:
                    meta["search_space_exhausted"] = True
                    break
                if declared_size is not None:
                    meta["search_space_exhausted"] = True
                    break
                raise RandomSearchStalled(
                    "RANDOM_SEARCH_STALLED: retry cap reached against an undeclared "
                    "(continuous) search space without reaching max_trials -- this is an "
                    "unreachable case under normal declared domains"
                )
            continue
        stall = 0
        seen.add(key)
        ordered.append(cand)
    meta["attempted_draw_count"] = draws
    meta["unique_evaluated_count"] = len(ordered)
    return ordered, meta


def _walk_forward_folds(tuning_years: Sequence[int]) -> List[Dict[str, Any]]:
    years = sorted(tuning_years)
    return [{"fit_years": years[:i], "val_year": years[i]} for i in range(1, len(years))]


def _fit_and_score(
    X: pd.DataFrame, y: pd.Series, meta: pd.DataFrame, fit_years: Sequence[int], val_year: int,
    *, family: str, hyperparameters: Dict[str, Any], seed: int, metric_name: str,
    study_path: "str | Path | None" = None, arm: str = "", config_index: "int | None" = None,
) -> Optional[float]:
    fit_mask = meta["_year"].isin(fit_years)
    val_mask = meta["_year"] == val_year
    if not fit_mask.any() or not val_mask.any():
        return None
    model = fit_model(
        X[fit_mask.values], y[fit_mask.values], arm=family, estimator=family,
        seed=seed, hyperparameters=hyperparameters,
        split_policy=SplitPolicy(kind="explicit_index", description="model_selection inner fold"),
    )
    scores = model.predict_proba(X[val_mask.values])
    value = _metric_value(metric_name, y[val_mask.values], scores)
    # Model contract v2 fit ledger: every actual candidate fit leaves bytes + a permanent row.
    if study_path is not None:
        try:
            from research_workflow.model_store import record_fit
            fit_id = model.provenance.fit_identity_sha256
            record_fit(study_path=Path(study_path), fit_id=fit_id, estimator=model, family=family,
                       row={"selection_status": "candidate", "arm": arm, "config_id": (f"C{config_index}" if config_index is not None else None),
                            "fold_id": f"fit_{'_'.join(str(y_) for y_ in fit_years)}_val_{val_year}", "fit_years": list(fit_years), "validation_year": int(val_year),
                            "seed": seed, "hyperparameters": dict(hyperparameters), "ordered_inputs": list(model.provenance.ordered_features),
                            "metrics": {metric_name: value}, "fit_identity_sha256": fit_id, "library_versions": dict(model.provenance.library_versions)})
        except Exception:  # the ledger is additive; a store failure never changes selection
            pass
    return value


def _evaluate_final_validation(
    X: pd.DataFrame, y: pd.Series, meta: pd.DataFrame, winner: Candidate,
    *, spec: ModelSelectionSpec, inner_score: Optional[float],
) -> Dict[str, Any]:
    """Refits the ALREADY-SELECTED winner and scores it on final_validation-role rows.

    No code path back into the candidate loop -- this function receives the winner as
    an argument and cannot influence which configuration was chosen.
    """
    tuning_mask = meta["_selection_role"] == "tuning"
    final_mask = meta["_selection_role"] == "final_validation"
    model = fit_model(
        X[tuning_mask.values], y[tuning_mask.values], arm=winner.family, estimator=winner.family,
        seed=spec.random_seed or 0, hyperparameters=winner.as_dict(),
        split_policy=SplitPolicy(kind="explicit_index", description="model_selection final validation refit"),
    )
    scores = model.predict_proba(X[final_mask.values])
    y_final = y[final_mask.values]

    metrics: Dict[str, Any] = {}
    if spec.primary_selection_metric:
        metrics[spec.primary_selection_metric] = _metric_value(spec.primary_selection_metric, y_final, scores)
    for m in spec.secondary_metrics or []:
        metrics[m] = _metric_value(m, y_final, scores)
    if spec.calibration_required or (spec.final_validation_requirements and spec.final_validation_requirements.calibration_max_brier is not None):
        metrics.setdefault("brier", _metric_value("brier", y_final, scores))

    status = "PASS"
    reasons: List[str] = []
    req = spec.final_validation_requirements
    if spec.final_validation_policy == "gated" and req:
        primary_val = metrics.get(spec.primary_selection_metric) if spec.primary_selection_metric else None
        if req.primary_metric_bound and primary_val is not None:
            b = req.primary_metric_bound
            if b.minimum is not None and primary_val < b.minimum:
                status, reasons = "FAIL", reasons + [f"{b.metric} {primary_val} < minimum {b.minimum}"]
            if b.maximum is not None and primary_val > b.maximum:
                status, reasons = "FAIL", reasons + [f"{b.metric} {primary_val} > maximum {b.maximum}"]
        if req.max_degradation_vs_inner_validation is not None and inner_score is not None and primary_val is not None:
            if spec.primary_selection_metric_direction == "maximize":
                degradation = (inner_score - primary_val) / abs(inner_score) if inner_score else None
            else:
                degradation = (primary_val - inner_score) / abs(inner_score) if inner_score else None
            if degradation is not None and degradation > req.max_degradation_vs_inner_validation:
                status = "FAIL"
                reasons.append(f"degradation {degradation:.4f} exceeds max {req.max_degradation_vs_inner_validation}")
        if req.calibration_max_brier is not None and metrics.get("brier") is not None:
            if metrics["brier"] > req.calibration_max_brier:
                status = "FAIL"
                reasons.append(f"brier {metrics['brier']} exceeds max {req.calibration_max_brier}")
        for bound in req.secondary_metric_bounds or []:
            val = metrics.get(bound.metric)
            if val is None:
                continue
            if bound.minimum is not None and val < bound.minimum:
                status = "FAIL"
                reasons.append(f"{bound.metric} {val} < minimum {bound.minimum}")
            if bound.maximum is not None and val > bound.maximum:
                status = "FAIL"
                reasons.append(f"{bound.metric} {val} > maximum {bound.maximum}")

    return {"metrics": metrics, "status": status, "reasons": reasons}


def run_model_selection(
    study_path: str | Path,
    X_by_arm: Mapping[str, pd.DataFrame],
    y: pd.Series,
    meta: pd.DataFrame,
    spec: ModelSelectionSpec,
) -> Dict[str, Any]:
    """Runs the declared bounded search per arm and writes
    ``artifacts/model_selection_manifest.json``."""
    _assert_partition_and_years(meta, spec)
    candidates, search_meta = _enumerate_candidates(spec)
    folds = _walk_forward_folds(spec.tuning_years or [])

    winners: Dict[str, Any] = {}
    attempts: Dict[str, List[Dict[str, Any]]] = {}
    final_validation: Dict[str, Any] = {}

    for arm, X in X_by_arm.items():
        scored: List[Tuple[Candidate, Optional[float]]] = []
        arm_attempts: List[Dict[str, Any]] = []
        for cand in candidates:
            fold_scores = [
                _fit_and_score(
                    X, y, meta, fold["fit_years"], fold["val_year"],
                    family=cand.family, hyperparameters=cand.as_dict(), seed=spec.random_seed or 0,
                    metric_name=spec.primary_selection_metric or "roc_auc",
                    study_path=study_path, arm=arm, config_index=candidates.index(cand),
                )
                for fold in folds
            ] if folds else [None]
            valid = [s for s in fold_scores if s is not None]
            avg = sum(valid) / len(valid) if valid else None
            scored.append((cand, avg))
            arm_attempts.append({
                "family": cand.family, "hyperparameters": cand.as_dict(),
                "fold_scores": fold_scores, "average_score": avg,
            })
        attempts[arm] = arm_attempts

        scoreable = [(c, s) for c, s in scored if s is not None]
        if not scoreable:
            raise RuntimeError(f"MODEL_SELECTION_NO_SCOREABLE_CANDIDATES: arm {arm!r}")
        reverse = spec.primary_selection_metric_direction == "maximize"
        best_score = max(s for _, s in scoreable) if reverse else min(s for _, s in scoreable)
        tied = [c for c, s in scoreable if s == best_score]
        tie_break_applied = len(tied) > 1
        if tie_break_applied and spec.simpler_model_tie_preference:
            family_by_name = {f.family: f for f in spec.allowed_families}
            complexity = {f.family: len(f.tunable_hyperparameters or []) for f in spec.allowed_families}
            family_order = {f.family: i for i, f in enumerate(spec.allowed_families)}
            tied.sort(key=lambda c: (complexity[c.family], family_order[c.family]))
        winner = tied[0]

        fv = _evaluate_final_validation(
            X, y, meta, winner, spec=spec, inner_score=best_score,
        ) if spec.final_train_validation_years else {"metrics": {}, "status": "PASS", "reasons": []}
        final_validation[arm] = fv

        winners[arm] = {
            "family": winner.family,
            "hyperparameters": winner.as_dict(),
            "inner_validation_score": best_score,
            "winner_selection_reason": {"rule": "best_primary_metric", "tie_break_applied": tie_break_applied},
        }

    overall_final_status = "PASS"
    if spec.final_validation_policy == "gated":
        if any(fv["status"] != "PASS" for fv in final_validation.values()):
            overall_final_status = "FAIL"

    manifest = {
        "schema_version": 1,
        "search_method": spec.search_method,
        "max_trials": spec.max_trials,
        "random_seed": spec.random_seed,
        "tuning_years": spec.tuning_years,
        "final_train_validation_years": spec.final_train_validation_years,
        "primary_selection_metric": spec.primary_selection_metric,
        "primary_selection_metric_direction": spec.primary_selection_metric_direction,
        "secondary_metrics": spec.secondary_metrics,
        **search_meta,
        "attempts": attempts,
        "winner": winners,
        "final_validation_metric": {arm: fv["metrics"] for arm, fv in final_validation.items()},
        "final_validation_reasons": {arm: fv["reasons"] for arm, fv in final_validation.items()},
        "final_validation_policy": spec.final_validation_policy,
        "final_validation_status": overall_final_status,
        "no_retuning_after_final_validation_assertion": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    manifest["manifest_sha256"] = canonical_sha256(
        {k: v for k, v in manifest.items() if k != "generated_at_utc"}
    )

    out = Path(study_path).resolve() / "artifacts" / "model_selection_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    import json
    out.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return manifest


__all__ = [
    "SelectionPartitionMismatch",
    "SearchSpaceExceedsMaxTrials",
    "RandomSearchStalled",
    "UnsupportedSelectionMetric",
    "run_model_selection",
]
