"""``session_end_rule: truncate`` for the BARRIER/COMPOSITE kernel.

The defect this file exists to close: ``truncate`` was implemented for ``kernel: flip``
(``test_session_end_truncate.py``) but not for the barrier/composite path, where the kernel
censored an arm AT SETUP the moment its declared horizon crossed the session close::

    if p.session_close is not None and p.arm_end[i] > p.session_close:
        self._resolve_arm(p, i, CENSORED, p.session_close, "SESSION_END")

With milestone horizons of 24h and a session shorter than 24h that is every arm of every
candidate, so a two-year collection produced 14,549 trades of which 100% were CENSORED /
SESSION_END: no terminal flip, no exit fill, no economics, no resolved milestone. The frame
completed, and was unusable.

``truncate`` means ``effective_end = min(horizon_end, session_close)``: the arm keeps being
evaluated, a touch at or before the effective end resolves at its own first-passage bar, and
only an arm that REACHES the effective end untouched is CENSORED / SESSION_END -- stamped at
the close. The same bound applies to the composite's canonical flip child, independently.

SESSION_END censoring is not itself the error. Some milestones genuinely go untouched when the
trading day ends. The error was deciding that at setup, from the requested horizon alone,
without looking at a single bar. After the repair a normal population is a MIXTURE.

Everything here drives ``research_workflow.host.outcomes.LabelOutcomeKernel`` -- the production
kernel -- never a mirrored reimplementation, and checks it against an independent brute-force
scan and against ``research_workflow.target_replay_oracle.replay``.
"""
from __future__ import annotations

import pytest

from research_workflow.host.interfaces import BarView
from research_workflow.host.outcomes import LabelOutcomeContract, LabelOutcomeKernel
from research_workflow.sessions import CalendarSessionTable

NS = 1_000_000_000
T0 = 1_700_000_000 * NS          # session open
SESSION_SECONDS = 600            # a 10-minute session: every 24h horizon crosses its close
CLOSE = T0 + SESSION_SECONDS * NS
ATR = 20.0
ENTRY_PX = 15_000.0
HORIZON_NS = 24 * 3600 * NS      # the study's declared milestone/flip horizon
PARKED = 99.0                    # the unreachable side of a one-sided milestone arm

FAV = [0.25, 1.00, 5.00]
ADV = [0.25, 1.00]


def _lab(x: float) -> str:
    return f"{x:.2f}".replace(".", "p")


FAV_IDS = [f"fav_{_lab(f)}" for f in FAV]
ADV_IDS = [f"adv_{_lab(a)}" for a in ADV]


def contract(session_end_rule: str = "truncate", *, horizon_ns: int = HORIZON_NS,
             expiry: str = "censor", horizon_end_rule: str = "strict") -> LabelOutcomeContract:
    arms = [{"id": f"fav_{_lab(f)}", "favorable_atr": f, "adverse_atr": PARKED,
             "horizon_ns": horizon_ns, "expiry": expiry, "prefix": f"fp_fav_{_lab(f)}"} for f in FAV]
    arms += [{"id": f"adv_{_lab(a)}", "favorable_atr": PARKED, "adverse_atr": a,
              "horizon_ns": horizon_ns, "expiry": expiry, "prefix": f"fp_adv_{_lab(a)}"} for a in ADV]
    return LabelOutcomeContract.from_plan({
        "contract": "label", "kernel": "composite", "direction": "regime_1m.dir",
        "atr": "excursion_1m.frozen_atr", "entry_reference": "next_bar_open",
        "session_end_censoring": session_end_rule != "ignore",
        "session_end_rule": session_end_rule,
        "horizon_end_rule": horizon_end_rule, "max_gap_ns": 300 * NS,
        "same_bar_rule": "ambiguous_censor", "arms": arms,
        "flip": {"horizon_ns": horizon_ns, "source": "regime_1m", "role": "opposite",
                 "inclusive_start": True},
        "primary_arm": "fav_1p00", "composition": {"logic": "OR"},
        "direction_sign": 1, "observed_seconds": True, "terminal_outcome": True,
    })


