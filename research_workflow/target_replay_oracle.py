"""Independent bounded target-contract replay oracle (intentionally NOT a TargetRuntime).

This is a second, deliberately separate implementation of the target semantics.  It
derives everything it needs from the compiled ``TargetContract`` and the causal tape --
candidate T, the frozen candidate-time ATR, the first qualifying 1s OPEN strictly after T
(``entry_reference == "next_bar_open"``), the ordered-barrier race, the flip window, and
the Boolean composition of a composite target -- and never reads a runtime-internal
pending field such as a pre-populated ``entry_price`` or a per-child ``TargetResult``
computed by the runtime.  The collector's runtime and this oracle are then compared row
for row (``validate_target_parity``); a divergence is a defect.

``replay_expression`` re-parses ``conditions`` / ``condition_logic`` off the contract
directly (not via ``target_expression.compile_target_expression``) and re-implements the
monotone ``worst_status`` composition here, so the composition logic is genuinely
independent of the runtime's.
"""
from __future__ import annotations

from typing import Iterable, Mapping

NS = 1_000_000_000
SUPPORTED_ATR_SOURCE = "latest_causally_completed_1m_wilder_atr_14_available_at_T"

# Independent copy of the monotone censor severity (kept deliberately separate from
# research_workflow.target_expression._CENSOR_SEVERITY so the oracle can catch a drift
# in either direction).
_ORACLE_CENSOR_SEVERITY = {
    None: 0, "SESSION_END": 1, "CENSORED_SESSION": 1, "HORIZON": 2, "CENSORED_HORIZON": 2,
    "GAP": 3, "DATA_END": 3, "CENSORED_DATA_END": 3, "AMBIGUOUS_SAME_BAR_TOUCH": 4,
    "AMBIGUOUS_FIRST_TOUCH": 4, "FROZEN_ATR_NONPOSITIVE": 5, "UNRESOLVED_CHILD": 5,
    "MISSING_DATA": 6,
}


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
    declared_source = next((fo.get("atr_source") for fo in (contract.get("required_forward_outcomes") or [])
                            if fo.get("atr_source") is not None), None)
    if declared_source is not None and (declared_source != SUPPORTED_ATR_SOURCE or candidate.get("atr_source") != declared_source):
        return {"disposition": "CENSORED", "label": None, "censor_reason": "ATR_SOURCE_BINDING"}
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


# --- composite target expression -----------------------------------------------------
def _find_forward_outcome(contract: Mapping, fo_id) -> dict:
    for fo in (contract.get("required_forward_outcomes") or []):
        if fo.get("id") == fo_id:
            return dict(fo)
    raise ValueError(f"ORACLE_FORWARD_OUTCOME_MISSING: {fo_id!r}")


def _replay_ordered_barrier_condition(
    contract: Mapping, cond: Mapping, candidate: Mapping, events: Iterable[Mapping]
) -> dict:
    """One ordered-barrier condition, evaluated independently off the tape."""
    fo = _find_forward_outcome(contract, cond.get("forward_outcome_id"))
    barrier = next(
        (b for b in (fo.get("ordered_barriers") or []) if b.get("id") == cond.get("barrier_id")),
        None,
    )
    if barrier is None:
        raise ValueError(f"ORACLE_ORDERED_BARRIER_MISSING: {cond.get('barrier_id')!r}")
    entry_reference = fo.get("entry_reference", "next_bar_open")
    if entry_reference != "next_bar_open":
        raise ValueError(f"ORACLE_UNSUPPORTED_ENTRY_REFERENCE: {entry_reference!r}")

    T = int(candidate["observation_ts"])
    atr = float(candidate["atr"])
    declared_source = fo.get("atr_source")
    if declared_source is not None and (declared_source != SUPPORTED_ATR_SOURCE or candidate.get("atr_source") != declared_source):
        return {"disposition": "CENSORED", "label": None, "censor_reason": "ATR_SOURCE_BINDING"}
    if not (atr > 0):
        return {"disposition": "CENSORED", "label": None, "censor_reason": "FROZEN_ATR_NONPOSITIVE"}
    direction = int(candidate.get("direction", candidate.get("regime_direction", 1)))
    fav = float(barrier["favorable_atr"]); adv = float(barrier["adverse_atr"])
    horizon_s = int(barrier["horizon_seconds"])
    session_close_ts = candidate.get("session_close_ts") if fo.get("session_end_censoring") else None
    max_gap_seconds = fo.get("max_gap_seconds")

    evs = sorted((dict(e) for e in events), key=lambda x: int(x["ts"]))
    entry_ev = next((e for e in evs if int(e["ts"]) > T and e.get("open") is not None), None)
    if entry_ev is None:
        return {"disposition": "CENSORED", "label": None, "censor_reason": "DATA_END"}
    entry_price = float(entry_ev["open"])
    entry_ts = int(entry_ev["ts"]) - NS
    horizon_end_ts = entry_ts + horizon_s * NS

    if session_close_ts is not None and horizon_end_ts > int(session_close_ts):
        return {"disposition": "CENSORED", "label": None, "censor_reason": "SESSION_END"}

    good = entry_price + direction * fav * atr
    bad = entry_price - direction * adv * atr
    max_gap_ns = int(max_gap_seconds) * NS if max_gap_seconds is not None else None

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


