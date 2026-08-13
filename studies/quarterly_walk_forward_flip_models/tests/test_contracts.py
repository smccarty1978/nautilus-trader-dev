from studies.quarterly_walk_forward_flip_models.implementation.contracts import (
    HORIZON_NS, Quarter, evaluation_mask, first_crossings, resolved_train_mask,
)
import numpy as np


def test_training_boundary_excludes_unresolved_label_window():
    start = Quarter(2023, 2).start
    values = np.array([start - HORIZON_NS - 1, start - HORIZON_NS, start - 1])
    assert resolved_train_mask(values, start).tolist() == [True, False, False]


def test_evaluation_boundary_respects_visible_end():
    q = Quarter(2025, 4)
    values = np.array([q.end - HORIZON_NS, q.end - HORIZON_NS + 1])
    assert evaluation_mask(values, q, q.end).tolist() == [True, False]


def test_crossing_requires_post_gate_transition_and_is_one_per_regime():
    selected = first_crossings(
        np.array([1, 1, 1, 2, 2]),
        np.array([1, 2, 3, 4, 5]),
        np.array([590, 605, 610, 605, 610]),
        np.array([0.1, 0.6, 0.2, 0.1, 0.6]),
        0.5,
    )
    assert selected.tolist() == [False, True, False, False, True]