def sessions() -> CalendarSessionTable:
    return CalendarSessionTable([(T0, CLOSE)], name="TRADING_DAY")


def bars_from(offsets_atr, *, start_index: int = 0):
    """One 1s bar per offset. ``offsets_atr[i]`` is the signed ATR extreme of bar i.

    Bar 0 is flat at ENTRY_PX so nothing resolves on the executable fill bar itself.
    """
    out = []
    for i, off in enumerate(offsets_atr):
        idx = start_index + i
        px = ENTRY_PX + off * ATR
        hi, lo = max(ENTRY_PX, px), min(ENTRY_PX, px)
        if i == 0:
            hi = lo = px = ENTRY_PX
        ts_event = T0 + idx * NS
        out.append(BarView("1s", ts_event, ts_event + NS, ENTRY_PX if i == 0 else px, hi, lo, px, 1.0))
    return out


def pad_past_close(bars, until=None):
    """Hold the last price flat until the tape runs past the close.

    A tape that simply STOPS before the close is DATA_END, not SESSION_END -- a different and
    equally correct censor reason. To say anything about SESSION_END the bars must actually
    reach the close.
    """
    until = (CLOSE + 5 * NS) if until is None else until
    last = bars[-1]
    px = last.close
    ts_event = last.ts_event
    while ts_event + NS <= until:
        ts_event += NS
        bars.append(BarView("1s", ts_event, ts_event + NS, px, px, px, px, 1.0))
    return bars


def run(offsets, *, session_end_rule="truncate", flip_at_index=None, pad=True,
        T=T0, session_table=None, **ckw):
    """Drive the production kernel over one candidate and return (row, bars, kernel)."""
    bars = bars_from(offsets)
    if pad:
        pad_past_close(bars)
    k = LabelOutcomeKernel(contract(session_end_rule, **ckw),
                           sessions() if session_table is None else session_table)
    k.open({"observation_ts": T, "regime_start_ns": T, "checkpoint_index": 0}, T, 1, ATR)
    for i, b in enumerate(bars):
        k.on_bar(b)
        if flip_at_index is not None and i == flip_at_index:
            k.on_flip(b.ts_init, -1, 1)
    k.finalize(bars[-1].ts_init)
    rows = k.drain_rows()
    assert len(rows) == 1, f"expected exactly one row, got {len(rows)}"
    return rows[0], bars, k


def brute_force_first_passage(bars, entry_ts):
    """Independent scan: first bar strictly after the entry instant reaching each level."""
    out = {}
    for f in FAV:
        lvl = ENTRY_PX + f * ATR
        hit = next((b for b in bars if b.ts_init > entry_ts and b.high >= lvl), None)
        out[f"fp_fav_{_lab(f)}"] = None if hit is None else hit.ts_init
    for a in ADV:
        lvl = ENTRY_PX - a * ATR
        hit = next((b for b in bars if b.ts_init > entry_ts and b.low <= lvl), None)
        out[f"fp_adv_{_lab(a)}"] = None if hit is None else hit.ts_init
    return out


# A path that spends the whole session inside +-0.30A, then a late +0.30A drift: nothing beyond
# +-0.25A is ever reached, so the arms above it must go untouched to the close.
def _quiet(n):
    return [0.0] + [0.10 if i % 2 else -0.10 for i in range(n - 1)]


# --------------------------------------------------------------------------------------- #
# 1-2. a barrier resolves BEFORE the close although its declared horizon runs past it
# --------------------------------------------------------------------------------------- #
def test_favorable_barrier_resolves_before_session_close_under_truncate():
    offsets = [0.0, 0.30, 0.60, 1.10] + [1.0] * 20
    row, bars, _ = run(offsets)
    touch = bars[3]
    assert row["fp_fav_0p25_disposition"] == "POSITIVE"
    assert row["fp_fav_1p00_disposition"] == "POSITIVE"
    # exact first passage, not the close
    assert row["fp_fav_1p00_resolution_seconds"] == (touch.ts_init - bars[0].ts_event) / NS
    assert row["fp_fav_1p00_censor_reason"] is None
    # and +5.00A, never reached, is the SESSION_END case -- at the close, not at setup
    assert row["fp_fav_5p00_disposition"] == "CENSORED"
    assert row["fp_fav_5p00_censor_reason"] == "SESSION_END"


