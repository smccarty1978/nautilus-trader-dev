from studies.full_trade_path_builder.implementation.phase_a_core import (
    HORIZON_NS,
    NS,
    SourceProvenance,
    checkpoint_index,
    label_checkpoint,
    should_dispatch,
)


def test_source_boundaries():
    T = 100 * NS
    SourceProvenance(T - NS, T, T - 120 * NS, T - 60 * NS).assert_admissible(T)
    for bad in (
        SourceProvenance(T, T + NS, T - 120 * NS, T - 60 * NS),
        SourceProvenance(T - NS, T + 1, T - 120 * NS, T - 60 * NS),
        SourceProvenance(T - NS, T, T - 60 * NS, T),
    ):
        try:
            bad.assert_admissible(T)
        except ValueError:
            pass
        else:
            raise AssertionError("inadmissible provenance accepted")


def test_label_boundaries_and_censoring():
    T = 1_000 * NS
    assert label_checkpoint(T, T, T + HORIZON_NS).label_flip_le_300 == 0
    assert label_checkpoint(T, T + 299 * NS, T + HORIZON_NS).label_flip_le_300 == 1
    assert label_checkpoint(T, T + 300 * NS, T + HORIZON_NS).label_flip_le_300 == 1
    assert label_checkpoint(T, T + 301 * NS, T + HORIZON_NS).label_flip_le_300 == 0
    censored = label_checkpoint(T, None, T + HORIZON_NS - 1)
    assert censored.censored and censored.label_flip_le_300 is None


def test_dataset_boundary_censor_and_preboundary_flip():
    boundary = 2_000 * NS
    T = boundary - 120 * NS
    assert label_checkpoint(T, None, boundary).censored
    positive = label_checkpoint(T, boundary - NS, boundary)
    assert positive.label_flip_le_300 == 1 and not positive.censored


def test_exact_availability_grid_and_timeout():
    start = 10 * NS
    assert checkpoint_index(start, start + 5 * NS) == 0
    assert checkpoint_index(start, start + 1795 * NS) == 358
    assert checkpoint_index(start, start + 1800 * NS) is None
    assert not should_dispatch(start, start + 6 * NS)
