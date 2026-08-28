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
    primitive = "ordered_barrier"
    def terminal(self, candidate, events, *, final=True):
        end = int(candidate["horizon_end_ts"]); start = int(candidate["observation_ts"])
        close = candidate.get("session_close_ts")
        if close is not None and end > int(close):
            return TargetResult(CENSORED, None, int(close), "SESSION_END")
        direction = int(candidate.get("direction", candidate.get("regime_direction", 1)))
        entry = float(candidate["entry_price"]); atr = float(candidate["atr"])
        fav = float(candidate["favorable_atr"]); adv = float(candidate["adverse_atr"])
        good = entry + direction * fav * atr; bad = entry - direction * adv * atr
        for e in events:
            ts = int(e["ts"])
            if ts <= start or ts > end: continue
            if e.get("gap"): return TargetResult(CENSORED, None, ts, "GAP")
            hi, lo = float(e["high"]), float(e["low"])
            hit_good = hi >= good if direction > 0 else lo <= good
            hit_bad = lo <= bad if direction > 0 else hi >= bad
            if hit_good and hit_bad:
                return TargetResult(CENSORED, None, ts, "AMBIGUOUS_SAME_BAR_TOUCH")
            if hit_good: return TargetResult(POSITIVE, 1, ts)
            if hit_bad: return TargetResult(NEGATIVE, 0, ts)
        return TargetResult(NEGATIVE, 0, end) if final else TargetResult("PENDING", None)

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

def validate_target_parity(contract: Mapping[str, Any], rows: Iterable[Mapping[str, Any]], *, legacy_mode: bool = False) -> dict[str, Any]:
    runtime = resolve_target_runtime(contract, legacy_mode=legacy_mode)
    dm = lm = 0; total = 0; examples = []
    for row in rows:
        from research_workflow.target_replay_oracle import replay
        oracle = replay(contract, row["candidate"], row.get("events", ())) if runtime.primitive == "ordered_barrier" else runtime.terminal(row["candidate"], row.get("events", ())).__dict__
        actual = row["actual"]
        total += 1
        expected_disposition = oracle["disposition"]
        expected_label = oracle["label"]
        d_bad = actual.get("disposition") != expected_disposition
        l_bad = actual.get("label") != expected_label
        dm += int(d_bad); lm += int(l_bad)
        if d_bad or l_bad: examples.append({"expected": oracle, "actual": dict(actual)})
    return {"primitive": runtime.primitive, "rows": total, "disposition_mismatches": dm,
            "binary_label_mismatches": lm, "passed": dm == 0 and lm == 0, "examples": examples[:10]}

__all__ = ["TargetRuntimeError", "TargetResult", "FlipTargetRuntime", "OrderedBarrierTargetRuntime", "resolve_target_runtime", "validate_target_parity"]