def test_adverse_barrier_resolves_before_session_close_under_truncate():
    offsets = [0.0, -0.30, -0.60, -1.10] + [-1.0] * 20
    row, bars, _ = run(offsets)
    touch = bars[3]
    assert row["fp_adv_0p25_disposition"] == "NEGATIVE"
    assert row["fp_adv_1p00_disposition"] == "NEGATIVE"
    assert row["fp_adv_1p00_resolution_seconds"] == (touch.ts_init - bars[0].ts_event) / NS
    assert row["fp_adv_1p00_censor_reason"] is None


# --------------------------------------------------------------------------------------- #
# 3. an untouched arm is SESSION_END only once the EFFECTIVE end is actually reached
# --------------------------------------------------------------------------------------- #
def test_untouched_arm_is_censored_only_when_the_truncated_end_is_reached():
    k = LabelOutcomeKernel(contract("truncate"), sessions())
    k.open({"observation_ts": T0, "regime_start_ns": T0, "checkpoint_index": 0}, T0, 1, ATR)
    bars = bars_from(_quiet(SESSION_SECONDS + 5))
    mid = SESSION_SECONDS // 2
    for i, b in enumerate(bars):
        k.on_bar(b)
        if i == mid:
            # THE REGRESSION: mid-session, with the close still ahead, every arm must still be
            # OPEN. Pre-repair all five were already CENSORED/SESSION_END on the entry bar.
            assert len(k.pending) == 1
            p = k.pending[0]
            assert p.arm_open == len(FAV) + len(ADV), \
                f"arms resolved before the effective end: {p.arm_state}"
            assert all(e == CLOSE for e in p.arm_end), "effective end must be the session close"
            assert all(p.arm_truncated), "every 24h arm is truncated by a 10-minute session"
    k.finalize(bars[-1].ts_init)
    row = k.drain_rows()[0]
    for arm_id in FAV_IDS + ADV_IDS:
        pre = f"fp_{arm_id}"
        assert row[f"{pre}_disposition"] == "CENSORED", arm_id
        assert row[f"{pre}_censor_reason"] == "SESSION_END", arm_id
        # stamped at the close it failed to survive -- never at the 24h horizon, never later
        assert row[f"{pre}_resolution_seconds"] == (CLOSE - bars[0].ts_event) / NS, arm_id


def test_truncate_never_resolves_an_arm_from_a_bar_past_the_close():
    """The mirror failure of `ignore`: a +5.00A move AFTER the close must not resolve the arm."""
    offsets = _quiet(SESSION_SECONDS + 2) + [5.5] * 10
    row, _, _ = run(offsets)
    assert row["fp_fav_5p00_disposition"] == "CENSORED"
    assert row["fp_fav_5p00_censor_reason"] == "SESSION_END"


# --------------------------------------------------------------------------------------- #
# 4-5. the canonical opposite flip and its executable next-bar-open exit fill
# --------------------------------------------------------------------------------------- #
def test_opposite_flip_before_the_close_survives_into_the_terminal_columns():
    offsets = [0.0, 0.30, 0.60, 0.40, 0.35] + [0.30] * 20
    flip_i = 3
    row, bars, _ = run(offsets, flip_at_index=flip_i)
    flip_bar, exit_bar, entry_bar = bars[flip_i], bars[flip_i + 1], bars[0]
    assert row["terminal_flip_ts"] == flip_bar.ts_init
    assert row["terminal_flip_disposition"] == "LABELED_POSITIVE"
    assert row["terminal_flip_censor_reason"] is None
    assert row["terminal_time_to_flip_seconds"] == (flip_bar.ts_init - T0) / NS
    # 5. executable fill: the OPEN of the first bar strictly after the flip, never the close
    assert row["terminal_exit_ts"] == exit_bar.ts_event
    assert row["terminal_exit_price"] == exit_bar.open
    assert row["terminal_exit_price"] != flip_bar.close
    assert row["terminal_entry_price"] == entry_bar.open
    want = exit_bar.open - entry_bar.open
    assert row["terminal_gross_pnl_points"] == pytest.approx(want)
    assert row["terminal_gross_pnl_atr"] == pytest.approx(want / ATR)
    assert row["terminal_net_pnl_points"] is None          # no declared cost -> explicitly absent


