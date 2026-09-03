"""Outcome contracts: one primitive family, two strongly typed compiled contracts, one kernel.

``LabelOutcomeKernel`` executes a ``LabelOutcomeContract``: observational path resolution
(mark touches on completed-bar high/low), dispositions, censoring -- no fill semantics.
``TradeExecutionContract`` is the typed structure for order/fill semantics (latency,
slippage, spread, position state); it shares the barrier/event/horizon vocabulary and
the same-bar collision rule but is a different type, and nothing here lets one
masquerade as the other.  A trade-mode sink is out of scope for this phase.

Kernel semantics preserved exactly from the accepted target runtime
(``research_workflow.target_runtime``) and the Phase C.2 multi-arm replay:

* barrier arms: entry reference ``next_bar_open`` = OPEN of the first execution bar
  strictly after T, entry instant = that bar's close minus its duration, horizon from the
  entry instant; ``SESSION_END`` when the arm's horizon end lies past the session close
  (resolved at the close); the entry bar and every later bar are touch-eligible, the bar
  closing exactly at the horizon end included; favorable+adverse in one bar ->
  ``AMBIGUOUS_SAME_BAR_TOUCH``; a tape gap over ``max_gap`` -> ``GAP``; no touch by the
  horizon -> ``TIMEOUT`` (censor) or ``NEGATIVE`` (expiry policy); unresolved at run end
  -> ``DATA_END``.
* flip within horizon (legacy collector path): a qualifying regime change with
  ``T <= flip_ts <= horizon_end`` is ``POSITIVE``; the horizon is inclusive and a
  candidate whose horizon ends exactly at the current bar is held one tick so the
  same-timestamp 1m flip can land; ``SESSION_END`` when the horizon end lies past the
  session close (evaluated at resolution time); every pending candidate is resolved on a
  qualifying flip.
* composite: monotone worst-status censoring over children, no Boolean short-circuit
  (``research_workflow.target_expression``).

Bounded state: one scalar record per pending candidate, no tape retention, no per-bar
allocation beyond the resolution rows.  The independent replay oracle stays a separate
process (``research_workflow.target_replay_oracle``); parity is proven after the run.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Mapping, Optional, Sequence, Tuple

from research_workflow.host.interfaces import NS, BarView

POSITIVE, NEGATIVE, CENSORED = "POSITIVE", "NEGATIVE", "CENSORED"
LEGACY = {POSITIVE: "LABELED_POSITIVE", NEGATIVE: "LABELED_NEGATIVE", CENSORED: "CENSORED"}

LEGACY_OBSERVATION_COLUMNS = (
    "observation_ts", "regime_start_ns", "regime_direction", "checkpoint_index", "flip_ts", "time_to_flip_seconds",
    "target_flip_within_horizon", "disposition", "censored", "censor_reason", "horizon_end_ts", "session_close_ts",
    "resolved_at_ts",
)


class OutcomeContractError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# typed contracts
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BarrierArm:
    id: str
    favorable_atr: float
    adverse_atr: float
    horizon_ns: int
    expiry: str                 # "censor" | "negative"
    prefix: str                 # output column prefix (per-arm columns)


@dataclass(frozen=True)
class FlipItem:
    horizon_ns: int
    source: str                 # tracker id whose "changed" events are the flip events
    role: str = "opposite"      # "opposite" | "same" (relative to prevailing) | "absolute" (target_direction)
    inclusive_start: bool = True
    target_direction: int = 0   # used when role == "absolute"


@dataclass(frozen=True)
class LabelOutcomeContract:
    kernel: str                                # "flip" | "barrier" | "composite"
    direction_ref: str
    atr_ref: Optional[str]
    entry_reference: str
    session_end_censoring: bool
    max_gap_ns: Optional[int]
    same_bar_rule: str
    horizon_end_rule: str = "strict"
    arms: Tuple[BarrierArm, ...] = ()
    flip: Optional[FlipItem] = None
    primary_arm: Optional[str] = None
    composition: Optional[Mapping[str, Any]] = None
    data_end_lookahead_ns: Optional[int] = None
    direction_sign: int = 1
    contract: str = "label"
    resolution: str = "mark_touch"

    @classmethod
    def from_plan(cls, spec: Mapping[str, Any]) -> "LabelOutcomeContract":
        if spec.get("contract") != "label":
            raise OutcomeContractError(f"NOT_A_LABEL_CONTRACT: {spec.get('contract')!r}")
        arms = tuple(BarrierArm(a["id"], float(a["favorable_atr"]), float(a["adverse_atr"]), int(a["horizon_ns"]),
                                str(a.get("expiry", "censor")), str(a.get("prefix", a["id"]))) for a in spec.get("arms") or ())
        flip = spec.get("flip")
        return cls(kernel=str(spec["kernel"]), direction_ref=str(spec["direction"]), atr_ref=spec.get("atr"),
                   entry_reference=str(spec.get("entry_reference", "next_bar_open")),
                   session_end_censoring=bool(spec.get("session_end_censoring", True)), horizon_end_rule=str(spec.get("horizon_end_rule", "strict")),
                   max_gap_ns=(int(spec["max_gap_ns"]) if spec.get("max_gap_ns") is not None else None),
                   same_bar_rule=str(spec.get("same_bar_rule", "ambiguous_censor")), arms=arms,
                   flip=(FlipItem(int(flip["horizon_ns"]), str(flip["source"]), str(flip.get("role", "opposite")),
                                  bool(flip.get("inclusive_start", True)), int(flip.get("target_direction", 0) or 0)) if flip else None),
                   primary_arm=spec.get("primary_arm"), composition=spec.get("composition"),
                   direction_sign=int(spec.get("direction_sign", 1)),
                   data_end_lookahead_ns=(int(spec["data_end_lookahead_ns"]) if spec.get("data_end_lookahead_ns") is not None else None))


@dataclass(frozen=True)
class FillModel:
    order_type: str = "market"
    latency_bars: int = 0
    slippage_ticks: float = 0.0
    spread_ticks: float = 0.0


@dataclass(frozen=True)
class TradeExecutionContract:
    """Order/fill semantics.  Typed so a label frame can never be described as execution."""
    direction_ref: str
    atr_ref: Optional[str]
    entry_reference: str
    fill_model: FillModel
    arms: Tuple[BarrierArm, ...]
    exits: Tuple[Mapping[str, Any], ...]
    precedence: Tuple[str, ...]
    same_bar_rule: str = "adverse_first"
    contract: str = "trade"
    resolution: str = "order_semantics"

    @classmethod
    def from_plan(cls, spec: Mapping[str, Any]) -> "TradeExecutionContract":
        if spec.get("contract") != "trade":
            raise OutcomeContractError(f"NOT_A_TRADE_CONTRACT: {spec.get('contract')!r}")
        fm = spec.get("fill_model") or {}
        arms = tuple(BarrierArm(a["id"], float(a["favorable_atr"]), float(a["adverse_atr"]), int(a["horizon_ns"]),
                                str(a.get("expiry", "censor")), str(a.get("prefix", a["id"]))) for a in spec.get("arms") or ())
        return cls(direction_ref=str(spec["direction"]), atr_ref=spec.get("atr"),
                   entry_reference=str(spec.get("entry_reference", "next_bar_open")),
                   fill_model=FillModel(str(fm.get("order_type", "market")), int(fm.get("latency_bars", 0)),
                                        float(fm.get("slippage_ticks", 0.0)), float(fm.get("spread_ticks", 0.0))),
                   arms=arms, exits=tuple(spec.get("exits") or ()), precedence=tuple(spec.get("precedence") or ()),
                   same_bar_rule=str(spec.get("same_bar_rule", "adverse_first")))


def compile_outcome_contract(spec: Mapping[str, Any]):
    kind = spec.get("contract")
    if kind == "label":
        return LabelOutcomeContract.from_plan(spec)
    if kind == "trade":
        return TradeExecutionContract.from_plan(spec)
    raise OutcomeContractError(f"UNKNOWN_OUTCOME_CONTRACT: {kind!r}")


# --------------------------------------------------------------------------- #
# pending state (scalar; one record per candidate)
# --------------------------------------------------------------------------- #
class _Pending:
    __slots__ = ("identity", "T", "direction", "prevailing", "atr", "session_close", "entry_resolved", "entry_price", "entry_ts",
                 "prev_ts", "arm_end", "arm_state", "arm_at", "arm_reason", "arm_good", "arm_bad", "arm_open",
                 "flip_end", "flip_state", "flip_at", "flip_reason", "flip_ts", "opened_at")

    def __init__(self, identity: Dict[str, Any], T: int, direction: int, atr: float, session_close: Optional[int],
                 n_arms: int, flip_end: Optional[int], prevailing: int) -> None:
        self.identity = identity
        self.T = T
        self.direction = direction
        self.prevailing = prevailing
        self.atr = atr
        self.session_close = session_close
        self.entry_resolved = False
        self.entry_price = 0.0
        self.entry_ts = 0
        self.prev_ts = T
        self.arm_end = [0] * n_arms
        self.arm_state = [None] * n_arms        # None (pending) | POSITIVE | NEGATIVE | CENSORED
        self.arm_at = [None] * n_arms
        self.arm_reason = [None] * n_arms
        self.arm_good = [0.0] * n_arms
        self.arm_bad = [0.0] * n_arms
        self.arm_open = n_arms
        self.flip_end = flip_end
        self.flip_state = None
        self.flip_at = None
        self.flip_reason = None
        self.flip_ts = None
        self.opened_at = T


# --------------------------------------------------------------------------- #
# kernel
# --------------------------------------------------------------------------- #
class LabelOutcomeKernel:
    def __init__(self, contract: LabelOutcomeContract, session_table: Any) -> None:
        self.c = contract
        self.session_table = session_table
        self.arms = list(contract.arms)
        self.n_arms = len(self.arms)
        self.pending: List[_Pending] = []
        self._flip_queue: Deque[_Pending] = deque()   # flip-kernel: ordered by horizon end (monotone T)
        self.rows: List[Dict[str, Any]] = []
        self.last_ts_seen: Optional[int] = None
        if contract.kernel == "flip" and contract.flip is None:
            raise OutcomeContractError("FLIP_KERNEL_WITHOUT_FLIP_ITEM")
        if contract.kernel == "barrier" and not self.arms:
            raise OutcomeContractError("BARRIER_KERNEL_WITHOUT_ARMS")
        if contract.kernel == "composite" and not (self.arms and contract.flip):
            raise OutcomeContractError("COMPOSITE_KERNEL_NEEDS_ARMS_AND_FLIP")
        if contract.entry_reference != "next_bar_open" and self.arms:
            raise OutcomeContractError(f"ENTRY_REFERENCE_UNSUPPORTED: {contract.entry_reference!r}")
        self.observation_columns: List[str] = list(LEGACY_OBSERVATION_COLUMNS)
        if self.n_arms > 1 or (self.n_arms == 1 and contract.primary_arm is None and self.arms[0].prefix != self.arms[0].id):
            for arm in self.arms:
                self.observation_columns += [f"{arm.prefix}_label", f"{arm.prefix}_disposition",
                                             f"{arm.prefix}_censor_reason", f"{arm.prefix}_resolution_seconds"]
        self._primary_index = 0
        if contract.primary_arm is not None:
            ids = [a.id for a in self.arms]
            if contract.primary_arm not in ids:
                raise OutcomeContractError(f"PRIMARY_ARM_UNKNOWN: {contract.primary_arm!r}")
            self._primary_index = ids.index(contract.primary_arm)

    # -- opening ------------------------------------------------------------------
    def open(self, identity: Dict[str, Any], T: int, direction: int, atr: Optional[float]) -> None:
        if self.arms:
            if atr is None or not (float(atr) > 0.0) or not math.isfinite(float(atr)):
                raise OutcomeContractError("TARGET_FROZEN_ATR_MISSING: barrier outcome needs a positive ATR at T")
        session_close = self.session_table.session_close(T) if self.c.session_end_censoring else None
        flip_end = (T + self.c.flip.horizon_ns) if self.c.flip is not None else None
        p = _Pending(identity, T, int(direction) * self.c.direction_sign, float(atr or 0.0), session_close, self.n_arms, flip_end, int(direction))
        self.pending.append(p)
        if self.c.kernel == "flip":
            self._flip_queue.append(p)

    # -- flip events ------------------------------------------------------------------
    def on_flip(self, flip_ts: int, new_direction: int, prev_direction: int) -> None:
        if self.c.flip is None or prev_direction not in (-1, 1):
            return
        role = self.c.flip.role
        if self.c.kernel == "flip":
            # legacy collector path: every pending candidate is resolved on a qualifying flip
            keep: List[_Pending] = []
            for p in self.pending:
                target = self._target(p, role)
                if target != 0 and new_direction != target:
                    keep.append(p)
                    continue
                if p.session_close is not None and p.flip_end > p.session_close:
                    self._finish_flip(p, CENSORED, flip_ts, "SESSION_END", None)
                elif (p.T <= flip_ts if self.c.flip.inclusive_start else p.T < flip_ts) and flip_ts <= p.flip_end:
                    self._finish_flip(p, POSITIVE, flip_ts, None, flip_ts)
                else:
                    self._finish_flip(p, NEGATIVE, p.flip_end, None, None)
            self.pending = keep
            self._flip_queue = deque(keep)
            return
        # composite: flip child records the first qualifying flip strictly after T
        for p in self.pending:
            if p.flip_state is not None or p.flip_ts is not None:
                continue
            target = self._target(p, role)
            if target and new_direction != target:
                continue
            if p.T < flip_ts <= p.flip_end:
                p.flip_ts = flip_ts

    def _target(self, p: _Pending, role: str) -> int:
        if role == "opposite":
            return -p.prevailing
        if role == "same":
            return p.prevailing
        if role == "absolute":
            return int(self.c.flip.target_direction)
        return 0

    def _finish_flip(self, p: _Pending, disposition: str, at: int, reason: Optional[str], flip_ts: Optional[int]) -> None:
        p.flip_state, p.flip_at, p.flip_reason, p.flip_ts = disposition, at, reason, flip_ts
        self._emit(p)

    # -- bars -----------------------------------------------------------------------
    def on_bar(self, bar: BarView) -> None:
        ts = bar.ts_init
        self.last_ts_seen = ts
        if not self.pending:
            return
        if self.c.kernel == "flip":
            self._sweep_flip(ts, final=False)
            return
        hi, lo, op = bar.high, bar.low, bar.open
        max_gap = self.c.max_gap_ns
        still: List[_Pending] = []
        for p in self.pending:
            if ts <= p.T:
                still.append(p)
                continue
            if not p.entry_resolved:
                p.entry_resolved = True
                p.entry_price = op
                p.entry_ts = ts - (bar.ts_init - bar.ts_event)
                p.prev_ts = p.entry_ts
                d, atr, ep = p.direction, p.atr, op
                for i, arm in enumerate(self.arms):
                    p.arm_end[i] = p.entry_ts + arm.horizon_ns
                    p.arm_good[i] = ep + d * arm.favorable_atr * atr
                    p.arm_bad[i] = ep - d * arm.adverse_atr * atr
                    if p.session_close is not None and p.arm_end[i] > p.session_close:
                        self._resolve_arm(p, i, CENSORED, p.session_close, "SESSION_END")
            if p.arm_open:
                gap = bool(max_gap is not None and ts - p.prev_ts > max_gap)
                for i in range(self.n_arms):
                    if p.arm_state[i] is not None:
                        continue
                    end = p.arm_end[i]
                    past_end = ts > end
                    if past_end and self.c.horizon_end_rule == "strict":
                        self._expire_arm(p, i)
                        continue
                    if past_end:
                        # first_bar_at_or_after: this bar is evaluated for a hit, then the arm expires --
                        # but only inside the arm's own session: a bar from the next session is never a fill
                        if p.session_close is not None and ts > p.session_close:
                            self._expire_arm(p, i)
                            continue
                        if gap:
                            self._resolve_arm(p, i, CENSORED, ts, "GAP")
                            continue
                        d = p.direction
                        good, bad = p.arm_good[i], p.arm_bad[i]
                        hit_good = hi >= good if d > 0 else lo <= good
                        hit_bad = lo <= bad if d > 0 else hi >= bad
                        if hit_good and hit_bad:
                            adverse_first = self.c.same_bar_rule == "adverse_first"
                            self._resolve_arm(p, i, NEGATIVE if adverse_first else CENSORED, ts, None if adverse_first else "AMBIGUOUS_SAME_BAR_TOUCH")
                        elif hit_good:
                            self._resolve_arm(p, i, POSITIVE, ts, None)
                        elif hit_bad:
                            self._resolve_arm(p, i, NEGATIVE, ts, None)
                        else:
                            self._expire_arm(p, i)
                        continue
                    if p.session_close is not None and ts > p.session_close:
                        self._resolve_arm(p, i, CENSORED, ts, "SESSION_END")
                        continue
                    if gap:
                        self._resolve_arm(p, i, CENSORED, ts, "GAP")
                        continue
                    d = p.direction
                    good, bad = p.arm_good[i], p.arm_bad[i]
                    hit_good = hi >= good if d > 0 else lo <= good
                    hit_bad = lo <= bad if d > 0 else hi >= bad
                    if hit_good and hit_bad:
                        if self.c.same_bar_rule == "adverse_first":
                            self._resolve_arm(p, i, NEGATIVE, ts, None)
                        else:
                            self._resolve_arm(p, i, CENSORED, ts, "AMBIGUOUS_SAME_BAR_TOUCH")
                    elif hit_good:
                        self._resolve_arm(p, i, POSITIVE, ts, None)
                    elif hit_bad:
                        self._resolve_arm(p, i, NEGATIVE, ts, None)
                    elif ts >= end:
                        self._expire_arm(p, i)
                p.prev_ts = ts
            if self._complete(p, ts, final=False):
                self._emit(p)
            else:
                still.append(p)
        self.pending = still

    def _expire_arm(self, p: _Pending, i: int) -> None:
        arm = self.arms[i]
        if arm.expiry == "negative":
            self._resolve_arm(p, i, NEGATIVE, p.arm_end[i], None)
        else:
            self._resolve_arm(p, i, CENSORED, p.arm_end[i], "TIMEOUT")

    def _resolve_arm(self, p: _Pending, i: int, disposition: str, at: int, reason: Optional[str]) -> None:
        if p.arm_state[i] is None:
            p.arm_state[i] = disposition
            p.arm_at[i] = at
            p.arm_reason[i] = reason
            p.arm_open -= 1

    def _complete(self, p: _Pending, now_ts: int, *, final: bool) -> bool:
        if self.arms and p.arm_open:
            return False
        if self.c.flip is not None and self.c.kernel == "composite":
            if p.flip_ts is not None:
                p.flip_state, p.flip_at = POSITIVE, p.flip_ts
            elif p.session_close is not None and p.flip_end > p.session_close:
                p.flip_state, p.flip_at, p.flip_reason = CENSORED, p.session_close, "SESSION_END"
            elif now_ts >= p.flip_end or final:
                if now_ts >= p.flip_end:
                    p.flip_state, p.flip_at = NEGATIVE, p.flip_end
                else:
                    p.flip_state, p.flip_at, p.flip_reason = CENSORED, now_ts, "DATA_END"
            else:
                return False
        return True

    def _sweep_flip(self, now_ts: int, *, final: bool) -> None:
        q = self._flip_queue
        while q:
            p = q[0]
            end = p.flip_end
            if end > now_ts or (end == now_ts and not final):
                break
            q.popleft()
            if p.session_close is not None and end > p.session_close:
                self._finish_flip(p, CENSORED, now_ts, "SESSION_END", None)
            else:
                self._finish_flip(p, NEGATIVE, end, None, None)
        self.pending = list(q)

    # -- run end ----------------------------------------------------------------------
    def finalize(self, last_ts: Optional[int] = None) -> None:
        now = last_ts if last_ts is not None else self.last_ts_seen
        if now is None:
            now = 0
        if self.c.kernel == "flip":
            self._sweep_flip(now, final=True)
            for p in list(self.pending):
                if p.session_close is not None and p.flip_end > p.session_close:
                    self._finish_flip(p, CENSORED, now, "SESSION_END", None)
                else:
                    self._finish_flip(p, CENSORED, now, "DATA_END", None)
            self.pending = []
            self._flip_queue.clear()
            return
        for p in list(self.pending):
            for i in range(self.n_arms):
                if p.arm_state[i] is None:
                    if p.entry_resolved and now >= p.arm_end[i]:
                        self._expire_arm(p, i)
                    else:
                        self._resolve_arm(p, i, CENSORED, now, "DATA_END")
            self._complete(p, now, final=True)
            self._emit(p)
        self.pending = []

    # -- rows ---------------------------------------------------------------------------
    def _emit(self, p: _Pending) -> None:
        c = self.c
        row: Dict[str, Any] = dict(p.identity)
        row["regime_direction"] = p.prevailing
        if c.kernel == "flip":
            disp, at, reason, flip_ts, horizon_end = p.flip_state, p.flip_at, p.flip_reason, p.flip_ts, p.flip_end
        elif c.kernel == "barrier":
            i = self._primary_index
            disp, at, reason, horizon_end = p.arm_state[i], p.arm_at[i], p.arm_reason[i], (p.arm_end[i] if p.entry_resolved else None)
            flip_ts = at if disp == POSITIVE else None
        else:
            disp, at, reason, horizon_end = self._compose(p)
            flip_ts = at if disp == POSITIVE else None
        label = 1 if disp == POSITIVE else (0 if disp == NEGATIVE else None)
        row.update({
            "flip_ts": flip_ts,
            "time_to_flip_seconds": ((flip_ts - p.T) / NS) if flip_ts is not None else None,
            "target_flip_within_horizon": label,
            "disposition": LEGACY[disp],
            "censored": int(disp == CENSORED),
            "censor_reason": reason,
            "horizon_end_ts": horizon_end,
            "session_close_ts": p.session_close,
            "resolved_at_ts": at,
        })
        if len(self.observation_columns) > len(LEGACY_OBSERVATION_COLUMNS):
            for i, arm in enumerate(self.arms):
                st, rat, rr = p.arm_state[i], p.arm_at[i], p.arm_reason[i]
                if p.entry_resolved:
                    if rr == "DATA_END" and rat is not None and rat < p.arm_end[i]:
                        res_s = arm.horizon_ns / NS
                    else:
                        res_s = (rat - p.entry_ts) / NS if rat is not None else None
                else:
                    res_s = arm.horizon_ns / NS
                row[f"{arm.prefix}_label"] = 1.0 if st == POSITIVE else (0.0 if st == NEGATIVE else None)
                row[f"{arm.prefix}_disposition"] = st
                row[f"{arm.prefix}_censor_reason"] = rr
                row[f"{arm.prefix}_resolution_seconds"] = res_s
        self.rows.append(row)

    def _compose(self, p: _Pending) -> Tuple[str, Optional[int], Optional[str], Optional[int]]:
        from research_workflow.target_expression import TargetResult, worst_censor_reason
        children: List[TargetResult] = []
        for i in range(self.n_arms):
            st = p.arm_state[i]
            children.append(TargetResult(st, 1 if st == POSITIVE else (0 if st == NEGATIVE else None), p.arm_at[i], p.arm_reason[i]))
        children.append(TargetResult(p.flip_state, 1 if p.flip_state == POSITIVE else (0 if p.flip_state == NEGATIVE else None),
                                     p.flip_at, p.flip_reason))
        unresolved = [r for r in children if r.label is None]
        at = max((r.resolved_at_ts for r in children if r.resolved_at_ts is not None), default=None)
        horizon_end = max([e for e in p.arm_end] + ([p.flip_end] if p.flip_end else [])) if p.entry_resolved else None
        if unresolved:
            reasons = [(r.censor_reason if r.censor_reason is not None else "UNRESOLVED_CHILD") for r in unresolved]
            return CENSORED, at, worst_censor_reason(reasons), horizon_end
        labels = [int(r.label) for r in children]
        logic = str((self.c.composition or {}).get("logic", "AND"))
        composed = all(labels) if logic == "AND" else any(labels)
        return (POSITIVE if composed else NEGATIVE), at, None, horizon_end

    def drain_rows(self) -> List[Dict[str, Any]]:
        out, self.rows = self.rows, []
        return out


__all__ = ["LabelOutcomeContract", "TradeExecutionContract", "BarrierArm", "FlipItem", "FillModel",
           "LabelOutcomeKernel", "compile_outcome_contract", "OutcomeContractError", "LEGACY_OBSERVATION_COLUMNS",
           "POSITIVE", "NEGATIVE", "CENSORED"]
