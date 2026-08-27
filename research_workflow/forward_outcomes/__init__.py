"""Generic forward-outcome / economic-path observation.

    research idea -> causal features -> ML score -> proposed entry (frozen)
                                                          |
                                                          v
                                          forward path -> economic outcome

The package owns only the second half of that pipeline. A prediction system decides
*when* and *why* to enter; this layer answers one question about the result --
"what happened after that proposed entry?" -- and nothing else.

Everything here is study-agnostic. Nothing imports a regime engine, a flip definition,
an instrument, or a classifier. A study supplies a :class:`ForwardOutcomeSpec` and an
immutable set of :class:`ProposedEntry` anchors; the package supplies observation,
censoring, partition parity, provenance and descriptive analysis.

Outcome data is post-event by construction. Every artifact is stamped
``OUTCOME_LABEL_POST_EVENT`` and ``guard.py`` refuses to let those columns enter a
causal feature surface.
"""

from research_workflow.forward_outcomes.analysis import (
    OutcomeAnalysisConfig,
    confidence_ranking_report,
    summarize_group,
    summarize_outcomes,
)
from research_workflow.forward_outcomes.contracts import (
    BarInclusion,
    ConfirmationSpec,
    Direction,
    ForwardOutcomeError,
    ForwardOutcomeSpec,
    OrderedBarrierDisposition,
    OrderedBarrierSpec,
    OutcomeStatus,
    ProposedEntry,
    ReferencePrice,
    build_outcome_columns,
    horizon_label,
    level_label,
    worst_status,
)
from research_workflow.forward_outcomes.governance import (
    OutcomeProvenanceError,
    outcomes_to_frame,
    reconcile_outcome_artifacts,
    write_outcome_artifacts,
)
from research_workflow.forward_outcomes.guard import (
    OUTCOME_DATA_CLASS,
    OutcomeLeakError,
    assert_causal_feature_surface,
    assert_outcome_columns_not_registrable,
    find_outcome_columns,
    guard_training_frame,
    is_outcome_column,
    outcome_column_namespace,
    outcome_table_metadata,
)
from research_workflow.forward_outcomes.partition import (
    OutcomePartition,
    PartitionParityError,
    assert_partition_parity,
    build_outcome_partitions,
    merge_outcome_partitions,
    partitions_from_specs,
    required_lookahead_seconds,
)
from research_workflow.forward_outcomes.selection import (
    EntryColumns,
    EntryContext,
    SelectionError,
    assign_frozen_deciles,
    build_entries,
    entries_to_frame,
    first_crossing_entries,
    local_score_maximum_entries,
    score_decile_entries,
    threshold_crossing_entries,
    validate_frozen_threshold,
)
from research_workflow.forward_outcomes.tracker import (
    ForwardObservation,
    ForwardOutcomeTracker,
    compute_forward_outcomes,
)

__all__ = [
    # contracts
    "BarInclusion", "ConfirmationSpec", "Direction", "ForwardOutcomeError",
    "ForwardOutcomeSpec", "OrderedBarrierDisposition", "OrderedBarrierSpec", "OutcomeStatus", "ProposedEntry", "ReferencePrice",
    "build_outcome_columns", "horizon_label", "level_label", "worst_status",
    # observation
    "ForwardObservation", "ForwardOutcomeTracker", "compute_forward_outcomes",
    # selection
    "EntryColumns", "EntryContext", "SelectionError", "assign_frozen_deciles",
    "build_entries", "entries_to_frame", "first_crossing_entries",
    "local_score_maximum_entries", "score_decile_entries",
    "threshold_crossing_entries", "validate_frozen_threshold",
    # partitioning
    "OutcomePartition", "PartitionParityError", "assert_partition_parity",
    "build_outcome_partitions", "merge_outcome_partitions", "partitions_from_specs",
    "required_lookahead_seconds",
    # guard
    "OUTCOME_DATA_CLASS", "OutcomeLeakError", "assert_causal_feature_surface",
    "assert_outcome_columns_not_registrable", "find_outcome_columns",
    "guard_training_frame", "is_outcome_column", "outcome_column_namespace",
    "outcome_table_metadata",
    # governance
    "OutcomeProvenanceError", "outcomes_to_frame", "reconcile_outcome_artifacts",
    "write_outcome_artifacts",
    # analysis
    "OutcomeAnalysisConfig", "confidence_ranking_report", "summarize_group",
    "summarize_outcomes",
]