def test_flip_after_the_close_is_session_end_not_a_cross_session_terminal():
    offsets = _quiet(SESSION_SECONDS + 20)
    row, bars, _ = run(offsets, flip_at_index=SESSION_SECONDS + 5)
    assert bars[SESSION_SECONDS + 5].ts_init > CLOSE
    assert row["terminal_flip_ts"] is None
    assert row["terminal_flip_disposition"] == "CENSORED"
    assert row["terminal_flip_censor_reason"] == "SESSION_END"
    assert row["terminal_exit_price"] is None


# --------------------------------------------------------------------------------------- #
# 6. first-passage ORDER stays exact against an independent scan
# --------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("offsets", [
    [0.0, 0.30, 0.60, -0.10, -0.30, -0.60, -1.10, 1.10],     # favorable first, then adverse
    [0.0, -0.30, -0.60, 0.20, 0.60, 1.10, -1.10],            # adverse first, then favorable
    [0.0, 0.26, -0.26, 0.30, -0.30],                         # only the 0.25A pair is reachable
])
def test_first_passage_order_is_exact_under_truncate(offsets):
    row, bars, _ = run(offsets)
    entry_ts = bars[0].ts_event
    expected = brute_force_first_passage(bars, entry_ts)
    for prefix, want_ts in expected.items():
        got = row[f"{prefix}_resolution_seconds"]
        disp = row[f"{prefix}_disposition"]
        if want_ts is None or want_ts > CLOSE:
            assert disp == "CENSORED" and row[f"{prefix}_censor_reason"] == "SESSION_END", prefix
        else:
            assert disp == ("POSITIVE" if prefix.startswith("fp_fav_") else "NEGATIVE"), prefix
            assert got == (want_ts - entry_ts) / NS, prefix


def test_kernel_agrees_with_the_independent_replay_oracle_under_truncate():
    from research_workflow.target_replay_oracle import replay
    offsets = [0.0, 0.30, 0.60, 1.10, 0.80, -0.30, -0.60, -1.10] + [0.2] * 30
    row, bars, _ = run(offsets)
    events = [{"ts": b.ts_init, "open": b.open, "high": b.high, "low": b.low} for b in bars]
    mismatches = []
    for arm_id, fav, adv in ([(f"fav_{_lab(f)}", f, PARKED) for f in FAV]
                             + [(f"adv_{_lab(a)}", PARKED, a) for a in ADV]):
        oracle_contract = {
            "primitive": "ordered_barrier", "session_end_rule": "truncate",
            "required_forward_outcomes": [{
                "id": "fo", "entry_reference": "next_bar_open", "session_end_censoring": True,
                "max_gap_seconds": 300,
                "ordered_barriers": [{"id": arm_id, "favorable_atr": fav, "adverse_atr": adv,
                                      "horizon_seconds": HORIZON_NS // NS,
                                      "horizon_expiry_policy": "censor",
                                      "horizon_end_rule": "strict"}]}]}
        cand = {"observation_ts": T0, "atr": ATR, "regime_direction": 1,
                "session_close_ts": CLOSE, "barrier_id": arm_id}
        o = replay(oracle_contract, cand, events)
        pre = f"fp_{arm_id}"
        if o["disposition"] != row[f"{pre}_disposition"] or o["censor_reason"] != row[f"{pre}_censor_reason"]:
            mismatches.append((arm_id, row[f"{pre}_disposition"], row[f"{pre}_censor_reason"],
                               o["disposition"], o["censor_reason"]))
    assert not mismatches, mismatches


# --------------------------------------------------------------------------------------- #
# 7. the C1 terminal fixture is unaffected (it runs under session_end_rule: ignore)
# --------------------------------------------------------------------------------------- #
def test_c1_first_passage_terminal_fixture_still_passes():
    from research_workflow.tests import test_first_passage_oracle_parity as c1
    assert c1.main() == 0
    import json
    card = json.loads(c1.CARD_PATH.read_text(encoding="utf-8"))
    assert card["verdict"] == "PASS"
    assert card["terminal_flip_check"]["verdict"] == "PASS"
    assert card["terminal_flip_check"]["cases_with_null_flip_ts"] == []


