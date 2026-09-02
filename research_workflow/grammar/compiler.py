"""The static compiler: StudySpecV2 -> CompiledPlan | CapabilityGapReport.

Everything here is resolved from committed text (dataset YAML, the generated capability
registry, the feature bundle, binding class declarations).  No catalog is opened, no
provider is fed a bar, no study directory is read.  Binding proof is a compiler output:
every declared primitive maps to exactly one runtime implementation, or the compile
returns a typed gap.
"""
from __future__ import annotations

import re

import difflib
import hashlib
import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import yaml

from research_workflow.grammar.expansion import expand_instances
from research_workflow.grammar.gaps import CapabilityGapReport, CompileError, GapKind
from research_workflow.grammar.plan import CompiledPlan, canonical_json
from research_workflow.grammar.predicates import PredicateSyntaxError, parse_predicate, referenced_paths, render
from research_workflow.grammar.spec import StudySpecV2, duration_seconds

REPO_ROOT = Path(__file__).resolve().parents[2]
NS = 1_000_000_000

_RESERVED_ROOTS = {"state", "age", "T", "price", "in_position", "triggers", "epoch"}
_EVENT_ATTRS = {"flipped", "changed", "turned", "crossed", "fired", "new_leg", "terminated"}
_FEATURE_HOST_ID = "features"
_HOST_MODULES = ("research_workflow/host/interfaces.py", "research_workflow/host/mux.py", "research_workflow/host/triggers.py",
                 "research_workflow/host/outcomes.py", "research_workflow/host/predicate_eval.py", "research_workflow/host/sink.py",
                 "research_workflow/host/strategy.py", "research_workflow/host_runner.py", "research_workflow/sessions.py",
                 "research_workflow/target_expression.py", "research_workflow/target_replay_oracle.py",
                 "research_workflow/grammar/compiler.py", "research_workflow/grammar/predicates.py", "research_workflow/grammar/spec.py",
                 "research_workflow/grammar/expansion.py", "research_workflow/grammar/plan.py", "research_workflow/provider_host.py",
                 "utils/session_boundaries.py")


@dataclass
class CompileOutcome:
    plan: Optional[CompiledPlan]
    gaps: Optional[CapabilityGapReport]

    @property
    def ok(self) -> bool:
        return self.plan is not None

    def card(self) -> Dict[str, Any]:
        return self.plan.card() if self.plan is not None else self.gaps.to_dict()


def load_spec(path: Path) -> Dict[str, Any]:
    p = Path(path)
    if p.is_dir():
        p = p / "study.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise CompileError(f"SPEC_NOT_A_MAPPING: {p}")
    return data


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _closest(name: str, options: Sequence[str]) -> Optional[str]:
    m = difflib.get_close_matches(name, list(options), n=1, cutoff=0.5)
    return m[0] if m else None


def _tf_ns(tf: str) -> int:
    return duration_seconds(tf) * NS


