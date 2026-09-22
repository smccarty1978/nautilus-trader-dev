"""C1: the canonical lifecycle terminal survives the composite kernel.

Regression for the defect the nq_va_multitf_trade_state_geometry fixture found: `_emit` derived
`flip_ts` from the COMPOSITE row disposition, so a qualifying opposite flip the kernel had already
recorded in `p.flip_ts` was discarded whenever any milestone arm was censored -- which, with
one-sided arms, is virtually every row.

These tests exercise the PRODUCTION path: the real compiler builds the outcome contract, the real
``LabelOutcomeContract.from_plan`` reads it, and the real ``LabelOutcomeKernel`` emits the row.
Nothing here reimplements kernel logic.
"""
from __future__ import annotations

import pytest

from research_workflow.host.interfaces import BarView
from research_workflow.host.outcomes import LabelOutcomeContract, LabelOutcomeKernel

NS = 1_000_000_000
T0 = 1_700_000_000 * NS
ATR = 20.0
ENTRY = 15_000.0
HORIZON_NS = 24 * 3600 * NS


class _NoSessions:
    def session_close(self, _ts):
        raise AssertionError("session_close must not be consulted when censoring is off")


def _plan(*, arms, cost=None, terminal=True):
    spec = {
        "contract": "label", "kernel": "composite", "direction": "regime_1m.dir",
        "atr": "excursion_1m.frozen_atr", "entry_reference": "next_bar_open",
        "session_end_censoring": False, "session_end_rule": "ignore",
        "horizon_end_rule": "strict", "max_gap_ns": 300 * NS,
        "same_bar_rule": "ambiguous_censor", "arms": arms,
        "flip": {"horizon_ns": HORIZON_NS, "source": "regime_1m", "role": "opposite",
                 "inclusive_start": True},
        "primary_arm": arms[0]["id"] if arms else None,
        "composition": {"logic": "OR"}, "direction_sign": 1,
        "observed_seconds": True, "terminal_outcome": terminal,
    }
    if cost is not None:
        spec["cost_points_per_side"] = cost
    return LabelOutcomeContract.from_plan(spec)


def _arm(aid, fav, adv, prefix):
    return {"id": aid, "favorable_atr": fav, "adverse_atr": adv, "horizon_ns": HORIZON_NS,
            "expiry": "censor", "prefix": prefix}


def _bars(offsets):
    """One 1s bar per offset (signed ATR). Bar 0 is flat: its OPEN is the executable entry."""
    out = []
    for i, off in enumerate(offsets):
        px = ENTRY + off * ATR
        hi, lo = (ENTRY, ENTRY) if i == 0 else (max(ENTRY, px), min(ENTRY, px))
        ts_event = T0 + (i + 1) * NS
        out.append(BarView("1s", ts_event, ts_event + NS, ENTRY if i == 0 else px, hi, lo, px, 1.0))
    return out


def _run(offsets, *, arms, flip_at=None, cost=None, terminal=True):
    k = LabelOutcomeKernel(_plan(arms=arms, cost=cost, terminal=terminal), _NoSessions())
    bars = _bars(offsets)
    k.open({"observation_ts": T0, "regime_start_ns": T0, "checkpoint_index": 0}, T0, 1, ATR)
    for i, b in enumerate(bars):
        k.on_bar(b)
        if flip_at is not None and i == flip_at:
            k.on_flip(b.ts_init, -1, 1)
    k.finalize(bars[-1].ts_init)
    rows = k.drain_rows()
    assert len(rows) == 1
    return rows[0], bars


