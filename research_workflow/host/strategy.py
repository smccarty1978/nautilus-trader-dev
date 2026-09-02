"""HostCore (pure Python, engine-agnostic) and the NautilusTrader strategy that drives it.

The core is deliberately testable without NautilusTrader and without any real
primitive: feed ``BarView``s in ``ts_init`` order, read frames back.  The strategy is a
thin adapter from NT ``Bar`` objects to ``BarView`` keyed by bar type.
"""
from __future__ import annotations

import importlib
import json
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from research_workflow.host.interfaces import NS, BarView, EmittedEvent, EpochView
from research_workflow.host.mux import StreamMux
from research_workflow.host.outcomes import LabelOutcomeKernel, compile_outcome_contract, LabelOutcomeContract
from research_workflow.host.predicate_eval import compile_predicate
from research_workflow.host.sink import CollectionSink
from research_workflow.host.triggers import OBSERVE, TriggerEngine, Transition


class HostPlanError(RuntimeError):
    pass


def _load(dotted: str) -> Any:
    module, _, attr = dotted.rpartition(".")
    return getattr(importlib.import_module(module), attr)


class HostCore:
    """Coordinates the compiled plan's primitives over a causally ordered bar stream."""

    def __init__(self, plan: Mapping[str, Any], *, session_table: Any, primary_interval: Optional[Tuple[int, int]] = None,
                 ledger: Optional[List[Dict[str, Any]]] = None, progress_path: Optional[str] = None,
                 progress_every_bars: int = 0, studies_root: Optional[str] = None) -> None:
        self.plan = dict(plan)
        self.studies_root = studies_root
        self.session_table = session_table
        self.primary_start, self.primary_end = (primary_interval if primary_interval else (None, None))
        self.progress_path = progress_path
        self.progress_every_bars = int(progress_every_bars)
        self._bars_processed = 0
        self._started = time.perf_counter()

        # streams / mux
        self.streams = list(self.plan["streams"])
        self.execution_streams = [s["key"] for s in self.streams if s["role"] == "execution"]
        self.mux = StreamMux(self.streams, self._deliver)
        self.stream_duration = {s["key"]: int(s["duration_ns"]) for s in self.streams}

        # trackers (in plan order)
        self.trackers: Dict[str, Any] = {}
        self.epoch_fields: Dict[str, Set[str]] = {}
        self._stream_subscribers: Dict[str, List[Tuple[Any, str, str]]] = {}
        self._event_subscribers: Dict[str, List[Tuple[Any, str, str, Set[str]]]] = {}
        self._tracker_ids: List[str] = []
        for t in self.plan["trackers"]:
            cls = _load(t["implementation"])
            inputs_resolved: Dict[str, Any] = {}
            for key, binding in (t.get("inputs") or {}).items():
                if "tracker" in binding:
                    ref = binding["tracker"]
                    if ref not in self.trackers:
                        raise HostPlanError(f"TRACKER_INPUT_ORDER: {t['id']} needs {ref} constructed first")
                    inputs_resolved[key] = self.trackers[ref]
                elif "stream" in binding:
                    inputs_resolved[key] = binding["stream"]
            params = dict(t.get("params") or {})
            if getattr(cls, "NEEDS_STUDIES_ROOT", False):
                params.setdefault("studies_root", self.studies_root)
            obj = cls(params, inputs_resolved)
            self.trackers[t["id"]] = obj
            self._tracker_ids.append(t["id"])
            self.epoch_fields[t["id"]] = set(getattr(cls, "EPOCH_FIELDS", ()) or ())
            for key, binding in (t.get("inputs") or {}).items():
                if "stream" in binding:
                    self._stream_subscribers.setdefault(binding["stream"], []).append((obj, key, t["id"]))
            for sub in t.get("subscriptions") or []:
                src = sub["from"]
                self._event_subscribers.setdefault(src, []).append((obj, sub["input"], t["id"], set(sub.get("events") or ())))

        # population
        pop = self.plan["population"]
        self.cadence = dict(pop["cadence"])
        self.epoch_stream = self.cadence["stream"]
        self.qualify = compile_predicate(pop["qualify"]["ast"], epoch_fields=self.epoch_fields, allow_events=False) if pop.get("qualify") else None
        self.direction_ref = pop.get("direction")
        self.anchor_identity_ref = pop.get("anchor_identity")
        self.identity_columns = list(self.plan["columns"]["identity"])
        self.metadata_columns = [(m["column"], m["ref"]) for m in self.plan["columns"].get("metadata") or []]
        self.feature_columns = list(self.plan["columns"].get("features") or [])
        self.feature_host = self.trackers.get((self.plan.get("features") or {}).get("host_id", "features")) if self.plan.get("features") else None
        self.derived_columns = list(self.plan["columns"].get("derived") or [])
        self.derived_bindings = [(t["derived_column"], self.trackers[t["id"]]) for t in self.plan["trackers"] if t.get("derived_column")]

        # grid state
        self._grid_next_index = 0
        self._grid_anchor: Optional[int] = None
        self._grid_every = int(self.cadence.get("every_ns") or 0)
        self._grid_max_age = self.cadence.get("max_age_ns")
        self._grid_anchor_ref = self.cadence.get("anchor")

        # triggers
        trig = self.plan["triggers"]
        self.trigger_engine: Optional[TriggerEngine] = None
        self.sub_epoch_sources: List[str] = []
        if trig.get("kind") == "graph":
            self.trigger_engine = TriggerEngine(trig, self.epoch_fields)
            self.sub_epoch_sources = list(trig.get("sub_epoch_sources") or [])
        self._turn_events: List[Tuple[str, Mapping[str, Any]]] = []

        # outcome
        contract = compile_outcome_contract(self.plan["outcome"])
        if not isinstance(contract, LabelOutcomeContract):
            raise HostPlanError("TRADE_CONTRACT_SINK_NOT_AVAILABLE: this phase executes label contracts only")
        self.contract = contract
        self.kernel = LabelOutcomeKernel(contract, session_table)
        self.outcome_stream = self.plan["outcome"].get("stream") or self.epoch_stream
        self.flip_source = contract.flip.source if contract.flip is not None else None
        self.atr_ref = contract.atr_ref
        self.atr_through_ts = str(self.plan["outcome"].get("atr_availability", "at_decision_delivery")) == "through_decision_ts"
        self._deferred_opens: List[Tuple[Dict[str, Any], int, int, EpochView]] = []

        # sink
        candidate_columns = self.identity_columns + [c for c, _ in self.metadata_columns if c not in self.identity_columns] + self.feature_columns + self.derived_columns
        self.sink = CollectionSink(candidate_columns, self.kernel.observation_columns, ledger=ledger,
                                   primary_interval=(self.primary_start, self.primary_end))
        self.candidates_emitted = 0
        self.epochs_evaluated = 0
        self.last_ts_seen: Optional[int] = None

    # -- reference resolution -------------------------------------------------------------
    def resolve(self, ref: str, epoch: EpochView) -> Any:
        if ref.startswith("const:"):
            return json.loads(ref[len("const:"):])
        root, _, rest = ref.partition(".")
        if root == "epoch":
            if rest == "T":
                return epoch.T
            if rest == "price":
                return epoch.price
            if rest == "index":
                return epoch.grid_index
            if rest.startswith("event."):
                return (epoch.event or {}).get(rest[len("event."):])
            if rest == "bar.ts_init":
                return epoch.bar.ts_init if epoch.bar else None
            raise HostPlanError(f"UNKNOWN_EPOCH_REF: {ref}")
        tracker = self.trackers[root]
        if not rest:
            return tracker
        if rest in self.epoch_fields.get(root, ()):
            return tracker.epoch_value(rest, epoch)
        value = tracker
        for part in rest.split("."):
            value = getattr(value, part)
        return value

    # -- ingestion --------------------------------------------------------------------------
    def ingest(self, bar: BarView) -> None:
        self._turn_events = []
        self.mux.ingest(bar)
        self._bars_processed += 1
        if self.progress_every_bars and self._bars_processed % self.progress_every_bars == 0:
            self._heartbeat()

    def _flush_deferred_opens(self, before_ts: Optional[int]) -> None:
        """Open pending outcomes whose decision timestamp is strictly before ``before_ts``
        (every bar with ts_init == T has been applied by then)."""
        if not self._deferred_opens:
            return
        keep: List[Tuple[Dict[str, Any], int, int, EpochView]] = []
        for identity, T, direction, epoch in self._deferred_opens:
            if before_ts is None or T < before_ts:
                atr = self.resolve(self.atr_ref, epoch) if self.atr_ref else None
                self.kernel.open(identity, T, direction, atr)
            else:
                keep.append((identity, T, direction, epoch))
        self._deferred_opens = keep

    def _deliver(self, bar: BarView) -> None:
        if bar.stream == self.outcome_stream:
            # run-end censoring is measured on the outcome (execution) stream only
            self.last_ts_seen = max(self.last_ts_seen or 0, bar.ts_init)
        if self._deferred_opens:
            self._flush_deferred_opens(bar.ts_init)
        for tracker, key, tid in self._stream_subscribers.get(bar.stream, ()):
            tracker.on_bar(key, bar)
            self._route_events(tid, tracker)
        if bar.stream == self.epoch_stream:
            self._epochs(bar)
        if bar.stream == self.outcome_stream:
            self.kernel.on_bar(bar)
            rows = self.kernel.drain_rows()
            if rows:
                for r in rows:
                    self.sink.add_observation(r)

    def _route_events(self, source_id: str, tracker: Any) -> None:
        events = tracker.drain_events()
        if not events:
            return
        for ev in events:
            if source_id == self.flip_source and ev.name == "changed":
                p = ev.payload
                self.kernel.on_flip(int(p["start_ns"]), int(p["direction"]), int(p["prev_direction"]))
                rows = self.kernel.drain_rows()
                for r in rows:
                    self.sink.add_observation(r)
            if source_id in self.sub_epoch_sources and ev.name == "changed":
                p = ev.payload
                if int(p.get("prev_direction", 0)) in (-1, 1) and int(p["direction"]) in (-1, 1):
                    self._turn_events.append((source_id, p))
            for sub, key, sub_id, names in self._event_subscribers.get(source_id, ()):
                if names and ev.name not in names:
                    continue
                sub.on_event(key, ev)
                self._route_events(sub_id, sub)

    # -- epochs -------------------------------------------------------------------------------
    def _epochs(self, bar: BarView) -> None:
        kind = self.cadence["kind"]
        if kind == "completed_bar":
            self._epoch(bar, bar.ts_init, None)
            return
        # grid: T = anchor + (k+1) * every, skip missing seconds, stop after max_age
        epoch_probe = EpochView(T=bar.ts_init, price=bar.close, bar=bar, trackers=self.trackers)
        anchor = self.resolve(self._grid_anchor_ref, epoch_probe)
        if anchor is None or not anchor:
            return
        anchor = int(anchor)
        if anchor != self._grid_anchor:
            self._grid_anchor = anchor
            self._grid_next_index = 0
        every = self._grid_every
        while True:
            T = anchor + (self._grid_next_index + 1) * every
            if T > bar.ts_init:
                break
            if self._grid_max_age is not None and (T - anchor) > int(self._grid_max_age):
                break
            if T < bar.ts_init:
                self._grid_next_index += 1
                continue
            self._epoch(bar, T, self._grid_next_index)
            self._grid_next_index += 1

    def _epoch(self, bar: BarView, T: int, grid_index: Optional[int]) -> None:
        self.epochs_evaluated += 1
        self.mux.assert_epoch_visibility(T, self.execution_streams)
        epoch = EpochView(T=T, price=bar.close, bar=bar, trackers=self.trackers, grid_index=grid_index)
        if not self.session_table.in_session(T):
            return
        if self.qualify is not None and not self.qualify(epoch):
            return
        if self.trigger_engine is None:
            self._emit_candidate(epoch)
            return
        # trigger graph: base sub-epoch then one sub-epoch per turn event
        sub_epochs: List[Tuple[Optional[str], Optional[Mapping[str, Any]]]] = [(None, None)]
        if self.trigger_engine.spec.get("sub_epochs") == "tracker_events":
            sub_epochs += [(src, payload) for src, payload in self._turn_events]
        for src, payload in sub_epochs:
            ev = EpochView(T=T, price=bar.close, bar=bar, trackers=self.trackers, grid_index=grid_index,
                           event=payload, event_source=src)
            transitions, entry = self.trigger_engine.evaluate(ev)
            for tr in transitions:
                self._notify_transition(tr, ev)
            if entry:
                self._emit_candidate(ev)
                for tid in self._tracker_ids:
                    self.trackers[tid].on_trigger_transition("ENTRY", "entry", T, ev)

    def _notify_transition(self, tr: Transition, epoch: EpochView) -> None:
        if tr.kind == "entry":
            return
        for tid in self._tracker_ids:
            self.trackers[tid].on_trigger_transition(tr.state, tr.kind, tr.ts, epoch)
        self.sink.record("trigger", tr.ts, f"{tr.kind}:{tr.state}", {"kind": tr.kind, "state": tr.state, "reason": tr.reason,
                                                                        "event_close_ts": tr.epoch_event_ts,
                                                                        "sub_epoch_source": epoch.event_source})

    def _emit_candidate(self, epoch: EpochView) -> None:
        T = epoch.T
        direction = int(self.resolve(self.direction_ref, epoch)) if self.direction_ref else 0
        anchor_identity = self.resolve(self.anchor_identity_ref, epoch) if self.anchor_identity_ref else None
        index = epoch.grid_index
        row: Dict[str, Any] = {"observation_ts": T, "regime_start_ns": anchor_identity, "checkpoint_index": index}
        for col, ref in self.metadata_columns:
            v = self.resolve(ref, epoch)
            if col == "checkpoint_index":
                row["checkpoint_index"] = v
            else:
                row[col] = v
        if self.feature_host is not None:
            feats = self.feature_host.snapshot(epoch, self.resolve)
            row.update(feats)
        for col, binding in self.derived_bindings:
            row[col] = binding.derive(row, epoch, self.resolve)
        if self.sink.add_candidate(row):
            self.candidates_emitted += 1
        identity = {"observation_ts": T, "regime_start_ns": row["regime_start_ns"], "checkpoint_index": row["checkpoint_index"]}
        if self.atr_through_ts and self.atr_ref:
            self._deferred_opens.append((identity, T, direction, epoch))
        else:
            atr = self.resolve(self.atr_ref, epoch) if self.atr_ref else None
            self.kernel.open(identity, T, direction, atr)
        self.sink.record("candidate", T, (row["regime_start_ns"], row["checkpoint_index"]), {"direction": direction})

    # -- end -------------------------------------------------------------------------------------
    def finalize(self):
        self.mux.flush()
        self._flush_deferred_opens(None)
        self.kernel.finalize(self.last_ts_seen)
        for r in self.kernel.drain_rows():
            self.sink.add_observation(r)
        self._heartbeat(final=True)
        return self.sink.frames()

    def _heartbeat(self, final: bool = False) -> None:
        if not self.progress_path:
            return
        payload = {"bars": self._bars_processed, "candidates": self.candidates_emitted, "epochs": self.epochs_evaluated,
                   "pending": len(self.kernel.pending), "last_ts": self.last_ts_seen,
                   "elapsed_s": round(time.perf_counter() - self._started, 3), "final": final}  # host-constant: heartbeat rounding
        try:
            with open(self.progress_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
        except OSError:
            pass

    def stats(self) -> Dict[str, Any]:
        return {"bars": self._bars_processed, "bars_by_stream": dict(self.mux.bars_seen), "candidates": self.candidates_emitted,
                "observations": len(self.sink.observations), "epochs": self.epochs_evaluated, "pending_at_end": len(self.kernel.pending),
                "dropped_outside_primary": {"candidates": self.sink.dropped_candidates, "observations": self.sink.dropped_observations}}


# --------------------------------------------------------------------------- #
# NautilusTrader adapter
# --------------------------------------------------------------------------- #
try:  # pragma: no cover - import guard keeps the core usable without NT installed
    from nautilus_trader.config import StrategyConfig
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.trading.strategy import Strategy
except Exception:  # pragma: no cover
    StrategyConfig = object  # type: ignore
    Strategy = object  # type: ignore
    Bar = BarType = None  # type: ignore


if Strategy is not object:
    class GovernedHostStrategyConfig(StrategyConfig, frozen=True):
        plan_json: str
        session_table_json: str = '{"kind": "legacy", "session": "RTH"}'
        primary_start_ts: Optional[int] = None
        primary_end_ts: Optional[int] = None
        progress_path: str = ""
        progress_every_bars: int = 0
        ledger_enabled: bool = False
        studies_root: str = ""

    class GovernedHostStrategy(Strategy):
        """NT face of the host: subscribes to the plan's external streams, forwards bars."""

        def __init__(self, config: GovernedHostStrategyConfig) -> None:
            super().__init__(config)
            from research_workflow.sessions import build_session_table
            plan = json.loads(config.plan_json)
            table = build_session_table(json.loads(config.session_table_json))
            interval = None
            if config.primary_start_ts is not None or config.primary_end_ts is not None:
                interval = (config.primary_start_ts, config.primary_end_ts)
            self.ledger: Optional[List[Dict[str, Any]]] = [] if config.ledger_enabled else None
            self.core = HostCore(plan, session_table=table, primary_interval=interval, ledger=self.ledger,
                                 progress_path=(config.progress_path or None), progress_every_bars=config.progress_every_bars,
                                 studies_root=(config.studies_root or None))
            self._bar_types: Dict[Any, str] = {}
            for s in plan["streams"]:
                if s.get("bar_type"):
                    self._bar_types[BarType.from_str(s["bar_type"])] = s["key"]
            self.bars_1s_count = 0
            self.bars_1m_count = 0
            self._counts: Dict[str, int] = {}
            self._frames = None

        def on_start(self) -> None:
            for bt in self._bar_types:
                self.subscribe_bars(bt)

        def on_bar(self, bar: Bar) -> None:
            key = self._bar_types.get(bar.bar_type)
            if key is None:
                return
            self._counts[key] = self._counts.get(key, 0) + 1
            self.core.ingest(BarView(key, int(bar.ts_event), int(bar.ts_init), float(bar.open), float(bar.high),
                                     float(bar.low), float(bar.close), float(bar.volume)))

        def on_stop(self) -> None:
            self._frames = self.core.finalize()
            for s in self.core.streams:
                if s["role"] == "execution" and s["timeframe"] == "1s":
                    self.bars_1s_count = self._counts.get(s["key"], 0)
                if s["role"] == "execution" and s["timeframe"] == "1m":
                    self.bars_1m_count = self._counts.get(s["key"], 0)

        def get_candidates_dataframe(self):
            if self._frames is None:
                self._frames = self.core.finalize()
            return self._frames[0]

        def get_observations_dataframe(self):
            if self._frames is None:
                self._frames = self.core.finalize()
            return self._frames[1]
else:  # pragma: no cover
    GovernedHostStrategyConfig = None  # type: ignore
    GovernedHostStrategy = None  # type: ignore


__all__ = ["HostCore", "GovernedHostStrategy", "GovernedHostStrategyConfig", "HostPlanError"]
