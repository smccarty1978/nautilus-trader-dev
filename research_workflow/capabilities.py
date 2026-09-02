"""Generated capability registry: one index over every active governed capability.

The registry is GENERATED, never hand-maintained:

* ``features``  -- introspected from the active canonical feature authority
                   (``features.candidate_authority.load_authority("active")``).
* ``datasets``  -- introspected from ``research/datasets/*.yaml`` (DatasetSpec) with digests.
* ``streams``   -- derived from the datasets' declared streams.
* trackers, trigger primitives, outcomes, entry references, model drivers, validation
  protocols -- seeded by ``research_workflow/capabilities_index.yaml`` and VERIFIED at
  generation time (implementation importable, attribute present, required tests exist).
  An unverifiable entry is emitted with ``status: broken`` rather than dropped.

Each entry exposes: identity, version, parameters, dependencies, update_cadence, derived
cost_class, status, implementation path, required tests. No benchmark fields: measured
provider cost belongs in ``bench/*.json`` (see ``scripts/bench_baseline.py``).

Output: ``research_workflow/capabilities/registry.json`` (committed, so agents read it for
zero tokens). ``generate(check=True)`` fails when the committed file is stale.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = Path(__file__).resolve().parent / "capabilities_index.yaml"
REGISTRY_PATH = Path(__file__).resolve().parent / "capabilities" / "registry.json"
KINDS = ("streams", "features", "trackers", "trigger_primitives", "outcomes", "entry_references", "model_drivers", "validation_protocols", "datasets")

COST_CLASS_BY_CADENCE = {
    "per_1s": "per_1s", "per_source_bar": "per_source_event", "per_source_event": "per_source_event",
    "per_candidate": "per_candidate", "on_demand": "on_demand", "offline_only": "offline_only",
}


def _cadence_for_feature(definition: Dict[str, Any]) -> str:
    """Declared cadence derived from the feature's input availability contracts and parameters."""
    contracts = " ".join(str(c) for c in definition.get("input_availability_contracts") or [])
    params = set(definition.get("parameter_schema") or [])
    if "update_every" in params or "window" in params:
        return "per_1s"
    if "timeframe" in params or "source_timeframe" in params or "input_timeframe" in params:
        return "per_source_bar"
    if "1s" in contracts and ("1m" not in contracts and "5m" not in contracts):
        return "per_1s"
    return "per_source_bar"


def _tests_naming(name: str, roots: Iterable[Path]) -> List[str]:
    out: List[str] = []
    pattern = re.compile(r"\b" + re.escape(name) + r"\b")
    for root in roots:
        for p in sorted(root.rglob("test_*.py")):
            try:
                if pattern.search(p.read_text(encoding="utf-8", errors="ignore")):
                    out.append(p.relative_to(REPO_ROOT).as_posix())
            except OSError:
                continue
    return out


def _verify_implementation(dotted: str) -> tuple[bool, str]:
    module, _, attr = dotted.rpartition(".")
    try:
        mod = importlib.import_module(module)
    except Exception as exc:
        return False, f"module import failed: {type(exc).__name__}: {exc}"
    if not hasattr(mod, attr):
        return False, f"attribute {attr!r} missing in {module}"
    return True, (getattr(mod, attr).__doc__ or "").strip().splitlines()[0] if (getattr(mod, attr).__doc__ or "").strip() else ""


def _features(repo_root: Path) -> List[Dict[str, Any]]:
    from features.candidate_authority import load_authority
    selected = load_authority("active")
    bundle_version = str((selected.get("manifest") or {}).get("bundle_composite_sha256") or "")[:12]
    test_roots = [repo_root / "features" / "tests", repo_root / "research_workflow" / "tests", repo_root / "scripts" / "tests"]
    test_cache: Dict[str, List[str]] = {}
    out = []
    for d in selected["registry"]["definitions"]:
        name = d["canonical_name"]
        cadence = _cadence_for_feature(d)
        provider = str(d.get("provider") or "")
        provider_path = provider.rpartition(".")[0].replace(".", "/") + ".py"
        if name not in test_cache:
            test_cache[name] = _tests_naming(name, test_roots)
        out.append({
            "id": f"feature.{name}", "kind": "features", "name": name, "version": bundle_version or "active",
            "description": f"Canonical feature {name} ({', '.join(d.get('family') or [])})",
            "parameters": list(d.get("parameter_schema") or []),
            "dependencies": [f"stream.completed_{tf}" for tf in sorted({t for c in (d.get("input_availability_contracts") or []) for t in str(c).split("+")})],
            "update_cadence": cadence, "cost_class": COST_CLASS_BY_CADENCE[cadence],
            "status": d.get("status"), "implementation": provider, "implementation_path": provider_path,
            "implementation_exists": (repo_root / provider_path).is_file(),
            "null_policies": d.get("null_policies"), "reset_policies": d.get("reset_policies"), "dtype": d.get("dtype"),
            "required_tests": test_cache[name], "legacy_alias_count": d.get("legacy_alias_count"),
        })
    return out