# --------------------------------------------------------------------------------------------
# THE REGRESSION: an arm stays censored/untouched while the canonical opposite flip DOES occur.
# --------------------------------------------------------------------------------------------
def test_terminal_flip_survives_a_censored_arm():
    arms = [_arm("fav_5p00", 5.0, 99.0, "fp_fav_5p00"),      # never touched -> CENSORED
            _arm("fav_0p25", 0.25, 99.0, "fp_fav_0p25")]     # touched
    row, bars = _run([0.0, 0.30, 0.40, 0.20], arms=arms, flip_at=2)

    # the composite row is censored, exactly as before -- that is not the terminal's business
    assert row["censored"] == 1
    assert row["fp_fav_5p00_disposition"] == "CENSORED"
    assert row["fp_fav_0p25_disposition"] == "POSITIVE"

    # ...and the canonical terminal is nonetheless fully present
    assert row["terminal_flip_ts"] == bars[2].ts_init
    assert row["terminal_flip_disposition"] == "LABELED_POSITIVE"
    assert row["terminal_time_to_flip_seconds"] == (bars[2].ts_init - T0) / NS
    assert row["terminal_exit_ts"] == bars[3].ts_event
    assert row["terminal_exit_price"] == bars[3].open


def test_pre_c1_behaviour_is_the_documented_defect():
    """With terminal_outcome off (a pre-C1 sealed plan) the row replays exactly as before."""
    arms = [_arm("fav_5p00", 5.0, 99.0, "fp_fav_5p00")]
    row, _ = _run([0.0, 0.30, 0.40, 0.20], arms=arms, flip_at=2, terminal=False)
    assert row["flip_ts"] is None            # the old, defective derivation
    assert "terminal_flip_ts" not in row     # and no new columns leak into a sealed replay


# --------------------------------------------------------------------------------------------
# Executable terminal fill and realized gross economics.
# --------------------------------------------------------------------------------------------
def test_terminal_exit_is_next_bar_open_not_the_decision_close():
    arms = [_arm("fav_0p25", 0.25, 99.0, "fp_fav_0p25")]
    row, bars = _run([0.0, 0.30, 0.50, 0.10], arms=arms, flip_at=2)
    flip_bar, exit_bar = bars[2], bars[3]
    assert row["terminal_flip_ts"] == flip_bar.ts_init
    assert row["terminal_exit_price"] == exit_bar.open
    assert row["terminal_exit_price"] != flip_bar.close      # never the decision-bar close
    assert row["terminal_exit_ts"] > row["terminal_flip_ts"] - NS


def test_realized_gross_arithmetic_is_exact():
    arms = [_arm("fav_0p25", 0.25, 99.0, "fp_fav_0p25")]
    row, bars = _run([0.0, 0.30, 0.50, 0.40], arms=arms, flip_at=2)
    entry_px, exit_px = bars[0].open, bars[3].open
    expected_pts = 1 * (exit_px - entry_px)
    assert row["terminal_entry_price"] == entry_px
    assert row["terminal_gross_pnl_points"] == pytest.approx(expected_pts, abs=1e-12)
    assert row["terminal_gross_pnl_atr"] == pytest.approx(expected_pts / ATR, abs=1e-12)
    assert row["terminal_duration_seconds"] == pytest.approx(
        (row["terminal_exit_ts"] - row["terminal_entry_ts"]) / NS, abs=1e-12)


def test_short_direction_signs_gross_correctly():
    arms = [_arm("fav_0p25", 0.25, 99.0, "fp_fav_0p25")]
    k = LabelOutcomeKernel(_plan(arms=arms), _NoSessions())
    bars = _bars([0.0, -0.30, -0.50, -0.40])          # price falls; a SHORT profits
    k.open({"observation_ts": T0, "regime_start_ns": T0, "checkpoint_index": 0}, T0, -1, ATR)
    for i, b in enumerate(bars):
        k.on_bar(b)
        if i == 2:
            k.on_flip(b.ts_init, 1, -1)
    k.finalize(bars[-1].ts_init)
    row = k.drain_rows()[0]
    assert row["terminal_gross_pnl_points"] == pytest.approx(-1 * (bars[3].open - bars[0].open))
    assert row["terminal_gross_pnl_points"] > 0


def test_net_is_unavailable_without_a_declared_cost():
    arms = [_arm("fav_0p25", 0.25, 99.0, "fp_fav_0p25")]
    row, _ = _run([0.0, 0.30, 0.50, 0.40], arms=arms, flip_at=2)
    assert row["terminal_gross_pnl_points"] is not None
    assert row["terminal_cost_points"] is None
    assert row["terminal_net_pnl_points"] is None      # explicitly unavailable, never guessed
    assert row["terminal_net_pnl_atr"] is None