# --------------------------------------------------------------------------------------- #
# 8. ordinary censor / ignore semantics are untouched
# --------------------------------------------------------------------------------------- #
def test_censor_still_voids_an_overlong_window_at_the_close():
    """Unchanged: every arm is decided at SETUP, so a +1.10A touch two bars later is invisible
    and the row is already emitted before the flip at bar 3 can be recorded."""
    offsets = [0.0, 0.30, 0.60, 1.10] + [1.0] * 20
    k = LabelOutcomeKernel(contract("censor"), sessions())
    k.open({"observation_ts": T0, "regime_start_ns": T0, "checkpoint_index": 0}, T0, 1, ATR)
    bars = bars_from(offsets)
    k.on_bar(bars[0])
    k.on_bar(bars[1])                      # the entry bar: censor decides everything here
    rows = k.drain_rows()
    assert len(rows) == 1 and not k.pending, "censor must still resolve at the entry bar"
    row = rows[0]
    for arm_id in FAV_IDS + ADV_IDS:
        assert row[f"fp_{arm_id}_disposition"] == "CENSORED", arm_id
        assert row[f"fp_{arm_id}_censor_reason"] == "SESSION_END", arm_id
    assert row["censor_reason"] == "SESSION_END"
    assert row["resolved_at_ts"] == CLOSE
    assert row["terminal_flip_ts"] is None


def test_censor_is_unchanged_for_a_horizon_that_fits_inside_the_session():
    """Additivity: where the close is not binding, truncate and censor agree exactly."""
    offsets = [0.0, 0.30, 0.60, 1.10, -0.30, -0.60, -1.10] + [0.1] * 60
    short = 30 * NS
    cols = [f"fp_{a}_{s}" for a in FAV_IDS + ADV_IDS
            for s in ("disposition", "censor_reason", "resolution_seconds")]
    a, _, _ = run(offsets, session_end_rule="censor", horizon_ns=short, pad=False)
    b, _, _ = run(offsets, session_end_rule="truncate", horizon_ns=short, pad=False)
    assert {c: a[c] for c in cols} == {c: b[c] for c in cols}
    assert a["disposition"] == b["disposition"] and a["censor_reason"] == b["censor_reason"]


def test_ignore_still_sees_past_the_close():
    offsets = _quiet(SESSION_SECONDS + 2) + [5.5] * 10
    row, _, _ = run(offsets, session_end_rule="ignore")
    assert row["fp_fav_5p00_disposition"] == "POSITIVE"


def test_expiry_negative_is_unchanged_when_the_horizon_fits():
    offsets = [0.0] + [0.05] * 60
    row, _, _ = run(offsets, session_end_rule="truncate", horizon_ns=30 * NS, expiry="negative", pad=False)
    assert row["fp_fav_5p00_disposition"] == "NEGATIVE"
    assert row["fp_fav_5p00_censor_reason"] is None


def test_a_truncated_arm_is_session_end_not_the_negative_expiry_policy():
    """`expiry: negative` describes a FULL horizon elapsing. A window the close cut short did
    not elapse, so it must censor rather than manufacture a negative label."""
    offsets = _quiet(SESSION_SECONDS + 5)
    row, _, _ = run(offsets, session_end_rule="truncate", expiry="negative")
    assert row["fp_fav_5p00_disposition"] == "CENSORED"
    assert row["fp_fav_5p00_censor_reason"] == "SESSION_END"


def test_a_tape_gap_still_outranks_session_end_under_truncate():
    bars = bars_from(_quiet(10))
    resume = bars[-1].ts_event + 600 * NS          # 600s > max_gap 300s, still before this close
    bars.append(BarView("1s", resume, resume + NS, ENTRY_PX, ENTRY_PX, ENTRY_PX, ENTRY_PX, 1.0))
    k = LabelOutcomeKernel(contract("truncate"), CalendarSessionTable([(T0, resume + 3600 * NS)]))
    k.open({"observation_ts": T0, "regime_start_ns": T0, "checkpoint_index": 0}, T0, 1, ATR)
    for b in bars:
        k.on_bar(b)
    k.finalize(bars[-1].ts_init)
    row = k.drain_rows()[0]
    assert row["fp_fav_5p00_censor_reason"] == "GAP"


