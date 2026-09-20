"""First-passage integrity proof for the 16 milestone arms of this study.

Required BEFORE collection: prove that the one-sided barrier encoding records exact first-passage
timestamps and the correct favorable/adverse ORDER across the WHOLE flip-to-flip lifecycle, and in
particular that nothing is truncated at the T300 checkpoint bound.

This drives the real ``research_workflow.host.outcomes.LabelOutcomeKernel`` (no reimplementation)
against synthetic 1s bars, and compares every arm against an INDEPENDENT brute-force oracle that
scans the same bars. It touches no platform file and is not a platform test -- it is study
evidence, written and run in the study worktree.

Run:  python studies/nq_va_multitf_trade_state_geometry/fixtures/first_passage_parity.py
Exit: 0 = PASS (writes first_passage_parity.json beside this file), 1 = FAIL.
"""
from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from research_workflow.host.interfaces import BarView                    # noqa: E402
from research_workflow.host.outcomes import LabelOutcomeContract, LabelOutcomeKernel  # noqa: E402

NS = 1_000_000_000
T0 = 1_700_000_000 * NS          # arbitrary UTC anchor
ATR = 20.0                       # frozen 1m entry ATR, points
ENTRY = 15_000.0                 # the next-bar OPEN after T is the executable fill

FAV = [0.25, 0.50, 0.75, 1.00, 1.50, 2.00, 3.00, 4.00, 5.00]
ADV = [0.25, 0.50, 0.75, 1.00, 1.50, 2.00, 3.00]
HORIZON_NS = 24 * 3600 * NS
PARKED = 99.0                    # the unreachable side of each one-sided arm


def _lab(x: float) -> str:
    return f"{x:.2f}".replace(".", "p")


def contract() -> LabelOutcomeContract:
    arms = [{"id": f"fav_{_lab(f)}", "favorable_atr": f, "adverse_atr": PARKED,
             "horizon_ns": HORIZON_NS, "expiry": "censor", "prefix": f"fp_fav_{_lab(f)}"} for f in FAV]
    arms += [{"id": f"adv_{_lab(a)}", "favorable_atr": PARKED, "adverse_atr": a,
              "horizon_ns": HORIZON_NS, "expiry": "censor", "prefix": f"fp_adv_{_lab(a)}"} for a in ADV]
    return LabelOutcomeContract.from_plan({
        "contract": "label", "kernel": "composite", "direction": "regime_1m.dir",
        "atr": "excursion_1m.frozen_atr", "entry_reference": "next_bar_open",
        "session_end_censoring": False, "session_end_rule": "ignore",
        "horizon_end_rule": "strict", "max_gap_ns": 300 * NS,
        "same_bar_rule": "ambiguous_censor", "arms": arms,
        "flip": {"horizon_ns": HORIZON_NS, "source": "regime_1m", "role": "opposite",
                 "inclusive_start": True},
        "primary_arm": "fav_1p00", "composition": {"logic": "OR"},
        "direction_sign": 1, "observed_seconds": True,
    })


class _NoSessions:
    """session_end_censoring is False, so the kernel never consults this."""

    def session_close(self, _ts):  # pragma: no cover - defensive
        raise AssertionError("session_close must not be consulted when censoring is off")


def path_bars(offsets_atr):
    """One 1s bar per entry. offsets_atr[i] is the signed ATR extreme of bar i (LONG convention).

    Bar 0 is the entry bar: its OPEN is the executable fill. Each later bar's high/low straddle
    the requested offset so a touch is unambiguous (only one side moves away from entry).
    """
    bars = []
    for i, off in enumerate(offsets_atr):
        px = ENTRY + off * ATR
        hi, lo = (max(ENTRY, px), min(ENTRY, px))
        if i == 0:
            hi, lo = ENTRY, ENTRY          # entry bar: flat, so no arm resolves on the fill bar
        ts_event = T0 + (i + 1) * NS
        bars.append(BarView("1s", ts_event, ts_event + NS, ENTRY if i == 0 else px, hi, lo, px, 1.0))
    return bars


def oracle(bars, entry_ts):
    """Independent brute force: first bar whose high/low reaches each level, LONG direction."""
    out = {}
    for f in FAV:
        lvl = ENTRY + f * ATR
        hit = next((b for b in bars if b.ts_init > entry_ts and b.high >= lvl), None)
        out[f"fp_fav_{_lab(f)}"] = None if hit is None else (hit.ts_init - entry_ts) / NS
    for a in ADV:
        lvl = ENTRY - a * ATR
        hit = next((b for b in bars if b.ts_init > entry_ts and b.low <= lvl), None)
        out[f"fp_adv_{_lab(a)}"] = None if hit is None else (hit.ts_init - entry_ts) / NS
    return out


