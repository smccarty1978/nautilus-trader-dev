"""Compiled target-contract -> executable target-runtime binding.

Target labels are runtime semantics.  This module is deliberately independent from
the collector so a bounded replay can prove the emitted disposition before TRAIN.

A ``composite`` target (``condition_logic: AND``/``OR`` over two or more conditions) is
executed by :class:`CompositeTargetRuntime`, which owns one child ``TargetRuntime`` per
condition and composes their terminal results through
:mod:`research_workflow.target_expression` -- MONOTONE ``worst_status`` composition, no
Boolean short-circuit (see that module).  A single-condition or plain ``flip`` target is
unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib, json
from pathlib import Path
from typing import Any, Iterable, Mapping

from research_workflow.target_expression import (
    CENSORED,
    NEGATIVE,
    PENDING,
    POSITIVE,
    TargetExpression,
    TargetExpressionError,
    TargetResult,
    compile_target_expression,
    runtime_executable,
)

NS = 1_000_000_000
SUPPORTED_ATR_SOURCE = "latest_causally_completed_1m_wilder_atr_14_available_at_T"


class TargetRuntimeError(RuntimeError): pass

class TargetRuntime:
    primitive: str = ""
    def terminal(self, candidate: Mapping[str, Any], events: Iterable[Mapping[str, Any]], *, final: bool = True) -> TargetResult:
        raise NotImplementedError
    def ingest_flip(self, pending: dict, flip_event: Mapping[str, Any]) -> None:
        """A prevailing-regime flip observed on the forward path.  No-op for runtimes
        whose label does not depend on flip events (ordered barrier)."""
        return None
    def from_disposition(self, disposition: str, *, resolved_at_ts: int | None = None,
                         censor_reason: str | None = None) -> TargetResult:
        if disposition in {POSITIVE, "LABELED_POSITIVE"}: return TargetResult(disposition, 1, resolved_at_ts)
        if disposition in {NEGATIVE, "LABELED_NEGATIVE"}: return TargetResult(disposition, 0, resolved_at_ts)
        return TargetResult(disposition, None, resolved_at_ts, censor_reason)

class FlipTargetRuntime(TargetRuntime):
    primitive = "flip_within_horizon"

    # RT-05: semantic target-contract fields this runtime actually consumes at execution
    # time, and the allowed values where the runtime supports only a subset. A non-default
    # authored value for a semantic field that is in neither CONSUMED_SEMANTIC_FIELDS nor
    # PROVENANCE_ONLY_SEMANTIC_FIELDS (for the resolved runtime) is rejected before seal
    # (TARGET_SEMANTIC_FIELD_UNSUPPORTED) rather than silently ignored.
    CONSUMED_SEMANTIC_FIELDS = frozenset({
        "horizon_seconds", "session_end_censoring", "max_gap_seconds",
        "event", "direction", "target_direction_role", "confirmation",
    })
    PROVENANCE_ONLY_SEMANTIC_FIELDS = frozenset()
    # A flip event IS a completed-bar regime flip confirmed over one bar -- that is the
    # regime engine's intrinsic behaviour, so a matching confirmation is satisfied by
    # construction. Anything else (multi-bar confirmation, a tick mode) has no runtime.
    SUPPORTED_SEMANTIC_VALUES = {
        "confirmation.mode": {"bar_close", "completed_1m_bar"},
        "confirmation.confirmation_bars": {None, 1},
    }

    # -- runtime-owned pending lifecycle (composite child) ---------------------
    def open_pending(self, candidate: Mapping[str, Any]) -> dict:
        T = int(candidate["observation_ts"])
        horizon_s = int(candidate["horizon_seconds"])
        role = str(candidate.get("target_direction_role", "opposite"))
        prevailing = int(
            candidate.get("regime_direction", candidate.get("direction", 0)) or 0
        )
        # "opposite" -> the flip that ends the prevailing regime; "same" -> a flip back
        # into it; 0 (unknown) -> any established flip.
        target_direction = {
            "opposite": -prevailing,
            "same": prevailing,
        }.get(role, 0)
        return {
            "flip_events": [],
            "observation_ts": T,
            "horizon_end_ts": T + horizon_s * NS,
            "session_close_ts": (
                int(candidate["session_close_ts"])
                if candidate.get("session_close_ts") is not None else None
            ),
            "target_direction": int(target_direction),
            "max_gap_seconds": (
                int(candidate["max_gap_seconds"])
                if candidate.get("max_gap_seconds") is not None else None
            ),
            "gap": False,
            "gap_ts": None,
            "prev_ts": T,
            "last_ts": T,
        }

    def ingest_bar(self, pending: dict, bar: Mapping[str, Any]) -> None:
        if "flip_events" not in pending:
            return
        ts = int(bar["ts"])
        if ts <= pending["prev_ts"]:
            pending["last_ts"] = max(pending["last_ts"], ts)
            return
        # Same gap rule as the ordered-barrier child: an explicit gap flag OR an inter-bar
        # delta over max_gap_seconds interrupts the flip window.
        mg = pending.get("max_gap_seconds")
        if not pending["gap"] and (
            bar.get("gap") or (mg is not None and ts - pending["prev_ts"] > mg * NS)
        ):
            pending["gap"], pending["gap_ts"] = True, ts
        pending["prev_ts"] = ts
        pending["last_ts"] = ts

    def ingest_flip(self, pending: dict, flip_event: Mapping[str, Any]) -> None:
        if "flip_events" not in pending:
            return
        pending["flip_events"].append(
            {"ts": int(flip_event["ts"]), "direction": int(flip_event.get("direction", 0))}
        )

    def parity_row(self, pending: Mapping[str, Any], actual: Mapping[str, Any]) -> dict:
        """RT-07: an independent-replay parity row from a resolved flip pending.

        Carries only raw causal inputs -- candidate T, the prevailing direction, the
        observed prevailing-regime flips, the retained tape (for the gap rule) -- so
        ``validate_target_parity`` re-derives the label through
        ``target_replay_oracle._replay_flip_condition`` and never reads a
        ``TargetResult`` this runtime computed.  ``regime_direction`` is emitted so the
        oracle's default ``role == "opposite"`` yields the same target direction the
        runtime resolved from ``target_direction_role``.
        """
        tgt = int(pending.get("target_direction", 0))
        prevailing = -tgt if tgt else int(pending.get("regime_direction", 0))
        return {
            "candidate": {
                "observation_ts": int(pending["observation_ts"]),
                "regime_direction": prevailing,
                "direction": prevailing,
                "session_close_ts": pending.get("session_close_ts"),
            },
            "flip_events": [dict(f) for f in pending.get("flip_events", ())],
            "events": [dict(b) for b in pending.get("tape", ())],
            "actual": dict(actual),
        }

    def terminal(self, candidate, events=None, *, final=True):
        if "flip_events" in candidate:
            return self._terminal_pending(candidate, final=final)
        return self._terminal_legacy(candidate, events, final=final)

    @staticmethod
    def _terminal_legacy(candidate, events, *, final):
        end = int(candidate["horizon_end_ts"]); start = int(candidate["observation_ts"])
        close = candidate.get("session_close_ts")
        if close is not None and end > int(close):
            return TargetResult(CENSORED, None, int(close), "SESSION_END")
        for e in events or ():
            ts = int(e["ts"])
            if e.get("gap"):
                return TargetResult(CENSORED, None, ts, "GAP")
            if start <= ts <= end and e.get("flip"):
                return TargetResult(POSITIVE, 1, ts)
        return TargetResult(NEGATIVE, 0, end) if final else TargetResult(PENDING, None)

    @staticmethod
    def _terminal_pending(pending, *, final):
        start = int(pending["observation_ts"]); end = int(pending["horizon_end_ts"])
        close = pending.get("session_close_ts")
        if close is not None and end > int(close):
            return TargetResult(CENSORED, None, int(close), "SESSION_END")
        gap_ts = int(pending["gap_ts"]) if pending.get("gap") and pending.get("gap_ts") is not None else None
        # A flip is only observed if it lands within the horizon AND before any tape gap.
        limit = end if gap_ts is None else min(end, gap_ts)
        tgt = int(pending.get("target_direction", 0))
        for fe in sorted(pending["flip_events"], key=lambda x: int(x["ts"])):
            ts = int(fe["ts"])
            if start < ts <= limit and (tgt == 0 or int(fe["direction"]) == tgt):
                return TargetResult(POSITIVE, 1, ts)
        if gap_ts is not None and gap_ts <= end:
            return TargetResult(CENSORED, None, gap_ts, "GAP")
        if final or int(pending.get("last_ts", start)) >= end:
            return TargetResult(NEGATIVE, 0, end)
        return TargetResult(PENDING, None)

class OrderedBarrierTargetRuntime(TargetRuntime):
    """Asymmetric direction-normalized favorable/adverse ATR barrier race.

    Entry-reference resolution lives HERE, not in the population candidate builder.
    The compiled ``TargetContract`` (``entry_reference``, the ordered-barrier ATR
    distances, ``session_end_censoring``, ``max_gap_seconds``) is the sole authority
    for the terminal label; the population supplies only candidate identity, the
    decision timestamp T, and the causal candidate-time ATR that the barriers are
    frozen against.  ``open_pending`` builds the runtime-owned pending observation
    from that candidate-time state; ``ingest_bar`` streams the causal 1s execution
    tape and resolves ``entry_reference == "next_bar_open"`` on the first bar strictly
    after T (using that bar's OPEN, never the decision close); ``terminal`` reports
    the disposition.  ``bar_inclusion`` is ``fully_forward``: the entry reference bar
    itself is eligible for a barrier touch.
    """

    primitive = "ordered_barrier"

    # RT-05 -- see FlipTargetRuntime.
    CONSUMED_SEMANTIC_FIELDS = frozenset({
        "horizon_seconds", "session_end_censoring", "max_gap_seconds",
        "entry_reference", "bar_inclusion", "excursion_units", "ordered_barriers",
        "favorable_atr", "adverse_atr", "max_tracking_seconds", "atr_source",
        "horizon_expiry_policy",
    })
    PROVENANCE_ONLY_SEMANTIC_FIELDS = frozenset({
        "atr_frozen_at", "id", "spec_id", "spec_sha256",
        "generated_outcome_columns",
    })
    SUPPORTED_SEMANTIC_VALUES = {
        "entry_reference": {"next_bar_open"},
        "bar_inclusion": {"fully_forward"},
        "horizon_expiry_policy": {"censor", "negative"},
    }

    def __init__(self, binding: Mapping[str, Any] | None = None):
        self._binding = dict(binding or {})

    # -- runtime-owned pending lifecycle ---------------------------------------
    def open_pending(self, candidate: Mapping[str, Any]) -> dict:
        """A ``PendingOrderedBarrier`` built from candidate-time state only.

        No ``entry_price``: the execution reference is resolved from the forward
        tape by :meth:`ingest_bar` according to the contract's ``entry_reference``.
        """
        for field in ("forward_outcome_id", "barrier_id"):
            expected = self._binding.get(field)
            if expected is not None and candidate.get(field) != expected:
                raise TargetRuntimeError("ORDERED_BARRIER_IDENTITY_BINDING_MISMATCH")
        declared_source = candidate.get("declared_atr_source", self._binding.get("atr_source"))
        source = candidate.get("atr_source")
        if declared_source is not None:
            if declared_source != SUPPORTED_ATR_SOURCE or source != declared_source:
                raise TargetRuntimeError("TARGET_ATR_SOURCE_BINDING_MISMATCH")
        atr = float(candidate["atr"])
        if not (atr > 0):
            raise TargetRuntimeError(
                "TARGET_FROZEN_ATR_NONPOSITIVE: ordered-barrier ATR must be frozen "
                "positive at the candidate decision timestamp T"
            )
        entry_reference = str(candidate.get("entry_reference", "next_bar_open"))
        if entry_reference != "next_bar_open":
            raise TargetRuntimeError(
                f"TARGET_ENTRY_REFERENCE_UNSUPPORTED: this runtime resolves "
                f"'next_bar_open' only, not {entry_reference!r}"
            )
        horizon_expiry_policy = str(
            candidate.get(
                "horizon_expiry_policy",
                self._binding.get("horizon_expiry_policy", "censor"),
            )
        ).lower()
        if horizon_expiry_policy not in {"censor", "negative"}:
            raise TargetRuntimeError(
                f"TARGET_HORIZON_EXPIRY_POLICY_UNSUPPORTED: {horizon_expiry_policy!r}"
            )
        obs_ts = int(candidate["observation_ts"])
        return {
            "observation_ts": obs_ts,
            "regime_start_ns": candidate.get("regime_start_ns"),
            "regime_direction": int(candidate.get("regime_direction", candidate.get("direction", 1))),
            "checkpoint_index": candidate.get("checkpoint_index"),
            "direction": int(candidate.get("direction", candidate.get("regime_direction", 1))),
            "atr": atr,
            "atr_source": source,
            "declared_atr_source": declared_source,
            "favorable_atr": float(candidate["favorable_atr"]),
            "adverse_atr": float(candidate["adverse_atr"]),
            "horizon_seconds": int(candidate["horizon_seconds"]),
            "horizon_expiry_policy": horizon_expiry_policy,
            "session_close_ts": (
                int(candidate["session_close_ts"])
                if candidate.get("session_close_ts") is not None else None
            ),
            "max_gap_seconds": (
                int(candidate["max_gap_seconds"])
                if candidate.get("max_gap_seconds") is not None else None
            ),
            "entry_reference": entry_reference,
            "entry_resolved": False,
            "entry_price": None,
            "entry_ts": None,
            "horizon_end_ts": None,
            "events": [],
        }

    def ingest_bar(self, pending: dict, bar: Mapping[str, Any]) -> None:
        """Feed one completed 1s execution bar (close-stamped ``ts``).

        The entry reference resolves on the first bar strictly after T; the barrier
        horizon deadline is then measured from the entry instant, not from T.
        """
        ts = int(bar["ts"])
        if not pending["entry_resolved"]:
            if ts <= pending["observation_ts"]:
                return  # not yet strictly after the decision timestamp
            pending["entry_price"] = float(bar["open"])
            # next_bar_open executes at this 1s bar's OPEN instant, which is its
            # close-stamp minus the 1s bar duration.
            pending["entry_ts"] = ts - NS
            pending["horizon_end_ts"] = pending["entry_ts"] + pending["horizon_seconds"] * NS
            pending["entry_resolved"] = True
        # fully_forward: the entry bar and every later bar are barrier-eligible. `open`
        # is retained so an independent replay can re-derive the entry reference from the
        # event tape alone (never from a runtime-internal pending field).
        pending["events"].append({
            "ts": ts,
            "open": (None if bar.get("open") is None else float(bar["open"])),
            "high": (None if bar.get("high") is None else float(bar["high"])),
            "low": (None if bar.get("low") is None else float(bar["low"])),
            "gap": bool(bar.get("gap")),
        })

    def terminal(self, pending, events=None, *, final=True):
        # A pre-resolved candidate that never went through open_pending/ingest_bar
        # (direct unit calls, historical fixtures): the entry instant is the decision
        # T and the deadline is the supplied horizon_end_ts.
        legacy = "entry_resolved" not in pending
        if legacy:
            if pending.get("entry_price") is None:
                return TargetResult(PENDING, None)
            entry_ts = int(pending["observation_ts"])
            entry_price = float(pending["entry_price"])
            horizon_end_ts = int(pending["horizon_end_ts"])
        else:
            if not pending["entry_resolved"]:
                return TargetResult(PENDING, None)
            entry_ts = int(pending["entry_ts"])
            entry_price = float(pending["entry_price"])
            horizon_end_ts = int(pending["horizon_end_ts"])

        evs = list(events if events is not None else pending.get("events", ()))
        close = pending.get("session_close_ts")
        if close is not None and horizon_end_ts > int(close):
            return TargetResult(CENSORED, None, int(close), "SESSION_END")

        direction = int(pending.get("direction", pending.get("regime_direction", 1)))
        atr = float(pending["atr"])
        fav = float(pending["favorable_atr"]); adv = float(pending["adverse_atr"])
        good = entry_price + direction * fav * atr
        bad = entry_price - direction * adv * atr
        max_gap_ns = (
            int(pending["max_gap_seconds"]) * NS
            if pending.get("max_gap_seconds") is not None else None
        )

        prev_ts = entry_ts
        for e in sorted(evs, key=lambda x: int(x["ts"])):
            ts = int(e["ts"])
            if ts <= entry_ts:
                continue
            if ts > horizon_end_ts:
                break
            if close is not None and ts > int(close):
                return TargetResult(CENSORED, None, ts, "SESSION_END")
            if e.get("gap") or (max_gap_ns is not None and ts - prev_ts > max_gap_ns):
                return TargetResult(CENSORED, None, ts, "GAP")
            prev_ts = ts
            hi, lo = e.get("high"), e.get("low")
            if hi is None or lo is None:
                continue
            hi = float(hi); lo = float(lo)
            hit_good = hi >= good if direction > 0 else lo <= good
            hit_bad = lo <= bad if direction > 0 else hi >= bad
            if hit_good and hit_bad:
                return TargetResult(CENSORED, None, ts, "AMBIGUOUS_SAME_BAR_TOUCH")
            if hit_good:
                return TargetResult(POSITIVE, 1, ts)
            if hit_bad:
                return TargetResult(NEGATIVE, 0, ts)

        last_ts = int(evs[-1]["ts"]) if evs else entry_ts
        if final or last_ts >= horizon_end_ts:
            policy = pending.get("horizon_expiry_policy", "censor")
            if policy == "censor":
                return TargetResult(CENSORED, None, horizon_end_ts, "TIMEOUT")
            elif policy == "negative":
                return TargetResult(NEGATIVE, 0, horizon_end_ts)
            else:
                raise TargetRuntimeError(f"UNKNOWN_HORIZON_EXPIRY_POLICY: {policy!r}")
        return TargetResult(PENDING, None)


class CompositeTargetRuntime(TargetRuntime):
    """Executes the FULL compiled Boolean target expression.

    Owns one child ``TargetRuntime`` per condition and composes their terminal results
    through :func:`research_workflow.target_expression.compose_child_results`
    (monotone ``worst_status``, no short-circuit).  Unknown / non-executable
    composition fails closed at construction.
    """

    primitive = "composite"

    # RT-05: the composite runtime's own bookkeeping fields; per-condition semantics are
    # covered by the child runtimes' declarations (see assert_target_semantic_field_coverage).
    CONSUMED_SEMANTIC_FIELDS = frozenset({
        "conditions", "condition_logic", "target_expression", "censoring_composition",
        "required_forward_outcomes", "horizon_seconds", "session_end_censoring",
    })
    PROVENANCE_ONLY_SEMANTIC_FIELDS = frozenset()

    def __init__(self, contract: Mapping[str, Any]):
        self.expression: TargetExpression = compile_target_expression(contract)
        runtime_executable(self.expression)  # fail closed on excursion/return leaves
        self._leaves = {leaf.condition_id: leaf for leaf in self.expression.leaves()}
        self._child_runtimes: dict[str, TargetRuntime] = {}
        for cid, leaf in self._leaves.items():
            cls = _RUNTIMES.get(leaf.primitive)
            if cls is None:  # pragma: no cover - runtime_executable already guarded
                raise TargetRuntimeError(f"UNKNOWN_TARGET_PRIMITIVE: {leaf.primitive!r}")
            self._child_runtimes[cid] = cls(leaf.params) if leaf.primitive == "ordered_barrier" else cls()

    # -- identity ------------------------------------------------------------
    def canonical(self) -> str:
        return self.expression.canonical()

    def expression_dict(self) -> dict[str, Any]:
        return self.expression.to_dict()

    # -- pending lifecycle --------------------------------------------------
    def open_pending(self, candidate: Mapping[str, Any]) -> dict:
        T = int(candidate["observation_ts"])
        session_close = (
            int(candidate["session_close_ts"])
            if candidate.get("session_close_ts") is not None else None
        )
        prevailing = int(
            candidate.get("regime_direction", candidate.get("direction", 0)) or 0
        )
        children: dict[str, dict] = {}
        horizon_ends: list[int] = []
        for cid, leaf in self._leaves.items():
            p = dict(leaf.params)
            child_candidate = {
                "observation_ts": T,
                "regime_start_ns": candidate.get("regime_start_ns"),
                "regime_direction": prevailing,
                "direction": prevailing,
                "checkpoint_index": candidate.get("checkpoint_index"),
                "session_close_ts": session_close,
            }
            if leaf.primitive == "flip_within_horizon":
                child_candidate["horizon_seconds"] = int(p["horizon_seconds"])
                child_candidate["target_direction_role"] = str(p.get("target_direction_role", "opposite"))
                child_candidate["max_gap_seconds"] = p.get("max_gap_seconds")
                if not p.get("session_end_censoring", False):
                    child_candidate["session_close_ts"] = None
                horizon_ends.append(T + int(p["horizon_seconds"]) * NS)
            elif leaf.primitive == "ordered_barrier":
                child_candidate["atr"] = float(candidate["atr"])
                child_candidate["favorable_atr"] = float(p["favorable_atr"])
                child_candidate["adverse_atr"] = float(p["adverse_atr"])
                child_candidate["horizon_seconds"] = int(p["horizon_seconds"])
                child_candidate["entry_reference"] = str(p.get("entry_reference", "next_bar_open"))
                child_candidate["max_gap_seconds"] = p.get("max_gap_seconds")
                child_candidate["declared_atr_source"] = p.get("atr_source")
                child_candidate["atr_source"] = candidate.get("atr_source")
                child_candidate["forward_outcome_id"] = p.get("forward_outcome_id")
                child_candidate["barrier_id"] = p.get("barrier_id")
                child_candidate["horizon_expiry_policy"] = p.get("horizon_expiry_policy", "censor")
                if not p.get("session_end_censoring", False):
                    child_candidate["session_close_ts"] = None
                horizon_ends.append(T + int(p["horizon_seconds"]) * NS)
            children[cid] = self._child_runtimes[cid].open_pending(child_candidate)
        return {
            "__composite__": True,
            "observation_ts": T,
            "regime_start_ns": candidate.get("regime_start_ns"),
            "regime_direction": prevailing,
            "checkpoint_index": candidate.get("checkpoint_index"),
            "session_close_ts": session_close,
            "children": children,
            "horizon_end_ts": max(horizon_ends) if horizon_ends else T,
            "entry_resolved": True,  # refined by ingest_bar; composite has no single entry
        }

    def parity_row(self, pending: Mapping[str, Any], actual: Mapping[str, Any]) -> dict:
        """Assemble an independent-replay parity row from a resolved composite pending.

        The oracle (``validate_target_parity`` -> ``replay_expression``) re-derives the
        label from the contract + these raw causal inputs (the 1s tape and the observed
        flips), never from a per-child ``TargetResult`` the runtime computed.
        """
        events: list = []
        flip_events: list = []
        atr = None
        for cid, child in pending["children"].items():
            prim = self._leaves[cid].primitive
            if prim == "ordered_barrier":
                events = [dict(e) for e in child.get("events", ())]
                atr = child.get("atr")
            elif prim == "flip_within_horizon":
                flip_events = [dict(f) for f in child.get("flip_events", ())]
        return {
            "candidate": {
                "observation_ts": int(pending["observation_ts"]),
                "atr": atr,
                "direction": int(pending["regime_direction"]),
                "regime_direction": int(pending["regime_direction"]),
                "session_close_ts": pending.get("session_close_ts"),
                "atr_source": atr and next((c.get("atr_source") for c in pending["children"].values()
                                              if c.get("atr_source") is not None), None),
            },
            "events": events,
            "flip_events": flip_events,
            "actual": dict(actual),
        }

    def ingest_bar(self, pending: dict, bar: Mapping[str, Any]) -> None:
        for cid, child in pending["children"].items():
            self._child_runtimes[cid].ingest_bar(child, bar)
        # Keep the sweep bookkeeping honest: an ordered-barrier child's deadline is only
        # known once its next_bar_open entry has resolved.
        ends = [pending["observation_ts"]]
        all_entered = True
        for child in pending["children"].values():
            if "entry_resolved" in child:  # ordered-barrier child
                if child["entry_resolved"] and child.get("horizon_end_ts") is not None:
                    ends.append(int(child["horizon_end_ts"]))
                else:
                    all_entered = False
            elif "horizon_end_ts" in child:  # flip child
                ends.append(int(child["horizon_end_ts"]))
        pending["horizon_end_ts"] = max(ends)
        pending["entry_resolved"] = all_entered

    def ingest_flip(self, pending: dict, flip_event: Mapping[str, Any]) -> None:
        for cid, child in pending["children"].items():
            self._child_runtimes[cid].ingest_flip(child, flip_event)

    def terminal(self, pending, events=None, *, final=True, now_ts: int | None = None):
        child_results: dict[str, TargetResult] = {}
        for cid, child in pending["children"].items():
            res = self._child_runtimes[cid].terminal(child, final=final)
            if res.disposition == PENDING and final:
                # An unresolved required child at run end is unobservable -> DATA_END,
                # which the monotone rule turns into a censored composite.
                res = TargetResult(CENSORED, None, now_ts, "DATA_END")
            child_results[cid] = res
        return self.expression.evaluate(child_results)


_RUNTIMES = {"flip_within_horizon": FlipTargetRuntime, "ordered_barrier": OrderedBarrierTargetRuntime}


def resolve_target_runtime_closure(study_dir: str | Path) -> dict[str, Any]:
    """Identity of target contract, runtime/oracle code, and actual collector dispatch."""
    study = Path(study_dir).resolve()
    compiled_path = study / "compiled_study.json"
    compiled = json.loads(compiled_path.read_text(encoding="utf-8")) if compiled_path.is_file() else {}
    root = Path(__file__).resolve().parents[1]
    files = [root / "research_workflow/target_runtime.py", root / "research_workflow/target_expression.py",
             root / "research_workflow/target_replay_oracle.py", root / "research_workflow/generic_collector.py"]
    parts = {"target_contract": (compiled.get("contracts") or {}).get("target_contract") or {}}
    parts["files"] = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    return {"target_runtime_closure_sha256": hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "components": parts}


# --------------------------------------------------------------------------- #
# RT-05 -- accepted target semantic-field coverage
# --------------------------------------------------------------------------- #
# Semantic contract fields that a study can author and that a runtime could silently
# ignore. Value = the set of "present but semantically inert" values (a default that is a
# documented no-op). A value outside this set for a field the resolved runtime neither
# consumes nor treats as provenance-only fails closed before seal.
_TARGET_SEMANTIC_FIELDS: dict[str, tuple] = {
    "confirmation": ({"mode": "bar_close", "confirmation_bars": 1},),
    "bar_inclusion": ("fully_forward",),
    "entry_reference": ("next_bar_open",),
    "atr_source": (),
    "atr_frozen_at": (),
    "excursion_units": (["atr"],),
    "max_gap_seconds": (),
}

_RUNTIME_CLASSES = {
    "flip_within_horizon": FlipTargetRuntime,
    "ordered_barrier": OrderedBarrierTargetRuntime,
    "composite": CompositeTargetRuntime,
}


def _semantic_field_sites(contract: Mapping[str, Any]):
    """Yield (location, field, value) for every semantic field authored in the contract
    -- top level, each required_forward_outcomes entry, each conditions entry."""
    for f in _TARGET_SEMANTIC_FIELDS:
        if f in contract:
            yield ("target", f, contract[f])
    for i, fo in enumerate(contract.get("required_forward_outcomes") or []):
        for f in _TARGET_SEMANTIC_FIELDS:
            if f in fo:
                yield (f"required_forward_outcomes[{i}]", f, fo[f])
    for i, cond in enumerate(contract.get("conditions") or []):
        for f in _TARGET_SEMANTIC_FIELDS:
            if f in cond:
                yield (f"conditions[{i}]", f, cond[f])


def _is_inert(field: str, value: Any) -> bool:
    if value is None:
        return True
    return any(value == inert for inert in _TARGET_SEMANTIC_FIELDS[field])


def _allowed_semantic_fields(primitive: str, contract: Mapping[str, Any]) -> tuple[set, list]:
    """(allowed field names, [runtime classes]) for the resolved primitive."""
    if primitive == "composite":
        classes = [CompositeTargetRuntime]
        for leaf in (contract.get("conditions") or []):
            kind = leaf.get("kind")
            prim = {"flip": "flip_within_horizon", "ordered_barrier": "ordered_barrier"}.get(kind)
            if prim and _RUNTIME_CLASSES.get(prim) not in classes:
                classes.append(_RUNTIME_CLASSES[prim])
    else:
        cls = _RUNTIME_CLASSES.get(primitive)
        classes = [cls] if cls else []
    allowed: set = set()
    for cls in classes:
        allowed |= set(getattr(cls, "CONSUMED_SEMANTIC_FIELDS", frozenset()))
        allowed |= set(getattr(cls, "PROVENANCE_ONLY_SEMANTIC_FIELDS", frozenset()))
    return allowed, classes


def assert_target_semantic_field_coverage(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed (``TARGET_SEMANTIC_FIELD_UNSUPPORTED``) if the compiled target contract
    authors a non-default semantic field the resolved runtime neither executes nor records
    as provenance -- so an accepted field can never be silently ignored (RT-05).

    Returns a coverage report on success.
    """
    primitive = str(contract.get("primitive") or "flip_within_horizon")
    allowed, classes = _allowed_semantic_fields(primitive, contract)
    if not classes:
        raise TargetRuntimeError(f"UNKNOWN_TARGET_PRIMITIVE: {primitive!r}")

    unsupported: list[str] = []
    checked: list[dict] = []
    for location, field, value in _semantic_field_sites(contract):
        if _is_inert(field, value):
            checked.append({"where": location, "field": field, "status": "inert_default"})
            continue
        if field not in allowed:
            unsupported.append(
                f"{location}.{field}={value!r} -- {primitive} runtime has no implementation "
                f"for it (neither consumed nor provenance-only)"
            )
            continue
        # Constrained-value check for any runtime class that supports only a subset.
        for cls in classes:
            svv = getattr(cls, "SUPPORTED_SEMANTIC_VALUES", {})
            if field in svv and value not in svv[field]:
                unsupported.append(
                    f"{location}.{field}={value!r} -- {cls.__name__} supports only "
                    f"{sorted(str(v) for v in svv[field])}"
                )
            if isinstance(value, Mapping):
                for sub, allowed_vals in svv.items():
                    if sub.startswith(field + "."):
                        key = sub.split(".", 1)[1]
                        if value.get(key) not in allowed_vals:
                            unsupported.append(
                                f"{location}.{sub}={value.get(key)!r} -- {cls.__name__} "
                                f"supports only {sorted(str(v) for v in allowed_vals)}"
                            )
        checked.append({"where": location, "field": field, "status": "consumed_or_provenance"})

    if unsupported:
        raise TargetRuntimeError(
            "TARGET_SEMANTIC_FIELD_UNSUPPORTED: the compiled target contract authors "
            "semantic field(s) the runtime does not execute; reject them or implement "
            f"the semantics before seal: {unsupported}"
        )
    return {"primitive": primitive, "runtime_classes": [c.__name__ for c in classes],
            "allowed_fields": sorted(allowed), "checked": checked, "passed": True}


def resolve_target_runtime(contract: Mapping[str, Any], *, legacy_mode: bool = False) -> TargetRuntime:
    primitive = contract.get("primitive")
    if primitive is None and legacy_mode:
        primitive = "flip_within_horizon"
    if str(primitive) == "composite":
        try:
            return CompositeTargetRuntime(contract)
        except TargetExpressionError as exc:
            raise TargetRuntimeError(str(exc)) from exc
    cls = _RUNTIMES.get(str(primitive))
    if cls is None:
        raise TargetRuntimeError(f"UNKNOWN_TARGET_PRIMITIVE: {primitive!r}")
    if str(primitive) == "ordered_barrier":
        if not contract.get("required_forward_outcomes"):
            return cls()  # isolated legacy fixtures carry a pre-resolved candidate
        expression = compile_target_expression(contract)
        leaves = expression.leaves()
        if len(leaves) != 1 or leaves[0].primitive != "ordered_barrier":
            raise TargetRuntimeError("ORDERED_BARRIER_IDENTITY_REQUIRED")
        return cls(leaves[0].params)
    return cls()

_DISPOSITION_ALIASES = {
    "LABELED_POSITIVE": POSITIVE, "LABELED_NEGATIVE": NEGATIVE,
    "POSITIVE": POSITIVE, "NEGATIVE": NEGATIVE, "CENSORED": CENSORED, "PENDING": PENDING,
}


def _norm_disposition(value: Any) -> Any:
    return _DISPOSITION_ALIASES.get(str(value), value)


def validate_target_parity(contract: Mapping[str, Any], rows: Iterable[Mapping[str, Any]], *, legacy_mode: bool = False) -> dict[str, Any]:
    """Compare the runtime's emitted disposition against the INDEPENDENT replay oracle.

    The oracle re-derives candidate T, the frozen candidate-time ATR, the first
    qualifying 1s open after T, the ordered-barrier path, the flip window, AND the
    Boolean composition -- from the contract and the causal tape.  It never reads a
    runtime-internal pending field such as a pre-populated ``entry_price`` or a
    per-child ``TargetResult`` computed by the runtime.  Disposition names are
    normalized so the collector's ``LABELED_*`` compare equal to the oracle's bare
    names.

    A composite row supplies ``events`` (the 1s tape, carrying ``open``) and
    ``flip_events`` (the observed prevailing-regime flips).
    """
    runtime = resolve_target_runtime(contract, legacy_mode=legacy_mode)
    dm = lm = cm = 0; total = 0; examples = []
    for row in rows:
        from research_workflow.target_replay_oracle import replay, replay_expression
        if runtime.primitive == "composite":
            oracle = replay_expression(
                contract, row["candidate"], row.get("events", ()), row.get("flip_events", ())
            )
        elif runtime.primitive == "ordered_barrier":
            oracle = replay(contract, row["candidate"], row.get("events", ()))
        else:
            # RT-07: a bare flip_within_horizon target is checked against the SAME
            # independent replay implementation as a composite flip child
            # (target_replay_oracle._replay_flip_condition, reached via replay_expression) --
            # never against FlipTargetRuntime.terminal(), which would make the runtime its
            # own oracle.
            oracle = replay_expression(
                contract, row["candidate"], row.get("events", ()), row.get("flip_events", ())
            )
        actual = row["actual"]
        total += 1
        d_bad = _norm_disposition(actual.get("disposition")) != _norm_disposition(oracle["disposition"])
        l_bad = actual.get("label") != oracle["label"]
        exp_censored = _norm_disposition(oracle["disposition"]) == CENSORED
        act_censored = _norm_disposition(actual.get("disposition")) == CENSORED
        c_bad = (exp_censored != act_censored) or (
            exp_censored and act_censored
            and actual.get("censor_reason") is not None
            and actual.get("censor_reason") != oracle.get("censor_reason")
        )
        dm += int(d_bad); lm += int(l_bad); cm += int(c_bad)
        if d_bad or l_bad or c_bad:
            examples.append({"expected": oracle, "actual": dict(actual)})
    return {"primitive": runtime.primitive, "rows": total, "rows_compared": total,
            "disposition_mismatches": dm, "binary_label_mismatches": lm,
            "censoring_mismatches": cm,
            "passed": dm == 0 and lm == 0 and cm == 0, "examples": examples[:10]}

__all__ = ["TargetRuntimeError", "TargetResult", "FlipTargetRuntime", "OrderedBarrierTargetRuntime",
           "CompositeTargetRuntime", "resolve_target_runtime", "resolve_target_runtime_closure",
           "assert_target_semantic_field_coverage",
           "validate_target_parity", "POSITIVE", "NEGATIVE", "CENSORED", "PENDING", "NS", "SUPPORTED_ATR_SOURCE"]
