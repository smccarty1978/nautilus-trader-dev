"""Deterministic contract tests for the generic forward-outcome module.

Every path here is hand-constructed so the expected MFE/MAE/return is arithmetic, not
a regression fixture. A test that only compares against last run's numbers cannot tell
a correct change from a broken one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from research_workflow.forward_outcomes import (
    ConfirmationSpec,
    Direction,
    EntryColumns,
    EntryContext,
    ForwardOutcomeSpec,
    ForwardOutcomeTracker,
    OutcomeAnalysisConfig,
    OutcomeLeakError,
    OutcomeStatus,
    OrderedBarrierDisposition,
    OrderedBarrierSpec,
    ProposedEntry,
    ReferencePrice,
    SelectionError,
    assert_causal_feature_surface,
    assert_outcome_columns_not_registrable,
    assert_partition_parity,
    build_outcome_partitions,
    compute_forward_outcomes,
    first_crossing_entries,
    guard_training_frame,
    is_outcome_column,
    merge_outcome_partitions,
    outcomes_to_frame,
    reconcile_outcome_artifacts,
    required_lookahead_seconds,
    summarize_outcomes,
    write_outcome_artifacts,
)

NS = 1_000_000_000
T0 = pd.Timestamp("2021-06-01 15:00:00", tz="UTC").value

# (high, low, close) for consecutive 1s bars starting at T0.
PATH = [
    (101.0, 99.5, 100.5),   # bar 1: t0 -> t0+1s
    (103.0, 100.0, 102.0),  # bar 2: t0+1s -> t0+2s   <- LONG max favourable (+3)
    (102.0, 97.0, 98.0),    # bar 3: t0+2s -> t0+3s   <- LONG max adverse   (-3)
    (99.0, 98.0, 98.5),     # bar 4: t0+3s -> t0+4s
]


def make_bars(rows, start_ns=T0, step_ns=NS):
    out = []
    t = start_ns
    for high, low, close in rows:
        out.append((t, t + step_ns, high, low, close))
        t += step_ns
    return out


def make_entry(direction="LONG", *, entry_ts=T0, price=100.0, atr=2.0, key="c1", **kw):
    return ProposedEntry(
        study_id="test_study",
        source_period="train",
        candidate_key=key,
        decision_ts=entry_ts,
        entry_ts=entry_ts,
        direction=Direction(direction),
        entry_price=price,
        reference_price=ReferencePrice.DECISION_CLOSE,
        authorization_sha256="auth",
        source_freeze_sha256="freeze",
        entry_atr=atr,
        **kw,
    )


def spec(**kw):
    base = dict(spec_id="test_spec", horizons_seconds=(2, 3), max_tracking_seconds=4)
    base.update(kw)
    return ForwardOutcomeSpec(**base)


# --------------------------------------------------------------------------
# TEST 1 / 2 -- direction-aware excursions
# --------------------------------------------------------------------------

def test_long_path_has_known_mfe_and_mae():
    rows = compute_forward_outcomes([make_entry("LONG")], make_bars(PATH), spec())
    assert len(rows) == 1
    rec = rows[0]
    # entry 100. best high 103 -> +3. worst low 97 -> -3. ATR 2 -> 1.5 ATR each way.
    assert rec["max_mfe"] == pytest.approx(3.0)
    assert rec["max_mae"] == pytest.approx(3.0)
    assert rec["max_mfe_atr"] == pytest.approx(1.5)
    assert rec["max_mae_atr"] == pytest.approx(1.5)
    assert rec["outcome_status"] == OutcomeStatus.RESOLVED.value


def test_short_path_mirrors_the_long_definition():
    rows = compute_forward_outcomes([make_entry("SHORT")], make_bars(PATH), spec())
    rec = rows[0]
    # For a SHORT the favourable side is the low (100 - 97 = +3) and the adverse side
    # is the high (103 - 100 = +3), i.e. the LONG assignment with the roles swapped.
    assert rec["max_mfe"] == pytest.approx(3.0)
    assert rec["max_mae"] == pytest.approx(3.0)
    assert rec["time_to_max_mfe"] == pytest.approx(3.0)   # low set on bar 3
    assert rec["time_to_max_mae"] == pytest.approx(2.0)   # high set on bar 2


def ordered_spec(*, horizon=3, max_tracking=None, max_gap_seconds=1):
    return ForwardOutcomeSpec(
        spec_id="ordered_test",
        horizons_seconds=(horizon,),
        max_tracking_seconds=max_tracking or horizon,
        max_gap_seconds=max_gap_seconds,
        ordered_barriers=(
            OrderedBarrierSpec(
                barrier_id="primary",
                favorable_atr=1.0,
                adverse_atr=0.75,
                horizon_seconds=horizon,
            ),
        ),
    )


@pytest.mark.parametrize(
    ("direction", "rows", "expected"),
    [
        ("LONG", [(102.0, 99.5, 101.0)], OrderedBarrierDisposition.SUCCESS),
        ("LONG", [(101.0, 98.5, 99.0)], OrderedBarrierDisposition.FAILURE),
        ("SHORT", [(100.5, 98.0, 99.0)], OrderedBarrierDisposition.SUCCESS),
        ("SHORT", [(101.5, 99.0, 101.0)], OrderedBarrierDisposition.FAILURE),
    ],
)
def test_asymmetric_ordered_barrier_is_direction_normalized(direction, rows, expected):
    rec = compute_forward_outcomes(
        [make_entry(direction)], make_bars(rows), ordered_spec(horizon=1)
    )[0]
    assert rec["ordered_primary_disposition"] == expected.value
    assert rec["ordered_primary_binary_label"] == (
        1 if expected is OrderedBarrierDisposition.SUCCESS else 0
    )


def test_same_completed_bar_collision_is_ambiguous_and_unlabelled():
    rec = compute_forward_outcomes(
        [make_entry("LONG")], make_bars([(102.0, 98.5, 100.0)]), ordered_spec(horizon=1)
    )[0]
    assert rec["ordered_primary_disposition"] == "AMBIGUOUS_FIRST_TOUCH"
    assert rec["ordered_primary_binary_label"] is None
    assert rec["ordered_primary_time_to_favorable"] == pytest.approx(1.0)
    assert rec["ordered_primary_time_to_adverse"] == pytest.approx(1.0)
    assert rec["ordered_primary_first_touch_ambiguous"] is True


def test_fully_observed_ordered_barrier_timeout_is_negative():
    quiet = [(100.5, 99.5, 100.0)] * 3
    rec = compute_forward_outcomes(
        [make_entry("LONG")], make_bars(quiet), ordered_spec(horizon=3)
    )[0]
    assert rec["ordered_primary_disposition"] == "TIMEOUT"
    assert rec["ordered_primary_binary_label"] == 0


def test_incomplete_ordered_barrier_path_is_censored_and_unlabelled():
    rec = compute_forward_outcomes(
        [make_entry("LONG")],
        make_bars([(100.5, 99.5, 100.0)]),
        ordered_spec(horizon=3),
    )[0]
    assert rec["ordered_primary_disposition"] == "CENSORED"
    assert rec["ordered_primary_binary_label"] is None


def test_ordered_barrier_outputs_are_structurally_blocked_from_training():
    for name in (
        "ordered_primary_binary_label",
        "ordered_primary_disposition",
        "ordered_primary_time_to_favorable",
        "ordered_primary_time_to_adverse",
        "ordered_primary_favorable_touch_ts",
        "ordered_primary_adverse_touch_ts",
        "ordered_primary_first_touch_ambiguous",
        "ordered_primary_censor_reason",
        "ordered_primary_resolved_at_ts",
    ):
        assert is_outcome_column(name)
    with pytest.raises(OutcomeLeakError):
        guard_training_frame(
            pd.DataFrame({"x": [1.0], "ordered_primary_binary_label": [1]}),
            ["x"],
        )


# --------------------------------------------------------------------------
# TEST 3 -- fixed-horizon returns
# --------------------------------------------------------------------------

def test_fixed_horizon_returns_are_direction_signed():
    long_rec = compute_forward_outcomes([make_entry("LONG")], make_bars(PATH), spec())[0]
    short_rec = compute_forward_outcomes([make_entry("SHORT")], make_bars(PATH), spec())[0]

    # Horizon 2s closes on bar 2 (close 102); horizon 3s closes on bar 3 (close 98).
    assert long_rec["price_2s"] == pytest.approx(102.0)
    assert long_rec["return_2s"] == pytest.approx(2.0)
    assert long_rec["return_3s"] == pytest.approx(-2.0)
    assert long_rec["return_2s_atr"] == pytest.approx(1.0)
    assert short_rec["return_2s"] == pytest.approx(-2.0)
    assert short_rec["return_3s"] == pytest.approx(2.0)
    # Final return uses the last observed close (bar 4).
    assert long_rec["final_return"] == pytest.approx(-1.5)


def test_horizon_excursions_are_restricted_to_their_window():
    rec = compute_forward_outcomes([make_entry("LONG")], make_bars(PATH), spec())[0]
    # At 2s the adverse side has only seen bar 1 (low 99.5) and bar 2 (low 100.0).
    assert rec["mae_2s"] == pytest.approx(0.5)
    assert rec["mfe_2s"] == pytest.approx(3.0)
    # By 3s the drop to 97 is inside the window.
    assert rec["mae_3s"] == pytest.approx(3.0)


# --------------------------------------------------------------------------
# TEST 4 -- time to extrema
# --------------------------------------------------------------------------

def test_time_to_extrema_resolves_to_the_setting_bar_close():
    rec = compute_forward_outcomes([make_entry("LONG")], make_bars(PATH), spec())[0]
    assert rec["time_to_max_mfe"] == pytest.approx(2.0)
    assert rec["time_to_max_mae"] == pytest.approx(3.0)
    assert rec["time_to_mfe_2s"] == pytest.approx(2.0)
    assert rec["time_to_mae_2s"] == pytest.approx(1.0)   # bar 1 low 99.5


def test_bar_straddling_the_entry_is_excluded():
    # A bar whose interval starts before the entry carries pre-entry price action.
    entry = make_entry("LONG", entry_ts=T0 + NS // 2)
    rec = compute_forward_outcomes([entry], make_bars(PATH), spec(max_tracking_seconds=4))[0]
    # Bar 1 (t0 -> t0+1s) straddles the entry and must not contribute its 101 high.
    assert rec["first_bar_ts"] == T0 + 2 * NS
    assert rec["bars_observed"] == 3


# --------------------------------------------------------------------------
# TEST 5 -- confirmation-aware pre/post metrics
# --------------------------------------------------------------------------

def test_confirmation_splits_the_path_at_the_confirmation_price():
    conf = ConfirmationSpec(
        confirmation_id="flip_confirm",
        max_wait_seconds=3,
        post_max_tracking_seconds=2,
        post_horizons_seconds=(2,),
    )
    sp = spec(horizons_seconds=(2,), max_tracking_seconds=4, confirmation=conf)
    entry = make_entry("LONG")
    rows = compute_forward_outcomes(
        [entry], make_bars(PATH), sp,
        confirmations={entry.entry_id: (T0 + 2 * NS, 102.0)},
    )
    rec = rows[0]
    assert rec["confirmed"] is True
    assert rec["seconds_to_confirmation"] == pytest.approx(2.0)
    assert rec["confirmation_price"] == pytest.approx(102.0)
    # Pre-confirmation: bars 1-2 only. best high 103 (+3), worst low 99.5 (-0.5).
    assert rec["pre_confirmation_mfe"] == pytest.approx(3.0)
    assert rec["pre_confirmation_mae"] == pytest.approx(0.5)
    # Post-confirmation is measured from 102, over bars 3-4 only.
    assert rec["post_confirmation_mfe"] == pytest.approx(0.0)   # high 102 on bar 3
    assert rec["post_confirmation_mae"] == pytest.approx(5.0)   # low 97 on bar 3
    # Post-confirmation horizon runs from the confirmation, not the entry.
    assert rec["post_confirmation_return_2s"] == pytest.approx(98.5 - 102.0)


def test_unconfirmed_entry_reports_confirmed_false_after_the_wait_window():
    conf = ConfirmationSpec(
        confirmation_id="flip_confirm", max_wait_seconds=2, post_max_tracking_seconds=2
    )
    sp = spec(horizons_seconds=(2,), max_tracking_seconds=4, confirmation=conf)
    rec = compute_forward_outcomes([make_entry("LONG")], make_bars(PATH), sp)[0]
    assert rec["confirmed"] is False
    assert rec["confirmation_ts"] is None
    assert rec["pre_confirmation_mfe"] is None
    assert rec["post_confirmation_mfe"] is None


def test_confirmation_at_exact_wait_deadline_is_accepted():
    conf = ConfirmationSpec(
        confirmation_id="flip_confirm", max_wait_seconds=2, post_max_tracking_seconds=2
    )
    sp = spec(horizons_seconds=(2,), max_tracking_seconds=4, confirmation=conf)
    entry = make_entry("LONG")
    rec = compute_forward_outcomes(
        [entry], make_bars(PATH), sp,
        confirmations={entry.entry_id: (T0 + 2 * NS, 102.0)},
    )[0]
    assert rec["confirmed"] is True
    assert rec["seconds_to_confirmation"] == pytest.approx(2.0)


def test_confirmation_before_its_entry_is_rejected():
    conf = ConfirmationSpec(
        confirmation_id="c", max_wait_seconds=3, post_max_tracking_seconds=2
    )
    sp = spec(horizons_seconds=(2,), max_tracking_seconds=4, confirmation=conf)
    entry = make_entry("LONG")
    tracker = ForwardOutcomeTracker(sp, entries=[entry])
    tracker.on_bar(*make_bars(PATH)[0])
    with pytest.raises(Exception, match="precedes the entry"):
        tracker.record_confirmation(entry.entry_id, T0 - NS, 100.0)


# --------------------------------------------------------------------------
# TEST 6 -- censoring
# --------------------------------------------------------------------------

def test_data_end_censoring_never_shortens_a_horizon():
    sp = spec(horizons_seconds=(2, 10), max_tracking_seconds=30)
    rec = compute_forward_outcomes([make_entry("LONG")], make_bars(PATH), sp)[0]
    assert rec["status_2s"] == OutcomeStatus.RESOLVED.value
    assert rec["mfe_2s"] == pytest.approx(3.0)
    # The 10s horizon was never observable; it is reported as censored with no value
    # rather than being answered from a 4-second window.
    assert rec["status_10s"] == OutcomeStatus.CENSORED_DATA_END.value
    assert rec["mfe_10s"] is None
    assert rec["return_10s"] is None
    assert rec["outcome_status"] == OutcomeStatus.CENSORED_DATA_END.value


def test_session_censoring_marks_horizons_past_the_session_close():
    sp = spec(horizons_seconds=(2, 4), max_tracking_seconds=4,
              session="RTH", session_end_censoring=True)
    entry = make_entry("LONG", session_close_ts=T0 + 2 * NS)
    rec = compute_forward_outcomes([entry], make_bars(PATH), sp)[0]
    assert rec["status_2s"] == OutcomeStatus.RESOLVED.value
    assert rec["status_4s"] == OutcomeStatus.CENSORED_SESSION.value
    assert rec["mfe_4s"] is None
    assert rec["outcome_status"] == OutcomeStatus.CENSORED_SESSION.value
    # Accumulation stopped at the session close, so bar 3's -3 never entered the path.
    assert rec["max_mae"] == pytest.approx(0.5)


def test_entry_with_no_forward_data_still_produces_a_row():
    # Silently dropping an unresolvable member is selection on the future.
    entry = make_entry("LONG", entry_ts=T0 + 100 * NS)
    rows = compute_forward_outcomes([entry], make_bars(PATH), spec())
    assert len(rows) == 1
    assert rows[0]["bars_observed"] == 0
    assert rows[0]["outcome_status"] == OutcomeStatus.MISSING_DATA.value


def test_gap_larger_than_declared_tolerance_is_missing_data():
    sparse = [
        (T0, T0 + NS, 101.0, 99.5, 100.5),
        (T0 + 60 * NS, T0 + 61 * NS, 103.0, 100.0, 102.0),
    ]
    sp = spec(horizons_seconds=(61,), max_tracking_seconds=61, max_gap_seconds=5)
    rec = compute_forward_outcomes([make_entry("LONG")], sparse, sp)[0]
    # Gap is measured close-to-close between consecutive included bars.
    assert rec["max_gap_seconds_observed"] == pytest.approx(60.0)
    assert rec["outcome_status"] == OutcomeStatus.MISSING_DATA.value


# --------------------------------------------------------------------------
# TEST 7 -- multiple overlapping active entries
# --------------------------------------------------------------------------

def test_overlapping_entries_are_measured_independently():
    sp = spec(horizons_seconds=(1,), max_tracking_seconds=3)
    entries = [
        make_entry("LONG", entry_ts=T0, key="a"),
        make_entry("SHORT", entry_ts=T0 + NS, key="b", price=102.0),
        make_entry("LONG", entry_ts=T0 + 2 * NS, key="c", price=98.0),
    ]
    bars = make_bars(PATH)
    together = {r["candidate_key"]: r for r in compute_forward_outcomes(entries, bars, sp)}
    assert len(together) == 3

    # Each entry must produce exactly what it produces alone.
    for entry in entries:
        alone = compute_forward_outcomes([entry], bars, sp)[0]
        shared = together[entry.candidate_key]
        for column in ("max_mfe", "max_mae", "time_to_max_mfe", "time_to_max_mae",
                       "return_1s", "final_return", "outcome_status", "bars_observed"):
            assert shared[column] == alone[column], f"{entry.candidate_key}:{column}"


def test_active_set_drains_as_tracking_budgets_elapse():
    sp = spec(horizons_seconds=(1,), max_tracking_seconds=2)
    entries = [make_entry("LONG", entry_ts=T0 + i * NS, key=f"k{i}") for i in range(3)]
    tracker = ForwardOutcomeTracker(sp, entries=entries)
    seen_peak = 0
    for bar in make_bars(PATH + PATH):
        tracker.on_bar(*bar)
        seen_peak = max(seen_peak, tracker.active_count)
    tracker.finalize()
    # Full future paths are never retained: the live set is bounded by the tracking
    # budget, not by the number of entries seen so far.
    assert seen_peak <= 3
    assert tracker.active_count == 0
    assert len(tracker.records) == 3


# --------------------------------------------------------------------------
# TEST 8 -- partition boundary parity
# --------------------------------------------------------------------------

def test_partitioned_observation_matches_monolithic_exactly():
    sp = spec(horizons_seconds=(2, 4), max_tracking_seconds=6)
    long_path = [(100.0 + (i % 5), 99.0 - (i % 3), 100.0 + ((i * 7) % 4) - 1.5) for i in range(40)]
    bars = make_bars(long_path)
    entries = [
        make_entry("LONG" if i % 2 == 0 else "SHORT", entry_ts=T0 + i * NS, key=f"e{i}")
        for i in range(0, 30, 3)
    ]

    monolithic = pd.DataFrame(compute_forward_outcomes(entries, bars, sp))

    # Split so an entry lands within one tracking budget of the boundary.
    boundary = T0 + 14 * NS
    partitions = build_outcome_partitions(
        [("p1", T0, boundary), ("p2", boundary + 1, T0 + 40 * NS)], sp
    )
    assert required_lookahead_seconds(sp) == 6

    frames = []
    for part in partitions:
        # Each partition reads through its declared lookahead end and emits only its own
        # primary entries.
        part_bars = [b for b in bars if b[1] <= part.lookahead_end_ns]
        frames.append(pd.DataFrame(compute_forward_outcomes(
            entries, part_bars, sp, primary_interval=part.primary_interval
        )))

    merged = merge_outcome_partitions(frames, partitions)
    assert len(merged) == len(monolithic)
    assert assert_partition_parity(monolithic, merged)["passed"] is True


def test_partition_emits_each_entry_exactly_once():
    sp = spec(horizons_seconds=(2,), max_tracking_seconds=3)
    bars = make_bars(PATH * 6)
    entries = [make_entry("LONG", entry_ts=T0 + i * NS, key=f"e{i}") for i in range(12)]
    parts = build_outcome_partitions([("p1", T0, T0 + 5 * NS), ("p2", T0 + 5 * NS + 1, T0 + 20 * NS)], sp)
    frames = [
        pd.DataFrame(compute_forward_outcomes(entries, bars, sp, primary_interval=p.primary_interval))
        for p in parts
    ]
    merged = merge_outcome_partitions(frames, parts)
    assert merged["entry_id"].is_unique
    assert len(merged) == len(entries)


# --------------------------------------------------------------------------
# TEST 9 -- outcomes are unreachable from a causal feature surface
# --------------------------------------------------------------------------

def test_no_outcome_column_resolves_as_a_feature_instance():
    sp = spec(horizons_seconds=(30, 300), max_tracking_seconds=600,
              diagnostic_levels_atr=(1.0,))
    report = assert_outcome_columns_not_registrable(sp)
    assert report["resolvable_as_feature"] == []
    assert report["checked_columns"] > 0


def test_guard_rejects_outcome_columns_in_a_feature_list():
    sp = spec(horizons_seconds=(300,), max_tracking_seconds=600)
    with pytest.raises(OutcomeLeakError, match="OUTCOME_COLUMN_IN_CAUSAL_SURFACE"):
        assert_causal_feature_surface(["ema_slope", "mfe_300s"], spec=sp)
    with pytest.raises(OutcomeLeakError, match="OUTCOME_COLUMN_IN_CAUSAL_SURFACE"):
        # Caught by the structural patterns even with no spec available.
        assert_causal_feature_surface(["ema_slope", "max_mfe_atr", "outcome_status"])


def test_guard_rejects_outcome_columns_riding_along_in_a_training_frame():
    frame = pd.DataFrame({"ema_slope": [1.0], "atr": [2.0], "return_60s_atr": [0.4]})
    with pytest.raises(OutcomeLeakError, match="OUTCOME_COLUMN_IN_TRAINING_FRAME"):
        guard_training_frame(frame, ["ema_slope", "atr"])


def test_guard_does_not_flag_legitimate_causal_features():
    # These are computed from data available before the checkpoint and are real
    # features in this repository. A guard that caught them would be unusable.
    causal = [
        "running_mfe_atr", "running_mae_atr", "current_pnl_atr", "retained_mfe_ratio",
        "atr", "ema_slope", "regime_age_seconds", "arrival_vel_5s", "score",
        "entry_price", "entry_atr", "direction", "candidate_key", "entry_id",
    ]
    assert [c for c in causal if is_outcome_column(c)] == []
    assert_causal_feature_surface(causal)


# --------------------------------------------------------------------------
# TEST 10 -- deterministic artifacts and reconciliation
# --------------------------------------------------------------------------

def _write_run(tmp_path: Path, name: str):
    sp = spec(horizons_seconds=(2, 3), max_tracking_seconds=4)
    entries = [
        make_entry("LONG", entry_ts=T0, key="a", model_id="A", score=0.91),
        make_entry("SHORT", entry_ts=T0 + NS, key="b", price=102.0, model_id="A", score=0.62),
    ]
    records = compute_forward_outcomes(entries, make_bars(PATH), sp)
    out = tmp_path / name
    manifest = write_outcome_artifacts(
        out,
        entries=entries, records=records, spec=sp,
        study_id="test_study", source_period="train",
        authorization_sha256="auth", source_freeze_sha256="freeze",
        source_identity={"catalog": "synthetic", "bar_type": "TEST-1-SECOND"},
        selector_identity={"selector_id": "manual"},
    )
    return out, manifest


def test_artifact_hashes_are_deterministic_and_reconcile(tmp_path):
    out_a, manifest_a = _write_run(tmp_path, "run_a")
    out_b, manifest_b = _write_run(tmp_path, "run_b")

    assert manifest_a["manifest_sha256"] == manifest_b["manifest_sha256"]
    assert manifest_a["entry_set_sha256"] == manifest_b["entry_set_sha256"]
    assert manifest_a["spec_sha256"] == manifest_b["spec_sha256"]
    assert manifest_a["data_class"] == "OUTCOME_LABEL_POST_EVENT"
    assert manifest_a["outcome_table_metadata"]["usable_as_model_input"] is False

    report = reconcile_outcome_artifacts(out_a)
    assert report["passed"] is True, report["findings"]
    assert report["entry_count"] == 2 and report["outcome_count"] == 2


def test_reconciliation_detects_a_tampered_artifact(tmp_path):
    out, _ = _write_run(tmp_path, "run_c")
    frame = pd.read_parquet(out / "forward_outcomes.parquet")
    frame.loc[0, "max_mfe"] = 99.0
    frame.to_parquet(out / "forward_outcomes.parquet", index=False)
    report = reconcile_outcome_artifacts(out)
    assert report["passed"] is False
    assert any("artifact hash drift" in f for f in report["findings"])


def test_persisted_schema_is_exactly_the_spec_generated_schema():
    sp = spec(horizons_seconds=(2,), max_tracking_seconds=4,
              excursion_units=("points", "atr", "ticks"), tick_size=0.25,
              diagnostic_levels_atr=(0.5,))
    records = compute_forward_outcomes([make_entry("LONG")], make_bars(PATH), sp)
    assert set(records[0]) == set(sp.outcome_columns())
    frame = outcomes_to_frame(records, sp)
    assert list(frame.columns) == list(sp.outcome_columns())


# --------------------------------------------------------------------------
# Selection, diagnostics, and analysis
# --------------------------------------------------------------------------

def test_selector_refuses_a_threshold_not_frozen_on_train():
    frame = pd.DataFrame({
        "candidate_key": ["a", "b"], "decision_ts": [T0, T0 + NS],
        "close": [100.0, 101.0], "score": [0.9, 0.4], "atr": [2.0, 2.0],
        "regime": ["r1", "r1"],
    })
    ctx = EntryContext(study_id="s", source_period="oos",
                       authorization_sha256="auth", source_freeze_sha256="freeze")
    cols = EntryColumns(candidate_key="candidate_key", decision_ts="decision_ts",
                        price="close", score="score", atr="atr", direction_value="LONG")
    with pytest.raises(SelectionError, match="frozen on TRAIN"):
        first_crossing_entries(
            frame, context=ctx, columns=cols, group_column="regime",
            threshold_records={"p90": {"threshold": 0.8, "derivation_population": "oos"}},
        )


def test_first_crossing_takes_the_earliest_clearing_row_per_group():
    frame = pd.DataFrame({
        "candidate_key": ["a", "b", "c"],
        "decision_ts": [T0, T0 + NS, T0 + 2 * NS],
        "close": [100.0, 101.0, 102.0],
        "score": [0.85, 0.95, 0.99],
        "atr": [2.0, 2.0, 2.0],
        "regime": ["r1", "r1", "r1"],
    })
    ctx = EntryContext(study_id="s", source_period="oos",
                       authorization_sha256="auth", source_freeze_sha256="freeze",
                       model_id="A", model_hash="h")
    cols = EntryColumns(candidate_key="candidate_key", decision_ts="decision_ts",
                        price="close", score="score", atr="atr", direction_value="LONG")
    entries = first_crossing_entries(
        frame, context=ctx, columns=cols, group_column="regime",
        threshold_records={"p90": {"threshold": 0.90, "derivation_population": "train"}},
    )
    assert len(entries) == 1
    assert entries[0].candidate_key == "b"
    assert entries[0].threshold_id == "p90"
    assert entries[0].model_id == "A"


def test_diagnostic_levels_report_first_touch_and_its_ambiguity():
    sp = spec(horizons_seconds=(3,), max_tracking_seconds=4, diagnostic_levels_atr=(1.0,))
    rec = compute_forward_outcomes([make_entry("LONG")], make_bars(PATH), sp)[0]
    # 1 ATR = 2.0 points. Favourable 1 ATR first reached on bar 2 (high 103);
    # adverse 1 ATR first reached on bar 3 (low 97).
    assert rec["time_to_favorable_1atr"] == pytest.approx(2.0)
    assert rec["time_to_adverse_1atr"] == pytest.approx(3.0)
    assert rec["favorable_before_adverse_1atr"] is True
    assert rec["first_touch_ambiguous_1atr"] is False


def test_same_bar_touch_of_both_levels_is_reported_as_ambiguous():
    sp = spec(horizons_seconds=(1,), max_tracking_seconds=2, diagnostic_levels_atr=(1.0,))
    both = [(103.0, 97.0, 100.0), (100.5, 99.5, 100.0)]
    rec = compute_forward_outcomes([make_entry("LONG")], make_bars(both), sp)[0]
    assert rec["first_touch_ambiguous_1atr"] is True
    assert rec["favorable_before_adverse_1atr"] is False


def test_summary_counts_censored_rows_instead_of_dropping_them():
    sp = spec(horizons_seconds=(2, 10), max_tracking_seconds=30)
    entries = [
        make_entry("LONG", entry_ts=T0, key="a", model_id="A", score_decile=10),
        make_entry("LONG", entry_ts=T0 + NS, key="b", model_id="A", score_decile=1),
    ]
    frame = pd.DataFrame(compute_forward_outcomes(entries, make_bars(PATH), sp))
    config = OutcomeAnalysisConfig(
        mfe_thresholds=(0.5, 1.0), mae_thresholds=(0.5,), horizons_seconds=(2,)
    )
    table = summarize_outcomes(frame, config, group_by=["score_decile"])
    assert set(table["score_decile"]) == {1, 10}
    assert (table["n"] == 1).all()
    # Both rows were censored at the 10s horizon, and the summary says so rather than
    # reporting a resolved population of two.
    assert (table["n_resolved"] == 0).all()
    assert (table["censored_fraction"] == 1.0).all()


def test_spec_rejects_a_horizon_beyond_its_tracking_budget():
    with pytest.raises(Exception, match="exceeds max_tracking_seconds"):
        ForwardOutcomeSpec(spec_id="bad", horizons_seconds=(30, 600), max_tracking_seconds=300)


def test_tracker_rejects_an_entry_whose_reference_price_is_not_the_frozen_one():
    sp = spec(reference_price=ReferencePrice.NEXT_BAR_OPEN)
    with pytest.raises(Exception, match="reference price"):
        ForwardOutcomeTracker(sp, entries=[make_entry("LONG")])


def test_tracker_rejects_atr_units_without_a_frozen_entry_atr():
    with pytest.raises(Exception, match="entry_atr"):
        ForwardOutcomeTracker(spec(), entries=[make_entry("LONG", atr=None)])


# --------------------------------------------------------------------------
# Wiring into the governed fitting path
# --------------------------------------------------------------------------

def _train_meta(n=2):
    return pd.DataFrame({"_partition": ["train"] * n})


def test_fit_models_rejects_a_feature_matrix_carrying_outcome_columns():
    from research_workflow.modeling import fit_models

    X = pd.DataFrame({"ema_slope": [0.1, 0.2], "max_mfe_atr": [1.4, 2.2]})
    y = pd.Series([0, 1])
    # The guard must fire before any estimator is constructed, so spec=None is enough.
    # X is both the declared surface and the frame, so the surface check reports first.
    with pytest.raises(OutcomeLeakError, match="max_mfe_atr"):
        fit_models("studies/does_not_matter", X, y, meta=_train_meta(), spec=None)


def test_freeze_train_artifacts_rejects_a_leaked_frozen_feature_set():
    from research_workflow.modeling import freeze_train_artifacts

    with pytest.raises(OutcomeLeakError, match="OUTCOME_COLUMN_IN_CAUSAL_SURFACE"):
        freeze_train_artifacts(
            "studies/does_not_matter",
            feature_sets={"A": ["ema_slope", "return_300s_atr"]},
            models_manifest={"arms": {}}, preprocessing_hash="h",
            score_arrays={}, meta=_train_meta(),
        )


def test_guard_accepts_the_live_studys_real_feature_names():
    # Regression fence for the wiring above. These are the actual frozen feature sets
    # of the clean_maturity_flip_model study; a substring-matching guard would wrongly
    # flag prior_1m_regime_mfe_atr, rolling_300s_giveback_atr and
    # rolling_300s_max_progress_atr, and would have broken the fitting path.
    live = [
        "arrival_acceleration", "arrival_velocity", "ema_slope",
        "prior_1m_regime_efficiency", "prior_1m_regime_mfe_atr",
        "prior_1m_regime_range_atr", "prior_5m_regime_efficiency",
        "prior_5m_regime_mfe_atr", "prior_5m_regime_range_atr",
        "rolling_300s_current_progress_atr", "rolling_300s_giveback_atr",
        "rolling_300s_max_progress_atr", "rolling_300s_retention_ratio",
    ]
    assert_causal_feature_surface(live)
    guard_training_frame(pd.DataFrame({c: [0.0] for c in live}), live)