def _datasets(repo_root: Path) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    import yaml
    datasets, streams = [], []
    for p in sorted((repo_root / "research" / "datasets").glob("*.yaml")):
        spec = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        did = spec.get("dataset_id", p.stem)
        datasets.append({"id": f"dataset.{did}", "kind": "datasets", "name": did, "version": (spec.get("logical_digest") or "")[:12] or "undigested",
                         "description": f"{spec.get('instrument_id')} catalog {did}", "parameters": [], "dependencies": [],
                         "update_cadence": "offline_only", "cost_class": "offline_only", "status": "verified" if spec.get("logical_digest") else "undigested",
                         "implementation": p.relative_to(repo_root).as_posix(), "logical_digest": spec.get("logical_digest"),
                         "instrument_id": spec.get("instrument_id"), "coverage": spec.get("coverage"), "required_tests": ["scripts/tests/test_roots.py", "scripts/tests/test_dataset_spec.py"]})
        for tf, st in (spec.get("streams") or {}).items():
            streams.append({"id": f"stream.{did}.{tf}", "kind": "streams", "name": f"{did}:{tf}", "version": (spec.get("logical_digest") or "")[:12] or "undigested",
                            "description": f"{tf} {'external catalog' if st.get('source') == 'external' else 'derived'} stream of {did}",
                            "parameters": [], "dependencies": [f"dataset.{did}"] + ([f"stream.{did}.{st['derived_from']}"] if st.get("source") == "derived" else []),
                            "update_cadence": "per_source_bar", "cost_class": "per_source_event", "status": "verified",
                            "implementation": st.get("aggregator") or st.get("bar_type"), "availability_rule": st.get("availability_rule", "interval_end"),
                            "required_tests": ["scripts/tests/test_readiness.py"]})
    return datasets, streams


def _seeded(repo_root: Path) -> Dict[str, List[Dict[str, Any]]]:
    import yaml
    index = yaml.safe_load(INDEX_PATH.read_text(encoding="utf-8")) or {}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for kind, entries in index.items():
        rows = []
        for e in entries or []:
            ok, note = _verify_implementation(str(e["implementation"]))
            tests = [t for t in (e.get("required_tests") or [])]
            missing_tests = [t for t in tests if not (repo_root / t).is_file()]
            status = "verified" if ok and not missing_tests else "broken"
            cadence = e.get("update_cadence", "per_source_event")
            rows.append({"id": e["id"], "kind": kind, "name": e["id"].split(".", 1)[1], "version": e.get("version", 1),
                         "description": e.get("description", ""), "parameters": list(e.get("parameters") or []),
                         "dependencies": list(e.get("dependencies") or []), "update_cadence": cadence,
                         "cost_class": COST_CLASS_BY_CADENCE.get(cadence, "per_source_event"), "status": status,
                         "implementation": e["implementation"], "implementation_verified": ok, "implementation_note": note,
                         "required_tests": tests, "missing_tests": missing_tests})
        out[kind] = rows
    return out