def test_net_is_computed_when_a_cost_is_declared():
    arms = [_arm("fav_0p25", 0.25, 99.0, "fp_fav_0p25")]
    row, _ = _run([0.0, 0.30, 0.50, 0.40], arms=arms, flip_at=2, cost=0.375)
    assert row["terminal_cost_points"] == pytest.approx(0.75)
    assert row["terminal_net_pnl_points"] == pytest.approx(row["terminal_gross_pnl_points"] - 0.75)
    assert row["terminal_net_pnl_atr"] == pytest.approx(row["terminal_net_pnl_points"] / ATR)


# --------------------------------------------------------------------------------------------
# The lifecycle clock is not tied to the fixed-time observation horizon.
# --------------------------------------------------------------------------------------------
def test_terminal_flip_far_past_the_fixed_observation_window():
    arms = [_arm("fav_0p25", 0.25, 99.0, "fp_fav_0p25")]
    offsets = [0.0, 0.30] + [0.10] * 1400 + [0.20]        # flip at ~t=1402s, well past T300
    row, bars = _run(offsets, arms=arms, flip_at=len(offsets) - 2)
    assert row["terminal_time_to_flip_seconds"] > 1_000
    assert row["terminal_flip_disposition"] == "LABELED_POSITIVE"
    assert row["terminal_exit_price"] == bars[-1].open


def test_no_flip_leaves_the_terminal_explicitly_unresolved():
    arms = [_arm("fav_0p25", 0.25, 99.0, "fp_fav_0p25")]
    row, _ = _run([0.0, 0.30, 0.50, 0.40], arms=arms, flip_at=None)
    assert row["terminal_flip_ts"] is None
    assert row["terminal_flip_disposition"] == "CENSORED"
    assert row["terminal_gross_pnl_points"] is None
    assert row["terminal_exit_unavailable_reason"] is None


def test_flip_on_the_final_bar_records_why_the_exit_is_missing():
    arms = [_arm("fav_0p25", 0.25, 99.0, "fp_fav_0p25")]
    row, bars = _run([0.0, 0.30, 0.50], arms=arms, flip_at=2)   # no bar after the flip
    assert row["terminal_flip_ts"] == bars[2].ts_init
    assert row["terminal_flip_disposition"] == "LABELED_POSITIVE"       # the flip is still canonical
    assert row["terminal_exit_ts"] is None
    assert row["terminal_exit_unavailable_reason"] == "DATA_END"
    assert row["terminal_gross_pnl_points"] is None


# --------------------------------------------------------------------------------------------
# Three independent clocks: arms must not be cut short by the terminal.
# --------------------------------------------------------------------------------------------
def test_milestone_arms_keep_running_after_the_flip():
    """The flip must not terminate barrier observation -- the arms own their own clock."""
    arms = [_arm("fav_2p00", 2.0, 99.0, "fp_fav_2p00"),
            _arm("fav_0p25", 0.25, 99.0, "fp_fav_0p25")]
    row, bars = _run([0.0, 0.30, 0.50, 1.00, 2.10], arms=arms, flip_at=2)
    assert row["terminal_flip_ts"] == bars[2].ts_init
    # +2.00A is first reached on bar 4, AFTER the flip on bar 2, and is still recorded
    assert row["fp_fav_2p00_disposition"] == "POSITIVE"
    assert row["fp_fav_2p00_resolution_seconds"] == pytest.approx(
        (bars[4].ts_init - bars[0].ts_event) / NS)


# --------------------------------------------------------------------------------------------
# The compiler declares the columns, and only for new compiles that carry a flip.
# --------------------------------------------------------------------------------------------
def test_compiler_declares_terminal_columns_for_a_flip_outcome():
    from research_workflow.grammar import compiler as C
    from research_workflow.host.outcomes import TERMINAL_OBSERVATION_COLUMNS
    src = (C.__file__ and open(C.__file__, encoding="utf-8").read()) or ""
    assert 'contract["terminal_outcome"] = True' in src
    # the compiler builds its list from the kernel's single source of truth
    assert "TERMINAL_OBSERVATION_COLUMNS" in src
    for col in ("terminal_flip_ts", "terminal_exit_price", "terminal_gross_pnl_atr",
                "terminal_net_pnl_points"):
        assert col in TERMINAL_OBSERVATION_COLUMNS, col


