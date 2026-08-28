"""Compiled target-contract -> executable target-runtime binding.

Target labels are runtime semantics.  This module is deliberately independent from
the collector so a bounded replay can prove the emitted disposition before TRAIN.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib, json
from pathlib import Path
from typing import Any, Iterable, Mapping

POSITIVE, NEGATIVE, CENSORED = "POSITIVE", "NEGATIVE", "CENSORED"
NS = 1_000_000_000

class TargetRuntimeError(RuntimeError): pass

@dataclass(frozen=True)
class TargetResult:
    disposition: str
    label: int | None
    resolved_at_ts: int | None = None
    censor_reason: str | None = None

class TargetRuntime:
    primitive: str = ""
    def terminal(self, candidate: Mapping[str, Any], events: Iterable[Mapping[str, Any]], *, final: bool = True) -> TargetResult:
        raise NotImplementedError
    def from_disposition(self, disposition: str, *, resolved_at_ts: int | None = None,
                         censor_reason: str | None = None) -> TargetResult:
        if disposition in {POSITIVE, "LABELED_POSITIVE"}: return TargetResult(disposition, 1, resolved_at_ts)
        if disposition in {NEGATIVE, "LABELED_NEGATIVE"}: return TargetResult(disposition, 0, resolved_at_ts)
        return TargetResult(disposition, None, resolved_at_ts, censor_reason)

class FlipTargetRuntime(TargetRuntime):
    primitive = "flip_within_horizon"
    def terminal(self, candidate, events, *, final=True):
        end = int(candidate["horizon_end_ts"]); start = int(candidate["observation_ts"])
        close = candidate.get("session_close_ts")
        if close is not None and end > int(close):
            return TargetResult(CENSORED, None, int(close), "SESSION_END")
        for e in events:
            ts = int(e["ts"])
            if e.get("gap"):
                return TargetResult(CENSORED, None, ts, "GAP")
            if start <= ts <= end and e.get("flip"):
                return TargetResult(POSITIVE, 1, ts)
        return TargetResult(NEGATIVE, 0, end) if final else TargetResult("PENDING", None)

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

    # -- runtime-owned pending lifecycle ---------------------------------------
    def open_pending(self, candidate: Mapping[str, Any]) -> dict:
        """A ``PendingOrderedBarrier`` built from candidate-time state only.

        No ``entry_price``: the execution reference is resolved from the forward
        tape by :meth:`ingest_bar` according to the contract's ``entry_reference``.
        """
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
        obs_ts = int(candidate["observation_ts"])
        return {
            "observation_ts": obs_ts,
            "regime_start_ns": candidate.get("regime_start_ns"),
            "regime_direction": int(candidate.get("regime_direction", candidate.get("direction", 1))),
            "checkpoint_index": candidate.get("checkpoint_index"),
            "direction": int(candidate.get("direction", candidate.get("regime_direction", 1))),
            "atr": atr,
            "favorable_atr": float(candidate["favorable_atr"]),
            "adverse_atr": float(candidate["adverse_atr"]),
            "horizon_seconds": int(candidate["horizon_seconds"]),
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
                return TargetResult("PENDING", None)
            entry_ts = int(pending["observation_ts"])
            entry_price = float(pending["entry_price"])
            horizon_end_ts = int(pending["horizon_end_ts"])
        else:
            if not pending["entry_resolved"]:
                return TargetResult("PENDING", None)
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
            return TargetResult(NEGATIVE, 0, horizon_end_ts)  # TIMEOUT -> negative
        return TargetResult("PENDING", None)

_RUNTIMES = {"flip_within_horizon": FlipTargetRuntime, "ordered_barrier": OrderedBarrierTargetRuntime}
def resolve_target_runtime_closure(study_dir: str | Path) -> dict[str, Any]:
    """Identity of target contract, runtime/oracle code, and actual collector dispatch."""
    study = Path(study_dir).resolve()
    compiled_path = study / "compiled_study.json"
    compiled = json.loads(compiled_path.read_text(encoding="utf-8")) if compiled_path.is_file() else {}
    root = Path(__file__).resolve().parents[1]
    files = [root / "research_workflow/target_runtime.py", root / "research_workflow/target_replay_oracle.py", root / "research_workflow/generic_collector.py"]
    parts = {"target_contract": (compiled.get("contracts") or {}).get("target_contract") or {}}
    parts["files"] = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    return {"target_runtime_closure_sha256": hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "components": parts}
def resolve_target_runtime(contract: Mapping[str, Any], *, legacy_mode: bool = False) -> TargetRuntime:
    primitive = contract.get("primitive")
    if primitive is None and legacy_mode:
        primitive = "flip_within_horizon"
    cls = _RUNTIMES.get(str(primitive))
    if cls is None:
        raise TargetRuntimeError(f"UNKNOWN_TARGET_PRIMITIVE: {primitive!r}")
    return cls()

_DISPOSITION_ALIASES = {
    "LABELED_POSITIVE": POSITIVE, "LABELED_NEGATIVE": NEGATIVE,
    "POSITIVE": POSITIVE, "NEGATIVE": NEGATIVE, "CENSORED": CENSORED, "PENDING": "PENDING",
}


def _norm_disposition(value: Any) -> Any:
    return _DISPOSITION_ALIASES.get(str(value), value)


def validate_target_parity(contract: Mapping[str, Any], rows: Iterable[Mapping[str, Any]], *, legacy_mode: bool = False) -> dict[str, Any]:
    """Compare the runtime's emitted disposition against the INDEPENDENT replay oracle.

    The oracle re-derives candidate T, the frozen candidate-time ATR, the first
    qualifying 1s open after T, and the ordered-barrier path from the contract and the
    causal tape -- it never reads a runtime-internal pending field such as a
    pre-populated ``entry_price``.  Disposition names are normalized so the collector's
    ``LABELED_POSITIVE``/``LABELED_NEGATIVE`` compare equal to the oracle's
    ``POSITIVE``/``NEGATIVE``.
    """
    runtime = resolve_target_runtime(contract, legacy_mode=legacy_mode)
    dm = lm = cm = 0; total = 0; examples = []
    for row in rows:
        from research_workflow.target_replay_oracle import replay
        if runtime.primitive == "ordered_barrier":
            oracle = replay(contract, row["candidate"], row.get("events", ()))
        else:
            oracle = runtime.terminal(row["candidate"], row.get("events", ())).__dict__
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

__all__ = ["TargetRuntimeError", "TargetResult", "FlipTargetRuntime", "OrderedBarrierTargetRuntime", "resolve_target_runtime", "validate_target_parity"]