def _replay_flip_condition(
    contract: Mapping,
    cond: Mapping,
    candidate: Mapping,
    flip_events: Iterable[Mapping],
    events: Iterable[Mapping],
) -> dict:
    """One flip-within-horizon condition, evaluated independently.

    A flip is observable only over a contiguous tape.  The same gap rule the
    ordered-barrier condition applies (the explicit ``gap`` flag OR an inter-bar delta
    exceeding ``max_gap_seconds``) also bounds the flip window: if the tape is interrupted
    before the horizon closes and no qualifying flip landed first, the flip child is
    ``CENSORED`` (``GAP``), not silently ``DATA_END`` or ``NEGATIVE``.
    """
    T = int(candidate["observation_ts"])
    horizon = cond.get("horizon_seconds") if cond.get("horizon_seconds") is not None else contract.get("horizon_seconds")
    horizon_s = int(horizon)
    end = T + horizon_s * NS
    session_close_ts = candidate.get("session_close_ts") if cond.get("session_end_censoring", False) else None
    if session_close_ts is not None and end > int(session_close_ts):
        return {"disposition": "CENSORED", "label": None, "censor_reason": "SESSION_END"}

    role = str(cond.get("direction") or contract.get("direction") or "opposite")
    prevailing = int(candidate.get("regime_direction", candidate.get("direction", 0)) or 0)
    target = {"opposite": -prevailing, "same": prevailing}.get(role, 0)

    first_flip_ts = None
    for fe in sorted((dict(f) for f in flip_events), key=lambda x: int(x["ts"])):
        ts = int(fe["ts"])
        if T < ts <= end and (target == 0 or int(fe.get("direction", 0)) == target):
            first_flip_ts = ts
            break

    max_gap_seconds = cond.get("max_gap_seconds")
    max_gap_ns = int(max_gap_seconds) * NS if max_gap_seconds is not None else None
    first_gap_ts = None
    prev = T
    for e in sorted((dict(x) for x in events), key=lambda x: int(x["ts"])):
        ts = int(e["ts"])
        if ts <= T:
            prev = ts
            continue
        if ts > end:
            break
        if e.get("gap") or (max_gap_ns is not None and ts - prev > max_gap_ns):
            first_gap_ts = ts
            break
        prev = ts

    if first_flip_ts is not None and (first_gap_ts is None or first_flip_ts <= first_gap_ts):
        return {"disposition": "POSITIVE", "label": 1, "censor_reason": None}
    if first_gap_ts is not None:
        return {"disposition": "CENSORED", "label": None, "censor_reason": "GAP"}

    last_tape_ts = max((int(e["ts"]) for e in events), default=T)
    if last_tape_ts >= end:
        return {"disposition": "NEGATIVE", "label": 0, "censor_reason": None}
    return {"disposition": "CENSORED", "label": None, "censor_reason": "DATA_END"}


def _replay_condition(contract, cond, candidate, events, flip_events) -> dict:
    kind = cond.get("kind")
    if kind == "flip":
        return _replay_flip_condition(contract, cond, candidate, flip_events, events)
    if kind == "ordered_barrier":
        return _replay_ordered_barrier_condition(contract, cond, candidate, events)
    raise ValueError(f"ORACLE_UNSUPPORTED_COMPOSITE_CONDITION_KIND: {kind!r}")


def _compose_monotone(logic: str, child_results: list[dict]) -> dict:
    """Independent monotone ``worst_status`` composition (no Boolean short-circuit)."""
    resolved = [r for r in child_results if r["label"] is not None and r["disposition"] in ("POSITIVE", "NEGATIVE")]
    if len(resolved) != len(child_results):
        unresolved = [r for r in child_results if r not in resolved]
        worst = None; worst_sev = 0
        for r in unresolved:
            reason = r.get("censor_reason") or "UNRESOLVED_CHILD"
            sev = _ORACLE_CENSOR_SEVERITY.get(reason, max(_ORACLE_CENSOR_SEVERITY.values()))
            if sev > worst_sev:
                worst, worst_sev = reason, sev
        return {"disposition": "CENSORED", "label": None, "censor_reason": worst}
    labels = [int(r["label"]) for r in child_results]
    composed = all(labels) if logic == "AND" else any(labels)
    return {"disposition": "POSITIVE" if composed else "NEGATIVE",
            "label": 1 if composed else 0, "censor_reason": None}


def replay_expression(
    contract: Mapping,
    candidate: Mapping,
    events: Iterable[Mapping],
    flip_events: Iterable[Mapping] = (),
) -> dict:
    """Independently evaluate the FULL compiled target expression.

    * no ``conditions`` -> defer to :func:`replay` (single ordered-barrier) or a plain
      flip window.
    * one condition -> that condition, evaluated directly.
    * >= 2 conditions -> per-condition independent evaluation, then monotone composition
      by ``condition_logic`` (``AND``/``OR``; anything else fails closed).
    """
    events = list(events)
    flip_events = list(flip_events)
    conditions = list(contract.get("conditions") or [])

    if not conditions:
        if contract.get("primitive") == "ordered_barrier":
            return replay(contract, candidate, events)
        return _replay_flip_condition(contract, {"kind": "flip"}, candidate, flip_events, events)

    if len(conditions) == 1:
        return _replay_condition(contract, conditions[0], candidate, events, flip_events)

    logic = contract.get("condition_logic")
    if logic not in ("AND", "OR"):
        raise ValueError(f"ORACLE_UNKNOWN_CONDITION_LOGIC: {logic!r}")
    child_results = [
        _replay_condition(contract, c, candidate, events, flip_events) for c in conditions
    ]
    return _compose_monotone(logic, child_results)