def build_registry(repo_root: Path = REPO_ROOT) -> Dict[str, Any]:
    datasets, streams = _datasets(repo_root)
    seeded = _seeded(repo_root)
    reg: Dict[str, Any] = {"schema_version": 1, "generated_at_utc": None, "kinds": {}}
    reg["kinds"]["streams"] = streams
    reg["kinds"]["features"] = _features(repo_root)
    for kind in ("trackers", "trigger_primitives", "outcomes", "entry_references", "model_drivers", "validation_protocols"):
        reg["kinds"][kind] = seeded.get(kind, [])
    reg["kinds"]["datasets"] = datasets
    ids = [e["id"] for k in reg["kinds"].values() for e in k]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise RuntimeError(f"CAPABILITY_ID_DUPLICATE: {dup}")
    known = set(ids)
    for k in reg["kinds"].values():
        for e in k:
            e["unresolved_dependencies"] = [d for d in e.get("dependencies", []) if d not in known and not d.startswith("stream.completed_")]
    reg["summary"] = {kind: {"count": len(rows), "broken": sum(1 for r in rows if r.get("status") == "broken")} for kind, rows in reg["kinds"].items()}
    reg["summary"]["total"] = len(ids)
    body = json.dumps({k: v for k, v in reg.items() if k != "generated_at_utc"}, sort_keys=True, default=str)
    reg["content_sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    reg["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    return reg


def generate(*, check: bool = False, repo_root: Path = REPO_ROOT, path: Path = REGISTRY_PATH) -> Dict[str, Any]:
    reg = build_registry(repo_root)
    if check:
        if not path.is_file():
            raise RuntimeError("CAPABILITY_REGISTRY_MISSING: run 'research cap generate'")
        current = json.loads(path.read_text(encoding="utf-8"))
        if current.get("content_sha256") != reg["content_sha256"]:
            raise RuntimeError("CAPABILITY_REGISTRY_STALE: run 'research cap generate' and commit")
        return current
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reg, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return reg


def load_registry(path: Path = REGISTRY_PATH) -> Dict[str, Any]:
    if not path.is_file():
        raise RuntimeError("CAPABILITY_REGISTRY_MISSING: run 'research cap generate'")
    return json.loads(path.read_text(encoding="utf-8"))


def entries(reg: Dict[str, Any], kind: Optional[str] = None) -> List[Dict[str, Any]]:
    kinds = [kind] if kind else list(KINDS)
    return [e for k in kinds for e in reg["kinds"].get(k, [])]


def describe(reg: Dict[str, Any], capability_id: str) -> Optional[Dict[str, Any]]:
    for e in entries(reg):
        if e["id"] == capability_id or e.get("name") == capability_id:
            return e
    return None


def search(reg: Dict[str, Any], text: str) -> List[Dict[str, Any]]:
    needle = text.lower()
    hits = []
    for e in entries(reg):
        hay = " ".join(str(e.get(k, "")) for k in ("id", "name", "description", "implementation", "parameters", "dependencies")).lower()
        if needle in hay:
            hits.append(e)
    return hits


def _row(e: Dict[str, Any]) -> Dict[str, Any]:
    return {k: e.get(k) for k in ("id", "kind", "version", "status", "update_cadence", "cost_class", "parameters", "dependencies", "implementation")}


def cli(ns) -> int:
    """Entry for ``research cap ...`` (scripts/research.py)."""
    def out(payload: Dict[str, Any], ok: bool = True) -> int:
        print(json.dumps({"STATUS": "OK" if ok else "FAIL", **payload}, sort_keys=True, default=str))
        return 0 if ok else 2
    if ns.cmd == "generate":
        try:
            reg = generate(check=bool(getattr(ns, "check", False)))
        except RuntimeError as exc:
            return out({"error": str(exc)}, ok=False)
        return out({"registry": REGISTRY_PATH.relative_to(REPO_ROOT).as_posix(), "summary": reg["summary"], "content_sha256": reg["content_sha256"]})
    reg = load_registry()
    if ns.cmd == "list":
        kind = getattr(ns, "kind", None)
        if kind and kind not in KINDS:
            return out({"error": f"unknown kind {kind!r}; kinds={list(KINDS)}"}, ok=False)
        rows = entries(reg, kind)
        status = getattr(ns, "status", None)
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return out({"kind": kind or "all", "count": len(rows), "entries": [_row(r) for r in rows]})
    if ns.cmd == "describe":
        e = describe(reg, ns.capability_id)
        return out({"capability": e} if e else {"error": f"unknown capability {ns.capability_id!r}"}, ok=e is not None)
    if ns.cmd == "search":
        hits = search(reg, ns.text)
        return out({"query": ns.text, "count": len(hits), "entries": [_row(r) for r in hits]})
    return out({"error": f"unknown cap command {ns.cmd!r}"}, ok=False)


__all__ = ["KINDS", "REGISTRY_PATH", "INDEX_PATH", "build_registry", "generate", "load_registry", "entries", "describe", "search", "cli"]