def run_case(name, offsets, expect, flip_at_index=None):
    k = LabelOutcomeKernel(contract(), _NoSessions())
    bars = path_bars(offsets)
    k.open({"observation_ts": T0, "regime_start_ns": T0, "checkpoint_index": 0}, T0, 1, ATR)
    for i, b in enumerate(bars):
        k.on_bar(b)
        if flip_at_index is not None and i == flip_at_index:
            k.on_flip(b.ts_init, -1, 1)
    k.finalize(bars[-1].ts_init)
    rows = k.drain_rows()
    assert len(rows) == 1, f"{name}: expected exactly one row, got {len(rows)}"
    row = rows[0]
    entry_ts = bars[0].ts_init - (bars[0].ts_init - bars[0].ts_event)
    exp = oracle(bars, entry_ts)

    failures = []
    for prefix, want_s in exp.items():
        got_s = row.get(f"{prefix}_resolution_seconds")
        disp = row.get(f"{prefix}_disposition")
        fav = prefix.startswith("fp_fav_")
        if want_s is None:
            if disp not in ("CENSORED", None):
                failures.append(f"{prefix}: never touched but disposition={disp}")
        else:
            hit = (disp == "POSITIVE") if fav else (disp == "NEGATIVE")
            if not hit:
                failures.append(f"{prefix}: touched at {want_s}s but disposition={disp}")
            elif abs((got_s or -1) - want_s) > 1e-9:
                failures.append(f"{prefix}: first passage {got_s}s != oracle {want_s}s")
    for k_, v in expect.items():
        if row.get(k_) != v:
            failures.append(f"{k_}: {row.get(k_)!r} != expected {v!r}")
    return name, failures, row, exp


def main() -> int:
    cases = []

    # 1. ORDER: +0.50A is reached at 3s, -0.25A only later at 6s. Both must record their OWN
    #    first passage; the adverse arm must not be pre-empted by the earlier favorable touch.
    cases.append(run_case(
        "order_favorable_then_adverse",
        [0.0, 0.30, 0.60, -0.10, -0.20, -0.30, -0.60],
        {}, flip_at_index=6))

    # 2. ORDER REVERSED: -0.50A first, then +1.00A.
    cases.append(run_case(
        "order_adverse_then_favorable",
        [0.0, -0.30, -0.60, 0.20, 0.60, 1.10],
        {}, flip_at_index=5))

    # 3. THE T300 QUESTION: +2.00A is not reached until t = 1200s, far past the last fixed-time
    #    checkpoint. population.cadence.max_age must NOT truncate arm tracking.
    late = [0.0] + [0.10] * 1199 + [2.10]
    cases.append(run_case("milestone_past_T300", late, {},
                          flip_at_index=len(late) - 1))

    # 4. PARKED SIDE: a path that runs +5.5A must never resolve any adverse arm, and vice versa.
    cases.append(run_case("parked_side_never_fires",
                          [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 5.6],
                          {}, flip_at_index=6))

    results, ok = [], True
    for name, failures, row, exp in cases:
        ok &= not failures
        results.append({"case": name, "status": "PASS" if not failures else "FAIL",
                        "failures": failures,
                        "oracle_first_passage_seconds": exp,
                        "kernel_first_passage_seconds": {
                            p: row.get(f"{p}_resolution_seconds") for p in exp},
                        "kernel_disposition": {p: row.get(f"{p}_disposition") for p in exp},
                        "flip_ts": row.get("flip_ts"),
                        "time_to_flip_seconds": row.get("time_to_flip_seconds")})
        print(f"[{'PASS' if not failures else 'FAIL'}] {name}")
        for f in failures:
            print("    ", f)

    # SEPARATE FINDING -- the flip terminal, which the arms must not cost us.
    flip_lost = [r["case"] for r in results if r["flip_ts"] is None]
    terminal = {
        "check": "COMPOSITE_FLIP_TERMINAL_PRESERVED",
        "verdict": "FAIL" if flip_lost else "PASS",
        "cases_with_null_flip_ts": flip_lost,
        "cause": ("research_workflow/host/outcomes.py LabelOutcomeKernel._emit: for kernel "
                  "'composite' it sets flip_ts = at if disp == POSITIVE else None, discarding the "
                  "recorded p.flip_ts. With one-sided milestone arms most rows compose to "
                  "CENSORED (any arm that never touches expires CENSORED under expiry: censor), "
                  "so flip_ts and time_to_flip_seconds are null on virtually every row."),
        "consequence": ("Adding the milestone arms COSTS the terminal-flip timestamp that the "
                        "pure flip kernel provided. Milestones and the lifecycle terminal cannot "
                        "both be had from the current kernel; this is part of gap C1/T1."),
    }
    for r in results:
        r.pop("flip_ts", None)

    card = {"proof": "FIRST_PASSAGE_INTEGRITY",
            "verdict": "PASS" if ok else "FAIL",
            "terminal_flip_check": terminal,
            "kernel": "research_workflow.host.outcomes.LabelOutcomeKernel (composite)",
            "encoding": f"one-sided arms, unused side parked at {PARKED} ATR",
            "arms": len(FAV) + len(ADV),
            "oracle": "independent brute-force scan of the same synthetic bars",
            "cases": results}
    out = pathlib.Path(__file__).with_name("first_passage_parity.json")
    out.write_text(json.dumps(card, indent=2), encoding="utf-8")
    print(f"\n{card['verdict']}  ->  {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
