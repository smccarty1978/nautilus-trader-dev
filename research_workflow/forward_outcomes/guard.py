"""Hard separation between post-event outcomes and causal feature surfaces.

A forward outcome is, by construction, information from after the entry that produced
it. It is a label. The failure this module exists to prevent is not malice but
convenience: an outcome table joined onto a candidate table for analysis, then handed
to a fitter whose feature list was derived from "every numeric column".

Two independent barriers:

1. **Exact.** :func:`outcome_column_namespace` regenerates the schema from the spec, so
   the guard always knows precisely which columns a given spec produces.
2. **Structural.** :data:`OUTCOME_COLUMN_PATTERNS` matches the generated naming grammar
   even when no spec is at hand. The patterns are anchored to that grammar on purpose --
   ``running_mfe_atr`` is a legitimate causal feature in this repository and must not be
   caught, while ``mfe_300s`` and ``max_mfe_atr`` must be.

The registry check closes the third route: an outcome column must never resolve to a
FeatureInstance, because a name that resolves is a name a study contract can request.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional, Sequence

from research_workflow.forward_outcomes.contracts import (
    ForwardOutcomeSpec,
    build_outcome_columns,
)

# Declared role of every forward-outcome artifact. Persisted into the manifest so a
# downstream consumer can refuse the table on its own terms.
OUTCOME_DATA_CLASS = "OUTCOME_LABEL_POST_EVENT"

# Identity columns are shared with the entry table and are causal by construction, so
# they are exempt: joining outcomes back to entries must not trip the guard.
CAUSAL_IDENTITY_COLUMNS: frozenset[str] = frozenset({
    "entry_id", "candidate_key", "study_id", "source_period", "regime_id",
    "decision_ts", "entry_ts", "direction", "entry_price", "entry_atr",
    "model_id", "model_hash", "score", "score_decile", "threshold_id",
    "maturity_bucket", "maturity_seconds", "selector_id",
    "spec_sha256", "entry_sha256", "authorization_sha256", "source_freeze_sha256",
})

OUTCOME_COLUMN_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p) for p in (
        r"^(mfe|mae|return)_\d+s(_atr|_ticks)?$",
        r"^time_to_(mfe|mae)_\d+s$",
        r"^(price|status)_\d+s$",
        r"^(mfe_mae_ratio|return_over_mae|mfe_minus_mae|retained_mfe_fraction|giveback_from_mfe)_\d+s$",
        r"^(max_mfe|max_mae|final_return)(_atr|_ticks)?$",
        r"^time_to_max_(mfe|mae)$",
        r"^final_price$",
        r"^(max_mfe_mae_ratio|final_return_over_mae|max_mfe_minus_max_mae)$",
        r"^(retained_mfe_fraction_final|giveback_from_max_mfe)$",
        r"^time_to_(favorable|adverse)_[0-9p]+atr$",
        r"^(favorable_before_adverse|first_touch_ambiguous)_[0-9p]+atr$",
        r"^(pre|post)_confirmation_.+$",
        r"^confirmed$",
        r"^confirmation_(ts|price)$",
        r"^seconds_to_confirmation$",
        r"^outcome_status$",
        r"^censor_reason$",
        r"^resolved_at_ts$",
        r"^tracked_seconds$",
        r"^bars_observed$",
        r"^(first|last)_bar_ts$",
        r"^max_gap_seconds_observed$",
    )
)


class OutcomeLeakError(RuntimeError):
    """Raised when post-event outcome data reaches a causal feature surface."""


def outcome_column_namespace(spec: ForwardOutcomeSpec) -> frozenset[str]:
    """Every column this spec generates, minus the causal identity columns."""
    return frozenset(build_outcome_columns(spec)) - CAUSAL_IDENTITY_COLUMNS


def is_outcome_column(name: str, spec: Optional[ForwardOutcomeSpec] = None) -> bool:
    if name in CAUSAL_IDENTITY_COLUMNS:
        return False
    if spec is not None and name in outcome_column_namespace(spec):
        return True
    return any(pattern.match(name) for pattern in OUTCOME_COLUMN_PATTERNS)


def find_outcome_columns(
    names: Iterable[str], spec: Optional[ForwardOutcomeSpec] = None
) -> list[str]:
    return sorted({n for n in names if is_outcome_column(str(n), spec)})


def assert_causal_feature_surface(
    feature_names: Iterable[str],
    *,
    spec: Optional[ForwardOutcomeSpec] = None,
    context: str = "causal feature surface",
) -> None:
    """Fail closed when a feature list contains forward-outcome columns."""
    leaked = find_outcome_columns(feature_names, spec)
    if leaked:
        raise OutcomeLeakError(
            f"OUTCOME_COLUMN_IN_CAUSAL_SURFACE: {context} contains {len(leaked)} "
            f"post-event outcome column(s): {leaked[:10]}"
            f"{'...' if len(leaked) > 10 else ''}. Forward outcomes are labels; they "
            f"resolve after the entry that produced them and can never be model inputs."
        )


def guard_training_frame(
    frame: Any,
    feature_columns: Sequence[str],
    *,
    spec: Optional[ForwardOutcomeSpec] = None,
    context: str = "training frame",
) -> None:
    """Guard both the declared feature list and any outcome columns riding along.

    Checking only ``feature_columns`` would miss the common accident, which is a frame
    that was joined with outcomes and a fitter that later re-derives its own column list
    from the frame.
    """
    assert_causal_feature_surface(feature_columns, spec=spec, context=context)
    frame_columns = getattr(frame, "columns", None)
    columns = list(frame_columns) if frame_columns is not None else []
    riding = find_outcome_columns(columns, spec)
    if riding:
        raise OutcomeLeakError(
            f"OUTCOME_COLUMN_IN_TRAINING_FRAME: {context} carries {len(riding)} "
            f"post-event outcome column(s): {riding[:10]}"
            f"{'...' if len(riding) > 10 else ''}. Drop them before fitting; a feature "
            f"list derived from this frame would silently absorb them."
        )


def assert_outcome_columns_not_registrable(spec: ForwardOutcomeSpec) -> dict[str, Any]:
    """Assert no outcome column can be resolved as a FeatureInstance.

    A study contract requests features by name through ``features.registry``. If an
    outcome column ever resolved there, a contract could legally declare it and every
    downstream causal check would pass. This asserts the registry has no such door.
    """
    from features.registry import resolve_feature_request

    resolvable: list[str] = []
    for name in sorted(outcome_column_namespace(spec)):
        try:
            resolve_feature_request(name, {})
        except Exception:
            continue
        resolvable.append(name)
    if resolvable:
        raise OutcomeLeakError(
            f"OUTCOME_COLUMN_IS_REGISTRABLE_FEATURE: {resolvable} resolve through "
            f"features.registry and could therefore be declared as model inputs."
        )
    return {
        "spec_sha256": spec.spec_sha256,
        "checked_columns": len(outcome_column_namespace(spec)),
        "resolvable_as_feature": [],
        "data_class": OUTCOME_DATA_CLASS,
    }


def outcome_table_metadata(spec: ForwardOutcomeSpec) -> Mapping[str, Any]:
    """Self-describing marker persisted alongside every outcome artifact."""
    return {
        "data_class": OUTCOME_DATA_CLASS,
        "causal_relative_to_entry": False,
        "usable_as_model_input": False,
        "spec_sha256": spec.spec_sha256,
        "outcome_columns": sorted(outcome_column_namespace(spec)),
    }
