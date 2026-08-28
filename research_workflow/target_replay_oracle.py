"""Independent bounded target-contract replay oracle (intentionally NOT a TargetRuntime).

This is a second, deliberately separate implementation of the ordered-barrier semantics.
It derives everything it needs from the compiled ``TargetContract`` and the causal 1s
tape -- candidate T, the frozen candidate-time ATR, the first qualifying 1s OPEN strictly
after T (``entry_reference == "next_bar_open"``), and the barrier race -- and never reads
a runtime-internal pending field such as a pre-populated ``entry_price``.  The collector's
runtime and this oracle are then compared row for row (``validate_target_parity``); a
divergence is a defect.
"""
from __future__ import annotations

from typing import Iterable, Mapping

NS = 1_000_000_000


def _contract_barrier(contract: Mapping) -> tuple[dict | None, str, bool, int | None]:
    """(ordered_barrier, entry_reference, session_end_censoring, max_gap_seconds)."""
    barrier = None
    entry_reference = "next_bar_open"
    session_end_censoring = False
    max_gap_seconds = None
    for fo in (contract.get("required_forward_outcomes") or []):
        entry_reference = fo.get("entry_reference", entry_reference)
        session_end_censoring = bool(fo.get("session_end_censoring", session_end_censoring))
        max_gap_seconds = fo.get("max_gap_seconds", max_gap_seconds)
        for b in (fo.get("ordered_barriers") or []):
            barrier = dict(b)
            break
    return barrier, entry_reference, session_end_censoring, max_gap_seconds


def replay(contract: Mapping, candidate: Mapping, events: Iterable[Mapping]) -> dict:
    primitive = contract.get("primitive")
    if primitive != "ordered_barrier":
        raise ValueError(f"ORACLE_UNKNOWN_TARGET_PRIMITIVE: {primitive!r}")

    barrier, entry_reference, session_end_censoring, max_gap_seconds = _contract_barrier(contract)
    if entry_reference not in ("next_bar_open",):
        raise ValueError(f"ORACLE_UNSUPPORTED_ENTRY_REFERENCE: {entry_reference!r}")

    T = int(candidate["observation_ts"])
    session_close_ts = candidate.get("session_close_ts")
    atr = float(candidate["atr"])
    if not (atr > 0):
        return {"disposition": "CENSORED", "label": None, "censor_reason": "FROZEN_ATR_NONPOSITIVE"}
    direction = int(candidate.get("direction", candidate.get("regime_direction", 1)))
    fav = float(barrier["favorable_atr"]) if barrier else float(candidate["favorable_atr"])
    adv = float(barrier["adverse_atr"]) if barrier else float(candidate["adverse_atr"])
    horizon_s = (
        int(barrier["horizon_seconds"]) if barrier
        else int(candidate.get("horizon_seconds", 0))
    )

    evs = sorted((dict(e) for e in events), key=lambda x: int(x["ts"]))
    independent = any("open" in e for e in evs)

    if independent:
        # Derive the execution reference from the tape, never from a pre-populated field.
        entry_ev = next((e for e in evs if int(e["ts"]) > T), None)
        if entry_ev is None:
            return {"disposition": "CENSORED", "label": None, "censor_reason": "DATA_END"}
        entry_price = float(entry_ev["open"])
        entry_ts = int(entry_ev["ts"]) - NS          # next_bar_open instant
        horizon_end_ts = entry_ts + horizon_s * NS
    else:
        # Legacy fixture: a candidate that already carries its resolved entry.
        entry_price = float(candidate["entry_price"])
        entry_ts = T
        horizon_end_ts = int(candidate["horizon_end_ts"])

    if session_close_ts is not None and horizon_end_ts > int(session_close_ts):
        return {"disposition": "CENSORED", "label": None, "censor_reason": "SESSION_END"}

    good = entry_price + direction * fav * atr
    bad = entry_price - direction * adv * atr
    max_gap_ns = max_gap_seconds * NS if max_gap_seconds is not None else None

    prev_ts = entry_ts
    for e in evs:
        ts = int(e["ts"])
        if ts <= entry_ts:
            continue
        if ts > horizon_end_ts:
            break
        if session_close_ts is not None and ts > int(session_close_ts):
            return {"disposition": "CENSORED", "label": None, "censor_reason": "SESSION_END"}
        if e.get("gap") or (max_gap_ns is not None and ts - prev_ts > max_gap_ns):
            return {"disposition": "CENSORED", "label": None, "censor_reason": "GAP"}
        prev_ts = ts
        hi, lo = e.get("high"), e.get("low")
        if hi is None or lo is None:
            continue
        hi = float(hi); lo = float(lo)
        hit_good = hi >= good if direction > 0 else lo <= good
        hit_bad = lo <= bad if direction > 0 else hi >= bad
        if hit_good and hit_bad:
            return {"disposition": "CENSORED", "label": None, "censor_reason": "AMBIGUOUS_SAME_BAR_TOUCH"}
        if hit_good:
            return {"disposition": "POSITIVE", "label": 1, "censor_reason": None}
        if hit_bad:
            return {"disposition": "NEGATIVE", "label": 0, "censor_reason": None}
    return {"disposition": "NEGATIVE", "label": 0, "censor_reason": None}