def _dataset_yaml(repo_root: Path, dataset_id: str, datasets_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    p = (Path(datasets_dir) if datasets_dir else (repo_root / "research" / "datasets")) / f"{dataset_id}.yaml"
    if not p.is_file():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _instrument_facts(symbol: str, dataset: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    inst = dataset.get("instrument") or {}
    if inst:
        return {"instrument_id": inst.get("instrument_id", dataset.get("instrument_id")), "venue": inst.get("venue"),
                "multiplier": str(inst.get("multiplier")), "price_increment": str(inst.get("price_increment"))}
    try:
        from backtests.nt_runtime.data_plan import PRODUCT_CATALOGS
    except Exception:  # pragma: no cover
        PRODUCT_CATALOGS = {}
    prod = PRODUCT_CATALOGS.get(symbol.upper())
    if prod:
        return {"instrument_id": prod["instrument_id"], "venue": prod["venue"], "multiplier": prod["multiplier"],
                "price_increment": prod["price_increment"]}
    if dataset.get("instrument_id"):
        return {"instrument_id": dataset["instrument_id"], "venue": str(dataset["instrument_id"]).split(".")[-1],
                "multiplier": None, "price_increment": None}
    return None


class _Ctx:
    """Mutable compile context."""

    def __init__(self, spec: StudySpecV2, repo_root: Path, registry: Mapping[str, Any],
                 datasets_dir: Optional[Path] = None, extra_bindings: Optional[Mapping[str, Any]] = None) -> None:
        self.spec = spec
        self.repo_root = repo_root
        self.registry = registry
        self.datasets_dir = datasets_dir
        self.extra_bindings = dict(extra_bindings or {})
        self.gaps = CapabilityGapReport(spec.study.id)
        self.instruments: Dict[str, Dict[str, Any]] = {}
        self.streams: List[Dict[str, Any]] = []
        self.stream_by: Dict[Tuple[str, str], str] = {}     # (symbol, tf) -> key
        self.execution_symbol = ""
        self.trackers: List[Dict[str, Any]] = []
        self.tracker_meta: Dict[str, Any] = {}               # id -> binding class
        self.tracker_stream: Dict[str, Optional[str]] = {}   # id -> primary bars stream key
        self.notes: List[str] = []
        self.session: Dict[str, Any] = {}
        self.features: Optional[Dict[str, Any]] = None
        self.feature_aliases: List[str] = []
        self.binding_proof: List[Dict[str, Any]] = []
        self.closure_files: Set[str] = set(_HOST_MODULES)

    def gap(self, kind: GapKind, where: str, message: str, **detail: Any) -> None:
        self.gaps.add(kind, where, message, **detail)


# --------------------------------------------------------------------------- #
# stage 1: datasets, instruments, streams
# --------------------------------------------------------------------------- #
def _resolve_streams(ctx: _Ctx) -> None:
    spec = ctx.spec
    for i, s in enumerate(spec.streams):
        where = f"streams[{i}]"
        ds = _dataset_yaml(ctx.repo_root, s.dataset, ctx.datasets_dir)
        if ds is None:
            ctx.gap(GapKind.UNAVAILABLE_STREAM, where, f"dataset {s.dataset!r} has no committed DatasetSpec",
                    dataset=s.dataset)
            continue
        instrument_id = str(ds.get("instrument_id") or "")
        symbol = (s.instrument or instrument_id.split(".")[0] or "").upper()
        if not symbol:
            ctx.gap(GapKind.UNAVAILABLE_STREAM, where, f"dataset {s.dataset!r} declares no instrument", dataset=s.dataset)
            continue
        facts = _instrument_facts(symbol, ds)
        if facts is None:
            ctx.gap(GapKind.UNAVAILABLE_STREAM, where, f"instrument {symbol!r} has no registered facts", instrument=symbol)
            continue
        if s.role == "context" and s.same_ts == "available":
            ctx.gap(GapKind.SEMANTIC_DECISION_REQUIRED, f"{where}.same_ts",
                    "same-timestamp visibility of a context stream has no proven tie-order policy; the default is strictly earlier",
                    instrument=symbol)
        if s.role == "execution":
            ctx.execution_symbol = symbol
        ctx.instruments[symbol] = {**facts, "symbol": symbol, "dataset_id": s.dataset,
                                   "dataset_digest": ds.get("logical_digest"), "role": s.role,
                                   "calendar_table": bool(ds.get("calendar_table")), "same_ts": s.same_ts}
        declared = ds.get("streams") or {}
        externals = {tf: st for tf, st in declared.items() if (st or {}).get("source") == "external"}
        if not externals:
            ctx.gap(GapKind.UNAVAILABLE_STREAM, where, f"dataset {s.dataset!r} declares no external streams", dataset=s.dataset)
            continue
        finest = min(externals, key=_tf_ns)
        for tf in s.timeframes:
            key = f"{symbol.lower()}_{tf}"
            entry: Dict[str, Any] = {"key": key, "instrument": symbol, "timeframe": tf, "duration_ns": _tf_ns(tf),
                                     "role": s.role, "same_ts": s.same_ts,
                                     "visibility": "at_epoch" if s.role == "execution" else "strictly_before"}
            if tf in externals:
                st = externals[tf]
                entry.update({"source": "external", "bar_type": st.get("bar_type"),
                              "ts_init_delta_ns": int(st.get("ts_init_delta_ns") or _tf_ns(tf))})
            else:
                src = None
                for cand in sorted(externals, key=_tf_ns, reverse=True):
                    if _tf_ns(tf) % _tf_ns(cand) == 0 and _tf_ns(cand) < _tf_ns(tf):
                        src = cand
                        break
                # accepted derived semantics: complete buckets from the finest external stream
                src = finest if (finest in externals and _tf_ns(tf) % _tf_ns(finest) == 0) else src
                if src is None:
                    ctx.gap(GapKind.UNAVAILABLE_STREAM, f"{where}.timeframes", f"{tf} cannot be derived from {sorted(externals)}",
                            timeframe=tf, dataset=s.dataset)
                    continue
                entry.update({"source": "derived", "derived_from": f"{symbol.lower()}_{src}", "aggregation": "complete_bucket"})
            ctx.streams.append(entry)
            ctx.stream_by[(symbol, tf)] = key
    if ctx.execution_symbol:
        cal = ctx.instruments[ctx.execution_symbol].get("calendar_table")
        censor = (ctx.spec.outcome.session or ctx.spec.population.session)
        ctx.session = {"kind": "calendar" if cal else "legacy", "session": ctx.spec.population.session,
                       "censor_session": censor, "dataset": ctx.instruments[ctx.execution_symbol]["dataset_id"]}
        for where, name in (("population.session", ctx.spec.population.session), ("outcome.session", censor)):
            if str(name).upper() not in {"RTH", "ETH", "ALL"}:
                ctx.gap(GapKind.INVALID_PARAMETERIZATION, where, f"unknown session {name!r}", closest="RTH")
        if ctx.spec.outcome.session_end == "censor" and str(censor).upper() == "ALL":
            ctx.gap(GapKind.AMBIGUOUS_TEMPORAL_SEMANTICS, "outcome.session",
                    "session-end censoring needs a session with a close; declare outcome.session (e.g. RTH) or session_end: ignore")


# --------------------------------------------------------------------------- #
# stage 2: trackers
# --------------------------------------------------------------------------- #
def _binding_table(extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    from features.trackers.host_bindings import TRACKER_BINDINGS
    table = dict(TRACKER_BINDINGS)
    table.update(dict(extra or {}))
    return table


def _resolve_stream_ref(ctx: _Ctx, value: Any, symbol: str) -> Optional[str]:
    """'1m' | 'nq_1m' -> stream key."""
    if value is None:
        return None
    v = str(value)
    if v in {s["key"] for s in ctx.streams}:
        return v
    return ctx.stream_by.get((symbol, v))


def _resolve_trackers(ctx: _Ctx) -> None:
    table = _binding_table(ctx.extra_bindings)
    from research_workflow.host.interfaces import REQUIRED
    declared = ctx.spec.context
    # dependency order: a tracker may only reference trackers declared before it (after topo-sort)
    order: List[str] = []
    pending = dict(declared)
    guard = 0
    while pending and guard < 100:
        guard += 1
        for name, ct in list(pending.items()):
            cap = ct.tracker if ct.tracker.startswith("tracker.") else f"tracker.{ct.tracker}"
            cls = table.get(cap)
            deps = []
            if cls is not None:
                for key, kind in cls.INPUTS.items():
                    if kind.startswith("tracker"):
                        ref = getattr(ct, key, None) if hasattr(ct, key) else (ct.model_extra or {}).get(key)
                        if ref:
                            deps.append(str(ref))
            if all(d in order or d not in declared for d in deps):
                order.append(name)
                pending.pop(name)
    order += list(pending)  # cyclic leftovers surface as UNSUPPORTED_COMPOSITION below
    for name in order:
        ct = declared[name]
        where = f"context.{name}"
        cap = ct.tracker if ct.tracker.startswith("tracker.") else f"tracker.{ct.tracker}"
        cls = table.get(cap)
        if cls is None:
            ctx.gap(GapKind.MISSING_CAPABILITY, where, f"no registered tracker {cap!r}",
                    capability=cap, closest=_closest(cap, list(table)))
            continue
        extra = dict(ct.model_extra or {})
        symbol = (ct.instrument or ctx.execution_symbol).upper()
        params: Dict[str, Any] = {}
        inputs: Dict[str, Dict[str, Any]] = {}
        unknown = []
        for key, value in extra.items():
            if key in cls.PARAMS:
                params[key] = value
            elif key in cls.INPUTS:
                pass
            else:
                unknown.append(key)
        if unknown:
            ctx.gap(GapKind.INVALID_PARAMETERIZATION, where, f"{cap} does not accept {sorted(unknown)}",
                    accepted=sorted(list(cls.PARAMS) + list(cls.INPUTS)))
        for pname, default in cls.PARAMS.items():
            if pname not in params:
                if default is REQUIRED:
                    ctx.gap(GapKind.INVALID_PARAMETERIZATION, where, f"{cap} requires parameter {pname!r}")
                else:
                    params[pname] = default
        if "instrument" in cls.PARAMS:
            params["instrument"] = symbol
        for key, kind in cls.INPUTS.items():
            optional = kind.endswith("?")
            base = kind.rstrip("?")
            value = extra.get(key)
            if base == "stream":
                if value is None and key == "bars" and params.get("timeframe"):
                    value = params["timeframe"]
                if value is None and key == "reference" and params.get("timeframe"):
                    finest = min((s for s in ctx.streams if s["instrument"] == symbol), key=lambda s: s["duration_ns"], default=None)
                    value = finest["key"] if finest and finest["duration_ns"] < _tf_ns(str(params["timeframe"])) else None
                stream_key = _resolve_stream_ref(ctx, value, symbol)
                if stream_key is None:
                    if not optional:
                        ctx.gap(GapKind.UNAVAILABLE_STREAM, f"{where}.{key}",
                                f"{cap} input {key!r} needs a declared stream (got {value!r}) on {symbol}",
                                declared=sorted(k for (sym, _), k in ctx.stream_by.items() if sym == symbol))
                    continue
                inputs[key] = {"stream": stream_key}
            else:
                if value is None:
                    if not optional:
                        ctx.gap(GapKind.INVALID_PARAMETERIZATION, f"{where}.{key}", f"{cap} input {key!r} names another context tracker")
                    continue
                ref = str(value)
                if ref not in [t["id"] for t in ctx.trackers]:
                    ctx.gap(GapKind.UNSUPPORTED_COMPOSITION, f"{where}.{key}",
                            f"{cap} input {key!r} references {ref!r}, which is not a context tracker declared before it",
                            closest=_closest(ref, [t["id"] for t in ctx.trackers]))
                    continue
                inputs[key] = {"tracker": ref}
        subscriptions = []
        for key, binding in inputs.items():
            if "tracker" in binding:
                src_cls = ctx.tracker_meta[binding["tracker"]]
                events = sorted(set(cls.SUBSCRIBES) & set(src_cls.EVENTS))
                if events:
                    subscriptions.append({"from": binding["tracker"], "input": key, "events": events})
        entry = {"id": name, "capability": cap, "implementation": f"{cls.__module__}.{cls.__name__}", "params": params,
                 "inputs": inputs, "subscriptions": subscriptions, "fields": list(cls.FIELDS), "epoch_fields": list(cls.EPOCH_FIELDS),
                 "events": list(cls.EVENTS), "cadence": cls.CADENCE, "warmup_bars": int(cls.WARMUP_BARS), "instrument": symbol}
        ctx.trackers.append(entry)
        ctx.tracker_meta[name] = cls
        ctx.tracker_stream[name] = (inputs.get("bars") or {}).get("stream")
        ctx.binding_proof.append({"kind": "tracker", "id": name, "capability": cap, "implementation": entry["implementation"], "bound": True})
        try:
            ctx.closure_files.add(Path(importlib.import_module(cls.__module__).__file__).resolve().relative_to(ctx.repo_root).as_posix())
        except ValueError:
            pass


# --------------------------------------------------------------------------- #
# stage 3: features
# --------------------------------------------------------------------------- #
def _resolve_synthetic_features(ctx: _Ctx) -> None:
    fs = ctx.spec.features
    table = _binding_table(ctx.extra_bindings)
    cls = table.get("feature_host.synthetic")
    if cls is None:
        ctx.gap(GapKind.MISSING_CAPABILITY, "features.host", "no synthetic feature host is registered for this compile")
        return
    columns = dict(fs.columns or {})
    for col, ref in columns.items():
        _validate_ref(ctx, ref, f"features.columns.{col}")
    if not columns:
        ctx.features = None
        return
    impl = f"{cls.__module__}.{cls.__name__}"
    ctx.features = {"host_id": _FEATURE_HOST_ID, "implementation": impl, "instances": [], "routing": {}, "snapshot": {},
                    "aliases": list(columns), "required_events": [], "synthetic": True}
    ctx.feature_aliases = list(columns)
    ctx.trackers.append({"id": _FEATURE_HOST_ID, "capability": cls.CAPABILITY, "implementation": impl, "params": {"columns": columns},
                         "inputs": {}, "subscriptions": [], "fields": ["aliases"], "epoch_fields": [], "events": [],
                         "cadence": cls.CADENCE, "warmup_bars": 0, "instrument": ctx.execution_symbol})
    ctx.tracker_meta[_FEATURE_HOST_ID] = cls
    for col in columns:
        ctx.binding_proof.append({"kind": "feature", "id": col, "capability": cls.CAPABILITY, "implementation": impl, "bound": True})


def _resolve_features(ctx: _Ctx) -> None:
    fs = ctx.spec.features
    if fs.host == "synthetic":
        _resolve_synthetic_features(ctx)
        return
    items = [inst.model_dump() | {k: v for k, v in (inst.model_extra or {}).items()} for inst in fs.instances]
    try:
        expanded = expand_instances(items)
    except ValueError as exc:
        ctx.gap(GapKind.INVALID_PARAMETERIZATION, "features.instances", str(exc))
        return
    if not expanded:
        ctx.features = None
        return
    from features.registry import (FeatureInstance, FeatureInstanceError, _canonical_bundle, _canonical_definition_by_name,
                                   derive_resolved_input_requirements, generate_physical_alias, resolve_feature_instances,
                                   validate_feature_instance)
    bundle = _canonical_bundle("active")
    resolved: List[Dict[str, Any]] = []
    ok = True
    for i, it in enumerate(expanded):
        where = f"features.instances[{i}]"
        inst = FeatureInstance(it["feature"], dict(it.get("parameters") or {}), it.get("alias"))
        try:
            params = validate_feature_instance(inst)
            alias = generate_physical_alias(inst)
            definition = _canonical_definition_by_name(bundle, inst.canonical_name) if bundle else None
            if definition is None:
                raise KeyError(inst.canonical_name)
            reqs = derive_resolved_input_requirements(inst.canonical_name, params, definition)
            res = resolve_feature_instances("canonical_verified_definition_universe", (inst,))[0]
        except FeatureInstanceError as exc:
            msg = str(exc)
            code = msg.split(":")[0]
            kind = (GapKind.MISSING_CAPABILITY if code == "UNKNOWN_CANONICAL_FEATURE"
                    else GapKind.AMBIGUOUS_TEMPORAL_SEMANTICS if code.startswith("AMBIGUOUS_TEMPORAL")
                    else GapKind.INVALID_PARAMETERIZATION)
            ctx.gap(kind, where, msg, feature=it["feature"], parameters=it.get("parameters"))
            ok = False
            continue
        except KeyError as exc:
            ctx.gap(GapKind.MISSING_CAPABILITY, where, f"unknown canonical feature {it['feature']!r}", feature=it["feature"])
            ok = False
            continue
        resolved.append({"requested": it["feature"], "canonical_name": inst.canonical_name, "parameters": dict(params),
                         "physical_alias": alias, "provider": res["provider"], "family": [], "dtype": "float64",
                         "status": res["status"], "input_requirements": {"canonical_name": inst.canonical_name,
                                                                          "provider": res["provider"],
                                                                          "required_streams": list(reqs.get("required_streams") or [])}})
    if not ok:
        return
    aliases = [r["physical_alias"] for r in resolved]
    dup = sorted({a for a in aliases if aliases.count(a) > 1})
    if dup:
        ctx.gap(GapKind.INVALID_PARAMETERIZATION, "features.instances", f"duplicate physical aliases {dup}")
        return
    # binding proof through the feature host's own adapter registry (no bar is ever fed)
    from research_workflow.provider_host import ProviderHost
    try:
        host = ProviderHost.from_feature_contract({"contracts": {"feature_contract": {"runtime_data_requirements": {"resolved_instances": resolved}}}})
    except Exception as exc:
        ctx.gap(GapKind.MISSING_CAPABILITY, "features.instances", f"feature host cannot bind the surface: {exc}")
        return
    proof = host.verify_bindings()
    for m in proof["metadata"]:
        ctx.binding_proof.append({"kind": "feature", "id": m["physical_alias"], "capability": f"feature.{m['canonical_name']}",
                                  "implementation": m["canonical_provider"], "adapter": m["runtime_adapter"], "bound": bool(m["bound"])})
        if m["canonical_provider"]:
            mod = m["canonical_provider"].rpartition(".")[0]
            try:
                ctx.closure_files.add(Path(importlib.import_module(mod).__file__).resolve().relative_to(ctx.repo_root).as_posix())
            except Exception:
                pass
    if not proof["passed"]:
        for alias in proof["unbound"]:
            ctx.gap(GapKind.MISSING_CAPABILITY, "features.instances", f"no runtime adapter renders {alias!r}", alias=alias)
        return
    required_events = set(host.required_streams())
    bindings = dict(fs.bindings or {})
    sym = ctx.execution_symbol
    tracker_ids = [t["id"] for t in ctx.trackers]

    def dual_ema_on(tf: str) -> Optional[str]:
        for t in ctx.trackers:
            if t["capability"] == "tracker.regime.dual_ema" and str(t["params"].get("timeframe")) == tf and t["instrument"] == sym:
                return t["id"]
        return None

    def regime_bar_source(tf: str) -> Optional[str]:
        for t in ctx.trackers:
            if "regime_bar" in t["events"]:
                if t["capability"] == "tracker.regime.dual_ema" and str(t["params"].get("timeframe")) == tf:
                    return t["id"]
                if t["capability"] == "tracker.regime_bar.calendar_bucket" and str(t["params"].get("bucket")) == tf:
                    return t["id"]
        return None

    routing: Dict[str, Dict[str, Any]] = {}
    inputs: Dict[str, Dict[str, Any]] = {}
    subscriptions: List[Dict[str, Any]] = []
    regime_1m = dual_ema_on("1m")
    for ev in sorted(required_events):
        b = bindings.get(ev)
        if ev in ("completed_1s", "completed_1m"):
            tf = ev.split("_")[1]
            stream_key = _resolve_stream_ref(ctx, (b or {}).get("stream") if isinstance(b, dict) else b, sym) or ctx.stream_by.get((sym, tf))
            if stream_key is None:
                ctx.gap(GapKind.UNAVAILABLE_STREAM, f"features.bindings.{ev}", f"feature surface needs a {tf} stream on {sym}")
                continue
            inputs[ev] = {"stream": stream_key}
            routing[ev] = {"stream": stream_key}
            if ev == "completed_1m":
                reg = (b or {}).get("regime") if isinstance(b, dict) else regime_1m
                reg = reg or regime_1m
                if reg not in tracker_ids:
                    ctx.gap(GapKind.UNSUPPORTED_COMPOSITION, "features.bindings.completed_1m",
                            "completed_1m feature events need a 1m regime tracker (direction/ATR) in context")
                    continue
                inputs["completed_1m_regime"] = {"tracker": reg}
                routing[ev]["regime"] = reg
        elif ev in ("completed_5m", "completed_5s"):
            tf = ev.split("_")[1]
            src = (b or {}).get("tracker") if isinstance(b, dict) else (b if isinstance(b, str) else None)
            src = src or regime_bar_source(tf)
            if src not in tracker_ids:
                ctx.gap(GapKind.UNSUPPORTED_COMPOSITION, f"features.bindings.{ev}",
                        f"feature surface needs a {tf} regime-bar source in context (a dual_ema tracker on {tf} or a calendar_bucket tracker)",
                        closest=_closest(str(src), tracker_ids) if src else None)
                continue
            gate = bool((b or {}).get("ready_gate", ctx.tracker_meta[src].CAPABILITY == "tracker.regime.dual_ema")) if isinstance(b, dict) else (ctx.tracker_meta[src].CAPABILITY == "tracker.regime.dual_ema")
            inputs[ev] = {"tracker": src}
            routing[ev] = {"tracker": src, "ready_gate": gate}
            subscriptions.append({"from": src, "input": ev, "events": ["regime_bar"]})
        else:
            ctx.gap(GapKind.UNSUPPORTED_COMPOSITION, "features.instances", f"feature surface requires unknown event {ev!r}")
    # regime transition events for structural geometry (always wired when a 1m regime exists)
    b = bindings.get("regime_transition_1m")
    src = (b or {}).get("tracker") if isinstance(b, dict) else regime_1m
    src = src or regime_1m
    if src in tracker_ids:
        inputs["regime_transition_1m"] = {"tracker": src}
        routing["regime_transition_1m"] = {"tracker": src, "requires_atr": bool((b or {}).get("requires_atr", True)) if isinstance(b, dict) else True}
        subscriptions.append({"from": src, "input": "regime_transition_1m", "events": ["changed"]})
    snap = dict(bindings.get("snapshot") or {})
    if regime_1m is None and ("atr" not in snap):
        ctx.gap(GapKind.UNSUPPORTED_COMPOSITION, "features.bindings.snapshot",
                "feature snapshot needs an ATR reference (features.bindings.snapshot.atr) or a 1m regime tracker in context")
    snapshot = {"atr": snap.get("atr", f"{regime_1m}.atr"), "family_a_atr": snap.get("family_a_atr", f"{regime_1m}.frozen_atr"),
                "episode_state": dict(snap.get("episode_state") or ({"prevailing_direction": f"{regime_1m}.dir"} if regime_1m else {}))}
    for key, ref in [("atr", snapshot["atr"]), ("family_a_atr", snapshot["family_a_atr"])] + list(snapshot["episode_state"].items()):
        _validate_ref(ctx, ref, f"features.bindings.snapshot.{key}")
    from features.trackers.host_bindings import FeatureHostBinding
    ctx.features = {"host_id": _FEATURE_HOST_ID, "implementation": f"{FeatureHostBinding.__module__}.{FeatureHostBinding.__name__}",
                    "instances": resolved, "routing": routing, "snapshot": snapshot, "aliases": aliases,
                    "required_events": sorted(required_events)}
    ctx.feature_aliases = aliases
    ctx.trackers.append({"id": _FEATURE_HOST_ID, "capability": FeatureHostBinding.CAPABILITY, "implementation": ctx.features["implementation"],
                         "params": {"instances": resolved, "routing": routing, "snapshot": snapshot}, "inputs": inputs,
                         "subscriptions": subscriptions, "fields": ["aliases"], "epoch_fields": [], "events": [],
                         "cadence": FeatureHostBinding.CADENCE, "warmup_bars": 0, "instrument": sym})
    ctx.tracker_meta[_FEATURE_HOST_ID] = FeatureHostBinding
    ctx.closure_files.add("features/trackers/host_bindings.py")


# --------------------------------------------------------------------------- #
# references and predicates
# --------------------------------------------------------------------------- #
def _validate_ref(ctx: _Ctx, ref: Any, where: str, *, allow_epoch: bool = True) -> bool:
    if not isinstance(ref, str) or not ref:
        ctx.gap(GapKind.INVALID_PARAMETERIZATION, where, f"expected a reference string, got {ref!r}")
        return False
    if ref.startswith("const:"):
        try:
            json.loads(ref[6:])
            return True
        except ValueError:
            ctx.gap(GapKind.INVALID_PARAMETERIZATION, where, f"malformed constant reference {ref!r}")
            return False
    root, _, rest = ref.partition(".")
    if root == "epoch":
        if not allow_epoch:
            ctx.gap(GapKind.INVALID_PARAMETERIZATION, where, f"{ref!r}: epoch references are not allowed here")
            return False
        return True
    cls = ctx.tracker_meta.get(root)
    if cls is None:
        ctx.gap(GapKind.UNSUPPORTED_COMPOSITION, where, f"{ref!r} references unknown context tracker {root!r}",
                closest=_closest(root, list(ctx.tracker_meta)))
        return False
    if rest:
        head = rest.split(".")[0]
        if head not in cls.FIELDS and head not in cls.EPOCH_FIELDS and head not in _EVENT_ATTRS and not hasattr(cls, head):
            ctx.gap(GapKind.INVALID_PARAMETERIZATION, where, f"{root} ({cls.CAPABILITY}) has no field {head!r}",
                    closest=_closest(head, list(cls.FIELDS) + list(cls.EPOCH_FIELDS)))
            return False
    return True


def _compile_predicate(ctx: _Ctx, text: Optional[str], where: str, *, allow_events: bool, states: Sequence[str] = ()) -> Optional[Dict[str, Any]]:
    if text is None:
        return None
    try:
        ast_ = parse_predicate(text)
    except PredicateSyntaxError as exc:
        ctx.gap(GapKind.INVALID_PARAMETERIZATION, where, str(exc), predicate=text)
        return None
    ok = True
    for path in referenced_paths(ast_):
        root = path[0]
        if root in _RESERVED_ROOTS:
            if root == "triggers" and (len(path) < 3 or path[1] not in states):
                ctx.gap(GapKind.INVALID_PARAMETERIZATION, where, f"triggers.<state>.fired must name a declared state: {'.'.join(path)}")
                ok = False
            continue
        cls = ctx.tracker_meta.get(root)
        if cls is None:
            ctx.gap(GapKind.UNSUPPORTED_COMPOSITION, where, f"predicate references unknown context tracker {root!r}",
                    predicate=text, closest=_closest(root, list(ctx.tracker_meta)))
            ok = False
            continue
        if len(path) >= 2:
            attr = path[1]
            if attr in _EVENT_ATTRS:
                if not allow_events:
                    ctx.gap(GapKind.UNSUPPORTED_COMPOSITION, where,
                            f"event test {root}.{attr} is only valid inside a trigger graph, not in {where}", predicate=text)
                    ok = False
                elif attr in ("turned", "crossed") and "changed" in cls.EVENTS:
                    pass  # a turn test is the sub-epoch view of the tracker's own 'changed' events
                elif attr not in cls.EVENTS and f"{attr}_seq" not in cls.FIELDS and attr not in cls.FIELDS:
                    ctx.gap(GapKind.INVALID_PARAMETERIZATION, where, f"{root} ({cls.CAPABILITY}) emits no {attr!r} event",
                            predicate=text, closest=_closest(attr, list(cls.EVENTS)))
                    ok = False
            elif attr not in cls.FIELDS and attr not in cls.EPOCH_FIELDS and not hasattr(cls, attr):
                ctx.gap(GapKind.INVALID_PARAMETERIZATION, where, f"{root} ({cls.CAPABILITY}) has no field {attr!r}",
                        predicate=text, closest=_closest(attr, list(cls.FIELDS) + list(cls.EPOCH_FIELDS)))
                ok = False
    if not ok:
        return None
    return {"text": render(ast_), "ast": ast_}


# --------------------------------------------------------------------------- #
# stage 4: population, triggers
# --------------------------------------------------------------------------- #
def _resolve_population(ctx: _Ctx) -> Dict[str, Any]:
    pop = ctx.spec.population
    sym = ctx.execution_symbol
    finest = min((s for s in ctx.streams if s["instrument"] == sym), key=lambda s: s["duration_ns"], default=None)
    cadence: Dict[str, Any]
    if isinstance(pop.cadence, str):
        tf = pop.cadence.split("_", 1)[1] if pop.cadence.startswith("completed_") else pop.cadence
        key = ctx.stream_by.get((sym, tf))
        if key is None:
            ctx.gap(GapKind.UNAVAILABLE_STREAM, "population.cadence", f"cadence stream {tf!r} is not declared on {sym}")
            key = finest["key"] if finest else None
        cadence = {"kind": "completed_bar", "stream": key, "every_ns": _tf_ns(tf) if key else None}
    else:
        g = pop.cadence
        try:
            every = duration_seconds(g.every) * NS
            max_age = duration_seconds(g.max_age) * NS if g.max_age else None
        except ValueError as exc:
            ctx.gap(GapKind.INVALID_PARAMETERIZATION, "population.cadence", str(exc))
            every, max_age = 0, None
        _validate_ref(ctx, g.anchor, "population.cadence.anchor", allow_epoch=False)
        if finest is not None and every and every % finest["duration_ns"] != 0:
            ctx.gap(GapKind.AMBIGUOUS_TEMPORAL_SEMANTICS, "population.cadence.every",
                    f"grid step {g.every} is not a multiple of the evaluation stream ({finest['timeframe']})")
        cadence = {"kind": "grid", "stream": finest["key"] if finest else None, "every_ns": every, "anchor": g.anchor,
                   "max_age_ns": max_age, "index_column": g.index_column}
    qualify = _compile_predicate(ctx, pop.qualify, "population.qualify", allow_events=False)
    direction = pop.direction
    if direction is None:
        ctx.gap(GapKind.SEMANTIC_DECISION_REQUIRED, "population.direction",
                "the candidate direction reference is not declared (e.g. regime_1m.dir); the compiler will not guess it")
    else:
        _validate_ref(ctx, direction, "population.direction", allow_epoch=False)
    anchor_identity = pop.anchor_identity or (cadence.get("anchor") if cadence["kind"] == "grid" else None)
    if anchor_identity:
        _validate_ref(ctx, anchor_identity, "population.anchor_identity", allow_epoch=False)
    return {"session": pop.session, "cadence": cadence, "qualify": qualify, "direction": direction,
            "anchor_identity": anchor_identity}


def _resolve_triggers(ctx: _Ctx) -> Dict[str, Any]:
    trig = ctx.spec.triggers
    if trig == "every_candidate":
        return {"kind": "every_candidate"}
    states: Dict[str, Any] = {}
    names = list(trig.states)
    for name, st in trig.states.items():
        where = f"triggers.states.{name}"
        if not name.isupper():
            ctx.gap(GapKind.INVALID_PARAMETERIZATION, where, "state names are ALL-CAPS identifiers")
        enter = _compile_predicate(ctx, st.enter_when, f"{where}.enter_when", allow_events=True, states=names)
        expire = _compile_predicate(ctx, st.expire_when, f"{where}.expire_when", allow_events=True, states=names)
        for f in st.from_states:
            if f != "OBSERVE" and f not in names:
                ctx.gap(GapKind.INVALID_PARAMETERIZATION, f"{where}.from", f"unknown state {f!r}", closest=_closest(f, names))
        states[name] = {"enter_when": enter, "expire_when": expire, "from": list(st.from_states) or ["OBSERVE"], "chain": bool(st.chain)}
    entry = None
    if trig.entry is not None:
        when = _compile_predicate(ctx, trig.entry.when, "triggers.entry.when", allow_events=True, states=names)
        ref = trig.entry.reference
        entry_ids = {e["id"] for e in ctx.registry.get("kinds", {}).get("entry_references", [])}
        if f"entry.{ref}" not in entry_ids:
            ctx.gap(GapKind.MISSING_CAPABILITY, "triggers.entry.reference", f"entry reference {ref!r} is not registered",
                    closest=_closest(f"entry.{ref}", sorted(entry_ids)))
        cooldown = duration_seconds(trig.entry.cooldown) * NS if trig.entry.cooldown else None
        entry = {"when": when, "reference": ref, "max_per_watch": trig.entry.max_per_watch, "cooldown_ns": cooldown,
                 "context": list(trig.entry.context)}
        for c in trig.entry.context:
            _compile_predicate(ctx, c, "triggers.entry.context", allow_events=True, states=names)
    reset = _compile_predicate(ctx, getattr(trig, "reset_when", None), "triggers.reset_when", allow_events=True, states=names)
    if trig.add is not None:
        ctx.gap(GapKind.MISSING_CAPABILITY, "triggers.add", "add-to-position requires the trade execution sink, which is not available in this phase")
    for p in trig.precedence:
        if p not in names and p not in {"expire", "entry", "reset"}:
            ctx.gap(GapKind.INVALID_PARAMETERIZATION, "triggers.precedence", f"unknown precedence entry {p!r}", closest=_closest(p, names))
    sources: List[str] = []
    for st in states.values():
        for pred in (st["enter_when"], st["expire_when"]):
            if pred:
                for path in referenced_paths(pred["ast"]):
                    if len(path) >= 2 and path[1] in ("turned", "crossed") and path[0] not in sources:
                        sources.append(path[0])
    if entry and entry["when"]:
        for path in referenced_paths(entry["when"]["ast"]):
            if len(path) >= 2 and path[1] in ("turned", "crossed") and path[0] not in sources:
                sources.append(path[0])
    sub_epochs = trig.sub_epochs if trig.sub_epochs != "none" else ("tracker_events" if sources else "none")
    return {"kind": "graph", "states": states, "entry": entry, "reset_when": reset, "precedence": list(trig.precedence),
            "max_transitions_per_epoch": int(trig.max_transitions_per_epoch), "sub_epochs": sub_epochs,
            "sub_epoch_sources": sources, "cadence": trig.cadence}


# --------------------------------------------------------------------------- #
# stage 5: outcome
# --------------------------------------------------------------------------- #
def _resolve_outcome(ctx: _Ctx, population: Mapping[str, Any]) -> Dict[str, Any]:
    o = ctx.spec.outcome
    direction = o.direction or population.get("direction")
    if direction:
        _validate_ref(ctx, direction, "outcome.direction", allow_epoch=False)
    atr = o.atr
    if atr:
        _validate_ref(ctx, atr, "outcome.atr", allow_epoch=False)
    entry_ids = {e["id"] for e in ctx.registry.get("kinds", {}).get("entry_references", [])}
    if f"entry.{o.entry_reference}" not in entry_ids:
        ctx.gap(GapKind.MISSING_CAPABILITY, "outcome.entry_reference", f"entry reference {o.entry_reference!r} is not registered",
                closest=_closest(f"entry.{o.entry_reference}", sorted(entry_ids)))
    horizon_default = duration_seconds(o.horizon) * NS if o.horizon else None
    arms: List[Dict[str, Any]] = []
    primary: Optional[str] = None
    if o.barrier:
        b = dict(o.barrier)
        arm_specs = b.get("arms")
        if not arm_specs:
            arm_specs = [{"id": b.get("id", "barrier"), "favorable_atr": b.get("favorable_atr"), "adverse_atr": b.get("adverse_atr")}]
        for a in arm_specs:
            hz = a.get("horizon") or b.get("horizon") or o.horizon
            if hz is None:
                ctx.gap(GapKind.INVALID_PARAMETERIZATION, f"outcome.barrier.{a.get('id')}", "a barrier arm needs a horizon")
                continue
            try:
                fav, adv = float(a["favorable_atr"]), float(a["adverse_atr"])
            except (KeyError, TypeError, ValueError):
                ctx.gap(GapKind.INVALID_PARAMETERIZATION, f"outcome.barrier.{a.get('id')}", "favorable_atr and adverse_atr are required positive numbers")
                continue
            if fav <= 0 or adv <= 0:
                ctx.gap(GapKind.INVALID_PARAMETERIZATION, f"outcome.barrier.{a.get('id')}", "barrier distances must be positive ATR multiples")
            expiry = str(a.get("expiry") or b.get("expiry") or "censor")
            if expiry not in ("censor", "negative"):
                ctx.gap(GapKind.INVALID_PARAMETERIZATION, f"outcome.barrier.{a.get('id')}.expiry", f"unknown expiry policy {expiry!r}")
            arms.append({"id": str(a["id"]), "favorable_atr": fav, "adverse_atr": adv, "horizon_ns": duration_seconds(hz) * NS,
                         "expiry": expiry, "prefix": str(a.get("prefix") or a["id"])})
        primary = b.get("primary") or (arms[0]["id"] if len(arms) == 1 else None)
        if len(arms) > 1 and primary is None:
            ctx.gap(GapKind.SEMANTIC_DECISION_REQUIRED, "outcome.barrier.primary",
                    "a multi-arm barrier outcome must name which arm is the primary label (the legacy label columns)")
        if atr is None:
            ctx.gap(GapKind.INVALID_PARAMETERIZATION, "outcome.atr", "a barrier outcome needs the ATR reference frozen at the decision (e.g. regime_1m.atr)")
        if o.atr_availability is None:
            ctx.gap(GapKind.AMBIGUOUS_TEMPORAL_SEMANTICS, "outcome.atr_availability",
                    "two causal readings of 'the ATR available at T' exist when a coarser bar closes exactly at T: "
                    "declare atr_availability: at_decision_delivery (tracker state when the decision bar arrives) or "
                    "through_decision_ts (after every bar with ts_init == T is applied)")
        if o.entry_reference == "decision_close":
            ctx.gap(GapKind.INVALID_PARAMETERIZATION, "outcome.entry_reference",
                    "a label contract has no fill reference: decision_close is a research mark, not an entry; use next_bar_open")
        elif o.entry_reference != "next_bar_open":
            ctx.gap(GapKind.MISSING_CAPABILITY, "outcome.entry_reference", f"no runtime binding executes entry reference {o.entry_reference!r}",
                    closest="next_bar_open")
    flip: Optional[Dict[str, Any]] = None
    if o.event:
        pred = _compile_predicate(ctx, o.event, "outcome.event", allow_events=True)
        if pred is not None:
            ast_ = pred["ast"]
            path = ast_.get("path") if ast_.get("op") in ("ref", "call") else None
            if not path or len(path) != 2 or path[1] not in ("flipped", "changed"):
                ctx.gap(GapKind.UNSUPPORTED_COMPOSITION, "outcome.event",
                        "an event outcome must be a single tracker regime-change test (e.g. regime_1m.flipped); compose richer events as a registered tracker")
            else:
                hz = o.horizon
                if hz is None:
                    ctx.gap(GapKind.INVALID_PARAMETERIZATION, "outcome.horizon", "an event outcome needs outcome.horizon")
                role, target_direction = "opposite", 0
                args = ast_.get("args") or {}
                if "against" in args:
                    role = "opposite"
                elif "to" in args:
                    to = args["to"]
                    val = to.get("value") if to.get("op") == "const" else None
                    if to.get("op") == "neg" and to["arg"].get("op") == "const":
                        val = -to["arg"]["value"]
                    if val in (-1, 1):
                        role, target_direction = "absolute", int(val)
                    else:
                        ctx.gap(GapKind.UNSUPPORTED_COMPOSITION, "outcome.event",
                                "flipped(to=...) accepts an absolute direction literal (-1 or 1); relative targets use against=position")
                flip = {"horizon_ns": duration_seconds(hz) * NS if hz else None, "source": path[0], "role": role,
                        "inclusive_start": True, "target_direction": target_direction}
    if o.items:
        ctx.gap(GapKind.MISSING_CAPABILITY, "outcome.items",
                "exit items (stop_move/trail/event exits) require the trade execution sink, which is not available in this phase")
    if arms and flip:
        if o.composition is None:
            ctx.gap(GapKind.SEMANTIC_DECISION_REQUIRED, "outcome.composition", "barrier and event outcomes together need composition: AND | OR")
        kernel = "composite"
    elif arms:
        kernel = "barrier"
    elif flip:
        kernel = "flip"
    else:
        ctx.gap(GapKind.INVALID_PARAMETERIZATION, "outcome", "an outcome needs a barrier, an event, or both")
        kernel = "none"
    if direction is None:
        ctx.gap(GapKind.SEMANTIC_DECISION_REQUIRED, "outcome.direction", "the outcome direction reference is not declared")
    max_gap = duration_seconds(o.max_gap) * NS if o.max_gap else None
    stream = population.get("cadence", {}).get("stream")
    contract: Dict[str, Any] = {
        "contract": o.kind, "kernel": kernel, "direction": direction, "direction_sign": (-1 if o.relation == "fade" else 1),
        "relation": o.relation, "atr": atr, "atr_availability": (o.atr_availability or "at_decision_delivery"), "entry_reference": o.entry_reference,
        "session_end_censoring": o.session_end == "censor", "max_gap_ns": max_gap, "same_bar_rule": o.same_bar_rule,
        "arms": arms, "primary_arm": primary, "flip": flip, "stream": stream, "label_column": o.label_column or "target_flip_within_horizon",
        "composition": ({"logic": o.composition, "children": [a["id"] for a in arms] + (["event"] if flip else [])} if (arms and flip) else None),
    }
    if o.kind == "trade":
        fm = o.fill_model.model_dump() if o.fill_model else {}
        contract.update({"fill_model": fm, "exits": [it.model_dump() for it in o.items], "precedence": list(o.precedence),
                         "executable": False})
        ctx.notes.append("TRADE_CONTRACT_COMPILED_NOT_EXECUTABLE: the trade sink is out of scope for this phase")
    # observation columns (mirrors host.outcomes)
    from research_workflow.host.outcomes import LEGACY_OBSERVATION_COLUMNS
    obs = list(LEGACY_OBSERVATION_COLUMNS)
    if len(arms) > 1 or (len(arms) == 1 and primary is None and arms[0]["prefix"] != arms[0]["id"]):
        for a in arms:
            obs += [f"{a['prefix']}_label", f"{a['prefix']}_disposition", f"{a['prefix']}_censor_reason", f"{a['prefix']}_resolution_seconds"]
    contract["observation_columns"] = obs
    return contract


# --------------------------------------------------------------------------- #
# stage 6: columns, chronology, model, closure
# --------------------------------------------------------------------------- #
def _resolve_columns(ctx: _Ctx, population: Mapping[str, Any], outcome: Mapping[str, Any]) -> Dict[str, Any]:
    metadata = []
    for col, ref in (ctx.spec.features.metadata or {}).items():
        if _validate_ref(ctx, ref, f"features.metadata.{col}"):
            metadata.append({"column": col, "ref": ref})
    derived = []
    for d in ctx.spec.features.derived_inputs:
        body = d.model_dump() | dict(d.model_extra or {})
        if body.get("kind") != "frozen_external_model_score":
            ctx.gap(GapKind.MISSING_CAPABILITY, f"features.derived_inputs.{d.name}", f"unknown derived input kind {body.get('kind')!r}",
                    closest="frozen_external_model_score")
            continue
        from features.trackers.host_bindings import FrozenExternalScoreBinding
        direction_ref = population.get("direction")
        if not direction_ref:
            ctx.gap(GapKind.SEMANTIC_DECISION_REQUIRED, f"features.derived_inputs.{d.name}", "a frozen external score needs population.direction")
            continue
        impl = f"{FrozenExternalScoreBinding.__module__}.{FrozenExternalScoreBinding.__name__}"
        ctx.trackers.append({"id": f"derived.{d.name}", "capability": FrozenExternalScoreBinding.CAPABILITY, "implementation": impl,
                             "params": {"spec": body, "direction": direction_ref}, "inputs": {}, "subscriptions": [],
                             "fields": [], "epoch_fields": [], "events": [], "cadence": FrozenExternalScoreBinding.CADENCE,
                             "warmup_bars": 0, "instrument": ctx.execution_symbol, "derived_column": d.name})
        ctx.tracker_meta[f"derived.{d.name}"] = FrozenExternalScoreBinding
        ctx.binding_proof.append({"kind": "derived_input", "id": d.name, "capability": FrozenExternalScoreBinding.CAPABILITY,
                                  "implementation": impl, "bound": True})
        ctx.closure_files.add("research_workflow/external_model_scoring.py")
        derived.append(d.name)
    return {"identity": ["observation_ts", "regime_start_ns", "checkpoint_index"], "metadata": metadata,
            "features": list(ctx.feature_aliases), "derived": derived, "observation": list(outcome.get("observation_columns") or [])}


def _resolve_chronology_and_model(ctx: _Ctx, outcome_resolved: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    ch = ctx.spec.chronology
    train, dev, prohibited, diag = set(ch.train), set(ch.dev), set(ch.prohibited), set(ch.diagnostic)
    for a, b, na, nb in ((train, dev, "train", "dev"), (train, prohibited, "train", "prohibited"), (dev, prohibited, "dev", "prohibited")):
        if a & b:
            ctx.gap(GapKind.SEMANTIC_DECISION_REQUIRED, "chronology", f"years {sorted(a & b)} appear in both {na} and {nb}")
    chronology = {"train": sorted(train), "dev": sorted(dev), "prohibited": sorted(prohibited), "diagnostic": sorted(diag),
                  "warmup": ch.warmup.model_dump(), "authorized_dates": list(ch.authorized_dates)}
    model_spec = ctx.spec.model
    if model_spec == "none":
        return chronology, None
    kinds = ctx.registry.get("kinds", {})
    families = {e["id"] for e in kinds.get("model_drivers", [])}
    fam_id = f"model.{model_spec.family}" if model_spec.family else None
    if model_spec.mode == "train" and fam_id not in families:
        ctx.gap(GapKind.MISSING_CAPABILITY, "model.family", f"model family {model_spec.family!r} is not a registered driver",
                closest=_closest(fam_id, sorted(families)))
    scored: List[Dict[str, Any]] = []
    if model_spec.mode == "score":
        outcome = outcome_resolved or {}
        known_labels = {outcome.get("label_column")} | {f"{a.get('prefix')}_label" for a in (outcome.get("arms") or [])}
        known_labels.discard(None)
        for i, m in enumerate(model_spec.models):
            if m.label not in known_labels:
                ctx.gap(GapKind.INVALID_PARAMETERIZATION, f"model.models[{i}].label", f"label {m.label!r} is not an outcome column of this study",
                        closest=_closest(m.label, sorted(known_labels)))
            if not re.fullmatch(r"[0-9a-f]{64}", m.id):
                ctx.gap(GapKind.INVALID_PARAMETERIZATION, f"model.models[{i}].id", "model id must be a model-store sha256")
            scored.append({"id": m.id, "label": m.label, "subset": dict(m.subset), "name": m.name or m.id[:12]})
    validation = None
    if model_spec.validation is not None:
        v = model_spec.validation
        protocols = {e["id"] for e in kinds.get("validation_protocols", [])}
        pid = v.protocol if v.protocol.startswith("validation.") else f"validation.{v.protocol}"
        if pid not in protocols:
            ctx.gap(GapKind.MISSING_CAPABILITY, "model.validation.protocol", f"validation protocol {v.protocol!r} is not registered",
                    closest=_closest(pid, sorted(protocols)))
        tuning, final = set(v.tuning_years), set(v.final_train_validation_years)
        roles: List[Dict[str, Any]] = []
        for y in sorted(tuning):
            roles.append({"year": y, "role": "tuning"})
        for y in sorted(final):
            roles.append({"year": y, "role": "final_validation"})
        if tuning & final:
            ctx.gap(GapKind.SEMANTIC_DECISION_REQUIRED, "model.validation", f"years {sorted(tuning & final)} are used for both tuning and final validation (double use)")
        if (tuning | final) - train:
            ctx.gap(GapKind.SEMANTIC_DECISION_REQUIRED, "model.validation", f"validation years {sorted((tuning | final) - train)} are outside TRAIN")
        if (tuning | final) & dev:
            ctx.gap(GapKind.SEMANTIC_DECISION_REQUIRED, "model.validation", "dev/OOS years may not be used in TRAIN-side validation")
        validation = {"protocol": pid, "tuning_years": sorted(tuning), "final_train_validation_years": sorted(final),
                      "max_trials": v.max_trials, "random_seed": v.random_seed, "primary_metric": v.primary_metric,
                      "year_role_table": roles + [{"year": y, "role": "dev_oos"} for y in sorted(dev)] + [{"year": y, "role": "prohibited"} for y in sorted(prohibited)]}
    return chronology, {"mode": model_spec.mode, "family": fam_id, "params": dict(model_spec.params), "arms": list(model_spec.arms), "validation": validation, "models": scored}


def _resolve_closure(ctx: _Ctx) -> Dict[str, Any]:
    from research_workflow.closure_hash import hash_file_v2
    files: Dict[str, str] = {}
    for rel in sorted(ctx.closure_files):
        p = ctx.repo_root / rel
        if p.is_file():
            files[rel] = hash_file_v2(p)
    composite = hashlib.sha256(canonical_json([[k, v] for k, v in sorted(files.items())]).encode("utf-8")).hexdigest()
    return {"hash_algorithm": "v2", "files": files, "composite_sha256": composite, "file_count": len(files)}


def _resolve_warmup_and_availability(ctx: _Ctx) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    per_stream: Dict[str, int] = {s["key"]: 0 for s in ctx.streams}
    rows: List[Dict[str, Any]] = []
    for t in ctx.trackers:
        stream = (t.get("inputs") or {}).get("bars", {}).get("stream")
        if stream:
            per_stream[stream] = max(per_stream.get(stream, 0), int(t.get("warmup_bars") or 0))
        info = next((s for s in ctx.streams if s["key"] == stream), None)
        rows.append({"id": t["id"], "kind": "tracker", "stream": stream, "cadence": t["cadence"],
                     "availability": "completed_bar_ts_init", "visibility": (info or {}).get("visibility", "at_epoch")})
    for inst in (ctx.features or {}).get("instances") or []:
        rows.append({"id": inst["physical_alias"], "kind": "feature", "stream": None,
                     "required_events": inst["input_requirements"]["required_streams"], "availability": "completed_bar_ts_init",
                     "visibility": "at_epoch"})
    warmup = {"per_stream_bars": per_stream, "days_before_partition": ctx.spec.chronology.warmup.days_before_partition,
              "max_warmup_seconds": max((n * next(s["duration_ns"] for s in ctx.streams if s["key"] == k) // NS for k, n in per_stream.items()), default=0)}
    return warmup, {"rows": rows, "same_timestamp_rule": "context streams expose events with ts_init < T only"}


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def compile_study(spec_data: Any, *, repo_root: Path = REPO_ROOT, registry: Optional[Mapping[str, Any]] = None,
                  datasets_dir: Optional[Path] = None, extra_bindings: Optional[Mapping[str, Any]] = None) -> CompileOutcome:
    repo_root = Path(repo_root)
    if registry is None:
        from research_workflow.capabilities import load_registry
        registry = load_registry()
    if isinstance(spec_data, StudySpecV2):
        spec = spec_data
        raw = spec.model_dump(by_alias=True)
    else:
        raw = dict(spec_data)
        try:
            spec = StudySpecV2.model_validate(raw)
        except Exception as exc:  # pydantic ValidationError
            report = CapabilityGapReport(str((raw.get("study") or {}).get("id", "?")))
            errors = getattr(exc, "errors", None)
            if callable(errors):
                for e in errors():
                    loc = ".".join(str(x) for x in e.get("loc", ()))
                    report.add(GapKind.INVALID_PARAMETERIZATION, loc or "spec", e.get("msg", str(exc)))
            else:
                report.add(GapKind.INVALID_PARAMETERIZATION, "spec", str(exc))
            return CompileOutcome(None, report)
    ctx = _Ctx(spec, repo_root, registry, datasets_dir=datasets_dir, extra_bindings=extra_bindings)
    _resolve_streams(ctx)
    if not ctx.gaps.ok:
        return CompileOutcome(None, ctx.gaps)
    _resolve_trackers(ctx)
    _resolve_features(ctx)
    population = _resolve_population(ctx)
    triggers = _resolve_triggers(ctx)
    outcome = _resolve_outcome(ctx, population)
    columns = _resolve_columns(ctx, population, outcome)
    chronology, model = _resolve_chronology_and_model(ctx, outcome)
    if not ctx.gaps.ok:
        return CompileOutcome(None, ctx.gaps)
    warmup, availability = _resolve_warmup_and_availability(ctx)
    closure = _resolve_closure(ctx)
    spec_sha = hashlib.sha256(canonical_json(raw).encode("utf-8")).hexdigest()
    plan = CompiledPlan(
        study={"id": spec.study.id, "tier": spec.study.tier, "question": spec.study.question, "description": spec.study.description},
        instruments=ctx.instruments, streams=ctx.streams, session=ctx.session, trackers=ctx.trackers, population=population,
        triggers=triggers, outcome=outcome, columns=columns, chronology=chronology, model=model, closure=closure,
        binding_proof=ctx.binding_proof, warmup=warmup, availability=availability, features=ctx.features,
        spec_sha256=spec_sha, registry_sha256=str(registry.get("content_sha256", "")), notes=list(ctx.notes),
    ).seal()
    return CompileOutcome(plan, None)


__all__ = ["compile_study", "load_spec", "CompileOutcome", "REPO_ROOT"]