# --------------------------------------------------------------------------------------- #
# 9. one row carrying resolved arms, censored arms AND an independent terminal flip
# --------------------------------------------------------------------------------------- #
def test_a_mixed_composite_carries_resolved_and_censored_arms_and_a_real_terminal():
    offsets = [0.0, 0.30, 0.60, -0.30, -0.60, 0.20] + [0.15] * 30
    flip_i = 5
    row, bars, _ = run(offsets, flip_at_index=flip_i)
    resolved = [a for a in FAV_IDS + ADV_IDS if row[f"fp_{a}_disposition"] in ("POSITIVE", "NEGATIVE")]
    censored = [a for a in FAV_IDS + ADV_IDS if row[f"fp_{a}_disposition"] == "CENSORED"]
    assert resolved and censored, (resolved, censored)
    assert set(row[f"fp_{a}_censor_reason"] for a in censored) == {"SESSION_END"}
    # the terminal is independent of the aggregate: the row-level composite still censors
    assert row["disposition"] == "CENSORED"
    assert row["terminal_flip_ts"] == bars[flip_i].ts_init
    assert row["terminal_gross_pnl_atr"] is not None


# --------------------------------------------------------------------------------------- #
# 10. THE SANITY GATE: a normal population must not be 100% immediate SESSION_END
# --------------------------------------------------------------------------------------- #
def test_a_normal_truncate_population_is_a_mixture_not_total_session_end_censoring():
    """The assertion that would have failed the v3 collection before it was analysed.

    Many candidates spread across one session over a path that reaches several milestones and
    flips twice. Pre-repair every arm of every candidate was CENSORED/SESSION_END and every
    terminal was null; the collection still "completed".
    """
    import math

    n = SESSION_SECONDS + 30
    offsets = [0.0] + [1.6 * math.sin(i / 40.0) for i in range(1, n)]
    bars = bars_from(offsets)
    flip_indices = {120, 400}
    k = LabelOutcomeKernel(contract("truncate"), sessions())
    opened = 0
    for i, b in enumerate(bars):
        if i % 20 == 0 and b.ts_init < CLOSE - 60 * NS:
            k.open({"observation_ts": b.ts_init, "regime_start_ns": b.ts_init,
                    "checkpoint_index": opened}, b.ts_init, 1, ATR)
            opened += 1
        k.on_bar(b)
        if i in flip_indices:
            k.on_flip(b.ts_init, -1, 1)
    k.finalize(bars[-1].ts_init)
    rows = k.drain_rows()
    assert len(rows) == opened > 10

    arm_cells = [(r, a) for r in rows for a in FAV_IDS + ADV_IDS]
    resolved_milestones = sum(1 for r, a in arm_cells if r[f"fp_{a}_disposition"] in ("POSITIVE", "NEGATIVE"))
    session_end_milestones = sum(1 for r, a in arm_cells if r[f"fp_{a}_censor_reason"] == "SESSION_END")
    resolved_terminals = sum(1 for r in rows if r["terminal_flip_ts"] is not None)
    session_end_terminals = sum(1 for r in rows if r["terminal_flip_censor_reason"] == "SESSION_END")

    # the four gates the post-collection verification must apply to the real frame
    assert resolved_terminals > 0, "RESOLVED_TERMINAL_COUNT == 0"
    assert resolved_milestones > 0, "RESOLVED_MILESTONE_COUNT == 0"
    assert session_end_terminals < len(rows), "ALL_TERMINALS_SESSION_END"
    assert session_end_milestones < len(arm_cells), "ALL_MILESTONES_SESSION_END"
    # and it is a genuine mixture in both directions: censoring still happens
    assert session_end_milestones > 0
    assert any(r["terminal_gross_pnl_atr"] is not None for r in rows)