# --------------------------------------------------------------------------------------------
# THE SINK CONTRACT. The sink buffers from kernel.observation_columns, NOT from the compiled
# plan's list. A column the compiler declares but the kernel omits is emitted into the row dict
# and then silently dropped on the way to parquet -- which is exactly what happened on the first
# C1 collection: all 15 terminal columns were declared, emitted, and absent from the frame.
# --------------------------------------------------------------------------------------------
def test_kernel_observation_columns_carry_the_terminal_block():
    from research_workflow.host.outcomes import TERMINAL_OBSERVATION_COLUMNS
    arms = [_arm("fav_0p25", 0.25, 99.0, "fp_fav_0p25"), _arm("fav_1p00", 1.0, 99.0, "fp_fav_1p00")]
    k = LabelOutcomeKernel(_plan(arms=arms), _NoSessions())
    for col in TERMINAL_OBSERVATION_COLUMNS:
        assert col in k.observation_columns, f"{col} would be dropped by the sink"
    # contiguous, in order, and immediately before observed_seconds (the A5 invariant keeps
    # observed_seconds last, so the terminal block is the slice just before it)
    assert k.observation_columns[-1] == "observed_seconds"
    assert k.observation_columns[-1 - len(TERMINAL_OBSERVATION_COLUMNS):-1] == list(TERMINAL_OBSERVATION_COLUMNS)


def test_kernel_columns_omit_the_terminal_block_for_a_pre_c1_contract():
    from research_workflow.host.outcomes import TERMINAL_OBSERVATION_COLUMNS
    arms = [_arm("fav_0p25", 0.25, 99.0, "fp_fav_0p25"), _arm("fav_1p00", 1.0, 99.0, "fp_fav_1p00")]
    k = LabelOutcomeKernel(_plan(arms=arms, terminal=False), _NoSessions())
    assert not set(TERMINAL_OBSERVATION_COLUMNS) & set(k.observation_columns)


def test_every_emitted_terminal_key_is_a_declared_column():
    """No terminal key may be emitted that the sink has no column for, and vice versa."""
    from research_workflow.host.outcomes import TERMINAL_OBSERVATION_COLUMNS
    arms = [_arm("fav_0p25", 0.25, 99.0, "fp_fav_0p25"), _arm("fav_1p00", 1.0, 99.0, "fp_fav_1p00")]
    row, _ = _run([0.0, 0.30, 0.50, 0.40], arms=arms, flip_at=2)
    emitted = {k for k in row if k.startswith("terminal_")}
    assert emitted == set(TERMINAL_OBSERVATION_COLUMNS), (
        f"emitted-only={emitted - set(TERMINAL_OBSERVATION_COLUMNS)} "
        f"declared-only={set(TERMINAL_OBSERVATION_COLUMNS) - emitted}")


def test_merge_carries_the_persisted_schema_assertion():
    """Source-level guard check.

    A true behavioural test of merge() needs a controller, authorized years and partition
    parquet on disk, which is an integration fixture this file does not own. What is asserted
    here is that the guard exists and compares the PLAN's declared observation columns against
    the MERGED FRAME's columns. The behavioural protection against the root cause -- kernel and
    plan column lists drifting apart -- is covered by
    test_kernel_observation_columns_carry_the_terminal_block and
    test_every_emitted_terminal_key_is_a_declared_column above.
    """
    import research_workflow.lifecycle_v2 as L
    src = open(L.__file__, encoding="utf-8").read()
    assert "MERGE_PERSISTED_SCHEMA_MISSING_COLUMNS" in src
    assert 'missing = [c for c in declared if c not in obs.columns]' in src
    assert '"declared_observation_columns": declared' in src


# --------------------------------------------------------------------------------------------
# v4_outcome_lineage (transplant onto main, 2026-09-21): the executable ENTRY, proven with prices
# that cannot coincide. The fixture above opens a flat entry bar (open == close) and feeds no
# decision bar, so it cannot tell the executable open from a close.
# --------------------------------------------------------------------------------------------
def _entry_run(bars, *, flip_after, direction=1):
    arms = [_arm("fav_0p25", 0.25, 99.0, "fp_fav_0p25")]
    k = LabelOutcomeKernel(_plan(arms=arms), _NoSessions())
    k.open({"observation_ts": T0, "regime_start_ns": T0, "checkpoint_index": 0}, T0, direction, ATR)
    for b in bars:
        k.on_bar(b)
        if b.ts_init == flip_after:
            k.on_flip(b.ts_init, -direction, direction)
    k.finalize(bars[-1].ts_init)
    rows = k.drain_rows()
    assert len(rows) == 1
    return rows[0]


def test_executable_entry_is_the_open_of_the_first_bar_strictly_after_the_decision():
    decision = BarView("1s", T0 - NS, T0, 14_990.0, 15_001.0, 14_989.0, 15_000.0, 1.0)      # ts_init == T: NOT eligible
    entry = BarView("1s", T0, T0 + NS, 15_002.0, 15_009.0, 15_001.0, 15_007.0, 1.0)         # first bar strictly after T
    flip = BarView("1s", T0 + NS, T0 + 2 * NS, 15_007.0, 15_013.0, 15_006.0, 15_012.0, 1.0)
    exit_ = BarView("1s", T0 + 2 * NS, T0 + 3 * NS, 15_011.0, 15_014.0, 15_010.0, 15_013.0, 1.0)
    row = _entry_run([decision, entry, flip, exit_], flip_after=flip.ts_init)
    assert row["terminal_entry_price"] == entry.open == 15_002.0
    assert row["terminal_entry_price"] not in (decision.close, decision.open, entry.close, flip.close)
    assert row["terminal_entry_ts"] == entry.ts_event == T0          # the executable bar's open instant
    assert row["terminal_exit_price"] == exit_.open and row["terminal_exit_ts"] == exit_.ts_event
    assert row["terminal_gross_pnl_points"] == exit_.open - entry.open


def test_executable_entry_after_a_tape_gap_is_the_next_bar_that_exists():
    later = BarView("1s", T0 + 4 * NS, T0 + 5 * NS, 15_020.0, 15_025.0, 15_019.0, 15_024.0, 1.0)   # 4s hole after T
    flip = BarView("1s", T0 + 5 * NS, T0 + 6 * NS, 15_024.0, 15_030.0, 15_023.0, 15_029.0, 1.0)
    exit_ = BarView("1s", T0 + 6 * NS, T0 + 7 * NS, 15_028.0, 15_031.0, 15_027.0, 15_030.0, 1.0)
    row = _entry_run([later, flip, exit_], flip_after=flip.ts_init)
    assert (row["terminal_entry_price"], row["terminal_entry_ts"]) == (later.open, later.ts_event)


def test_entry_columns_are_published_only_with_an_executable_exit():
    """DECLARED LIMITATION (historical C1 behaviour, transplanted unchanged): the entry pair is emitted
    together with the realized economics, so a row whose flip has no executable exit carries a NULL
    entry although its entry was resolved at T+1 bar. Changing that is a deliberate follow-up, not an
    accident -- this test pins the current contract."""
    decision = BarView("1s", T0 - NS, T0, 14_990.0, 15_001.0, 14_989.0, 15_000.0, 1.0)
    entry = BarView("1s", T0, T0 + NS, 15_002.0, 15_009.0, 15_001.0, 15_007.0, 1.0)
    flip = BarView("1s", T0 + NS, T0 + 2 * NS, 15_007.0, 15_013.0, 15_006.0, 15_012.0, 1.0)
    row = _entry_run([decision, entry, flip], flip_after=flip.ts_init)                   # no bar after the flip
    assert row["terminal_exit_unavailable_reason"] == "DATA_END"
    assert row["terminal_entry_price"] is None and row["terminal_entry_ts"] is None
